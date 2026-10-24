import contextlib
import os
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from gui.enums import TkinterCfgRelief
from gui.icons import apply_icon
from gui.widgets import Action, DefaultActions, add_tooltip
from utils.logger import logger


class ModernButton(ttk.Button):
    """Modern themed button maintaining full backward compatibility with .config('relief') toggle checks."""

    def __init__(
        self,
        master: tk.Misc | None = None,
        relief: str = TkinterCfgRelief.RAISED.value,
        default_style: str = '',
        **kwargs,
    ):
        self._relief = relief
        self._default_style = default_style
        kwargs.pop('relief', None)
        kwargs.pop('font', None)
        style = default_style or 'TButton'
        if relief == TkinterCfgRelief.SUNKEN.value:
            style = 'Accent.TButton'
        if 'style' not in kwargs and style:
            kwargs['style'] = style
        super().__init__(master, **kwargs)

    def _apply_style(self):
        if self._relief == TkinterCfgRelief.SUNKEN.value:
            self.configure(style='Accent.TButton')
        elif self._default_style:
            self.configure(style=self._default_style)
        else:
            self.configure(style='TButton')

    def config(self, *args, **kwargs):
        if 'default_style' in kwargs:
            self._default_style = kwargs.pop('default_style')
            self._apply_style()
        if 'relief' in kwargs:
            self._relief = kwargs.pop('relief')
            self._apply_style()
        if 'font' in kwargs:
            kwargs.pop('font')
        if args and len(args) == 1 and args[0] == 'relief':
            return ('relief', 'relief', 'Relief', TkinterCfgRelief.RAISED.value, self._relief)
        if args or kwargs:
            return super().config(*args, **kwargs)
        res = super().config()
        if isinstance(res, dict):
            res['relief'] = ('relief', 'relief', 'Relief', TkinterCfgRelief.RAISED.value, self._relief)
        return res

    configure = config  # type: ignore[assignment]

    def cget(self, key):
        if key == 'relief':
            return self._relief
        return super().cget(key)

    def __getitem__(self, key):
        if key == 'relief':
            return self._relief
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key == 'relief':
            self._relief = value
            self._apply_style()
        elif key == 'font':
            pass
        else:
            super().__setitem__(key, value)


