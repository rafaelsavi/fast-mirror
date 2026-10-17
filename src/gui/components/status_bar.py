import tkinter as tk
from tkinter import ttk


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

        # Left: App status
        status_box = ttk.Frame(self)
        status_box.grid(row=0, column=0, sticky='w', padx=(4, 16), pady=2)

        lbl_status_title = ttk.Label(status_box, text='Engine Status: ', font=('Segoe UI', 10, 'bold'))
        lbl_status_title.pack(side='left')

        self.lbl_status_val = ttk.Label(
            status_box,
            textvariable=self.text_var_status,
            font=('Segoe UI', 10, 'bold'),
        )
        self.lbl_status_val.pack(side='left')

        # Right: Next scheduled appointment
        sched_box = ttk.Frame(self)
        sched_box.grid(row=0, column=1, sticky='e', padx=8, pady=2)

        lbl_sched_title = ttk.Label(sched_box, text='Next Sync: ', font=('Segoe UI', 10, 'bold'))
        lbl_sched_title.pack(side='left')

        lbl_sched_val = ttk.Label(
            sched_box,
            textvariable=self.text_var_next_appointment,
            font=('Segoe UI', 9),
        )
        lbl_sched_val.pack(side='left')

        sep = ttk.Separator(self, orient='horizontal')
        sep.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4, 0))
