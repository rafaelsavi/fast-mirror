import contextlib
import datetime
import json
import os
import queue
import threading
import tkinter as tk
from logging import LogRecord
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

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
from gui.icons import apply_window_icon, conceal_window, reveal_window
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
from utils.constants import CONFIG_PATH, WINDOW_TITLE
from utils.logger import logger
from utils.profile_manager import ProfileManager, sanitize_profile_name
from utils.utils import CompareMethod, DirectoryPair, round_time_to_minutes


class Gui:
    """Main application orchestrator coordinating GUI panels, scheduler watchdogs, and backend execution."""

    def __init__(self, config_path: str | None = None, profile_name: str | None = None):
        # Initialize GUI window
        self.root = TrayableTk()
        conceal_window(self.root)
        apply_window_icon(self.root)
        self.root.title(WINDOW_TITLE)

        self._config_path = Path(config_path or CONFIG_PATH).resolve()
        self.profile_manager = ProfileManager(config_path=self._config_path)
        self.profile_manager.ensure_profiles_dir()
        self.active_profile_name = profile_name or self.profile_manager.get_active_profile_name()
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
        self._last_saved_config_vars: dict[str, Any] | None = None

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
        self.actions_panel.set_profiles(self.profile_manager.list_profiles(), self.active_profile_name)

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
            on_exit_check=self.confirm_exit_unsaved_changes,
        )
        self.update_tray_status()

        # Start parallel threads
        self.backend_thread_holder = None
        self.backend_watchdog()
        self.log_queue_watchdog()

        # Load existing configuration
        self._snapshot_saved_config()
        self.load_config()

        # Center main window on primary display and smoothly reveal
        self._center_and_reveal_root()

        # Run GUI loop
        self.root.mainloop()

    def _center_and_reveal_root(self):
        """Center the main window on display and reveal it smoothly without top-left flicker."""
        try:
            self.root.update_idletasks()
            w = max(self.root.winfo_reqwidth(), 1200)
            h = max(self.root.winfo_reqheight(), 750)
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            pos_x = max(0, (sw - w) // 2)
            pos_y = max(0, (sh - h) // 2)
            self.root.geometry(f'{w}x{h}+{pos_x}+{pos_y}')
        except Exception:
            pass
        reveal_window(self.root)

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
    def config_path(self) -> str:
        return str(self._config_path)

    @config_path.setter
    def config_path(self, value: str | Path):
        self._config_path = Path(value).resolve()
        if hasattr(self, 'profile_manager'):
            self.profile_manager.config_path = self._config_path
            self.profile_manager.profiles_dir = self._config_path.parent / 'profiles'

    @property
    def toggle_state_schedule(self) -> bool:
        if hasattr(self, 'schedule_panel') and hasattr(self.schedule_panel, 'toggle_state_schedule'):
            return self.schedule_panel.toggle_state_schedule
        if hasattr(self, 'actions_panel') and hasattr(self.actions_panel, 'button_schedule_sync'):
            return self.actions_panel.button_schedule_sync.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value
        return False

    @toggle_state_schedule.setter
    def toggle_state_schedule(self, value: bool):
        if hasattr(self, 'schedule_panel') and hasattr(self.schedule_panel, 'toggle_state_schedule'):
            self.schedule_panel.toggle_state_schedule = value
        if hasattr(self, 'actions_panel') and hasattr(self.actions_panel, 'button_schedule_sync'):
            with contextlib.suppress(Exception):
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
            on_load_config=self.button_action_load_config,
            on_load_config_from_file=self.button_action_load_config_from_file,
            on_save_config=self.button_action_save_config,
            on_save_config_as=self.button_action_save_config_as,
            on_select_profile=self.button_action_switch_profile,
            on_new_profile=self.button_action_new_profile,
            on_delete_profile=self.button_action_delete_profile,
            on_clone_profile=self.button_action_clone_profile,
            on_rename_profile=self.button_action_rename_profile,
            on_open_profiles_dir=self.button_action_open_profiles_dir,
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
            on_toggle_schedule=self.on_schedule_panel_toggled,
            text_var_next_appointment=self.text_var_next_appointment,
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

        # Keyboard shortcuts for configuration workflows
        self.root.bind('<Control-s>', lambda e: self.button_action_save_config())
        self.root.bind('<Control-S>', lambda e: self.button_action_save_config())
        self.root.bind('<Control-o>', lambda e: self.button_action_load_config_from_file())
        self.root.bind('<Control-O>', lambda e: self.button_action_load_config_from_file())
        self.root.bind('<Control-r>', lambda e: self.button_action_load_config())
        self.root.bind('<Control-R>', lambda e: self.button_action_load_config())

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
        style.configure('Accent.TButton', font=('Segoe UI', 9))
        style.configure('ActiveToggle.TButton', font=('Segoe UI', 9))
        style.configure('Stop.TButton', font=('Segoe UI', 9), foreground='#cc0000')
        style.map(
            'Stop.TButton',
            foreground=[('disabled', '#888888'), ('pressed', '#990000'), ('active', '#cc0000')],
        )

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

    def _get_current_config_vars(self) -> dict[str, Any]:
        """Extract all current GUI configuration values into a dictionary."""
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
            'toggle_auto_scroll',
        ]
        config_vars: dict[str, Any] = {}
        for name in config_var_names:
            if name == 'checkbox_var_reset_mirror':
                config_vars[name] = False  # Reset mirror is a one-shot option
            elif name == 'entry_paths' and hasattr(self, 'entry_paths'):
                if hasattr(self.entry_paths, 'get_configured_pairs'):
                    config_vars[name] = self.entry_paths.get_configured_pairs()
                else:
                    config_vars[name] = self.entry_paths.get()
            elif hasattr(self, name):
                config_vars[name] = getattr(self, name).get()
        return config_vars

    def _get_blank_config_vars(self) -> dict[str, Any]:
        """Return a clean default configuration dictionary with no configured directory pairs."""
        return {
            'entry_paths': [],
            'week_days': [],
            'entry_times': [],
            'entry_exclusions': ['$RECYCLE.BIN', r'\~$'],
            'log_levels': ['INFO', 'WARNING', 'ERROR', 'CRITICAL'],
            'checkbox_default_actions': ['copy'],
            'radio_var_compare_method': 'metadata',
            'checkbox_var_reset_mirror': False,
            'checkbox_var_use_mirror': True,
            'checkbox_var_build_mirror': False,
            'checkbox_var_metadata_comparison': True,
            'checkbox_var_confirm_sync': True,
            'checkbox_var_save_report': False,
            'toggle_auto_scroll': True,
        }

    def _apply_config_vars_to_gui(self, config_vars: dict[str, Any]):
        """Populate GUI widgets and control variables from a dictionary."""
        for name, value in config_vars.items():
            if name == 'radio_var_compare_method':
                self.radio_var_compare_method.set(value)
            elif name == 'checkbox_var_reset_mirror':
                self.checkbox_var_reset_mirror.set(False)
            elif hasattr(self, name):
                gui_element = getattr(self, name)
                if isinstance(gui_element, tk.BooleanVar):
                    gui_element.set(bool(value))
                else:
                    gui_element.set(value)

        if 'radio_var_compare_method' not in config_vars and 'checkbox_var_metadata_comparison' in config_vars:
            self.radio_var_compare_method.set(
                'metadata' if config_vars['checkbox_var_metadata_comparison'] else 'content'
            )

        self.text_logger.set_log_levels(self.log_levels.get())
        if hasattr(self, 'paths_panel'):
            with contextlib.suppress(Exception):
                self.paths_panel._update_pair_stats()
                self.paths_panel._update_exclusion_count()

    def _normalize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Normalize configuration values into canonical immutable types for dirty detection."""
        entry_paths_raw = config.get('entry_paths', [])
        normalized_paths: list[tuple[str, str]] = []
        for p in entry_paths_raw:
            if isinstance(p, list | tuple) and len(p) >= 2:
                normalized_paths.append((str(p[0]).strip(), str(p[1]).strip()))
            elif hasattr(p, 'source') and hasattr(p, 'target'):
                normalized_paths.append((str(p.source).strip(), str(p.target).strip()))
        normalized_paths.sort()

        compare_method = config.get('radio_var_compare_method')
        if not compare_method:
            compare_method = 'metadata' if config.get('checkbox_var_metadata_comparison', True) else 'content'
        compare_method = str(compare_method).lower()

        return {
            'entry_paths': tuple(normalized_paths),
            'week_days': tuple(sorted(str(d).strip().upper() for d in config.get('week_days', []))),
            'entry_times': tuple(sorted(str(t).strip() for t in config.get('entry_times', []))),
            'entry_exclusions': tuple(
                sorted(str(e).strip() for e in config.get('entry_exclusions', ['$RECYCLE.BIN', r'\~$']))
            ),
            'log_levels': tuple(
                sorted(
                    str(lvl).strip().upper()
                    for lvl in config.get('log_levels', ['INFO', 'WARNING', 'ERROR', 'CRITICAL'])
                )
            ),
            'checkbox_default_actions': tuple(
                sorted(str(a).strip().lower() for a in config.get('checkbox_default_actions', ['copy']))
            ),
            'radio_var_compare_method': compare_method,
            'checkbox_var_use_mirror': bool(config.get('checkbox_var_use_mirror', True)),
            'checkbox_var_build_mirror': bool(config.get('checkbox_var_build_mirror', False)),
            'checkbox_var_metadata_comparison': (compare_method == 'metadata'),
            'checkbox_var_confirm_sync': bool(config.get('checkbox_var_confirm_sync', True)),
            'checkbox_var_save_report': bool(config.get('checkbox_var_save_report', False)),
            'toggle_auto_scroll': bool(config.get('toggle_auto_scroll', True)),
        }

    def _snapshot_saved_config(self):
        """Record the current GUI configuration as the saved baseline for dirty detection."""
        try:
            self._last_saved_config_vars = self._normalize_config(self._get_current_config_vars())
        except Exception as e:
            logger.warning(f'Could not record saved config snapshot: {e}')

    def has_unsaved_changes(self) -> bool:
        """Check whether current GUI configuration has unsaved changes compared to the active profile."""
        try:
            current = self._normalize_config(self._get_current_config_vars())
            if getattr(self, '_last_saved_config_vars', None) is not None:
                return current != self._last_saved_config_vars

            profile_data = self.profile_manager.load_profile(self.active_profile_name)
            return current != self._normalize_config(profile_data)
        except Exception as e:
            logger.warning(f'Error evaluating unsaved changes: {e}')
            return False

    def confirm_exit_unsaved_changes(self) -> bool:
        """
        Check for unsaved configuration changes before closing the application.

        Prompts the user if settings were modified without saving to the active profile:
        - Yes: Saves changes to the active profile and returns True (proceed with exit).
        - No: Discards changes and returns True (proceed with exit).
        - Cancel: Returns False (abort exit).
        """
        if not self.has_unsaved_changes():
            return True

        with contextlib.suppress(Exception):
            self.root.deiconify()
            self.root.lift()

        active_profile = self.active_profile_name
        response = messagebox.askyesnocancel(
            'Unsaved Changes',
            f"You have unsaved changes in profile '{active_profile}'.\n\n"
            f'Do you want to save them to the active profile before closing?',
            parent=self.root,
        )

        if response is True:
            try:
                self.button_action_save_config(ask_confirmation=False)
                logger.info(f"Saved unsaved changes to active profile '{active_profile}' before closing")
                return True
            except Exception as e:
                logger.error(f"Failed to save profile '{active_profile}' before closing: {e}")
                messagebox.showerror(
                    'Save Error',
                    f"Failed to save configuration to profile '{active_profile}':\n{e}",
                    parent=self.root,
                )
                return False
        elif response is False:
            logger.info(f"Discarding unsaved changes in profile '{active_profile}' upon exit")
            return True
        else:
            logger.info('Application exit cancelled by user due to unsaved changes')
            return False

    def button_action_switch_profile(self, profile_name: str, show_success_msg: bool = True) -> bool:
        """Switch active configuration profile, updating GUI controls and internal state."""
        try:
            clean_name = sanitize_profile_name(profile_name)
            data = self.profile_manager.load_profile(clean_name)
            self._apply_config_vars_to_gui(data)
            self.active_profile_name = clean_name
            self.profile_manager.set_active_profile_name(clean_name)
            self._snapshot_saved_config()
            if hasattr(self, 'actions_panel'):
                self.actions_panel.set_profiles(self.profile_manager.list_profiles(), clean_name)
            if show_success_msg:
                logger.info(f"Loaded configuration profile '{clean_name}'")
            self.get_next_appointment()
            return True
        except Exception as e:
            logger.error(f"Failed to switch to profile '{profile_name}': {e}")
            messagebox.showerror(
                'Profile Error',
                f"Failed to load profile '{profile_name}':\n{e}",
                parent=self.root,
            )
            return False

    def button_action_new_profile(self):
        """Prompt user for a new profile name and template choice ('blank' vs 'current')."""
        from gui.components.new_profile_modal import prompt_new_profile

        prompt_result = prompt_new_profile(
            self.root,
            active_profile_name=self.active_profile_name,
            existing_profiles=self.profile_manager.list_profiles(),
        )
        if not prompt_result:
            return

        if isinstance(prompt_result, tuple):
            new_name, template = prompt_result
        else:
            new_name, template = str(prompt_result), 'current'

        try:
            clean_name = sanitize_profile_name(new_name)
        except ValueError as e:
            messagebox.showwarning('Invalid Profile Name', str(e), parent=self.root)
            return

        config_vars = self._get_blank_config_vars() if template == 'blank' else self._get_current_config_vars()

        self.profile_manager.save_profile(clean_name, config_vars, sync_active_config=True)
        self.button_action_switch_profile(clean_name, show_success_msg=True)

    def button_action_delete_profile(self):
        """Delete active profile after user confirmation (Default cannot be deleted)."""
        active = self.active_profile_name
        if active.lower() == self.profile_manager.DEFAULT_PROFILE_NAME.lower():
            messagebox.showwarning(
                'Cannot Delete Profile',
                f"The '{self.profile_manager.DEFAULT_PROFILE_NAME}' profile cannot be deleted.",
                parent=self.root,
            )
            return

        confirmed = messagebox.askyesno(
            'Delete Profile',
            f"Are you sure you want to delete profile '{active}'?\n\nThis will remove it from data/profiles/.",
            parent=self.root,
        )
        if confirmed:
            self.profile_manager.delete_profile(active)
            logger.info(f"Deleted profile '{active}'")
            self.button_action_switch_profile(self.profile_manager.DEFAULT_PROFILE_NAME)

    def button_action_clone_profile(self):
        """Clone the current profile into a new named profile."""
        from tkinter import simpledialog

        clone_name = simpledialog.askstring(
            'Clone Profile',
            f"Enter name for clone of profile '{self.active_profile_name}':",
            parent=self.root,
        )
        if not clone_name:
            return
        try:
            clean_name = sanitize_profile_name(clone_name)
            self.profile_manager.clone_profile(self.active_profile_name, clean_name)
            self.button_action_switch_profile(clean_name)
        except Exception as e:
            messagebox.showerror('Clone Profile Error', str(e), parent=self.root)

    def button_action_rename_profile(self):
        """Rename the current profile (Default cannot be renamed)."""
        from tkinter import simpledialog

        if self.active_profile_name.lower() == self.profile_manager.DEFAULT_PROFILE_NAME.lower():
            messagebox.showwarning(
                'Cannot Rename Profile',
                f"The '{self.profile_manager.DEFAULT_PROFILE_NAME}' profile cannot be renamed.",
                parent=self.root,
            )
            return

        new_name = simpledialog.askstring(
            'Rename Profile',
            f"Enter new name for profile '{self.active_profile_name}':",
            initialvalue=self.active_profile_name,
            parent=self.root,
        )
        if not new_name:
            return
        try:
            clean_name = sanitize_profile_name(new_name)
            self.profile_manager.rename_profile(self.active_profile_name, clean_name)
            self.button_action_switch_profile(clean_name)
        except Exception as e:
            messagebox.showerror('Rename Profile Error', str(e), parent=self.root)

    def button_action_open_profiles_dir(self):
        """Open the data/profiles directory in Windows File Explorer."""
        try:
            os.startfile(str(self.profile_manager.profiles_dir))
        except Exception as e:
            logger.error(f'Could not open profiles directory: {e}')

    def button_action_save_config(self, ask_confirmation=True, file_path=None):
        if file_path:
            target_path = file_path
            if os.path.isfile(target_path) and ask_confirmation:
                confirmation = messagebox.askyesno(
                    'Caution',
                    'Are you sure you want to save configuration? '
                    f'This will overwrite existing configuration at:\n{target_path}',
                    parent=self.root,
                )
                if not confirmation:
                    return
            config_vars = self._get_current_config_vars()
            self.profile_manager.export_profile(config_vars, target_path)
            logger.info(f"Configuration successfully exported to '{target_path}'")
            return

        active_profile = self.active_profile_name
        profile_path = self.profile_manager.get_profile_path(active_profile)
        if profile_path.is_file() and ask_confirmation:
            confirmation = messagebox.askyesno(
                'Save Profile',
                f"Are you sure you want to save current settings to profile '{active_profile}'?\n\n"
                f'Target: {profile_path}',
                parent=self.root,
            )
            if not confirmation:
                return

        config_vars = self._get_current_config_vars()
        self.profile_manager.save_profile(active_profile, config_vars, sync_active_config=True)
        self._snapshot_saved_config()
        logger.info(f"Configuration profile '{active_profile}' was successfully saved")
        self.get_next_appointment()

    def button_action_save_config_as(self):
        from tkinter import filedialog

        initial_dir = str(self.profile_manager.profiles_dir)
        file_path = filedialog.asksaveasfilename(
            parent=self.root,
            title='Save Configuration As',
            initialdir=initial_dir if os.path.isdir(initial_dir) else None,
            defaultextension='.json',
            filetypes=[('JSON Files', '*.json'), ('All Files', '*.*')],
        )
        if file_path:
            self.button_action_save_config(ask_confirmation=False, file_path=file_path)

    def button_action_load_config(self, ask_confirmation=True, file_path=None):
        if file_path:
            self.load_config(file_path=file_path, show_success_msg=True)
            return

        active_profile = self.active_profile_name
        if ask_confirmation:
            confirmation = messagebox.askyesno(
                'Reload Profile',
                f"Are you sure you want to reload profile '{active_profile}' from disk?\n\n"
                'Any unsaved changes in the current session will be discarded.',
                parent=self.root,
            )
            if not confirmation:
                return

        self.button_action_switch_profile(active_profile, show_success_msg=True)

    def button_action_load_config_from_file(self):
        from tkinter import filedialog

        initial_dir = str(self.profile_manager.profiles_dir)
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title='Load Configuration File',
            initialdir=initial_dir if os.path.isdir(initial_dir) else None,
            filetypes=[('JSON Files', '*.json'), ('All Files', '*.*')],
        )
        if file_path:
            self.load_config(file_path=file_path, show_success_msg=True)

    def load_config(self, file_path=None, show_success_msg=True) -> bool:
        if file_path:
            target_path = file_path
            if os.path.isfile(target_path):
                try:
                    with open(target_path, encoding='utf-8') as f:
                        config_vars = json.load(f)
                    if not isinstance(config_vars, dict):
                        raise ValueError(f'Expected JSON object at root, got {type(config_vars).__name__}')
                    self._apply_config_vars_to_gui(config_vars)
                    if show_success_msg:
                        logger.info(f"Configuration was successfully loaded from '{target_path}'")
                    self.get_next_appointment()
                    return True
                except Exception as e:
                    logger.error(f"Failed to load configuration from '{target_path}': {e}")
                    messagebox.showerror(
                        'Configuration Error',
                        f'Failed to parse configuration file:\n{target_path}\n\nError: {e}',
                        parent=self.root,
                    )
                    return False
            else:
                messagebox.showwarning(
                    'Configuration Not Found',
                    f'Configuration file not found:\n{target_path}',
                    parent=self.root,
                )
                return False

        # Load active profile by default
        return self.button_action_switch_profile(self.active_profile_name, show_success_msg=show_success_msg)

    def button_action_open_report(self):
        if not os.path.isdir(logger.log_dir):
            logger.error(f"Could not open last report because directory does not exist: '{logger.log_dir}'")
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
            logger.info(f"Opening '{last_filepath}'")
            try:
                os.startfile(last_filepath)
            except OSError as e:
                logger.error(f"Could not open last report file '{last_filepath}': {e}")
        else:
            logger.error(f"Could not open last report because it was not found in directory '{logger.log_dir}'")

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

    def on_schedule_panel_toggled(self, active: bool):
        """Handle user toggling automated schedule directly in SchedulePanel."""
        self.get_next_appointment()
        if hasattr(self, 'actions_panel') and hasattr(self.actions_panel, 'button_schedule_sync'):
            with contextlib.suppress(Exception):
                self.actions_panel.button_schedule_sync.config(
                    relief=TkinterCfgRelief.SUNKEN.value if active else TkinterCfgRelief.RAISED.value,
                    text='Schedule (ON)' if active else 'Schedule (OFF)',
                )

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

    def _on_default_notification_clicked(self):
        """Handle user clicking a standard completion notification."""
        if hasattr(self, 'log_panel') and hasattr(self.log_panel, 'text_logger'):
            with contextlib.suppress(Exception):
                self.log_panel.text_logger.yview(tk.END)

    def _on_error_notification_clicked(self):
        """Handle user clicking an error notification by navigating to the error in the log."""
        if hasattr(self, 'log_panel'):
            with contextlib.suppress(Exception):
                self.log_panel.jump_to_next_error()

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

        def _on_scan_progress(action: str, current: int, total: int, current_path: str):
            if self._cancel_event.is_set():
                return
            if action == 'Comparing':
                if hasattr(self, 'telemetry_bar'):
                    self.root.after(
                        0,
                        lambda: self.telemetry_bar.set_indeterminate('Comparing and analyzing files...'),
                    )
                if hasattr(self, 'taskbar'):
                    self.root.after(0, self.taskbar.set_indeterminate)
            else:
                if hasattr(self, 'telemetry_bar'):

                    def _update_telemetry(a=action, c=current, t=total, cp=current_path):
                        self.telemetry_bar.set_determinate(
                            action=a,
                            current=c,
                            total=t,
                            current_file=cp,
                        )

                    self.root.after(0, _update_telemetry)
                if hasattr(self, 'taskbar'):

                    def _update_taskbar(c=current, t=total):
                        self.taskbar.set_determinate(c, t)

                    self.root.after(0, _update_taskbar)

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
            progress_callback=_on_scan_progress,
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
                            lambda a=action, c=current, t=total, bt=bytes_transferred, cf=current_file, s=speed: (
                                self.telemetry_bar.set_determinate(
                                    action=a,
                                    current=c,
                                    total=t,
                                    bytes_transferred=bt,
                                    current_file=cf,
                                    speed=s,
                                )
                            ),
                        )
                    if hasattr(self, 'taskbar'):
                        self.root.after(0, lambda c=current, t=total: self.taskbar.set_determinate(c, t))

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
                had_work = bool(compare.files_to_copy or compare.files_to_move or compare.files_to_delete)
                cancelled = self._cancel_event.is_set()
                if not cancelled and sync is not None:
                    total_errors = (
                        sum(1 for _, success in sync.files_copied if not success)
                        + sum(1 for _, success in sync.files_moved if not success)
                        + sum(1 for _, success in sync.files_deleted if not success)
                    )
                    total_successes = (
                        sum(1 for _, success in sync.files_copied if success)
                        + sum(1 for _, success in sync.files_moved if success)
                        + sum(1 for _, success in sync.files_deleted if success)
                    )

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
                                on_click=self._on_error_notification_clicked,
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
                                on_click=self._on_default_notification_clicked,
                            ),
                        )
                    elif not had_work:
                        msg = 'Synchronization finished: no files were modified.'
                        self.root.after(
                            0,
                            lambda m=msg: self.root.notify(
                                message=m,
                                title='FastMirror',
                                on_click=self._on_default_notification_clicked,
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
                        lambda m=summary_msg: self.root.notify(
                            message=m,
                            title='FastMirror',
                            on_click=self._on_default_notification_clicked,
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
            if build_mirror:
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
