import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from gui.widgets import EntryExclusions, EntryPaths


class PathsPanel(ttk.LabelFrame):
    """Panel managing configured directory backup pairs and file exclusions."""

    def __init__(
        self,
        master: tk.Misc,
        on_add_path: Callable[[], None] | None = None,
        entry_paths: EntryPaths | None = None,
        entry_exclusions: EntryExclusions | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' Directory Pairs & Exclusions ', **kwargs)
        self.on_add_path = on_add_path

        self._create_widgets(entry_paths, entry_exclusions)

    def _create_widgets(
        self,
        entry_paths: EntryPaths | None,
        entry_exclusions: EntryExclusions | None,
    ):
        self.columnconfigure(2, weight=1)

        # Row 0: Directory Pairs
        lbl_paths = ttk.Label(self, text='Paths:', font=('Segoe UI', 9, 'bold'))
        lbl_paths.grid(row=0, column=0, sticky='nw', padx=(8, 4), pady=(6, 4))

        self.btn_add_path = ttk.Button(
            self,
            text='+ Add Pair',
            command=self._handle_add_path,
            width=11,
        )
        self.btn_add_path.grid(row=0, column=1, sticky='nw', padx=4, pady=(4, 4))

        if entry_paths is not None:
            self.entry_paths = entry_paths
        else:
            self.entry_paths = EntryPaths(self, width=110, height=3)
        self.entry_paths.grid(row=0, column=2, sticky='ew', padx=(4, 8), pady=(4, 4))

        # Row 1: Exclusions
        lbl_exclusions = ttk.Label(self, text='Exclusions:', font=('Segoe UI', 9, 'bold'))
        lbl_exclusions.grid(row=1, column=0, columnspan=2, sticky='w', padx=(8, 4), pady=(4, 6))

        if entry_exclusions is not None:
            self.entry_exclusions = entry_exclusions
        else:
            self.entry_exclusions = EntryExclusions(self, width=110)
        self.entry_exclusions.grid(row=1, column=2, sticky='ew', padx=(4, 8), pady=(4, 6))

    def _handle_add_path(self):
        if self.on_add_path:
            self.on_add_path()
