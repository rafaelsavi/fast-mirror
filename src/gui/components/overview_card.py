import tkinter as tk
from tkinter import ttk


class OverviewCard(ttk.LabelFrame):
    """Summary overview card displaying active pairs count, mirror status, and safety profile."""

    def __init__(
        self,
        master: tk.Misc,
        text_var_pairs_count: tk.StringVar | None = None,
        text_var_mirror_status: tk.StringVar | None = None,
        text_var_confirm_status: tk.StringVar | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' System Overview ', **kwargs)

        self.text_var_pairs_count = text_var_pairs_count or tk.StringVar(value='0 pairs configured')
        self.text_var_mirror_status = text_var_mirror_status or tk.StringVar(value='Active (WAL mode)')
        self.text_var_confirm_status = text_var_confirm_status or tk.StringVar(value='Interactive Approval')

        self._create_widgets()

    def _create_widgets(self):
        self.columnconfigure(1, weight=1)

        # Row 0: Active Directory Pairs
        lbl_pairs_title = ttk.Label(self, text='📁 Directory Pairs:', font=('Segoe UI', 9, 'bold'))
        lbl_pairs_title.grid(row=0, column=0, sticky='w', padx=(6, 8), pady=3)

        self.lbl_pairs_val = ttk.Label(
            self,
            textvariable=self.text_var_pairs_count,
            font=('Segoe UI', 9),
        )
        self.lbl_pairs_val.grid(row=0, column=1, sticky='w', padx=(0, 6), pady=3)

        # Row 1: Mirror Database
        lbl_mirror_title = ttk.Label(self, text='🗄️ Mirror Cache:', font=('Segoe UI', 9, 'bold'))
        lbl_mirror_title.grid(row=1, column=0, sticky='w', padx=(6, 8), pady=3)

        self.lbl_mirror_val = ttk.Label(
            self,
            textvariable=self.text_var_mirror_status,
            font=('Segoe UI', 9),
            foreground='#2e7d32',
        )
        self.lbl_mirror_val.grid(row=1, column=1, sticky='w', padx=(0, 6), pady=3)

        # Row 2: Confirmation Safety Profile
        lbl_safety_title = ttk.Label(self, text='🛡️ Sync Safety:', font=('Segoe UI', 9, 'bold'))
        lbl_safety_title.grid(row=2, column=0, sticky='w', padx=(6, 8), pady=3)

        self.lbl_safety_val = ttk.Label(
            self,
            textvariable=self.text_var_confirm_status,
            font=('Segoe UI', 9),
        )
        self.lbl_safety_val.grid(row=2, column=1, sticky='w', padx=(0, 6), pady=3)
