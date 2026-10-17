import contextlib
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from gui.enums import TkinterCfgRelief
from gui.widgets import Action, DefaultActions


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

    configure = config

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
        checkbox_var_build_mirror: tk.BooleanVar,
        checkbox_var_use_mirror: tk.BooleanVar,
        checkbox_var_metadata_comparison: tk.BooleanVar,
        checkbox_var_confirm_sync: tk.BooleanVar,
        on_reset_config: Callable[[], None],
        on_save_config: Callable[[], None],
        on_quick_compare: Callable[[], None],
        on_open_report: Callable[[], None],
        on_sync_now: Callable[[], None],
        on_schedule_sync: Callable[[], None],
        on_report_history: Callable[[], None] | None = None,
        on_toggle_theme: Callable[[], None] | None = None,
        on_rebuild_confirmation: Callable[[bool], None] | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' Actions & Operations ', **kwargs)

        self.checkbox_default_actions = checkbox_default_actions
        self.checkbox_var_save_report = checkbox_var_save_report
        self.checkbox_var_build_mirror = checkbox_var_build_mirror
        self.checkbox_var_use_mirror = checkbox_var_use_mirror
        self.checkbox_var_metadata_comparison = checkbox_var_metadata_comparison
        self.checkbox_var_confirm_sync = checkbox_var_confirm_sync

        self.on_reset_config = on_reset_config
        self.on_save_config = on_save_config
        self.on_quick_compare = on_quick_compare
        self.on_open_report = on_open_report
        self.on_report_history = on_report_history
        self.on_sync_now = on_sync_now
        self.on_schedule_sync = on_schedule_sync
        self.on_toggle_theme = on_toggle_theme
        self.on_rebuild_confirmation = on_rebuild_confirmation

        self._create_widgets()

    def _create_widgets(self):
        # Section 1: Configuration Management
        cfg_frame = ttk.Frame(self)
        cfg_frame.pack(fill='x', padx=8, pady=(4, 6))

        lbl_cfg = ttk.Label(cfg_frame, text='Configuration:', font=('Segoe UI', 9, 'bold'), width=14)
        lbl_cfg.pack(side='left')

        self.button_new_config = ModernButton(
            cfg_frame,
            text='Reset',
            command=self.on_reset_config,
            width=8,
        )
        self.button_new_config.pack(side='left', padx=2)

        self.button_save_config = ModernButton(
            cfg_frame,
            text='Save',
            command=self.on_save_config,
            width=8,
        )
        self.button_save_config.pack(side='left', padx=2)

        self.button_toggle_theme = ModernButton(
            cfg_frame,
            text='Theme: Native (Fast)',
            command=self.on_toggle_theme,
            width=18,
        )
        if self.on_toggle_theme is not None:
            self.button_toggle_theme.pack(side='left', padx=2)

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
        self.button_quick_compare.pack(side='left', padx=3)

        self.button_open_report = ModernButton(
            cmp_frame,
            text='Open Report',
            command=self.on_open_report,
            width=12,
        )
        self.button_open_report.pack(side='left', padx=3)

        self.button_report_history = ModernButton(
            cmp_frame,
            text='History...',
            command=self._handle_report_history,
            width=10,
        )
        self.button_report_history.pack(side='left', padx=3)

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
        self.button_sync_now.pack(side='left', padx=3)

        self.button_schedule_sync = ModernButton(
            sync_frame,
            text='Schedule (OFF)',
            command=self.on_schedule_sync,
            width=14,
        )
        self.button_schedule_sync.pack(side='left', padx=3)

        # Section 4: Behavior Options
        self.frame_options = ttk.Frame(self)
        self.frame_options.pack(fill='x', padx=8, pady=(4, 4))

        def _on_rebuild_mirror_changed(*args):
            if self.checkbox_var_build_mirror.get():
                self.checkbox_var_use_mirror.set(False)

        def _on_use_mirror_changed(*args):
            if self.checkbox_var_use_mirror.get():
                self.checkbox_var_build_mirror.set(False)

        self.checkbox_var_build_mirror.trace_add('write', _on_rebuild_mirror_changed)
        self.checkbox_var_use_mirror.trace_add('write', _on_use_mirror_changed)

        # Performance & Scanning sub-group
        lbl_perf = ttk.Label(
            self.frame_options,
            text='Performance & Scanning:',
            font=('Segoe UI', 8, 'bold'),
            foreground='#555555',
        )
        lbl_perf.pack(anchor='w', pady=(0, 2))

        self.cb_mirror = ttk.Checkbutton(
            self.frame_options,
            text='Use fast scan based on local mirror',
            variable=self.checkbox_var_use_mirror,
        )
        self.cb_mirror.pack(anchor='w', padx=(4, 0), pady=1)

        self.cb_meta = ttk.Checkbutton(
            self.frame_options,
            text='Use fast comparison based on metadata',
            variable=self.checkbox_var_metadata_comparison,
        )
        self.cb_meta.pack(anchor='w', padx=(4, 0), pady=1)

        self.cb_rebuild = ttk.Checkbutton(
            self.frame_options,
            text='Rebuild local mirror database',
            variable=self.checkbox_var_build_mirror,
            onvalue=True,
            offvalue=False,
            command=self._on_rebuild_mirror_clicked,
        )
        self.cb_rebuild.pack(anchor='w', padx=(4, 0), pady=1)

        # Safety & Reporting sub-group
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

        self.cb_report = ttk.Checkbutton(
            self.frame_options,
            text='Save detailed report (.xlsx)',
            variable=self.checkbox_var_save_report,
        )
        self.cb_report.pack(anchor='w', padx=(4, 0), pady=1)

        # Section 5: Default Actions
        actions_frame = ttk.Frame(self)
        actions_frame.pack(fill='x', padx=8, pady=(4, 6))

        lbl_acts = ttk.Label(actions_frame, text='Default Actions:', font=('Segoe UI', 9, 'bold'))
        lbl_acts.pack(side='left', padx=(0, 8))

        self.frame_default_actions = ttk.Frame(actions_frame)
        self.frame_default_actions.pack(side='left')

        cb_copy = ttk.Checkbutton(
            self.frame_default_actions,
            text='Copy',
            variable=self.checkbox_default_actions.get_var(Action.COPY),
        )
        cb_copy.pack(side='left', padx=6)

        cb_move = ttk.Checkbutton(
            self.frame_default_actions,
            text='Move',
            variable=self.checkbox_default_actions.get_var(Action.MOVE),
        )
        cb_move.pack(side='left', padx=6)

        cb_del = ttk.Checkbutton(
            self.frame_default_actions,
            text='Delete',
            variable=self.checkbox_default_actions.get_var(Action.DELETE),
        )
        cb_del.pack(side='left', padx=6)

    def _handle_report_history(self):
        if self.on_report_history:
            self.on_report_history()
        else:
            from gui.components.reports_window import ReportsWindow

            ReportsWindow(self.winfo_toplevel())

    def _on_rebuild_mirror_clicked(self):
        if self.checkbox_var_build_mirror.get():
            confirm = messagebox.askyesno(
                'Caution',
                'Are you sure you want to rebuild the local mirror database?\n\n'
                'This will reset and wipe the cached file records for the target directories.',
                parent=self.winfo_toplevel(),
            )
            if not confirm:
                self.checkbox_var_build_mirror.set(False)
                with contextlib.suppress(Exception):
                    self.cb_rebuild.state(['!selected'])
                self.checkbox_var_use_mirror.set(True)
                if self.on_rebuild_confirmation is not None:
                    self.on_rebuild_confirmation(False)
            else:
                self.checkbox_var_use_mirror.set(False)
                if self.on_rebuild_confirmation is not None:
                    self.on_rebuild_confirmation(True)
        else:
            if self.on_rebuild_confirmation is not None:
                self.on_rebuild_confirmation(False)

    def set_enabled(self, enabled: bool, leave_sunken_enabled: bool = False):
        """Enable or disable interactive controls in the actions panel."""
        state = 'normal' if enabled else 'disabled'
        buttons = [
            self.button_new_config,
            self.button_save_config,
            self.button_quick_compare,
            self.button_open_report,
            self.button_report_history,
            self.button_sync_now,
            self.button_schedule_sync,
        ]
        if hasattr(self, 'button_toggle_theme'):
            buttons.append(self.button_toggle_theme)
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