class ActionsPanel(ttk.LabelFrame):
    """Panel managing backup triggers, comparison options, and default action preferences."""

    def __init__(
        self,
        master: tk.Misc,
        checkbox_default_actions: DefaultActions,
        checkbox_var_save_report: tk.BooleanVar,
        checkbox_var_confirm_sync: tk.BooleanVar,
        on_reset_config: Callable[[], None],
        on_save_config: Callable[[], None],
        on_quick_compare: Callable[[], None],
        on_open_report: Callable[[], None],
        on_sync_now: Callable[[], None],
        on_schedule_sync: Callable[[], None],
        on_load_config: Callable[[], None] | None = None,
        on_load_config_from_file: Callable[[], None] | None = None,
        on_save_config_as: Callable[[], None] | None = None,
        on_select_profile: Callable[[str], None] | None = None,
        on_new_profile: Callable[[], None] | None = None,
        on_delete_profile: Callable[[], None] | None = None,
        on_clone_profile: Callable[[], None] | None = None,
        on_rename_profile: Callable[[], None] | None = None,
        on_open_profiles_dir: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        radio_var_compare_method: tk.StringVar | None = None,
        checkbox_var_reset_mirror: tk.BooleanVar | None = None,
        # Backward compatibility parameters
        checkbox_var_build_mirror: tk.BooleanVar | None = None,
        checkbox_var_use_mirror: tk.BooleanVar | None = None,
        checkbox_var_metadata_comparison: tk.BooleanVar | None = None,
        on_report_history: Callable[[], None] | None = None,
        on_rebuild_confirmation: Callable[[bool], None] | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' Actions & Operations ', **kwargs)

        self.checkbox_default_actions = checkbox_default_actions
        self.checkbox_var_save_report = checkbox_var_save_report
        self.checkbox_var_confirm_sync = checkbox_var_confirm_sync

        self.on_reset_config = on_reset_config
        self.on_load_config = on_load_config or (lambda: None)
        self.on_load_config_from_file = on_load_config_from_file
        self.on_save_config = on_save_config
        self.on_save_config_as = on_save_config_as
        self.on_select_profile = on_select_profile
        self.on_new_profile = on_new_profile
        self.on_delete_profile = on_delete_profile
        self.on_clone_profile = on_clone_profile
        self.on_rename_profile = on_rename_profile
        self.on_open_profiles_dir = on_open_profiles_dir
        self.on_quick_compare = on_quick_compare
        self.on_open_report = on_open_report
        self.on_report_history = on_report_history
        self.on_sync_now = on_sync_now
        self.on_schedule_sync = on_schedule_sync
        self.on_stop = on_stop
        self.on_rebuild_confirmation = on_rebuild_confirmation

        # Comparison method setup with backward compatibility
        if radio_var_compare_method is not None:
            self.radio_var_compare_method = radio_var_compare_method
        else:
            init_val = (
                'metadata'
                if checkbox_var_metadata_comparison is None or checkbox_var_metadata_comparison.get()
                else 'content'
            )
            self.radio_var_compare_method = tk.StringVar(master=master, value=init_val)

        self.checkbox_var_metadata_comparison = checkbox_var_metadata_comparison or tk.BooleanVar(
            master=master,
            value=self.radio_var_compare_method.get() == 'metadata',
        )

        # Mirror reset setup with backward compatibility
        if checkbox_var_reset_mirror is not None:
            self.checkbox_var_reset_mirror = checkbox_var_reset_mirror
        elif checkbox_var_build_mirror is not None:
            self.checkbox_var_reset_mirror = checkbox_var_build_mirror
        else:
            self.checkbox_var_reset_mirror = tk.BooleanVar(master=master, value=False)

        self.checkbox_var_build_mirror = checkbox_var_build_mirror or self.checkbox_var_reset_mirror
        self.checkbox_var_use_mirror = checkbox_var_use_mirror or tk.BooleanVar(
            master=master,
            value=not self.checkbox_var_reset_mirror.get(),
        )

        self._bind_sync_traces()
        self._create_widgets()

    def _bind_sync_traces(self):
        """Bind trace listeners to synchronize new and legacy variables."""

        def _sync_radio_to_cb(*_):
            is_meta = self.radio_var_compare_method.get() == 'metadata'
            if self.checkbox_var_metadata_comparison.get() != is_meta:
                self.checkbox_var_metadata_comparison.set(is_meta)

        def _sync_cb_to_radio(*_):
            method = 'metadata' if self.checkbox_var_metadata_comparison.get() else 'content'
            if self.radio_var_compare_method.get() != method:
                self.radio_var_compare_method.set(method)

        self.radio_var_compare_method.trace_add('write', _sync_radio_to_cb)
        self.checkbox_var_metadata_comparison.trace_add('write', _sync_cb_to_radio)

        def _sync_reset_to_legacy(*_):
            reset = self.checkbox_var_reset_mirror.get()
            if self.checkbox_var_build_mirror.get() != reset:
                self.checkbox_var_build_mirror.set(reset)
            if self.checkbox_var_use_mirror.get() == reset:
                self.checkbox_var_use_mirror.set(not reset)

        def _sync_legacy_build_to_reset(*_):
            build = self.checkbox_var_build_mirror.get()
            if self.checkbox_var_reset_mirror.get() != build:
                self.checkbox_var_reset_mirror.set(build)
            if build and self.checkbox_var_use_mirror.get():
                self.checkbox_var_use_mirror.set(False)

        def _sync_legacy_use_to_reset(*_):
            use = self.checkbox_var_use_mirror.get()
            if use:
                if self.checkbox_var_build_mirror.get():
                    self.checkbox_var_build_mirror.set(False)
                if self.checkbox_var_reset_mirror.get():
                    self.checkbox_var_reset_mirror.set(False)

        self.checkbox_var_reset_mirror.trace_add('write', _sync_reset_to_legacy)
        self.checkbox_var_build_mirror.trace_add('write', _sync_legacy_build_to_reset)
        self.checkbox_var_use_mirror.trace_add('write', _sync_legacy_use_to_reset)

    def _create_widgets(self):
        # Section 1: Profile & Configuration Management
        cfg_frame = ttk.Frame(self)
        cfg_frame.pack(fill='x', padx=8, pady=(4, 6))

        lbl_prof = ttk.Label(cfg_frame, text='Profile:', font=('Segoe UI', 9, 'bold'), width=7)
        lbl_prof.pack(side='left')

        self.profile_var = tk.StringVar(value='Default')
        self.combobox_profile = ttk.Combobox(
            cfg_frame,
            textvariable=self.profile_var,
            state='readonly',
            width=12,
            values=['Default'],
        )
        self.combobox_profile.pack(side='left', padx=2)
        self.combobox_profile.bind('<<ComboboxSelected>>', self._on_combobox_profile_selected)
        add_tooltip(self.combobox_profile, 'Active configuration profile. Select from dropdown to switch and load.')

        self.button_save_config = ModernButton(
            cfg_frame,
            text='Save',
            command=self.on_save_config,
            width=6,
        )
        apply_icon(self.button_save_config, 'save')
        self.button_save_config.pack(side='left', padx=2)
        add_tooltip(
            self.button_save_config,
            'Save current settings to active profile. Right-click for options.',
        )

        self.button_new_profile = ModernButton(
            cfg_frame,
            text='+ New',
            command=self.on_new_profile or self.on_reset_config,
            width=6,
        )
        apply_icon(self.button_new_profile, 'document')
        self.button_new_profile.pack(side='left', padx=2)
        add_tooltip(self.button_new_profile, 'Create a new named configuration profile.')

        self.button_delete_profile = ModernButton(
            cfg_frame,
            text='Delete',
            command=self.on_delete_profile or (lambda: None),
            width=6,
        )
        apply_icon(self.button_delete_profile, 'broom')
        self.button_delete_profile.pack(side='left', padx=2)
        add_tooltip(self.button_delete_profile, 'Delete active configuration profile (Default cannot be deleted).')

        # Backward compatibility aliases for tests and programmatic reload/reset workflows
        self.button_load_config = ModernButton(
            cfg_frame,
            text='Load',
            command=self.on_load_config,
            width=6,
        )
        apply_icon(self.button_load_config, 'folder')
        add_tooltip(
            self.button_load_config,
            'Reload active profile configuration from disk.',
        )

        self.button_new_config = ModernButton(
            cfg_frame,
            text='Reset',
            command=self.on_reset_config,
            width=6,
        )
        apply_icon(self.button_new_config, 'broom')
        add_tooltip(self.button_new_config, 'Reset all configuration fields to default values.')

        # Context menus for advanced profile operations
        profile_menu = tk.Menu(self.combobox_profile, tearoff=0)
        profile_menu.add_command(label='🔄 Reload Profile (Ctrl+R)', command=self.on_load_config)
        if self.on_clone_profile:
            profile_menu.add_command(label='📋 Clone Active Profile...', command=self.on_clone_profile)
        if self.on_rename_profile:
            profile_menu.add_command(label='✏️ Rename Active Profile...', command=self.on_rename_profile)
        profile_menu.add_separator()
        if self.on_load_config_from_file:
            profile_menu.add_command(label='📁 Import Profile from File...', command=self.on_load_config_from_file)
        if self.on_open_profiles_dir:
            profile_menu.add_command(label='📂 Open Profiles Folder', command=self.on_open_profiles_dir)
        profile_menu.add_separator()
        profile_menu.add_command(label='🧹 Reset to Defaults', command=self.on_reset_config)
        self.combobox_profile.bind('<Button-3>', lambda e: profile_menu.tk_popup(e.x_root, e.y_root))

        save_menu = tk.Menu(self.button_save_config, tearoff=0)
        save_menu.add_command(label='💾 Save to Active Profile', command=self.on_save_config)
        if self.on_save_config_as:
            save_menu.add_command(label='💾 Save As / Export to File...', command=self.on_save_config_as)
        self.button_save_config.bind('<Button-3>', lambda e: save_menu.tk_popup(e.x_root, e.y_root))

        # Section 2: Comparison
        cmp_frame = ttk.Frame(self)
        cmp_frame.pack(fill='x', padx=8, pady=4)

        lbl_cmp = ttk.Label(cmp_frame, text='Comparison:', font=('Segoe UI', 9, 'bold'), width=14)
        lbl_cmp.pack(side='left')

        self.button_quick_compare = ModernButton(
            cmp_frame,
            text='Start Compare',
            command=self.on_quick_compare,
            width=14,
        )
        apply_icon(self.button_quick_compare, 'compare')
        self.button_quick_compare.pack(side='left', padx=3)
        add_tooltip(self.button_quick_compare, 'Run dry-run comparison to analyze differences without altering files.')

        self.button_reports = ModernButton(
            cmp_frame,
            text='Reports...',
            command=self._handle_report_history,
            width=14,
        )
        apply_icon(self.button_reports, 'document')
        self.button_reports.pack(side='left', padx=3)
        add_tooltip(
            self.button_reports,
            'Browse and manage past comparison reports. Right-click for options (Open Latest, Open Folder).',
        )

        reports_menu = tk.Menu(self.button_reports, tearoff=0)
        reports_menu.add_command(label='📄 Open Latest Report', command=self.on_open_report)
        reports_menu.add_command(label='📂 Browse Reports History...', command=self._handle_report_history)
        reports_menu.add_separator()
        reports_menu.add_command(label='📁 Open Reports Folder', command=self._open_reports_dir)
        self.button_reports.bind('<Button-3>', lambda e: reports_menu.tk_popup(e.x_root, e.y_root))

        # Backward compatibility aliases for existing tests & scripts
        self.button_report_history = self.button_reports
        self.button_open_report = ModernButton(
            self,
            text='Open Report',
            command=self.on_open_report,
        )

        # Section 3: Synchronization
        sync_frame = ttk.Frame(self)
        sync_frame.pack(fill='x', padx=8, pady=4)

        lbl_sync = ttk.Label(sync_frame, text='Synchronization:', font=('Segoe UI', 9, 'bold'), width=14)
        lbl_sync.pack(side='left')

        self.button_sync_now = ModernButton(
            sync_frame,
            text='Sync Now',
            command=self.on_sync_now,
            width=14,
            default_style='Accent.TButton',
        )
        apply_icon(self.button_sync_now, 'sync')
        self.button_sync_now.pack(side='left', padx=3)
        add_tooltip(self.button_sync_now, 'Start synchronization between source and target directories.')

        # Backward compatibility alias for button_schedule_sync
        self.button_schedule_sync = ModernButton(
            self,
            text='Schedule (OFF)',
            command=self.on_schedule_sync,
            width=14,
        )

        # Section 4: Behavior Options
        self.frame_options = ttk.Frame(self)
        self.frame_options.pack(fill='x', padx=8, pady=(4, 4))

        # 4a. Comparison Method (Radio group)
        lbl_method = ttk.Label(
            self.frame_options,
            text='Comparison Method:',
            font=('Segoe UI', 8, 'bold'),
            foreground='#555555',
        )
        lbl_method.pack(anchor='w', pady=(0, 2))

        self.rb_meta = ttk.Radiobutton(
            self.frame_options,
            text='Metadata (fast: size & mtime)',
            value='metadata',
            variable=self.radio_var_compare_method,
        )
        self.rb_meta.pack(anchor='w', padx=(4, 0), pady=1)
        add_tooltip(
            self.rb_meta,
            'Fast comparison using file size and modification timestamp (recommended for regular backups).',
        )

        self.rb_content = ttk.Radiobutton(
            self.frame_options,
            text='Content (SHA-256 hash — thorough)',
            value='content',
            variable=self.radio_var_compare_method,
        )
        self.rb_content.pack(anchor='w', padx=(4, 0), pady=1)
        add_tooltip(
            self.rb_content,
            'Thorough byte comparison calculating SHA-256 hashes (detects bit rot and content changes).',
        )

        # 4b. Local Mirror Database
        lbl_mirror = ttk.Label(
            self.frame_options,
            text='Mirror Database:',
            font=('Segoe UI', 8, 'bold'),
            foreground='#555555',
        )
        lbl_mirror.pack(anchor='w', pady=(5, 2))

        self.cb_reset_mirror = ttk.Checkbutton(
            self.frame_options,
            text='Reset local mirror database (one-time full rescan)',
            variable=self.checkbox_var_reset_mirror,
            onvalue=True,
            offvalue=False,
            command=self._on_reset_mirror_clicked,
        )
        self.cb_reset_mirror.pack(anchor='w', padx=(4, 0), pady=1)
        add_tooltip(
            self.cb_reset_mirror,
            'Wipe cached index and perform a complete rescan of target files on next run. '
            'Automatically clears after run.',
        )
        # Compatibility alias for existing tests
        self.cb_rebuild = self.cb_reset_mirror

        # 4c. Safety & Reporting
        lbl_safe = ttk.Label(
            self.frame_options,
            text='Safety & Reporting:',
            font=('Segoe UI', 8, 'bold'),
            foreground='#555555',
        )
        lbl_safe.pack(anchor='w', pady=(5, 2))

        self.cb_confirm = ttk.Checkbutton(
            self.frame_options,
            text='Request confirmation before sync',
            variable=self.checkbox_var_confirm_sync,
        )
        self.cb_confirm.pack(anchor='w', padx=(4, 0), pady=1)
        add_tooltip(
            self.cb_confirm,
            'Display an interactive review dialog showing planned file actions before copying or deleting.',
        )

        self.cb_report = ttk.Checkbutton(
            self.frame_options,
            text='Save detailed report (.xlsx)',
            variable=self.checkbox_var_save_report,
        )
        self.cb_report.pack(anchor='w', padx=(4, 0), pady=1)
        add_tooltip(
            self.cb_report,
            'Generate a comprehensive Excel (.xlsx) report containing detailed lists of all differences.',
        )

        # Section 5: Default Actions
        actions_frame = ttk.Frame(self)
        actions_frame.pack(fill='x', padx=8, pady=(4, 6))

        lbl_acts = ttk.Label(actions_frame, text='Default Actions:', font=('Segoe UI', 9, 'bold'), width=14)
        lbl_acts.pack(side='left')

        self.frame_default_actions = ttk.Frame(actions_frame)
        self.frame_default_actions.pack(side='left', padx=3)

        cb_copy = ttk.Checkbutton(
            self.frame_default_actions,
            text='Copy',
            variable=self.checkbox_default_actions.get_var(Action.COPY),
        )
        cb_copy.pack(side='left', padx=(0, 8))
        add_tooltip(cb_copy, 'Automatically copy new and modified files from source to target.')

        cb_move = ttk.Checkbutton(
            self.frame_default_actions,
            text='Move',
            variable=self.checkbox_default_actions.get_var(Action.MOVE),
        )
        cb_move.pack(side='left', padx=(0, 8))
        add_tooltip(cb_move, 'Automatically move renamed or relocated files instead of re-copying.')

        cb_del = ttk.Checkbutton(
            self.frame_default_actions,
            text='Delete',
            variable=self.checkbox_default_actions.get_var(Action.DELETE),
        )
        cb_del.pack(side='left')
        add_tooltip(cb_del, 'Automatically delete files on target that no longer exist in source (mirror mode).')

    def _handle_report_history(self):
        if self.on_report_history:
            self.on_report_history()
        else:
            from gui.components.reports_window import ReportsWindow

            ReportsWindow(self.winfo_toplevel())

    def _open_reports_dir(self):
        """Open the directory containing comparison reports in File Explorer."""
        if hasattr(logger, 'log_dir') and os.path.isdir(logger.log_dir):
            try:
                os.startfile(logger.log_dir)
            except OSError as e:
                logger.error(f"Could not open reports directory '{logger.log_dir}': {e}")

    def _on_reset_mirror_clicked(self):
        """Handle mirror reset click, prompting confirmation if a confirmation callback is registered."""
        if self.on_rebuild_confirmation is not None:
            self._on_rebuild_mirror_clicked()

    def _on_rebuild_mirror_clicked(self):
        if self.checkbox_var_reset_mirror.get() or self.checkbox_var_build_mirror.get():
            confirm = messagebox.askyesno(
                'Caution',
                'Are you sure you want to rebuild the local mirror database?\n\n'
                'This will reset and wipe the cached file records for the target directories.',
                parent=self.winfo_toplevel(),
            )
            if not confirm:
                self.checkbox_var_reset_mirror.set(False)
                self.checkbox_var_build_mirror.set(False)
                with contextlib.suppress(Exception):
                    self.cb_reset_mirror.state(['!selected'])
                self.checkbox_var_use_mirror.set(True)
                if self.on_rebuild_confirmation is not None:
                    self.on_rebuild_confirmation(False)
            else:
                self.checkbox_var_reset_mirror.set(True)
                self.checkbox_var_build_mirror.set(True)
                self.checkbox_var_use_mirror.set(False)
                if self.on_rebuild_confirmation is not None:
                    self.on_rebuild_confirmation(True)
        else:
            if self.on_rebuild_confirmation is not None:
                self.on_rebuild_confirmation(False)

    def set_running_state(self, running: bool, trigger: str | None = None, stopping: bool = False):
        """Update button labels, styles, and command handlers to reflect operation running/idle state."""
        stop_cmd = self.on_stop or (lambda: None)

        if not running:
            self.button_sync_now.configure(
                text='Sync Now',
                command=self.on_sync_now,
                default_style='Accent.TButton',
                state='normal',
            )
            apply_icon(self.button_sync_now, 'sync')
            if hasattr(self.button_sync_now, '_tooltip'):
                self.button_sync_now._tooltip.text = 'Start synchronization between source and target directories.'

            self.button_quick_compare.configure(
                text='Start Compare',
                command=self.on_quick_compare,
                default_style='',
                state='normal',
            )
            apply_icon(self.button_quick_compare, 'compare')
            if hasattr(self.button_quick_compare, '_tooltip'):
                self.button_quick_compare._tooltip.text = (
                    'Run dry-run comparison to analyze differences without altering files.'
                )
            return

        if stopping:
            if trigger == 'sync_now':
                self.button_sync_now.configure(text='Stopping...', state='disabled')
                if hasattr(self.button_sync_now, '_tooltip'):
                    self.button_sync_now._tooltip.text = 'Cancelling active synchronization...'
            elif trigger == 'quick_compare':
                self.button_quick_compare.configure(text='Stopping...', state='disabled')
                if hasattr(self.button_quick_compare, '_tooltip'):
                    self.button_quick_compare._tooltip.text = 'Cancelling active comparison...'
        else:
            if trigger == 'sync_now':
                self.button_sync_now.configure(
                    command=stop_cmd,
                    default_style='Stop.TButton',
                    state='normal',
                )
                apply_icon(self.button_sync_now, 'stop', text='Stop Sync')
                if hasattr(self.button_sync_now, '_tooltip'):
                    self.button_sync_now._tooltip.text = 'Stop active synchronization safely.'
            elif trigger == 'quick_compare':
                self.button_quick_compare.configure(
                    command=stop_cmd,
                    default_style='Stop.TButton',
                    state='normal',
                )
                apply_icon(self.button_quick_compare, 'stop', text='Stop Compare')
                if hasattr(self.button_quick_compare, '_tooltip'):
                    self.button_quick_compare._tooltip.text = 'Stop active comparison safely.'

    def set_enabled(self, enabled: bool, leave_sunken_enabled: bool = False):
        """Enable or disable interactive controls in the actions panel."""
        state = 'normal' if enabled else 'disabled'
        buttons = [
            self.button_new_config,
            self.button_load_config,
            self.button_save_config,
            self.button_quick_compare,
            self.button_reports,
            self.button_sync_now,
            self.button_open_report,
            self.button_schedule_sync,
        ]
        for btn in buttons:
            is_sunken = False
            if hasattr(btn, 'config'):
                with contextlib.suppress(Exception):
                    is_sunken = btn.config('relief')[-1] == TkinterCfgRelief.SUNKEN.value

            if leave_sunken_enabled and is_sunken:
                with contextlib.suppress(Exception):
                    btn.configure(state='normal')
            else:
                with contextlib.suppress(Exception):
                    btn.configure(state=state)

        for child in self.frame_options.winfo_children():
            with contextlib.suppress(Exception):
                child.configure(state=state)

        for child in self.frame_default_actions.winfo_children():
            with contextlib.suppress(Exception):
                child.configure(state=state)

        if hasattr(self, 'combobox_profile'):
            with contextlib.suppress(Exception):
                self.combobox_profile.configure(state='readonly' if enabled else 'disabled')
        if hasattr(self, 'button_new_profile'):
            with contextlib.suppress(Exception):
                self.button_new_profile.configure(state=state)
        if hasattr(self, 'button_delete_profile'):
            with contextlib.suppress(Exception):
                self.button_delete_profile.configure(state=state)

    def _on_combobox_profile_selected(self, _event=None):
        selected = self.profile_var.get()
        if self.on_select_profile:
            self.on_select_profile(selected)

    def set_profiles(self, profiles: list[str], active_profile: str):
        """Update profile combobox choices and select the active profile."""
        if hasattr(self, 'combobox_profile'):
            self.combobox_profile['values'] = profiles
            self.profile_var.set(active_profile)

    def get_active_profile(self) -> str:
        """Return the currently selected profile name."""
        return self.profile_var.get()
