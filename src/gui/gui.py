import contextlib
import datetime
import json
import os
import queue
import tkinter as tk
from logging import LogRecord
from tkinter import filedialog, messagebox, ttk

import sv_ttk

from core.backend import CompareDirs, SyncDirs
from core.mirror import MirrorDatabase
from gui.components.actions_panel import ActionsPanel
from gui.components.log_panel import LogPanel
from gui.components.paths_panel import PathsPanel
from gui.components.schedule_panel import SchedulePanel
from gui.components.status_bar import StatusBar
from gui.enums import BackendThreadStatus, TkinterCfgRelief, TkinterCfgState
from gui.tray import TrayableTk
from gui.widgets import (
    DefaultActions,
    EntryExclusions,
    EntryPaths,
    EntryTimes,
    LogLevels,
    TextLogger,
    WeekDays,
)
from gui.worker_thread import KillableThread
from utils.constants import ROOT_DIR
from utils.logger import logger
from utils.utils import CompareMethod, DirectoryPair, round_time_to_minutes


def detect_system_theme() -> str:
    """Detect whether Windows system is currently configured for dark or light theme."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize',
        )
        val, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return 'light' if val == 1 else 'dark'
    except Exception:
        return 'dark'


class Gui:
    """Main application orchestrator coordinating GUI panels, scheduler watchdogs, and backend execution."""

    def __init__(self):
        # Initialize GUI window
        self.root = TrayableTk()
        self.root.resizable(False, False)
        icon_path = os.path.join(os.path.dirname(__file__), 'app_icon.ico')
        if os.path.isfile(icon_path):
            with contextlib.suppress(Exception):
                self.root.iconbitmap(icon_path)
        self.root.title('Automatic Backup Tool')

        # Apply modern Sun Valley ttk theme matching Windows preference
        self.current_theme = detect_system_theme()
        with contextlib.suppress(Exception):
            sv_ttk.set_theme(self.current_theme)

        self.config_path = os.path.join(ROOT_DIR, 'config.json')

        # State variables
        self._gui_initialized = False
        self.last_realized_sync: datetime.datetime | None = None
        self._backend_thread_holder: KillableThread | None = None
        self._backend_thread_status = BackendThreadStatus.STANDBY
        self._current_run_trigger: str | None = None
        self._active_sync: SyncDirs | None = None

        # Tkinter control variables
        self.toggle_auto_scroll = tk.BooleanVar(value=True)
        self.checkbox_var_use_mirror = tk.BooleanVar(value=True)
        self.checkbox_var_build_mirror = tk.BooleanVar(value=False)
        self.checkbox_var_metadata_comparison = tk.BooleanVar(value=True)
        self.checkbox_var_confirm_sync = tk.BooleanVar(value=True)
        self.checkbox_var_save_report = tk.BooleanVar(value=False)
        self.text_var_status = tk.StringVar(value=BackendThreadStatus.STANDBY.value)
        self.text_var_next_appointment = tk.StringVar(value='Schedule is not activated')

        # Model objects
        self.checkbox_default_actions = DefaultActions()
        self.week_days = WeekDays()
        self.log_levels = LogLevels()

        # Build GUI modular components
        self.create_widgets()

        # Start parallel threads
        self.backend_thread_holder = None
        self.backend_watchdog()
        self.log_queue_watchdog()

        # Load existing configuration
        self.load_config()

        # Run GUI loop
        self.root.mainloop()

    @property
    def backend_thread_status(self) -> BackendThreadStatus:
        return self._backend_thread_status

    @backend_thread_status.setter
    def backend_thread_status(self, status: BackendThreadStatus):
        self._backend_thread_status = status
        self.text_var_status.set(status.value)

        # If thread is running, disable unused buttons
        if status == BackendThreadStatus.STANDBY:
            self.set_gui_enable_state(general_state=True)
            self.toggle_state_quick_compare = False
            self.toggle_state_sync_now = False
            self._current_run_trigger = None
        elif status == BackendThreadStatus.RUNNING:
            self.set_gui_enable_state(general_state=False, leave_sunken_enabled=True)
        elif status == BackendThreadStatus.STOPPING:
            self.set_gui_enable_state(general_state=False, leave_sunken_enabled=False)

    def set_gui_enable_state(self, general_state: bool, leave_sunken_enabled=False):
        def convert_child_state(child_: tk.Widget, b: bool):
            with contextlib.suppress(Exception):
                child_.configure(state=TkinterCfgState.from_bool(b))  # type: ignore

        def is_sunken_button(child_):
            try:
                return isinstance(child_, tk.Button) and child_.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value
            except Exception:
                return False

        all_childs = [
            *self.frame_paths.winfo_children(),
            self.entry_paths,
            self.entry_exclusions,
            *self.frame_default_actions.winfo_children(),
            *self.frame_buttons_scheduler_days.winfo_children(),
            *self.frame_buttons.winfo_children(),
            self.entry_times,
        ]
        ignore_childs = [
            self.button_open_report,
            self.checkbox_auto_scroll,
            *self.frame_buttons_level.winfo_children(),
        ]

        for child in all_childs:
            if isinstance(child, tk.Label | ttk.Label) or child in ignore_childs:
                continue
            convert_child_state(child, general_state)
            if leave_sunken_enabled and is_sunken_button(child):
                convert_child_state(child, True)

    @property
    def backend_thread_holder(self):
        return self._backend_thread_holder

    @backend_thread_holder.setter
    def backend_thread_holder(self, thread):
        self._backend_thread_holder = thread
        self.backend_thread_status = BackendThreadStatus.RUNNING if thread is not None else BackendThreadStatus.STANDBY

    @property
    def toggle_state_schedule(self) -> bool:
        return self.button_schedule_sync.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_schedule.setter
    def toggle_state_schedule(self, value: bool):
        self.button_schedule_sync.config(
            relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value,
            text='Schedule (ON)' if value else 'Schedule (OFF)',
        )

    @property
    def toggle_state_quick_compare(self) -> bool:
        return self.button_quick_compare.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_quick_compare.setter
    def toggle_state_quick_compare(self, value: bool):
        self.button_quick_compare.config(
            relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value
        )

    @property
    def toggle_state_sync_now(self) -> bool:
        return self.button_sync_now.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_sync_now.setter
    def toggle_state_sync_now(self, value: bool):
        self.button_sync_now.config(relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value)

    def toggle_theme(self):
        """Toggle between Sun Valley dark and light themes and update text log colors."""
        try:
            new_theme = 'light' if sv_ttk.get_theme() == 'dark' else 'dark'
            sv_ttk.set_theme(new_theme)
            self.current_theme = new_theme
            self.log_panel.apply_theme(new_theme)
        except Exception as e:
            logger.warning(f'Could not toggle theme: {e}')

    def create_widgets(self):
        # Configure layout root grid
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        # 1. Top Status & Theme Bar spanning full width
        self.status_bar = StatusBar(
            self.root,
            text_var_status=self.text_var_status,
            text_var_next_appointment=self.text_var_next_appointment,
            on_toggle_theme=self.toggle_theme,
            padding=(8, 4),
        )
        self.status_bar.grid(row=0, column=0, columnspan=2, sticky='ew', padx=10, pady=(8, 4))

        # 2. Left Column: Operations, Schedule, and Configuration
        left_container = ttk.Frame(self.root)
        left_container.grid(row=1, column=0, sticky='nsw', padx=(10, 5), pady=(0, 10))

        # Actions & Operations Panel
        self.actions_panel = ActionsPanel(
            left_container,
            checkbox_default_actions=self.checkbox_default_actions,
            checkbox_var_save_report=self.checkbox_var_save_report,
            checkbox_var_build_mirror=self.checkbox_var_build_mirror,
            checkbox_var_use_mirror=self.checkbox_var_use_mirror,
            checkbox_var_metadata_comparison=self.checkbox_var_metadata_comparison,
            checkbox_var_confirm_sync=self.checkbox_var_confirm_sync,
            on_reset_config=self.button_action_reset_config,
            on_save_config=self.button_action_save_config,
            on_quick_compare=self.button_action_quick_compare,
            on_open_report=self.button_action_open_report,
            on_sync_now=self.button_action_sync_now,
            on_schedule_sync=self.button_action_schedule_sync,
            padding=6,
        )
        self.actions_panel.pack(fill='x', pady=(0, 6))

        # Schedule Settings Panel
        self.schedule_panel = SchedulePanel(
            left_container,
            week_days=self.week_days,
            padding=6,
        )
        self.schedule_panel.pack(fill='x')

        # 3. Right Column: Paths Panel and Activity Log Panel
        right_container = ttk.Frame(self.root)
        right_container.grid(row=1, column=1, sticky='nsew', padx=(5, 10), pady=(0, 10))
        right_container.columnconfigure(0, weight=1)
        right_container.rowconfigure(1, weight=1)

        # Paths Panel
        self.paths_panel = PathsPanel(
            right_container,
            on_add_path=self.button_action_add_path,
            padding=6,
        )
        self.paths_panel.grid(row=0, column=0, sticky='ew', pady=(0, 6))

        # Activity Log Panel
        self.log_panel = LogPanel(
            right_container,
            log_levels=self.log_levels,
            toggle_auto_scroll=self.toggle_auto_scroll,
            on_update_log_levels=self.button_action_update_log_levels,
            on_toggle_auto_scroll=self.button_action_toggle_auto_scroll,
            padding=6,
        )
        self.log_panel.grid(row=1, column=0, sticky='nsew')
        self.log_panel.apply_theme(self.current_theme)

        # Expose legacy attributes for 100% backward compatibility
        self.entry_paths: EntryPaths = self.paths_panel.entry_paths
        self.entry_exclusions: EntryExclusions = self.paths_panel.entry_exclusions
        self.entry_times: EntryTimes = self.schedule_panel.entry_times
        self.text_logger: TextLogger = self.log_panel.text_logger

        self.button_quick_compare = self.actions_panel.button_quick_compare
        self.button_open_report = self.actions_panel.button_open_report
        self.button_sync_now = self.actions_panel.button_sync_now
        self.button_schedule_sync = self.actions_panel.button_schedule_sync
        self.button_new_config = self.actions_panel.button_new_config
        self.button_save_config = self.actions_panel.button_save_config

        self.checkbox_auto_scroll = self.log_panel.checkbox_auto_scroll
        self.frame_paths = self.paths_panel
        self.frame_buttons = self.actions_panel
        self.frame_default_actions = self.actions_panel.frame_default_actions
        self.frame_buttons_scheduler_days = self.schedule_panel
        self.frame_buttons_level = self.log_panel.frame_buttons_level

        self._gui_initialized = True

    def button_action_reset_config(self, ask_confirmation=True):
        if ask_confirmation:
            confirmation = messagebox.askyesno(
                'Caution', 'Are you sure you want to reset the GUI configuration? This is not reversible'
            )
        else:
            confirmation = True
        if not ask_confirmation or confirmation:
            self.text_var_status.set(self.backend_thread_status.value)
            self.entry_paths.set([])
            self.entry_exclusions.reset()
            self.week_days.set([])
            self.entry_times.set([])
            self.checkbox_default_actions.reset()
            self.log_levels.reset()
            self.text_logger.set_log_levels(self.log_levels.get())
            self.checkbox_var_use_mirror.set(True)
            self.checkbox_var_build_mirror.set(False)
            self.checkbox_var_metadata_comparison.set(True)
            self.checkbox_var_confirm_sync.set(True)
            self.checkbox_var_save_report.set(False)
            self.toggle_state_schedule = False
            self.toggle_state_quick_compare = False
            self.toggle_state_sync_now = False
            with contextlib.suppress(Exception):
                os.remove(self.config_path)
            self.get_next_appointment()
            logger.info('GUI configuration was reset')

    def button_action_save_config(self, ask_confirmation=True):
        if os.path.isfile(self.config_path):
            confirmation = messagebox.askyesno(
                'Caution',
                'Are you sure you want to save the GUI configuration? This will overwrite an existing configuration',
            )
        else:
            confirmation = True
        if not ask_confirmation or confirmation:
            config_var_names = [
                'entry_paths',
                'week_days',
                'entry_times',
                'entry_exclusions',
                'log_levels',
                'checkbox_default_actions',
                'checkbox_var_use_mirror',
                'checkbox_var_build_mirror',
                'checkbox_var_metadata_comparison',
                'checkbox_var_confirm_sync',
                'checkbox_var_save_report',
            ]
            config_vars = {name: getattr(self, name).get() for name in config_var_names}
            with open(self.config_path, 'w') as f:
                json.dump(config_vars, f, indent=4)
            logger.info('Configuration was successfully saved')
            self.load_config(show_success_msg=False)

        self.get_next_appointment()

    def load_config(self, show_success_msg=True):
        if os.path.isfile(self.config_path):
            try:
                with open(self.config_path) as f:
                    config_vars = json.load(f)
                for name, value in config_vars.items():
                    if hasattr(self, name):
                        gui_element = getattr(self, name)
                        gui_element.set(value)

                self.text_logger.set_log_levels(self.log_levels.get())
                if show_success_msg:
                    logger.info('Configuration was successfully loaded')
            except Exception as e:
                with contextlib.suppress(Exception):
                    os.rename(self.config_path, self.config_path + '_old.json')
                raise e
        else:
            logger.info('Cannot find default configuration')
            self.button_action_reset_config(ask_confirmation=False)

        self.get_next_appointment()

    def button_action_add_path(self):
        source = filedialog.askdirectory(title='Select source folder')
        if source:
            target = filedialog.askdirectory(title='Select destination folder')
            if target:
                self.entry_paths.add(DirectoryPair(source=source, target=target))

    def button_action_open_report(self):
        if not os.path.isdir(logger.log_dir):
            logger.error(f'Could not open last report because directory does not exist: <{logger.log_dir}>')
            return

        filenames = [
            f
            for f in os.listdir(logger.log_dir)
            if f.startswith('compare_report_')
            and f.endswith('.xlsx')
            and len(f) == len('compare_report_2020-12-23_14-16-21.xlsx')
        ]
        filenames = sorted(
            filenames,
            key=lambda f: datetime.datetime.strptime(f[len('compare_report_') : -len('.xlsx')], '%Y-%m-%d_%H-%M-%S'),
        )
        if len(filenames) > 0:
            last_filepath = os.path.join(logger.log_dir, filenames[-1])
            logger.info(f'Opening {last_filepath}')
            try:
                os.startfile(last_filepath)
            except OSError as e:
                logger.error(f'Could not open last report file <{last_filepath}>: {e}')
        else:
            logger.error(f'Could not open last report because it was not found in directory <{logger.log_dir}>')

    def button_action_quick_compare(self):
        self.toggle_state_quick_compare = not self.toggle_state_quick_compare

    def button_action_sync_now(self):
        self.toggle_state_sync_now = not self.toggle_state_sync_now

    def button_action_schedule_sync(self):
        self.toggle_state_schedule = not self.toggle_state_schedule
        self.get_next_appointment()

    def button_action_update_log_levels(self):
        self.text_logger.set_log_levels(self.log_levels.get())
        if self.toggle_auto_scroll.get():
            self.text_logger.yview(tk.END)

    def button_action_toggle_auto_scroll(self):
        if self.toggle_auto_scroll.get():
            self.text_logger.yview(tk.END)

    def backend_watchdog(self):
        # Check if backend thread finished
        if self.backend_thread_holder is not None and not self.backend_thread_holder.is_alive():
            self.backend_thread_holder = None

        if self._gui_initialized:
            now = datetime.datetime.now()
            next_appointment = self.get_next_appointment()

            # If backend thread is in standby
            if self.backend_thread_status == BackendThreadStatus.STANDBY:
                if (
                    self.toggle_state_schedule
                    and next_appointment is not None
                    and next_appointment != self.last_realized_sync
                    and round_time_to_minutes(datetime.datetime.now()) == round_time_to_minutes(next_appointment)
                ):
                    logger.info('-------------------------------------')
                    logger.info('Initializing scheduled synchronization')
                    self._current_run_trigger = 'schedule'
                    self.call_backend_thread(also_sync=True, timestamp=next_appointment)

                elif self.toggle_state_quick_compare:
                    self._current_run_trigger = 'quick_compare'
                    self.call_backend_thread(also_sync=False, timestamp=now)

                elif self.toggle_state_sync_now:
                    self._current_run_trigger = 'sync_now'
                    self.call_backend_thread(also_sync=True, timestamp=now)

            # If backend thread is running but a cancellation was requested
            elif self.backend_thread_status == BackendThreadStatus.RUNNING:
                stop_requested = (
                    (self._current_run_trigger == 'quick_compare' and not self.toggle_state_quick_compare)
                    or (self._current_run_trigger == 'sync_now' and not self.toggle_state_sync_now)
                    or (self._current_run_trigger == 'schedule' and not self.toggle_state_schedule)
                    or not (self.toggle_state_quick_compare or self.toggle_state_sync_now or self.toggle_state_schedule)
                )

                if stop_requested:
                    logger.info('---------------------------------')
                    logger.info('Trying to stop background process')
                    if hasattr(self, '_active_sync') and self._active_sync is not None:
                        with contextlib.suppress(Exception):
                            self._active_sync.cancel()
                    if self.backend_thread_holder is None:
                        logger.warning('There is no background process to stop')
                    else:
                        try:
                            self.backend_thread_holder.kill()
                        except Exception as e:
                            logger.error(f'Could not stop background process. Exception: {e}')
                    self.backend_thread_status = BackendThreadStatus.STOPPING

        delay = 1000 if self.backend_thread_status == BackendThreadStatus.STANDBY else 50
        self.root.after(delay, self.backend_watchdog)

    def call_backend_thread(self, also_sync: bool, timestamp: datetime.datetime):
        self.last_realized_sync = timestamp
        self.backend_thread_holder = KillableThread(
            target=self.backend_thread,
            args=(also_sync,),
            daemon=True,
        )
        self.backend_thread_holder.start()

    def backend_thread(self, also_sync: bool):
        dirs = self.entry_paths.get_as_dir_pairs()
        if not dirs:
            logger.warning('No valid directory pairs configured. Please add at least one path pair.')
            return

        mirror = MirrorDatabase(exclusions=self.entry_exclusions.get())

        compare = CompareDirs(
            mirror=mirror,
            dirs=dirs,
            exclusions=self.entry_exclusions.get(),
            comparison_method=CompareMethod.METADATA
            if self.checkbox_var_metadata_comparison.get()
            else CompareMethod.CONTENT,
            save_report=self.checkbox_var_save_report.get(),
            use_mirror=self.checkbox_var_use_mirror.get(),
            increment_mirror=not self.checkbox_var_build_mirror.get(),
            rebuild_mirror=self.checkbox_var_build_mirror.get(),
        )

        try:
            if also_sync:
                default_actions = self.checkbox_default_actions.get_as_actions()
                self._active_sync = SyncDirs(
                    files_to_copy=compare.files_to_copy,
                    files_to_move=compare.files_to_move,
                    files_to_delete=compare.files_to_delete,
                    mirror=mirror,
                    root_gui=self.root,
                    dirs=dirs,
                    default_actions=default_actions,
                    increment_mirror=not self.checkbox_var_build_mirror.get(),
                    confirm_sync=self.checkbox_var_confirm_sync.get(),
                )
        finally:
            self._active_sync = None

        logger.debug('Processing thread was properly closed')

    def get_next_appointment(self) -> datetime.datetime | None:
        string = 'Schedule is not activated'
        next_appointment = None

        if self.toggle_state_schedule:
            days = self.week_days.get_as_numbers()
            times = self.entry_times.get()
            now = round_time_to_minutes(datetime.datetime.now())

            for i in range(60 * 24 * 7):
                delta = datetime.timedelta(minutes=i)
                future = now + delta
                if (
                    future.weekday() in days
                    and f'{future.hour:02d}:{future.minute:02d}' in times
                    and self.last_realized_sync != future
                ):
                    next_appointment = future
                    break

            string = (
                next_appointment.strftime('%Y/%m/%d %H:%M:%S (%A)') if next_appointment is not None else 'No date found'
            )

        self.text_var_next_appointment.set(string)
        return next_appointment

    def log_queue_watchdog(self):
        """Poll log queue every 100ms and display queued records in text logger."""
        while True:
            try:
                record: LogRecord = logger.log_queue.get(block=False)
            except queue.Empty:
                break
            else:
                msg = logger.queue_handler.format(record)
                self.text_logger.insert(msg, record.levelname)

                if self.toggle_auto_scroll.get():
                    self.text_logger.yview(tk.END)

        self.root.after(100, self.log_queue_watchdog)


if __name__ == '__main__':
    gui = Gui()
