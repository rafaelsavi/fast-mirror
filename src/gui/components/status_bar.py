import contextlib
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import sv_ttk


class StatusBar(ttk.Frame):
    """Status bar and application header displaying engine state, next sync countdown, and theme controls."""

    def __init__(
        self,
        master: tk.Misc,
        text_var_status: tk.StringVar,
        text_var_next_appointment: tk.StringVar,
        on_toggle_theme: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.text_var_status = text_var_status
        self.text_var_next_appointment = text_var_next_appointment
        self.on_toggle_theme = on_toggle_theme

        self._create_widgets()

    def _create_widgets(self):
        self.columnconfigure(1, weight=1)

        # Left: App title and status
        status_box = ttk.Frame(self)
        status_box.grid(row=0, column=0, sticky='w', padx=(4, 16), pady=2)

        lbl_status_title = ttk.Label(status_box, text='Engine Status: ', font=('Segoe UI', 9, 'bold'))
        lbl_status_title.pack(side='left')

        self.lbl_status_val = ttk.Label(
            status_box,
            textvariable=self.text_var_status,
            font=('Segoe UI', 9, 'bold'),
        )
        self.lbl_status_val.pack(side='left')

        # Center: Next scheduled appointment
        sched_box = ttk.Frame(self)
        sched_box.grid(row=0, column=1, sticky='w', padx=8, pady=2)

        lbl_sched_title = ttk.Label(sched_box, text='Next Sync: ', font=('Segoe UI', 9, 'bold'))
        lbl_sched_title.pack(side='left')

        lbl_sched_val = ttk.Label(
            sched_box,
            textvariable=self.text_var_next_appointment,
            font=('Segoe UI', 9),
        )
        lbl_sched_val.pack(side='left')

        # Right: Theme toggle button
        theme_box = ttk.Frame(self)
        theme_box.grid(row=0, column=2, sticky='e', padx=(8, 4), pady=2)

        self.btn_theme = ttk.Button(
            theme_box,
            text=self._get_theme_button_text(),
            command=self._handle_theme_toggle,
            width=12,
        )
        self.btn_theme.pack(side='right')

    def _get_theme_button_text(self) -> str:
        try:
            curr = sv_ttk.get_theme()
            return '☀️ Light Mode' if curr == 'dark' else '🌙 Dark Mode'
        except Exception:
            return '🌙 Theme'

    def _handle_theme_toggle(self):
        if self.on_toggle_theme:
            self.on_toggle_theme()
        else:
            with contextlib.suppress(Exception):
                sv_ttk.toggle_theme()
        self.btn_theme.config(text=self._get_theme_button_text())
