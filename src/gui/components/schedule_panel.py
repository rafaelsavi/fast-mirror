import contextlib
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Literal

from gui.widgets import EntryTimes, WeekDays


class SchedulePanel(ttk.LabelFrame):
    """Panel managing backup schedule days, execution times, and automated schedule activation."""

    def __init__(
        self,
        master: tk.Misc,
        week_days: WeekDays | None = None,
        entry_times: EntryTimes | None = None,
        schedule_var: tk.BooleanVar | None = None,
        on_toggle_schedule: Callable[[bool], None] | None = None,
        text_var_next_appointment: tk.StringVar | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' Schedule Settings ', **kwargs)
        self.week_days = week_days or WeekDays()
        self.on_toggle_schedule = on_toggle_schedule
        self.schedule_var = schedule_var if schedule_var is not None else tk.BooleanVar(value=False)
        self.text_var_next_appointment = text_var_next_appointment

        self._create_widgets(entry_times)

    def _create_widgets(self, entry_times: EntryTimes | None):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # Header Box: Master automated schedule toggle switch
        header_box = ttk.Frame(self)
        header_box.grid(row=0, column=0, columnspan=2, sticky='ew', padx=8, pady=(2, 6))

        self.cb_enable_schedule = ttk.Checkbutton(
            header_box,
            text='Enable Automated Schedule',
            variable=self.schedule_var,
            command=self._on_schedule_toggle,
        )
        self.cb_enable_schedule.pack(side='left')

        self.lbl_schedule_status = ttk.Label(
            header_box,
            text='(Active)' if self.schedule_var.get() else '(Inactive)',
            font=('Segoe UI', 8, 'italic'),
            foreground='#007acc' if self.schedule_var.get() else '#777777',
        )
        self.lbl_schedule_status.pack(side='left', padx=(6, 0))

        # Thin visual divider
        sep = ttk.Separator(self, orient='horizontal')
        sep.grid(row=1, column=0, columnspan=2, sticky='ew', padx=6, pady=(0, 6))

        # Days Container (Row 2, Column 0)
        days_box = ttk.Frame(self)
        days_box.grid(row=2, column=0, sticky='nw', padx=8, pady=2)

        lbl_days = ttk.Label(days_box, text='Week Days:', font=('Segoe UI', 9, 'bold'))
        lbl_days.pack(anchor='w', pady=(0, 4))

        # 2-column grid for week days
        days_grid = ttk.Frame(days_box)
        days_grid.pack(anchor='w')

        self.checkbox_week_days: dict[str, ttk.Checkbutton] = {}
        for idx, day in enumerate(self.week_days.options):
            col = 0 if idx < 4 else 1
            row = idx if col == 0 else (idx - 4)
            cb = ttk.Checkbutton(
                days_grid,
                text=day,
                variable=self.week_days.checkboxes[day],
            )
            cb.grid(row=row, column=col, sticky='w', padx=(0, 10), pady=1)
            self.checkbox_week_days[day] = cb

        # Times Container (Row 2, Column 1)
        times_box = ttk.Frame(self)
        times_box.grid(row=2, column=1, sticky='ne', padx=8, pady=2)

        lbl_times = ttk.Label(times_box, text='Times (hh:mm):', font=('Segoe UI', 9, 'bold'))
        lbl_times.pack(anchor='w', pady=(0, 4))

        if entry_times is not None:
            self.entry_times = entry_times
        else:
            self.entry_times = EntryTimes(times_box, width=8, height=5)
        self.entry_times.pack(anchor='w', pady=(0, 2))

    def _on_schedule_toggle(self):
        active = bool(self.schedule_var.get())
        self._update_status_label(active)
        if self.on_toggle_schedule:
            self.on_toggle_schedule(active)

    def _update_status_label(self, active: bool):
        if hasattr(self, 'lbl_schedule_status'):
            self.lbl_schedule_status.config(
                text='(Active)' if active else '(Inactive)',
                foreground='#007acc' if active else '#777777',
            )

    @property
    def toggle_state_schedule(self) -> bool:
        return bool(self.schedule_var.get())

    @toggle_state_schedule.setter
    def toggle_state_schedule(self, value: bool):
        self.schedule_var.set(value)
        self._update_status_label(value)

    @property
    def button_schedule_sync(self):
        """Backward-compatibility alias pointing to cb_enable_schedule."""
        return self.cb_enable_schedule

    def set_enabled(self, enabled: bool):
        """Enable or disable interactive widgets in the schedule panel."""
        state: Literal['normal', 'disabled'] = 'normal' if enabled else 'disabled'
        with contextlib.suppress(Exception):
            self.cb_enable_schedule.configure(state=state)
        for cb in self.checkbox_week_days.values():
            cb.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_times.configure(state=state)
