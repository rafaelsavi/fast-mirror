import contextlib
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Literal

from gui.health_check import TargetHealth, probe_targets_async
from gui.widgets import EntryExclusions, EntryPaths


class PathsPanel(ttk.LabelFrame):
    """Panel managing configured directory backup pairs, target health diagnostics, and file exclusions."""

    PRESET_OS_JUNK = ['Thumbs.db', 'desktop.ini', '$RECYCLE.BIN', '.DS_Store']
    PRESET_DEV = ['.git', 'node_modules', '__pycache__', '.venv']
    PRESET_TEMP = ['*.tmp', '*.~*', '~$*']

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

        self._preset_vars: dict[str, tk.BooleanVar] = {
            'os_junk': tk.BooleanVar(value=False),
            'dev': tk.BooleanVar(value=False),
            'temp': tk.BooleanVar(value=False),
        }

        self._create_widgets(entry_paths, entry_exclusions)

    def _create_widgets(
        self,
        entry_paths: EntryPaths | None,
        entry_exclusions: EntryExclusions | None,
    ):
        self.columnconfigure(2, weight=1)

        # Row 0: Directory Pairs & Action Buttons
        lbl_paths = ttk.Label(self, text='Paths:', font=('Segoe UI', 9, 'bold'))
        lbl_paths.grid(row=0, column=0, sticky='nw', padx=(8, 4), pady=(6, 2))

        btn_box = ttk.Frame(self)
        btn_box.grid(row=0, column=1, sticky='nw', padx=4, pady=(4, 2))

        self.btn_add_path = ttk.Button(
            btn_box,
            text='+ Add Pair',
            command=self._handle_add_path,
            width=11,
        )
        self.btn_add_path.pack(anchor='w', pady=(0, 2))

        self.btn_check_targets = ttk.Button(
            btn_box,
            text='🩺 Health Check',
            command=self.run_target_health_check,
            width=14,
        )
        self.btn_check_targets.pack(anchor='w')

        if entry_paths is not None:
            self.entry_paths = entry_paths
        else:
            self.entry_paths = EntryPaths(self, width=110, height=3)
        self.entry_paths.grid(row=0, column=2, sticky='ew', padx=(4, 8), pady=(4, 2))

        # Row 1: Health Diagnostic Status Line
        self.lbl_health_status = ttk.Label(
            self,
            text='Targets not verified. Click "Health Check" to probe reachability and storage.',
            font=('Segoe UI', 8),
            foreground='#666666',
        )
        self.lbl_health_status.grid(row=1, column=2, sticky='w', padx=(4, 8), pady=(0, 4))

        # Row 2: Exclusions
        lbl_exclusions = ttk.Label(self, text='Exclusions:', font=('Segoe UI', 9, 'bold'))
        lbl_exclusions.grid(row=2, column=0, columnspan=2, sticky='w', padx=(8, 4), pady=(4, 2))

        if entry_exclusions is not None:
            self.entry_exclusions = entry_exclusions
        else:
            self.entry_exclusions = EntryExclusions(self, width=110)
        self.entry_exclusions.grid(row=2, column=2, sticky='ew', padx=(4, 8), pady=(4, 2))

        # Row 3: Exclusion Presets Chips
        chips_frame = ttk.Frame(self)
        chips_frame.grid(row=3, column=2, sticky='w', padx=(4, 8), pady=(0, 6))

        lbl_presets = ttk.Label(chips_frame, text='Presets:', font=('Segoe UI', 8, 'bold'), foreground='#555555')
        lbl_presets.pack(side='left', padx=(0, 6))

        self.cb_preset_junk = ttk.Checkbutton(
            chips_frame,
            text='OS Junk (Thumbs.db, .DS_Store)',
            variable=self._preset_vars['os_junk'],
            command=lambda: self._on_preset_toggled(self.PRESET_OS_JUNK, self._preset_vars['os_junk']),
        )
        self.cb_preset_junk.pack(side='left', padx=(0, 8))

        self.cb_preset_dev = ttk.Checkbutton(
            chips_frame,
            text='Dev (.git, node_modules, .venv)',
            variable=self._preset_vars['dev'],
            command=lambda: self._on_preset_toggled(self.PRESET_DEV, self._preset_vars['dev']),
        )
        self.cb_preset_dev.pack(side='left', padx=(0, 8))

        self.cb_preset_temp = ttk.Checkbutton(
            chips_frame,
            text='Temp (*.tmp, *.~*)',
            variable=self._preset_vars['temp'],
            command=lambda: self._on_preset_toggled(self.PRESET_TEMP, self._preset_vars['temp']),
        )
        self.cb_preset_temp.pack(side='left')

    def _handle_add_path(self):
        if self.on_add_path:
            self.on_add_path()

    def run_target_health_check(self):
        """Asynchronously probe all target destinations and report health/disk space."""
        dirs = self.entry_paths.get_as_dir_pairs()
        if not dirs:
            self.lbl_health_status.config(
                text='⚠️ No paths configured to check.',
                foreground='#e65100',
            )
            return

        self.lbl_health_status.config(
            text='⏳ Probing targets reachability and free disk space...',
            foreground='#1565c0',
        )

        def _on_results(results: list[TargetHealth]):
            def _update_ui():
                if not results:
                    return
                all_online = all(r.is_online for r in results)
                any_warning = any(r.warning for r in results if r.is_online)

                if not all_online:
                    offline_targets = [r.path for r in results if not r.is_online]
                    self.lbl_health_status.config(
                        text=f'🔴 Offline / Unreachable: {", ".join(offline_targets)}',
                        foreground='#c62828',
                    )
                elif any_warning:
                    warn_texts = [f'{r.path} ({r.warning})' for r in results if r.warning]
                    self.lbl_health_status.config(
                        text=f'⚠️ {"; ".join(warn_texts)}',
                        foreground='#e65100',
                    )
                else:
                    summaries = [f'{r.free_str} free of {r.total_str}' for r in results]
                    self.lbl_health_status.config(
                        text=f'🟢 All targets online • Capacity: {"; ".join(summaries)}',
                        foreground='#2e7d32',
                    )

            self.after(0, _update_ui)

        probe_targets_async(dirs, _on_results)

    def _on_preset_toggled(self, patterns: list[str], var: tk.BooleanVar):
        current_exclusions = self.entry_exclusions.get()
        if var.get():
            # Add patterns that are not already present
            new_patterns = [p for p in patterns if p not in current_exclusions]
            if new_patterns:
                self.entry_exclusions.set(current_exclusions + new_patterns)
        else:
            # Remove patterns
            remaining = [p for p in current_exclusions if p not in patterns]
            self.entry_exclusions.set(remaining)

    def set_enabled(self, enabled: bool):
        """Enable or disable interactive widgets in the paths panel."""
        state: Literal['normal', 'disabled'] = 'normal' if enabled else 'disabled'
        self.btn_add_path.configure(state=state)
        self.btn_check_targets.configure(state=state)
        self.cb_preset_junk.configure(state=state)
        self.cb_preset_dev.configure(state=state)
        self.cb_preset_temp.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_paths.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_exclusions.configure(state=state)
