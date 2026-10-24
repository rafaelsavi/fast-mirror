import tkinter as tk
from tkinter import ttk

from gui.widgets import BadgeLabel


class StatusBar(ttk.Frame):
    """Status bar displaying engine status and next scheduled synchronization."""

    def __init__(
        self,
        master: tk.Misc,
        text_var_status: tk.StringVar,
        text_var_next_appointment: tk.StringVar,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.text_var_status = text_var_status
        self.text_var_next_appointment = text_var_next_appointment

        self._create_widgets()

    def _create_widgets(self):
        self.columnconfigure(1, weight=1)

        # Left: App status with colored pill badge
        status_box = ttk.Frame(self)
        status_box.grid(row=0, column=0, sticky='w', padx=(4, 16), pady=2)

        lbl_status_title = ttk.Label(status_box, text='Engine Status: ', font=('Segoe UI', 10, 'bold'))
        lbl_status_title.pack(side='left')

        self.lbl_status_pill = BadgeLabel(
            status_box,
            text='● Standby',
            variant='success',
            font=('Segoe UI', 9, 'bold'),
            padx=8,
            pady=2,
        )
        self.lbl_status_pill.pack(side='left', padx=(2, 0))
        self.lbl_status_val = self.lbl_status_pill

        # Right: Next scheduled appointment
        sched_box = ttk.Frame(self)
        sched_box.grid(row=0, column=1, sticky='e', padx=8, pady=2)

        lbl_sched_title = ttk.Label(sched_box, text='Next Sync: ', font=('Segoe UI', 10, 'bold'))
        lbl_sched_title.pack(side='left')

        self.lbl_sched_val = ttk.Label(
            sched_box,
            textvariable=self.text_var_next_appointment,
            font=('Segoe UI', 9),
        )
        self.lbl_sched_val.pack(side='left')

        sep = ttk.Separator(self, orient='horizontal')
        sep.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4, 0))

        # Trace status changes
        self.text_var_status.trace_add('write', self._on_status_changed)
        self._on_status_changed()

    def _on_status_changed(self, *args):
        raw_status = self.text_var_status.get()
        status_lower = raw_status.lower()
        if 'running' in status_lower:
            self.lbl_status_pill.set_variant('primary', text=f'● {raw_status}')
        elif 'stopping' in status_lower:
            self.lbl_status_pill.set_variant('warning', text=f'● {raw_status}')
        else:  # Standby or other
            self.lbl_status_pill.set_variant('success', text=f'● {raw_status}')
