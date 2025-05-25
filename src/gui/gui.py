import contextlib
import datetime
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from copy import deepcopy
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from core.backend import CompareDirs, SyncDirs
from core.file import CustomException
from core.mirror import MirrorDatabase
from gui.enums import BackendThreadStatus, TkinterCfgRelief, TkinterCfgStatus
from utils.logger import logger
from utils.utils import ROOT_DIR, CompareMethod, Counter, DirectoryPair, round_time_to_minutes


class KillableThread(threading.Thread):
    """A subclass of threading.Thread, with a kill() method."""

    def __init__(self, *args, **keywords):
        threading.Thread.__init__(self, *args, **keywords)
        self.killed = False

    def start(self):
        """Start the thread."""
        self.__run_backup = self.run
        self.run = self.__run  # Force the Thread to install our trace.
        threading.Thread.start(self)

    def __run(self):
        """Hacked run function, which installs the trace."""
        self.exc = None
        try:
            sys.settrace(self.globaltrace)
            self.__run_backup()
            self.run = self.__run_backup
        except CustomException as e:
            logger.critical(f'Processing thread was stopped abruptly because of exception: {e}')
        except Exception:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            msg = ''.join(traceback.format_tb(exc_tb))
            logger.critical(f'Processing thread was stopped abruptly because of exception {exc_type}:\n{msg}')

    def globaltrace(self, frame, why, arg):
        if why == 'call':
            return self.localtrace
        else:
            return None

    def localtrace(self, frame, why, arg):
        if self.killed and why == 'line':
            global gui
            logger.warning('Background process was stopped')
            raise SystemExit()
        return self.localtrace

    def kill(self):
        self.killed = True

    def join(self, *args):
        threading.Thread.join(self, *args)
        if self.exc:
            raise self.exc


