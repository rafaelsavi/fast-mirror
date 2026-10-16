import contextlib
import datetime
import json
import os
import queue
import tkinter as tk
from logging import LogRecord
from tkinter import filedialog, messagebox

from core.backend import CompareDirs, SyncDirs
from core.mirror import MirrorDatabase
from gui.custom_gui import TrayableTk
from gui.enums import BackendThreadStatus, TkinterCfgRelief, TkinterCfgState
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
from gui.worker_thread import KillableThread
from utils.constants import ROOT_DIR
from utils.logger import logger
from utils.utils import CompareMethod, DirectoryPair, round_time_to_minutes


class Counter:
    def __init__(self, init_value=-1):
        self.v = init_value

    def get(self, increment=True) -> int:
        if increment:
            self.v += 1
        return self.v


class Gui:
    def __init__(self):
        # Initialize GUI
        self.root = TrayableTk()
        self.root.resizable(False, False)
        self.root.iconbitmap(os.path.join(os.path.dirname(__file__), 'smiley.ico'))
        self.root.title('Automatic Backup Tool')

        self.config_path = os.path.join(ROOT_DIR, 'config.json')

        # State variables
        self._gui_initialized = False
        self.last_realized_sync = None
        self._backend_thread_holder: KillableThread | None = None
        self._backend_thread_status = BackendThreadStatus.STANDBY
        self._current_run_trigger: str | None = None

        # GUI elements
        self.toggle_auto_scroll = tk.BooleanVar()
        self.checkbox_var_use_mirror = tk.BooleanVar()
        self.checkbox_var_build_mirror = tk.BooleanVar()
        self.checkbox_var_metadata_comparison = tk.BooleanVar()
        self.checkbox_var_confirm_sync = tk.BooleanVar()
        self.checkbox_var_save_report = tk.BooleanVar()
        self.text_var_status = tk.StringVar()
        self.text_var_next_appointment = tk.StringVar()

        # Custom widgets
        self.checkbox_default_actions = DefaultActions()
        self.text_logger = TextLogger()
        self.week_days = WeekDays()
        self.log_levels = LogLevels()
        self.entry_paths = EntryPaths()
        self.entry_exclusions = EntryExclusions()
        self.entry_times = EntryTimes()

        self.create_widgets()

        # Start parallel threads
        self.backend_thread_holder = None
        self.backend_watchdog()
        self.log_queue_watchdog()

        # Try to load existing configuration
        self.load_config()

        # Run GUI
        self.root.mainloop()

    @property
    def backend_thread_status(self):
        return self._backend_thread_status

    @backend_thread_status.setter
    def backend_thread_status(self, status: BackendThreadStatus):
        self._backend_thread_status = status
        self.text_var_status.set(status.value)

        # If thread is running, disable all unused buttons
        if status == BackendThreadStatus.STANDBY:
            self.set_gui_enable_state(general_state=True)
            # Release triggers when backend is done
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
            except Exception as e:
                raise ValueError(f'Could not check if {child_} is a sunken button. Exception: {e}') from e

        all_childs = [
            *self.frame_paths.winfo_children(),
            self.entry_paths,
            self.entry_exclusions,
            *self.frame_default_actions.winfo_children(),
            *self.frame_buttons_scheduler_days.winfo_children(),
            *self.frame_buttons.winfo_children(),
            self.entry_times,
        ]
        ignore_childs = [self.button_open_report, self.checkbox_auto_scroll, *self.frame_buttons_level.winfo_children()]

        for child in all_childs:
            if isinstance(child, tk.Label) or child in ignore_childs:
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

        # Update text of status widget
        self.backend_thread_status = BackendThreadStatus.RUNNING if thread is not None else BackendThreadStatus.STANDBY

    @property
    def toggle_state_schedule(self):
        return self.button_schedule_sync.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_schedule.setter
    def toggle_state_schedule(self, value: bool):
        self.button_schedule_sync.config(
            relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value,
            text='Schedule (ON)' if value else 'Schedule (OFF)',
        )

    @property
    def toggle_state_quick_compare(self):
        return self.button_quick_compare.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_quick_compare.setter
    def toggle_state_quick_compare(self, value: bool):
        self.button_quick_compare.config(
            relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value
        )

    @property
    def toggle_state_sync_now(self):
        return self.button_sync_now.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

    @toggle_state_sync_now.setter
    def toggle_state_sync_now(self, value: bool):
        self.button_sync_now.config(relief=TkinterCfgRelief.SUNKEN.value if value else TkinterCfgRelief.RAISED.value)

    def create_widgets(self):
        # START FRAME OF STATUS (UP-LEFT)

        frame_status = tk.Frame(self.root)
        frame_status.grid(row=0, column=0, padx=10, pady=10, sticky='nsw')
        # ---
        label_status = tk.Label(frame_status, text='Overall status:')
        label_status.grid(row=0, column=0, sticky='w')
        # ---
        text_status = tk.Label(frame_status, anchor='w', textvariable=self.text_var_status)
        text_status.grid(row=0, column=1, sticky='w')
        # ---
        label_next_appointment = tk.Label(frame_status, text='Next synchronization:')
        label_next_appointment.grid(row=1, column=0, sticky='w')
        # ---
        text_next_appointment = tk.Label(
            frame_status, anchor='w', justify=tk.LEFT, textvariable=self.text_var_next_appointment
        )
        text_next_appointment.grid(row=1, column=1, sticky='w')

        # FINISH FRAME OF STATUS (UP-LEFT)

        # START FRAME OF PATHS (UP-RIGHT)

        self.frame_paths = tk.Frame(self.root)
        self.frame_paths.grid(row=0, column=1, padx=10, pady=10, sticky='we')
        # ---
        label_path_selection = tk.Label(self.frame_paths, text='Paths')
        label_path_selection.grid(row=0, column=0, sticky='w')
        # ---
        button_add_path = tk.Button(self.frame_paths, text='Add new', command=self.button_action_add_path)
        button_add_path.grid(row=0, column=1, sticky='nsw', padx=10)
        # ---
        self.entry_paths = EntryPaths(self.frame_paths, width=124, height=3)
        self.entry_paths.grid(row=0, column=2, sticky='we', padx=10)
        # ---
        label_path_exclusions = tk.Label(self.frame_paths, text='Exclusions')
        label_path_exclusions.grid(row=1, column=0, columnspan=2, sticky='w')
        # ---
        self.entry_exclusions = EntryExclusions(self.frame_paths, width=124)
        self.entry_exclusions.grid(row=1, column=2, sticky='we', padx=10)

        # FINISH FRAME OF PATHS (UP-RIGHT)

        # START FRAME OF BUTTONS (DOWN-LEFT)

        self.frame_buttons = tk.Frame(self.root)
        self.frame_buttons.grid(row=1, column=0, padx=10, pady=10, sticky='nw')
        row_counter = Counter()
        # ---
        label_configuration = tk.Label(self.frame_buttons, text='GUI Configuration')
        label_configuration.grid(row=row_counter.get(increment=True), column=0, sticky='nwe')
        # ---
        button_new_config = tk.Button(
            self.frame_buttons, text='Reset', command=self.button_action_reset_config, width=12
        )
        button_new_config.grid(row=row_counter.get(increment=False), column=1, sticky='nwe')
        # ---
        button_save_config = tk.Button(
            self.frame_buttons, text='Save', command=self.button_action_save_config, width=12
        )
        button_save_config.grid(row=row_counter.get(increment=False), column=2, sticky='nwe')
        # ---
        label_compare = tk.Label(self.frame_buttons, text='Compare')
        label_compare.grid(row=row_counter.get(increment=True), column=0, sticky='w')
        # ---
        self.button_quick_compare = tk.Button(
            self.frame_buttons, text='Start', command=self.button_action_quick_compare
        )
        self.button_quick_compare.grid(row=row_counter.get(increment=False), column=1, sticky='nwe')
        self.toggle_state_quick_compare = False
        # ---
        self.button_open_report = tk.Button(
            self.frame_buttons, text='Open last report', command=self.button_action_open_report
        )
        self.button_open_report.grid(row=row_counter.get(increment=False), column=2, sticky='nwe')
        # ---
        label_synchronization = tk.Label(self.frame_buttons, text='Synchronization')
        label_synchronization.grid(row=row_counter.get(increment=True), column=0, sticky='w')
        # ---
        self.button_sync_now = tk.Button(self.frame_buttons, text='Sync now', command=self.button_action_sync_now)
        self.button_sync_now.grid(row=row_counter.get(increment=False), column=1, sticky='nwe')
        self.toggle_state_sync_now = False
        # ---
        self.button_schedule_sync = tk.Button(
            self.frame_buttons,
            text='Schedule (OFF)',
            relief=TkinterCfgRelief.RAISED.value,
            command=self.button_action_schedule_sync,
        )
        self.button_schedule_sync.grid(row=row_counter.get(increment=False), column=2, sticky='nwe')
        self.toggle_state_schedule = False
        # ---
        checkbox_check_save_report = tk.Checkbutton(
            self.frame_buttons, text='Save detailed report', variable=self.checkbox_var_save_report
        )
        checkbox_check_save_report.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        checkbox_build_local_mirror = tk.Checkbutton(
            self.frame_buttons,
            text='Rebuild local mirror',
            variable=self.checkbox_var_build_mirror,
            command=lambda: checkbox_use_local_mirror.deselect(),
        )
        checkbox_build_local_mirror.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        self.checkbox_var_use_mirror.set(True)
        checkbox_use_local_mirror = tk.Checkbutton(
            self.frame_buttons,
            text='Use fast scan based on local mirror',
            variable=self.checkbox_var_use_mirror,
            command=lambda: checkbox_build_local_mirror.deselect(),
        )
        checkbox_use_local_mirror.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        self.checkbox_var_metadata_comparison.set(True)
        checkbox_metadata_comparison = tk.Checkbutton(
            self.frame_buttons,
            text='Use fast comparison based on metadata',
            variable=self.checkbox_var_metadata_comparison,
        )
        checkbox_metadata_comparison.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        self.checkbox_var_confirm_sync.set(True)
        checkbox_confirm_sync = tk.Checkbutton(
            self.frame_buttons, text='Request confirmation before sync', variable=self.checkbox_var_confirm_sync
        )
        checkbox_confirm_sync.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        label_default_actions = tk.Label(self.frame_buttons, text='Default actions')
        label_default_actions.grid(row=row_counter.get(increment=True), column=0, sticky='w')
        # ---
        self.frame_default_actions = tk.Frame(self.frame_buttons)
        self.frame_default_actions.grid(row=row_counter.get(increment=False), column=1, columnspan=2)
        # ---
        checkbox_default_action_copy = tk.Checkbutton(
            self.frame_default_actions,
            text='Copy',
            variable=self.checkbox_default_actions.get_var(Action.COPY),
        )
        checkbox_default_action_copy.grid(row=0, column=0, sticky='w')
        # ---
        checkbox_default_action_move = tk.Checkbutton(
            self.frame_default_actions,
            text='Move',
            variable=self.checkbox_default_actions.get_var(Action.MOVE),
        )
        checkbox_default_action_move.grid(row=0, column=1, sticky='w')
        # ---
        checkbox_default_action_delete = tk.Checkbutton(
            self.frame_default_actions,
            text='Delete',
            variable=self.checkbox_default_actions.get_var(Action.DELETE),
        )
        checkbox_default_action_delete.grid(row=0, column=2, sticky='w')
        # ---
        label_scheduler = tk.Label(self.frame_buttons, text='Schedule')
        label_scheduler.grid(row=row_counter.get(increment=True), column=0, sticky='w')
        # ---
        self.frame_buttons_scheduler = tk.Frame(self.frame_buttons)
        self.frame_buttons_scheduler.grid(row=row_counter.get(increment=False), column=1, columnspan=2)
        # ---
        self.frame_buttons_scheduler_days = tk.Frame(self.frame_buttons_scheduler)
        self.frame_buttons_scheduler_days.grid(row=0, column=0, sticky='nw', padx=10)
        # ---
        label_week_days = tk.Label(self.frame_buttons_scheduler_days, text='Week days')
        label_week_days.grid(row=0, column=0, sticky='w')
        # ---
        check_box_week_days = {}
        for i, day in enumerate(self.week_days.options):
            check_box_week_days[day] = tk.Checkbutton(
                self.frame_buttons_scheduler_days, text=day, variable=self.week_days.checkboxes[day]
            )
            check_box_week_days[day].grid(row=1 + i, column=0, sticky='w')

        frame_buttons_scheduler_times = tk.Frame(self.frame_buttons_scheduler)
        frame_buttons_scheduler_times.grid(row=0, column=1, sticky='ne', padx=10)
        # ---
        label_times = tk.Label(frame_buttons_scheduler_times, text='Times')
        label_times.grid(row=0, column=0, sticky='w')
        # ---
        self.entry_times = EntryTimes(frame_buttons_scheduler_times, width=5, height=5)
        self.entry_times.grid(row=1, column=0)
        # ---
        label_log_options = tk.Label(self.frame_buttons, text='Log window')
        label_log_options.grid(row=row_counter.get(increment=True), column=0, sticky='w')
        # ---
        self.toggle_auto_scroll.set(True)
        self.checkbox_auto_scroll = tk.Checkbutton(
            self.frame_buttons,
            text='Auto-scroll',
            variable=self.toggle_auto_scroll,
            command=self.button_action_toggle_auto_scroll,
        )
        self.checkbox_auto_scroll.grid(row=row_counter.get(increment=False), column=2, sticky='nw')
        # ---
        self.frame_buttons_level = tk.Frame(self.frame_buttons)
        self.frame_buttons_level.grid(row=row_counter.get(increment=False), column=1, sticky='nw')
        # ---
        check_box_log_level: dict[str, tk.Checkbutton] = {}

        for i, level in enumerate(self.log_levels.options):
            check_box_log_level[level] = tk.Checkbutton(
                self.frame_buttons_level,
                text=level,
                command=self.button_action_update_log_levels,
                variable=self.log_levels.checkboxes[level],
            )
            check_box_log_level[level].grid(row=i, column=0, sticky='w')

        # FINISH FRAME OF BUTTONS (DOWN-LEFT)

        # START FRAME OF LOG (DOWN-RIGHT)

        frame_log = tk.Frame(self.root)
        frame_log.grid(row=1, column=1, sticky='nsw', padx=10, pady=10)

        self.text_logger = TextLogger(frame_log, state=TkinterCfgState.DISABLED.value, height=33, width=140)
        self.text_logger.set_log_levels(self.log_levels.get())
        self.text_logger.grid(row=0, column=0, sticky='nsew')

        # FINISH FRAME OF LOG (DOWN-RIGHT)

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
        if source != '':
            target = filedialog.askdirectory(title='Select destination folder')
            if target != '':
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

            # If backend thread is not running
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

            # If backend thread is running but a stop command was requested
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

        if also_sync:
            default_actions = self.checkbox_default_actions.get_as_actions()
            SyncDirs(
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

        logger.debug('Processing thread was properly closed')

    def get_next_appointment(self):
        string = 'Schedule is not activated'
        next_appointment = None

        if self.toggle_state_schedule:
            days = self.week_days.get_as_numbers()
            times = self.entry_times.get()

            # Get now rounded on minutes
            now = round_time_to_minutes(datetime.datetime.now())

            # Iterate over the number of minutes in a week
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
        """Check every 100ms if there is a new message in the queue to be displayed"""
        while True:
            try:
                record: LogRecord = logger.log_queue.get(block=False)
            except queue.Empty:
                break
            else:
                msg = logger.queue_handler.format(record)
                self.text_logger.insert(msg, record.levelname)

                # Autoscroll to the bottom
                if self.toggle_auto_scroll.get():
                    self.text_logger.yview(tk.END)

        self.root.after(100, self.log_queue_watchdog)


if __name__ == '__main__':
    gui = Gui()
