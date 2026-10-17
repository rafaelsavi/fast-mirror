import contextlib
import tkinter as tk
from tkinter import ttk
from typing import Literal

from gui.widgets import EntryTimes, WeekDays


class SchedulePanel(ttk.LabelFrame):
    """Panel managing backup schedule days and execution times."""

    def __init__(
        self,
        master: tk.Misc,
        week_days: WeekDays | None = None,
        entry_times: EntryTimes | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' Schedule Settings ', **kwargs)
        self.week_days = week_days or WeekDays()

        self._create_widgets(entry_times)

    def _create_widgets(self, entry_times: EntryTimes | None):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # Days Container
        days_box = ttk.Frame(self)
        days_box.grid(row=0, column=0, sticky='nw', padx=8, pady=4)

        lbl_days = ttk.Label(days_box, text='Week Days:', font=('Segoe UI', 9, 'bold'))
        lbl_days.pack(anchor='w', pady=(0, 2))

        # Quick day presets row
        preset_frame = ttk.Frame(days_box)
        preset_frame.pack(anchor='w', pady=(0, 4))

        self.btn_weekdays = ttk.Button(
            preset_frame,
            text='Mon-Fri',
            width=7,
            command=self._set_weekdays,
        )
        self.btn_weekdays.pack(side='left', padx=(0, 2))

        self.btn_all_days = ttk.Button(
            preset_frame,
            text='All',
            width=4,
            command=self._set_all_days,
        )
        self.btn_all_days.pack(side='left', padx=2)

        self.btn_clear_days = ttk.Button(
            preset_frame,
            text='Clear',
            width=5,
            command=self._clear_days,
        )
        self.btn_clear_days.pack(side='left', padx=2)

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

        # Times Container
        times_box = ttk.Frame(self)
        times_box.grid(row=0, column=1, sticky='ne', padx=8, pady=4)

        lbl_times = ttk.Label(times_box, text='Times (hh:mm):', font=('Segoe UI', 9, 'bold'))
        lbl_times.pack(anchor='w', pady=(0, 4))

        if entry_times is not None:
            self.entry_times = entry_times
        else:
            self.entry_times = EntryTimes(times_box, width=8, height=5)
        self.entry_times.pack(anchor='w', pady=(0, 2))

    def _set_weekdays(self):
        self.week_days.set(['MON', 'TUE', 'WED', 'THU', 'FRI'])

    def _set_all_days(self):
        self.week_days.set(list(self.week_days.options))

    def _clear_days(self):
        self.week_days.set([])

    def set_enabled(self, enabled: bool):
        """Enable or disable interactive widgets in the schedule panel."""
        state: Literal['normal', 'disabled'] = 'normal' if enabled else 'disabled'
        self.btn_weekdays.configure(state=state)
        self.btn_all_days.configure(state=state)
        self.btn_clear_days.configure(state=state)
        for cb in self.checkbox_week_days.values():
            cb.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_times.configure(state=state)
