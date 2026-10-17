import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from gui.enums import TkinterCfgState
from gui.widgets import LogLevels, TextLogger


class LogPanel(ttk.LabelFrame):
    """Panel hosting the real-time activity log viewer, level filters, and auto-scroll controls."""

    def __init__(
        self,
        master: tk.Misc,
        log_levels: LogLevels | None = None,
        toggle_auto_scroll: tk.BooleanVar | None = None,
        on_update_log_levels: Callable[[], None] | None = None,
        on_toggle_auto_scroll: Callable[[], None] | None = None,
        text_logger: TextLogger | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' Activity & Operation Log ', **kwargs)

        self.log_levels = log_levels or LogLevels()
        self.toggle_auto_scroll = toggle_auto_scroll or tk.BooleanVar(value=True)
        self.on_update_log_levels = on_update_log_levels
        self.on_toggle_auto_scroll = on_toggle_auto_scroll

        self._create_widgets(text_logger)

    def _create_widgets(self, text_logger: TextLogger | None):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Header toolbar (Levels, Auto-scroll, Clear)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky='ew', padx=8, pady=(4, 6))

        lbl_filter = ttk.Label(toolbar, text='Levels:', font=('Segoe UI', 9, 'bold'))
        lbl_filter.pack(side='left', padx=(0, 6))

        self.frame_buttons_level = ttk.Frame(toolbar)
        self.frame_buttons_level.pack(side='left')

        self.check_box_log_level: dict[str, ttk.Checkbutton] = {}
        for level in self.log_levels.options:
            cb = ttk.Checkbutton(
                self.frame_buttons_level,
                text=level,
                variable=self.log_levels.checkboxes[level],
                command=self._handle_level_change,
            )
            cb.pack(side='left', padx=4)
            self.check_box_log_level[level] = cb

        # Right side of toolbar: Auto-scroll checkbox & Clear button
        self.checkbox_auto_scroll = ttk.Checkbutton(
            toolbar,
            text='Auto-scroll',
            variable=self.toggle_auto_scroll,
            command=self._handle_auto_scroll_toggle,
        )
        self.checkbox_auto_scroll.pack(side='right', padx=(6, 2))

        btn_clear = ttk.Button(
            toolbar,
            text='Clear Log',
            command=self.clear_log,
            width=10,
        )
        btn_clear.pack(side='right', padx=(2, 6))

        # Main Log Text View
        if text_logger is not None:
            self.text_logger = text_logger
        else:
            self.text_logger = TextLogger(self, state=TkinterCfgState.DISABLED.value, height=28, width=135)
        self.text_logger.set_log_levels(self.log_levels.get())
        self.text_logger.grid(row=1, column=0, sticky='nsew', padx=8, pady=(0, 8))

    def _handle_level_change(self):
        self.text_logger.set_log_levels(self.log_levels.get())
        if self.on_update_log_levels:
            self.on_update_log_levels()
        if self.toggle_auto_scroll.get():
            self.text_logger.yview(tk.END)

    def _handle_auto_scroll_toggle(self):
        if self.on_toggle_auto_scroll:
            self.on_toggle_auto_scroll()
        if self.toggle_auto_scroll.get():
            self.text_logger.yview(tk.END)

    def clear_log(self):
        self.text_logger.configure(state=TkinterCfgState.NORMAL.value)
        self.text_logger.delete('1.0', tk.END)
        self.text_logger.lines.clear()
        self.text_logger.configure(state=TkinterCfgState.DISABLED.value)

    def apply_theme(self, theme_name: str = 'light'):
        """Apply clean light/day theme styling to text logger."""
        self.text_logger.configure(
            bg='#ffffff',
            fg='#1c1c1c',
            insertbackground='#000000',
            selectbackground='#b0c4de',
        )
        self.text_logger.tag_config('DEBUG', foreground='gray')
        self.text_logger.tag_config('INFO', foreground='black')
        self.text_logger.tag_config('WARNING', foreground='orange')
        self.text_logger.tag_config('ERROR', foreground='red')
        self.text_logger.tag_config('CRITICAL', foreground='red', underline=True)
