import contextlib
import datetime
import json
import os
import queue
import threading
import tkinter as tk
from logging import LogRecord
from tkinter import messagebox, ttk

from core.backend import CompareDirs, SyncDirs
from core.mirror import MirrorDatabase
from gui.components.actions_panel import ActionsPanel
from gui.components.log_panel import LogPanel
from gui.components.paths_panel import PathsPanel
from gui.components.reports_window import ReportsWindow
from gui.components.schedule_panel import SchedulePanel
from gui.components.status_bar import StatusBar
from gui.components.telemetry_bar import TelemetryBar
from gui.enums import BackendThreadStatus, TkinterCfgRelief
from gui.icons import apply_window_icon
from gui.scheduler import calculate_next_run
from gui.taskbar import TaskbarProgress
from gui.tray import TrayableTk
from gui.widgets import (
    Action,
    DefaultActions,
    EntryExclusions,
    EntryPaths,
    EntryTimes,
    LogLevels,
    TextLogger,
    WeekDays,
)
from gui.worker_thread import WorkerThread
from utils.constants import CONFIG_PATH
from utils.logger import logger
from utils.utils import CompareMethod, DirectoryPair, round_time_to_minutes


class Gui:
    """Main application orchestrator coordinating GUI panels, scheduler watchdogs, and backend execution."""

    def __init__(self):
        # Initialize GUI window
        self.root = TrayableTk()
        apply_window_icon(self.root)
        self.root.title('FastMirror')

        self.config_path = CONFIG_PATH
        self.taskbar = TaskbarProgress()

        # State variables

        self._gui_initialized = False
        self.last_realized_sync: datetime.datetime | None = None
        self._cancel_event = threading.Event()
        self._backend_thread_holder: WorkerThread | None = None
        self._backend_thread_status = BackendThreadStatus.STANDBY
        self._current_run_trigger: str | None = None
        self._active_sync: SyncDirs | None = None
        self._last_tray_state: tuple[str, str] | None = None
        self._build_mirror_confirmed: bool = False

        # Tkinter control variables
        self.toggle_auto_scroll = tk.BooleanVar(value=True)
        self.radio_var_compare_method = tk.StringVar(value='metadata')
        self.checkbox_var_reset_mirror = tk.BooleanVar(value=False)
        self.checkbox_var_use_mirror = tk.BooleanVar(value=True)
        self.checkbox_var_build_mirror = tk.BooleanVar(value=False)
        self.checkbox_var_metadata_comparison = tk.BooleanVar(value=True)
        self.checkbox_var_confirm_sync = tk.BooleanVar(value=True)
        self.checkbox_var_save_report = tk.BooleanVar(value=False)
        self.text_var_status = tk.StringVar(value=BackendThreadStatus.STANDBY.value)
        self.text_var_next_appointment = tk.StringVar(value='Schedule is not activated')

        # Backward compatibility bidirectional sync traces
        def _sync_compare_to_meta(*_):
            self.checkbox_var_metadata_comparison.set(self.radio_var_compare_method.get() == 'metadata')

        def _sync_meta_to_compare(*_):
            self.radio_var_compare_method.set('metadata' if self.checkbox_var_metadata_comparison.get() else 'content')

        self.radio_var_compare_method.trace_add('write', _sync_compare_to_meta)
        self.checkbox_var_metadata_comparison.trace_add('write', _sync_meta_to_compare)

        def _sync_reset_to_build(*_):
            reset = self.checkbox_var_reset_mirror.get()
            if self.checkbox_var_build_mirror.get() != reset:
                self.checkbox_var_build_mirror.set(reset)
            if self.checkbox_var_use_mirror.get() == reset:
                self.checkbox_var_use_mirror.set(not reset)

        def _sync_build_to_reset(*_):
            build = self.checkbox_var_build_mirror.get()
            if self.checkbox_var_reset_mirror.get() != build:
                self.checkbox_var_reset_mirror.set(build)
            if build and self.checkbox_var_use_mirror.get():
                self.checkbox_var_use_mirror.set(False)

        def _sync_use_to_reset(*_):
            use = self.checkbox_var_use_mirror.get()
            if use:
                if self.checkbox_var_build_mirror.get():
                    self.checkbox_var_build_mirror.set(False)
                if self.checkbox_var_reset_mirror.get():
                    self.checkbox_var_reset_mirror.set(False)

        self.checkbox_var_reset_mirror.trace_add('write', _sync_reset_to_build)
        self.checkbox_var_build_mirror.trace_add('write', _sync_build_to_reset)
        self.checkbox_var_use_mirror.trace_add('write', _sync_use_to_reset)

        # Model objects
        self.checkbox_default_actions = DefaultActions()
        self.week_days = WeekDays()
        self.log_levels = LogLevels()

        # Build GUI modular components
        self.create_widgets()

        # Apply hardware-accelerated native Windows theme
        self.apply_theme()

        # Set minimum window bounds
        self.root.update_idletasks()
        init_w = self.root.winfo_reqwidth()
        init_h = self.root.winfo_reqheight()
        self.root.minsize(init_w, init_h)
        with contextlib.suppress(Exception):
            self.taskbar.set_hwnd(self.root.winfo_id())

        # Register tray actions and update initial tray state
        self.root.set_tray_callbacks(
            on_sync_now=self.tray_action_sync_now,
            on_quick_compare=self.tray_action_quick_compare,
            on_stop_operation=self.request_stop_operation,
            on_open_report=self.button_action_open_report,
            is_running=lambda: self.backend_thread_status == BackendThreadStatus.RUNNING,
        )
        self.update_tray_status()

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
            if hasattr(self, 'actions_panel'):
                self.actions_panel.set_running_state(False)
        elif status == BackendThreadStatus.RUNNING:
            self.set_gui_enable_state(general_state=False, leave_sunken_enabled=True)
            if hasattr(self, 'actions_panel'):
                self.actions_panel.set_running_state(True, trigger=self._current_run_trigger)
        elif status == BackendThreadStatus.STOPPING:
            self.set_gui_enable_state(general_state=False, leave_sunken_enabled=False)
            if hasattr(self, 'actions_panel'):
                self.actions_panel.set_running_state(True, trigger=self._current_run_trigger, stopping=True)

        if self._gui_initialized:
            self.update_tray_status()

    def set_gui_enable_state(self, general_state: bool, leave_sunken_enabled=False):
        """Enable or disable interactive widgets across all GUI panels."""
        if hasattr(self, 'paths_panel'):
            self.paths_panel.set_enabled(general_state)
        if hasattr(self, 'schedule_panel'):
            self.schedule_panel.set_enabled(general_state)
        if hasattr(self, 'actions_panel'):
            self.actions_panel.set_enabled(general_state, leave_sunken_enabled=leave_sunken_enabled)

    @property
    def backend_thread_holder(self):
        return self._backend_thread_holder

    @backend_thread_holder.setter
    def backend_thread_holder(self, thread):
        self._backend_thread_holder = thread
        self.backend_thread_status = BackendThreadStatus.RUNNING if thread is not None else BackendThreadStatus.STANDBY

    @property
    def toggle_state_schedule(self) -> bool:
        return self.actions_panel.button_schedule_sync.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_schedule.setter
    def toggle_state_schedule(self, value: bool):
        self.actions_panel.button_schedule_sync.config(
            relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value,
            text='Schedule (ON)' if value else 'Schedule (OFF)',
        )

    @property
    def toggle_state_quick_compare(self) -> bool:
        return self.actions_panel.button_quick_compare.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_quick_compare.setter
    def toggle_state_quick_compare(self, value: bool):
        self.actions_panel.button_quick_compare.config(
            relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value
        )

    @property
    def toggle_state_sync_now(self) -> bool:
        return self.actions_panel.button_sync_now.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_sync_now.setter
    def toggle_state_sync_now(self, value: bool):
        self.actions_panel.button_sync_now.config(
            relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value
        )

    @property
    def entry_paths(self) -> EntryPaths:
        return self.paths_panel.entry_paths

    @property
    def entry_exclusions(self) -> EntryExclusions:
        return self.paths_panel.entry_exclusions

    @property
    def entry_times(self) -> EntryTimes:
        return self.schedule_panel.entry_times

    @property
    def text_logger(self) -> TextLogger:
        return self.log_panel.text_logger

    def create_widgets(self):
        self.root._gui = self
        # Configure layout root grid
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        # 1. Top Status Bar spanning full width
        self.status_bar = StatusBar(
            self.root,
            text_var_status=self.text_var_status,
            text_var_next_appointment=self.text_var_next_appointment,
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
            checkbox_var_confirm_sync=self.checkbox_var_confirm_sync,
            on_reset_config=self.button_action_reset_config,
            on_save_config=self.button_action_save_config,
            on_quick_compare=self.button_action_quick_compare,
            on_open_report=self.button_action_open_report,
            on_report_history=self.button_action_open_report_history,
            on_sync_now=self.button_action_sync_now,
            on_schedule_sync=self.button_action_schedule_sync,
            on_stop=self.request_stop_operation,
            radio_var_compare_method=self.radio_var_compare_method,
            checkbox_var_reset_mirror=self.checkbox_var_reset_mirror,
            # Backward compatibility fallbacks
            checkbox_var_build_mirror=self.checkbox_var_build_mirror,
            checkbox_var_use_mirror=self.checkbox_var_use_mirror,
            checkbox_var_metadata_comparison=self.checkbox_var_metadata_comparison,
            on_rebuild_confirmation=self.on_rebuild_mirror_confirmation,
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
        self.log_panel.apply_theme('light')

        # 4. Bottom Telemetry Bar spanning full width
        self.telemetry_bar = TelemetryBar(
            self.root,
            padding=(8, 2),
        )
        self.telemetry_bar.grid(row=2, column=0, columnspan=2, sticky='ew', padx=10, pady=(0, 6))

        self._gui_initialized = True

    def apply_theme(self, theme_name: str = 'native'):
        """Apply fast hardware-accelerated Windows native theme and visual styling tokens."""
        style = ttk.Style()
        # Select best available hardware-accelerated theme
        available = style.theme_names()
        for cand in ['vista', 'xpnative', 'clam', 'default']:
            if cand in available:
                with contextlib.suppress(Exception):
                    style.theme_use(cand)
                break

        # Modern crisp Segoe UI typography and visual tokens
        with contextlib.suppress(Exception):
            self.root.configure(bg='SystemButtonFace')

        style.configure('.', font=('Segoe UI', 9))
        style.configure('TLabelframe', relief='groove', borderwidth=1)
        style.configure('TLabelframe.Label', font=('Segoe UI', 9, 'bold'), foreground='#003366')
        style.configure('Accent.TButton', font=('Segoe UI', 9, 'bold'), foreground='#004488')
        style.configure('ActiveToggle.TButton', font=('Segoe UI', 9, 'bold'), foreground='#006600')
        style.configure('Stop.TButton', font=('Segoe UI', 9, 'bold'), foreground='#cc0000')

        if hasattr(self, 'log_panel'):
            self.log_panel.apply_theme('light')

        if getattr(self, '_gui_initialized', False):
            self.root.update_idletasks()
            w = self.root.winfo_reqwidth()
            h = self.root.winfo_reqheight()
            self.root.minsize(w, h)

    def on_rebuild_mirror_confirmation(self, confirmed: bool):
        """Update confirmed state for rebuilding the mirror database."""
        self._build_mirror_confirmed = confirmed

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
            self.radio_var_compare_method.set('metadata')
            self.checkbox_var_reset_mirror.set(False)
            self.checkbox_var_use_mirror.set(True)
            self.checkbox_var_build_mirror.set(False)
            self._build_mirror_confirmed = False
            self.checkbox_var_metadata_comparison.set(True)
            self.checkbox_var_confirm_sync.set(True)
            self.checkbox_var_save_report.set(False)
            self.toggle_state_schedule = False
            self.toggle_state_quick_compare = False
            self.toggle_state_sync_now = False
            with contextlib.suppress(Exception):
                os.remove(self.config_path)
            if getattr(self, 'current_theme', 'native') != 'native':
                self.apply_theme('native')
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
                'radio_var_compare_method',
                'checkbox_var_reset_mirror',
                'checkbox_var_use_mirror',
                'checkbox_var_build_mirror',
                'checkbox_var_metadata_comparison',
                'checkbox_var_confirm_sync',
                'checkbox_var_save_report',
            ]
            config_vars = {}
            for name in config_var_names:
                if name == 'checkbox_var_reset_mirror':
                    config_vars[name] = False  # Reset mirror is a one-shot option
                elif hasattr(self, name):
                    config_vars[name] = getattr(self, name).get()

            os.makedirs(os.path.dirname(os.path.abspath(self.config_path)), exist_ok=True)
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
                    if name == 'radio_var_compare_method':
                        self.radio_var_compare_method.set(value)
                    elif name == 'checkbox_var_reset_mirror':
                        self.checkbox_var_reset_mirror.set(False)
                    elif hasattr(self, name):
                        gui_element = getattr(self, name)
                        gui_element.set(value)

                if 'radio_var_compare_method' not in config_vars and 'checkbox_var_metadata_comparison' in config_vars:
                    self.radio_var_compare_method.set(
                        'metadata' if config_vars['checkbox_var_metadata_comparison'] else 'content'
                    )

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

    def button_action_open_report_history(self):
        """Open past reports browser dialog."""
        ReportsWindow(self.root)

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

    def update_tray_status(self):
        """Update system system tray tooltip and contextual menu when state changes."""
        status_str = self.backend_thread_status.value
        next_app = self.text_var_next_appointment.get()
        state_key = (status_str, next_app)
        if getattr(self, '_last_tray_state', None) == state_key:
            return
        self._last_tray_state = state_key
        tooltip = f'FastMirror\nStatus: {status_str}\nNext: {next_app}'
        self.root.update_tray_tooltip(tooltip)
        self.root._update_tray_menu()

    def tray_action_sync_now(self):
        """Trigger immediate synchronization from the system tray menu."""
        if self.backend_thread_status == BackendThreadStatus.STANDBY:
            self.toggle_state_sync_now = True

    def tray_action_quick_compare(self):
        """Trigger quick comparison from the system tray menu."""
        if self.backend_thread_status == BackendThreadStatus.STANDBY:
            self.toggle_state_quick_compare = True

    def request_stop_operation(self):
        """Request cancellation/stopping of currently running background process."""
        if self.backend_thread_status == BackendThreadStatus.RUNNING:
            logger.info('---------------------------------')
            logger.info('Stopping background process upon cancellation request')
            self.toggle_state_quick_compare = False
            self.toggle_state_sync_now = False
            self._cancel_event.set()
            if hasattr(self, 'telemetry_bar'):
                self.root.after(0, lambda: self.telemetry_bar.lbl_status.config(text='Stopping...'))
            if hasattr(self, '_active_sync') and self._active_sync is not None:
                with contextlib.suppress(Exception):
                    self._active_sync.cancel()
            if self.backend_thread_holder is not None:
                with contextlib.suppress(Exception):
                    self.backend_thread_holder.cancel()
            self.backend_thread_status = BackendThreadStatus.STOPPING

    def backend_watchdog(self):
        # Check if backend thread finished
        if self.backend_thread_holder is not None and not self.backend_thread_holder.is_alive():
            self.backend_thread_holder = None

        if self._gui_initialized:
            now = datetime.datetime.now()

            # If backend thread is in standby
            if self.backend_thread_status == BackendThreadStatus.STANDBY:
                next_appointment = self.get_next_appointment()
                if (
                    self.toggle_state_schedule
                    and next_appointment is not None
                    and next_appointment != self.last_realized_sync
                    and round_time_to_minutes(now) == round_time_to_minutes(next_appointment)
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
                    self._cancel_event.set()
                    if hasattr(self, '_active_sync') and self._active_sync is not None:
                        with contextlib.suppress(Exception):
                            self._active_sync.cancel()
                    if self.backend_thread_holder is None:
                        logger.warning('There is no background process to stop')
                    else:
                        try:
                            self.backend_thread_holder.cancel()
                        except Exception as e:
                            logger.error(f'Could not stop background process. Exception: {e}')
                    self.backend_thread_status = BackendThreadStatus.STOPPING

        delay = 1000 if self.backend_thread_status == BackendThreadStatus.STANDBY else 250
        self.root.after(delay, self.backend_watchdog)

    def call_backend_thread(self, also_sync: bool, timestamp: datetime.datetime):
        self.last_realized_sync = timestamp
        dirs = self.entry_paths.get_as_dir_pairs()
        if not dirs:
            logger.warning('No valid directory pairs configured. Please add at least one path pair.')
            self.backend_thread_status = BackendThreadStatus.STANDBY
            return

        exclusions = self.entry_exclusions.get()
        comparison_method = (
            CompareMethod.METADATA if self.radio_var_compare_method.get() == 'metadata' else CompareMethod.CONTENT
        )
        save_report = self.checkbox_var_save_report.get()
        reset_mirror = self.checkbox_var_reset_mirror.get() or self.checkbox_var_build_mirror.get()
        use_mirror = not reset_mirror
        build_mirror = reset_mirror

        if reset_mirror and not getattr(self, '_build_mirror_confirmed', False):
            confirm = messagebox.askyesno(
                'Caution',
                'Resetting the local mirror database will wipe existing target file records and rebuild them '
                'from disk.\n\nAre you sure you want to proceed with resetting the DB?',
                parent=self.root,
            )
            if not confirm:
                logger.info('Database reset cancelled by user.')
                self.toggle_state_quick_compare = False
                self.toggle_state_sync_now = False
                self.toggle_state_schedule = False
                self.checkbox_var_reset_mirror.set(False)
                self.checkbox_var_build_mirror.set(False)
                self.checkbox_var_use_mirror.set(True)
                self.backend_thread_status = BackendThreadStatus.STANDBY
                return
            self._build_mirror_confirmed = True

        confirm_sync = self.checkbox_var_confirm_sync.get()
        default_actions = self.checkbox_default_actions.get_as_actions()

        if hasattr(self, 'taskbar'):
            self.root.after(0, self.taskbar.clear)

        self._cancel_event.clear()
        self.backend_thread_holder = WorkerThread(
            target=self.backend_thread,
            cancel_event=self._cancel_event,
            args=(
                also_sync,
                dirs,
                exclusions,
                comparison_method,
                save_report,
                use_mirror,
                build_mirror,
                confirm_sync,
                default_actions,
            ),
            daemon=True,
        )
        self.backend_thread_holder.start()

    def backend_thread(
        self,
        also_sync: bool,
        dirs: list[DirectoryPair],
        exclusions: list[str],
        comparison_method: CompareMethod,
        save_report: bool,
        use_mirror: bool,
        build_mirror: bool,
        confirm_sync: bool,
        default_actions: list[Action],
    ):
        mirror = MirrorDatabase(exclusions=exclusions)

        if hasattr(self, 'telemetry_bar'):
            self.root.after(0, lambda: self.telemetry_bar.set_indeterminate('Scanning and comparing files...'))
        if hasattr(self, 'taskbar'):
            self.root.after(0, self.taskbar.set_indeterminate)

        compare = CompareDirs(
            mirror=mirror,
            dirs=dirs,
            exclusions=exclusions,
            comparison_method=comparison_method,
            save_report=save_report,
            use_mirror=use_mirror,
            increment_mirror=not build_mirror,
            rebuild_mirror=build_mirror,
            cancel_requested=self._cancel_event,
        )

        if self._cancel_event.is_set():
            logger.info('Operation stopped upon cancellation request')
            if hasattr(self, 'taskbar'):
                self.root.after(0, self.taskbar.clear)
            return

        has_error = False
        try:
            if also_sync:

                def _on_sync_progress(
                    action: str,
                    current: int,
                    total: int,
                    bytes_transferred: int,
                    current_file: str,
                    speed: str,
                ):
                    if hasattr(self, 'telemetry_bar'):
                        self.root.after(
                            0,
                            lambda: self.telemetry_bar.set_determinate(
                                action=action,
                                current=current,
                                total=total,
                                bytes_transferred=bytes_transferred,
                                current_file=current_file,
                                speed=speed,
                            ),
                        )
                    if hasattr(self, 'taskbar'):
                        self.root.after(0, lambda: self.taskbar.set_determinate(current, total))

                self._active_sync = SyncDirs(
                    files_to_copy=compare.files_to_copy,
                    files_to_move=compare.files_to_move,
                    files_to_delete=compare.files_to_delete,
                    mirror=mirror,
                    root_gui=self.root,
                    dirs=dirs,
                    default_actions=default_actions,
                    increment_mirror=not build_mirror,
                    confirm_sync=confirm_sync,
                    progress_callback=_on_sync_progress,
                    cancel_requested=self._cancel_event,
                )
                sync = self._active_sync
                cancelled = self._cancel_event.is_set() or (sync is not None and sync.cancel_requested.is_set())
                if not cancelled and sync is not None:
                    total_errors = getattr(sync, 'total_errors', 0)
                    total_successes = getattr(sync, 'total_successes', 0)

                    if total_errors > 0:
                        msg = (
                            f'Backup completed with {total_errors} error{"s" if total_errors != 1 else ""} '
                            f'({total_successes} file{"s" if total_successes != 1 else ""} synchronized).'
                        )
                        self.root.after(
                            0,
                            lambda m=msg: self.root.notify(
                                message=m,
                                title='FastMirror - Errors Encountered',
                            ),
                        )
                        if hasattr(self, 'taskbar'):
                            self.root.after(0, self.taskbar.set_error)
                    elif total_successes > 0:
                        msg = (
                            f'Backup synchronization completed successfully '
                            f'({total_successes} file{"s" if total_successes != 1 else ""} processed).'
                        )
                        self.root.after(
                            0,
                            lambda m=msg: self.root.notify(
                                message=m,
                                title='FastMirror',
                            ),
                        )
                    else:
                        msg = 'Synchronization finished: no files were modified.'
                        self.root.after(
                            0,
                            lambda m=msg: self.root.notify(
                                message=m,
                                title='FastMirror',
                            ),
                        )
            else:
                if not self._cancel_event.is_set():
                    summary_msg = (
                        f'Comparison completed: {len(compare.files_to_copy)} to copy, '
                        f'{len(compare.files_to_move)} to move, {len(compare.files_to_delete)} to delete.'
                    )
                    self.root.after(
                        0,
                        lambda: self.root.notify(
                            message=summary_msg,
                            title='FastMirror',
                        ),
                    )
        except Exception as e:
            has_error = True
            logger.error(f'Backend execution encountered an unexpected error: {e}')
            if hasattr(self, 'taskbar'):
                self.root.after(0, self.taskbar.set_error)
            raise
        finally:
            self._active_sync = None
            if hasattr(self, 'telemetry_bar'):
                self.root.after(0, lambda: self.telemetry_bar.reset('Ready'))
            if hasattr(self, 'taskbar') and not has_error:
                self.root.after(0, self.taskbar.clear)
            if build_mirror or self.checkbox_var_reset_mirror.get():
                self.root.after(0, lambda: self.checkbox_var_reset_mirror.set(False))
                self.root.after(0, lambda: self.checkbox_var_build_mirror.set(False))
                self.root.after(0, lambda: self.checkbox_var_use_mirror.set(True))
                self.root.after(0, lambda: setattr(self, '_build_mirror_confirmed', False))

        logger.debug('Processing thread was properly closed')

    def get_next_appointment(self) -> datetime.datetime | None:
        """Calculate and update the next scheduled backup appointment timestamp."""
        if not self.toggle_state_schedule:
            self.text_var_next_appointment.set('Schedule is not activated')
            if self._gui_initialized:
                self.update_tray_status()
            return None

        days = self.week_days.get_as_numbers()
        times = self.entry_times.get()
        now = datetime.datetime.now()

        next_appointment = calculate_next_run(
            days=days,
            times=times,
            now=now,
            last_run=self.last_realized_sync,
        )

        display_str = (
            next_appointment.strftime('%Y/%m/%d %H:%M:%S (%A)') if next_appointment is not None else 'No date found'
        )

        self.text_var_next_appointment.set(display_str)
        if self._gui_initialized:
            self.update_tray_status()
        return next_appointment

    def log_queue_watchdog(self):
        """Poll log queue every 100ms and batch-display queued records in text logger."""
        # Only inspect text widget position if records are actually pending in queue
        if not logger.log_queue.empty():
            was_at_bottom = False
            with contextlib.suppress(Exception):
                was_at_bottom = self.text_logger.yview()[1] >= 0.95

            batch: list[tuple[str, str]] = []
            while True:
                try:
                    record: LogRecord = logger.log_queue.get(block=False)
                except queue.Empty:
                    break
                else:
                    msg = logger.queue_handler.format(record)
                    batch.append((msg, record.levelname))

            if batch:
                self.text_logger.insert_batch(batch)

                # Smart auto-scroll: only follow to bottom if user has not scrolled up to inspect previous lines
                if self.toggle_auto_scroll.get() and was_at_bottom:
                    with contextlib.suppress(Exception):
                        self.text_logger.yview(tk.END)

        self.root.after(100, self.log_queue_watchdog)


if __name__ == '__main__':
    gui = Gui()