class Gui:
    def __init__(self):
        # Initialize GUI
        self.root = tk.Tk()
        self.root.iconbitmap(os.path.join(os.path.dirname(__file__), 'smiley.ico'))
        self.root.title('Automatic Backup Tool')

        # Initialize variables
        self._gui_initialized = False
        self.last_realized_sync = None
        self._backend_thread_holder: KillableThread | None = None
        self._backend_thread_status = BackendThreadStatus.STANDBY
        self.toggle_auto_scroll = tk.BooleanVar()
        self.config_path = os.path.join(ROOT_DIR, 'config.json')
        self.check_box_value_default_actions = DefaultActions({})
        self.checkbox_value_use_mirror = tk.BooleanVar()
        self.checkbox_value_build_mirror = tk.BooleanVar()
        self.checkbox_value_metadata_comparison = tk.BooleanVar()
        self.checkbox_value_care_about_moved_files = tk.BooleanVar()
        self.checkbox_value_save_report = tk.BooleanVar()
        self.week_days = WeekDays()
        self.log_levels = LogLevels()
        self.entry_paths = EntryPaths()
        self.entry_exclusions = EntryExclusions()
        self.entry_times: EntryTimes()
        self.text_logger = TextLogger()
        self.text_var_status = tk.StringVar()
        self.text_var_next_appointment = tk.StringVar()

        # Create widgets
        self.create_widgets()

        # Start parallel threads
        self.backend_thread_holder = None
        self.backend_watchdog()
        self.log_queue_watchdog()

        # Try to load existing configuration
        self.load_config()

        # Run GUI
        self.root.mainloop()

    def set_gui_enable_state(self, general_state: bool, leave_sunken_enabled=False):
        def convert_child_state(child_, b: bool):
            with contextlib.suppress(Exception):
                child_.configure(state=TkinterCfgStatus.from_bool(b))

        def is_sunken_button(child_):
            try:
                return isinstance(child_, tk.Button) and child_.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value
            except:
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
        ignore_childs = [self.button_open_report, self.checkbox_auto_scroll, *self.frame_buttons_level.winfo_children()]

        for child in all_childs:
            if isinstance(child, tk.Label) or child in ignore_childs:
                continue
            convert_child_state(child, general_state)
            if leave_sunken_enabled and is_sunken_button(child):
                convert_child_state(child, True)

    @property
    def backend_thread_status(self):
        return self._backend_thread_status

    @backend_thread_status.setter
    def backend_thread_status(self, value):
        self._backend_thread_status = value
        self.text_var_status.set(value.value if isinstance(value, BackendThreadStatus) else str(value))

        # If thread is running, disable all unused buttons
        if value == BackendThreadStatus.STANDBY:
            self.set_gui_enable_state(general_state=True)
            # Release triggers when backend is done
            self.toggle_state_quick_compare = False
            self.toggle_state_sync_now = False
            self.toggle_state_schedule = False
        elif value == BackendThreadStatus.RUNNING:
            self.set_gui_enable_state(general_state=False, leave_sunken_enabled=True)
        elif value == BackendThreadStatus.STOPPING:
            self.set_gui_enable_state(general_state=False, leave_sunken_enabled=False)

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
            text={True: 'Schedule (ON)', False: 'Schedule (OFF)'}.get(value),
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
        label_next_appointment = tk.Label(frame_status, text='Next syncronization:')
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
        self.button_quick_compare.grid(row=1, column=1, sticky='nwe')
        self.toggle_state_quick_compare = False
        # ---
        self.button_open_report = tk.Button(
            self.frame_buttons, text='Open last report', command=self.button_action_open_report
        )
        self.button_open_report.grid(row=row_counter.get(increment=False), column=2, sticky='nwe')
        # ---
        label_syncronization = tk.Label(self.frame_buttons, text='Syncronization')
        label_syncronization.grid(row=row_counter.get(increment=True), column=0, sticky='w')
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
            self.frame_buttons, text='Save detailed report', variable=self.checkbox_value_save_report
        )
        checkbox_check_save_report.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        checkbox_build_local_mirror = tk.Checkbutton(
            self.frame_buttons,
            text='Rebuild local mirror',
            variable=self.checkbox_value_build_mirror,
            command=lambda: checkbox_use_local_mirror.deselect(),
        )
        checkbox_build_local_mirror.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        checkbox_use_local_mirror = tk.Checkbutton(
            self.frame_buttons,
            text='Use fast scan based on local mirror',
            variable=self.checkbox_value_use_mirror,
            command=lambda: checkbox_build_local_mirror.deselect(),
        )
        checkbox_use_local_mirror.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        self.checkbox_value_metadata_comparison.set(True)
        checkbox_metadata_comparison = tk.Checkbutton(
            self.frame_buttons,
            text='Use fast comparison based on metadata',
            variable=self.checkbox_value_metadata_comparison,
        )
        checkbox_metadata_comparison.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        checkbox_check_moved_files = tk.Checkbutton(
            self.frame_buttons, text='Try to guess moved files', variable=self.checkbox_value_care_about_moved_files
        )
        checkbox_check_moved_files.grid(row=row_counter.get(increment=True), column=1, columnspan=2, sticky='w')
        # ---
        label_default_actions = tk.Label(self.frame_buttons, text='Default actions')
        label_default_actions.grid(row=row_counter.get(increment=True), column=0, sticky='w')
        # ---
        self.frame_default_actions = tk.Frame(self.frame_buttons)
        self.frame_default_actions.grid(row=row_counter.get(increment=False), column=1, columnspan=2)
        # ---
        self.check_box_value_default_actions = DefaultActions({'copy': True, 'move': False, 'delete': False})
        # ---
        checkbox_default_action_copy = tk.Checkbutton(
            self.frame_default_actions, text='Copy', variable=self.check_box_value_default_actions.get_tk('copy')
        )
        checkbox_default_action_copy.grid(row=0, column=0, sticky='w')
        # ---
        checkbox_default_action_move = tk.Checkbutton(
            self.frame_default_actions, text='Move', variable=self.check_box_value_default_actions.get_tk('move')
        )
        checkbox_default_action_move.grid(row=0, column=1, sticky='w')
        # ---
        checkbox_default_action_delete = tk.Checkbutton(
            self.frame_default_actions, text='Delete', variable=self.check_box_value_default_actions.get_tk('delete')
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
            self.frame_buttons, text='Auto-scroll', variable=self.toggle_auto_scroll
        )
        self.checkbox_auto_scroll.grid(row=row_counter.get(increment=False), column=2, sticky='nw')
        # ---
        self.frame_buttons_level = tk.Frame(self.frame_buttons)
        self.frame_buttons_level.grid(row=row_counter.get(increment=False), column=1, sticky='nw')
        # ---
        check_box_log_level = {}

        def set_log_levels():
            self.text_logger.set_log_levels(self.log_levels.get())

        for i, level in enumerate(self.log_levels.options):
            check_box_log_level[level] = tk.Checkbutton(
                self.frame_buttons_level, text=level, command=set_log_levels, variable=self.log_levels.checkboxes[level]
            )
            check_box_log_level[level].grid(row=i, column=0, sticky='w')

        # FINISH FRAME OF BUTTONS (DOWN-LEFT)

        # START FRAME OF LOG (DOWN-RIGHT)

        frame_log = tk.Frame(self.root)
        frame_log.grid(row=1, column=1, sticky='nsw', padx=10, pady=10)

        self.text_logger = TextLogger(frame_log, state=TkinterCfgStatus.DISABLED.value, height=31, width=140)
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
            self.text_var_next_appointment.set('')
            self.text_var_status.set('')
            self.entry_paths.set([])
            self.entry_exclusions.reset()
            self.week_days.set([])
            self.entry_times.set([])
            self.check_box_value_default_actions.reset()
            self.log_levels.reset()
            for checkbox in [
                self.checkbox_value_use_mirror,
                self.checkbox_value_build_mirror,
                self.checkbox_value_metadata_comparison,
                self.checkbox_value_care_about_moved_files,
                self.checkbox_value_save_report,
            ]:
                checkbox.set(False)
            with contextlib.suppress(Exception):
                os.remove(self.config_path)
            logger.info('GUI configuration was reseted')

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
                'check_box_value_default_actions',
                'entry_exclusions',
                'log_levels',
                'checkbox_value_use_mirror',
                'checkbox_value_build_mirror',
                'checkbox_value_metadata_comparison',
                'checkbox_value_care_about_moved_files',
                'checkbox_value_save_report',
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
                    gui_element = getattr(self, name)
                    gui_element.set(value)
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
            os.startfile(last_filepath)
        else:
            logger.error(
                f'Could not open last report because no report was found in directory {os.path.realpath(logger.log_dir)}'
            )

    def button_action_quick_compare(self):
        self.toggle_state_quick_compare = not self.toggle_state_quick_compare

    def button_action_sync_now(self):
        self.toggle_state_sync_now = not self.toggle_state_sync_now

    def button_action_schedule_sync(self):
        self.toggle_state_schedule = not self.toggle_state_schedule

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
                    self.call_backend_thread(True, next_appointment)

                elif self.toggle_state_quick_compare:
                    self.call_backend_thread(False, now)

                elif self.toggle_state_sync_now:
                    self.call_backend_thread(True, now)

            # If backend thread is running but a stop command was requested
            elif self.backend_thread_status == BackendThreadStatus.RUNNING and not (
                self.toggle_state_quick_compare or self.toggle_state_sync_now or self.toggle_state_schedule
            ):
                try:
                    logger.info('---------------------------------')
                    logger.info('Trying to stop background process')
                    self.backend_thread_status = BackendThreadStatus.STOPPING
                    self.backend_thread_holder.kill()
                except Exception as e:
                    self.backend_thread_status = BackendThreadStatus.RUNNING
                    logger.error(f'Could not stop background process. Exception: {e}')

        delay = 1000 if self.backend_thread_status == BackendThreadStatus.STANDBY else 50
        self.root.after(delay, self.backend_watchdog)

    def call_backend_thread(self, also_sync: bool, timestamp: datetime.datetime):
        self.last_realized_sync = timestamp
        self.backend_thread_holder = KillableThread(
            target=self.backend_thread,
            args=(
                also_sync,
                timestamp,
            ),
        )
        self.backend_thread_holder.start()

    def backend_thread(self, also_sync: bool, timestamp: datetime.datetime):
        if self.checkbox_value_save_report.get():
            timestamp_str = timestamp.strftime('%Y-%m-%d_%H-%M-%S')
            save_path = os.path.join(logger.log_dir, 'compare_report_' + timestamp_str + '.xlsx')
        else:
            save_path = ''

        mirror = MirrorDatabase(exclusions=self.entry_exclusions.get())

        compare = CompareDirs(
            mirror=mirror,
            dirs=self.entry_paths.get_as_dir_pairs(),
            exclusions=self.entry_exclusions.get(),
            comparison_method=CompareMethod.METADATA
            if self.checkbox_value_metadata_comparison.get()
            else CompareMethod.CONTENT,
            care_about_moved_files=self.checkbox_value_care_about_moved_files.get(),
            save_report_path=save_path,
            use_mirror=self.checkbox_value_use_mirror.get(),
            increment_mirror=not self.checkbox_value_build_mirror.get(),
            rebuild_mirror=self.checkbox_value_build_mirror.get(),
        )

        if also_sync:
            default_actions = self.check_box_value_default_actions.get_actions()
            SyncDirs(
                files_to_copy=compare.files_to_copy,
                files_to_move=compare.files_to_move,
                files_to_delete=compare.files_to_delete,
                mirror=mirror,
                root_gui=self.root,
                dirs=self.entry_paths.get_as_dir_pairs(),
                default_actions=default_actions,
                increment_mirror=not self.checkbox_value_build_mirror.get(),
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
                record = logger.log_queue.get(block=False)
            except queue.Empty:
                break
            else:
                msg = logger.queue_handler.format(record)
                self.text_logger.insert(msg, record.levelname)

                # Autoscroll to the bottom
                if self.toggle_auto_scroll.get():
                    self.text_logger.yview(tk.END)

        self.root.after(1000, self.log_queue_watchdog)


class TextLogger(ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lines = []
        self.log_levels = []
        self.limit_lines = 50000
        self.configure(font='TkFixedFont')
        self.tag_config('DEBUG', foreground='gray')
        self.tag_config('INFO', foreground='black')
        self.tag_config('WARNING', foreground='orange')
        self.tag_config('ERROR', foreground='red')
        self.tag_config('CRITICAL', foreground='red', underline=1)

    def set_log_levels(self, levels: list[str]):
        self.log_levels = levels
        self._rewrite()

    def insert(self, *args, **kwargs):
        message, tag = args
        self.lines.append((message, tag))
        if tag in self.log_levels:
            self.configure(state=TkinterCfgStatus.NORMAL.value)
            super().insert(tk.END, message + '\n', tag)
            self.configure(state=TkinterCfgStatus.DISABLED.value)
            self._check_num_lines()

    def _check_num_lines(self):
        # Remove excessive lines
        lines = self.get('1.0', tk.END).splitlines()
        if len(lines) > self.limit_lines * 1.1:
            self._rewrite()

    def _rewrite(self):
        self.configure(state=TkinterCfgStatus.NORMAL.value)
        self.delete('1.0', tk.END)
        for message, tag in self.lines[-self.limit_lines :]:
            if tag in self.log_levels:
                super().insert(tk.END, message + '\n', tag)
        self.configure(state=TkinterCfgStatus.DISABLED.value)


class LogLevels:
    options = 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'

    def __init__(self):
        self.checkboxes = {option: tk.BooleanVar() for option in self.options}
        self.reset()

    def reset(self):
        for k, _v in self.checkboxes.items():
            if k in ['DEBUG']:
                self.checkboxes[k].set(False)
            else:
                self.checkboxes[k].set(True)

    def set(self, values: list[str]):
        for value, _status in self.checkboxes.items():
            self.checkboxes[value].set(True) if value in values else self.checkboxes[value].set(False)

    def get(self) -> list[str]:
        return [value for value, status in self.checkboxes.items() if status.get()]


class WeekDays:
    options = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

    def __init__(self):
        self.checkboxes = {day: tk.BooleanVar() for day in self.options}

    def set(self, values: list[str]):
        for value, _status in self.checkboxes.items():
            self.checkboxes[value].set(True) if value in values else self.checkboxes[value].set(False)

    def get(self) -> list[str]:
        return [value for value, status in self.checkboxes.items() if status.get()]

    def get_as_numbers(self) -> list[int]:
        return [self.options.index(day) for day in self.get()]


class EntryTimes(ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get(self, *args, **kwargs):
        raw: str
        raw = super().get('1.0', tk.END)
        times = raw.splitlines()
        times = [t for t in times if self.is_hh_mm(t)]
        return times

    def set(self, times):
        times = [t for t in times if self.is_hh_mm(t)]
        raw = '\n'.join(times)
        super().delete('1.0', tk.END)  # delete current text
        super().insert('1.0', raw)  # add at line 1, col 0

    @staticmethod
    def is_hh_mm(t):
        try:
            time.strptime(t, '%H:%M')
        except:
            if t.strip() != '':
                logger.warning(f'Time entry "{t}" was ignored because it does not match the format hh:mm')
            return False
        else:
            return True


class EntryExclusions(tk.Entry):
    def __init__(self, *args, **kwargs):
        self.var = tk.StringVar()
        super().__init__(*args, textvariable=self.var, **kwargs)
        self.reset()

    def get(self, *args, **kwargs) -> list[str]:
        raw = self.var.get()
        exclusions = list({x.strip().replace('/', '\\') for x in raw.split(',') if x.strip() != ''})
        return exclusions

    def set(self, exclusions: list[str]):
        raw = ','.join(exclusions)
        self.var.set(raw)

    def reset(self):
        self.set([r'D:\$RECYCLE.BIN', r'\~$'])


class EntryPaths(ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get(self, *args, **kwargs) -> list[tuple[str, str]]:
        raw: str
        raw = super().get('1.0', tk.END)
        lines = raw.splitlines()
        paths = list({self.parse_line(line) for line in lines})
        paths = [pair for pair in paths if pair is not None]
        return paths

    def get_as_dir_pairs(self) -> list[DirectoryPair]:
        return [DirectoryPair(source=pair[0], target=pair[1]) for pair in self.get()]

    def add(self, pair: tuple[str, str]):
        self.set(self.get() + [pair])

    def set(self, paths: list[tuple[str, str]] | list[DirectoryPair]):
        paths = [(pair.source, pair.target) if isinstance(pair, DirectoryPair) else pair for pair in paths]
        raw = '\n'.join([f'{pair[0]} -> {pair[1]}' for pair in paths])
        super().delete('1.0', tk.END)  # delete current text
        super().insert('1.0', raw)  # add at line 1, col 0

    @staticmethod
    def parse_line(raw: str) -> None | tuple[str, str]:
        try:
            source, target = raw.split(' -> ')
            if os.path.isdir(source) and os.path.isdir(target):
                return (os.path.realpath(source), os.path.realpath(target))
            else:
                return None
        except:
            return None


class DefaultActions:
    def __init__(self, d):
        self.data = deepcopy(d)
        self.data_as_tkinter = {k: tk.BooleanVar() for k, v in self.data.items()}
        self._set_tkinter_data()

    def get(self):
        for k, _v in self.data_as_tkinter.items():
            self.data[k] = self.data_as_tkinter[k].get()
        return self.data

    def get_tk(self, k):
        return self.data_as_tkinter[k]

    def __setitem__(self, k, v):
        self.data[k] = v
        self._set_tkinter_data()

    def set(self, obj):
        self.data = obj
        self._set_tkinter_data()

    def _set_tkinter_data(self):
        for k, v in self.data.items():
            self.data_as_tkinter[k].set(v)

    def get_actions(self) -> list[str]:
        return [k for k, v in self.get().items() if v]

    def reset(self):
        self['copy'] = True
        self['move'] = False
        self['delete'] = False


if __name__ == '__main__':
    gui = Gui()
