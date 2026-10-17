import contextlib
import os
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
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
        self.columnconfigure(0, weight=1)

        # Row 0: Action Toolbar (Header label + Horizontal buttons)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky='ew', padx=8, pady=(4, 4))

        lbl_paths = ttk.Label(toolbar, text='Directory Pairs:', font=('Segoe UI', 9, 'bold'))
        lbl_paths.pack(side='left', padx=(0, 8))

        self.btn_add_path = ttk.Button(
            toolbar,
            text='➕ Add Pair',
            command=self._handle_add_path,
            width=12,
        )
        self.btn_add_path.pack(side='left', padx=2)

        self.btn_manage_paths = ttk.Button(
            toolbar,
            text='⚙️ Manage...',
            command=self.open_pairs_manager,
            width=12,
        )
        self.btn_manage_paths.pack(side='left', padx=2)

        self.btn_check_targets = ttk.Button(
            toolbar,
            text='🩺 Health Check',
            command=self.run_target_health_check,
            width=14,
        )
        self.btn_check_targets.pack(side='left', padx=2)

        self.btn_open_selected = ttk.Button(
            toolbar,
            text='📂 Explorer',
            command=self.open_selected_folder,
            width=12,
        )
        self.btn_open_selected.pack(side='left', padx=2)

        # Row 1: Full-Width Paths Editor
        if entry_paths is not None:
            self.entry_paths = entry_paths
        else:
            self.entry_paths = EntryPaths(self, width=90, height=3)
        self.entry_paths.grid(row=1, column=0, sticky='ew', padx=8, pady=(2, 2))

        # Row 2: Health Diagnostic Status Line
        self.lbl_health_status = ttk.Label(
            self,
            text='Targets not verified. Click "Health Check" to probe reachability and storage.',
            font=('Segoe UI', 9),
            foreground='#666666',
        )
        self.lbl_health_status.grid(row=2, column=0, sticky='w', padx=8, pady=(0, 6))

        # Row 3: Exclusions Header
        excl_header = ttk.Frame(self)
        excl_header.grid(row=3, column=0, sticky='ew', padx=8, pady=(2, 2))

        lbl_exclusions = ttk.Label(excl_header, text='Ignore List (Exclusions):', font=('Segoe UI', 9, 'bold'))
        lbl_exclusions.pack(side='left', padx=(0, 6))

        self.lbl_excl_count = tk.Label(
            excl_header,
            text='0 patterns',
            font=('Segoe UI', 8, 'bold'),
            bg='#e2e8f0',
            fg='#1e293b',
            padx=7,
            pady=1,
            relief='solid',
            bd=1,
        )
        self.lbl_excl_count.pack(side='left', padx=(0, 8))

        self.btn_add_exclusion = ttk.Button(
            excl_header,
            text='➕ Add Pattern',
            command=self._handle_add_exclusion,
            width=13,
        )
        self.btn_add_exclusion.pack(side='left', padx=2)

        self.btn_manage_exclusions = ttk.Button(
            excl_header,
            text='⚙️ Manage List...',
            command=self.open_exclusions_manager,
            width=15,
        )
        self.btn_manage_exclusions.pack(side='left', padx=2)

        # Row 4: Full-Width Exclusions Entry
        if entry_exclusions is not None:
            self.entry_exclusions = entry_exclusions
        else:
            self.entry_exclusions = EntryExclusions(self, width=90)
        self.entry_exclusions.grid(row=4, column=0, sticky='ew', padx=8, pady=(2, 3))

        # Row 5: Interactive Exclusion Tag Chips
        self.chips_box = ttk.Frame(self)
        self.chips_box.grid(row=5, column=0, sticky='w', padx=8, pady=(0, 4))

        # Row 6: Exclusion Presets Checkbuttons
        chips_frame = ttk.Frame(self)
        chips_frame.grid(row=6, column=0, sticky='w', padx=8, pady=(0, 6))

        lbl_presets = ttk.Label(chips_frame, text='Presets:', font=('Segoe UI', 9, 'bold'), foreground='#555555')
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

        # Hook trace for automatic chips update
        self.entry_exclusions.var.trace_add('write', lambda *args: self._update_exclusion_chips())
        self._update_exclusion_chips()

    def _handle_add_path(self):
        if self.on_add_path:
            self.on_add_path()

    def open_pairs_manager(self):
        """Open the interactive directory pairs manager modal."""
        from gui.components.directory_pairs_modal import DirectoryPairsModal

        def _on_pairs_changed():
            top = self.winfo_toplevel()
            if hasattr(top, 'update_overview_stats'):
                top.update_overview_stats()
            self.lbl_health_status.config(
                text='Directory pairs updated. Click "Health Check" to probe reachability.',
                foreground='#1565c0',
            )

        DirectoryPairsModal(self.winfo_toplevel(), self.entry_paths, on_changed=_on_pairs_changed)

    def run_target_health_check(self):
        """Asynchronously probe all configured paths, check source existence and target free disk space."""
        raw_pairs = self.entry_paths.get_raw_pairs()
        source_errors = [err for _, _, err in raw_pairs if err]

        dirs = self.entry_paths.get_as_dir_pairs()
        if source_errors:
            if len(source_errors) > 2:
                err_summary = f'{"; ".join(source_errors[:2])} (and {len(source_errors) - 2} more)'
            else:
                err_summary = '; '.join(source_errors)
            self.lbl_health_status.config(
                text=f'🔴 Missing/Invalid Source: {err_summary}',
                foreground='#c62828',
            )
            return

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
                    if len(offline_targets) > 2:
                        offline_summary = f'{", ".join(offline_targets[:2])} (and {len(offline_targets) - 2} more)'
                    else:
                        offline_summary = ', '.join(offline_targets)
                    self.lbl_health_status.config(
                        text=f'🔴 Offline / Unreachable: {offline_summary}',
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

    def open_selected_folder(self):
        """Open the currently selected path or line under cursor in Windows File Explorer."""
        selected_text = ''
        with contextlib.suppress(Exception):
            selected_text = self.entry_paths.get_text(tk.SEL_FIRST, tk.SEL_LAST).strip().strip('"\'')

        target_to_open = ''
        if selected_text and os.path.exists(selected_text):
            target_to_open = selected_text
        else:
            line_text = self.entry_paths.get_text('insert linestart', 'insert lineend').strip()
            if ' -> ' in line_text:
                source, target = [p.strip().strip('"\'') for p in line_text.split(' -> ', 1)]
                cursor_idx = self.entry_paths.index('insert')
                cursor_col = int(cursor_idx.split('.')[1])
                arrow_idx = line_text.find(' -> ')
                if cursor_col > arrow_idx + 3:
                    target_to_open = target if os.path.exists(target) else os.path.dirname(target)
                else:
                    target_to_open = source
            elif os.path.exists(line_text.strip('"\'')):
                target_to_open = line_text.strip('"\'')

        if target_to_open and os.path.exists(target_to_open):
            try:
                if hasattr(os, 'startfile'):
                    os.startfile(target_to_open)
                else:
                    import subprocess

                    subprocess.Popen(['explorer', target_to_open])
            except Exception as e:
                messagebox.showerror('Explorer Error', f'Could not open directory: {e}')
        else:
            messagebox.showinfo(
                'Open in Explorer',
                'Please click on or select a valid directory path in the Paths box to open in Explorer.',
            )

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

    def _handle_add_exclusion(self):
        from tkinter import simpledialog

        pattern = simpledialog.askstring(
            'Add Ignore Pattern',
            'Enter glob pattern to ignore (e.g. *.iso, cache/**, node_modules):',
            parent=self.winfo_toplevel(),
        )
        if pattern:
            from utils.utils import sanitize_path

            sanitized = sanitize_path(pattern.strip())
            current = self.entry_exclusions.get()
            if sanitized not in current:
                self.entry_exclusions.set(current + [sanitized])

    def open_exclusions_manager(self):
        """Open the interactive ignore patterns manager modal."""
        from gui.components.exclusions_modal import ExclusionsModal

        ExclusionsModal(self.winfo_toplevel(), self.entry_exclusions, on_changed=self._update_exclusion_chips)

    def _remove_single_exclusion(self, pattern: str):
        current = self.entry_exclusions.get()
        if pattern in current:
            remaining = [p for p in current if p != pattern]
            self.entry_exclusions.set(remaining)

    def _update_exclusion_chips(self, *args):
        if not hasattr(self, 'chips_box') or not hasattr(self, 'lbl_excl_count'):
            return
        patterns = self.entry_exclusions.get()
        self.lbl_excl_count.config(text=f'{len(patterns)} patterns')

        for child in self.chips_box.winfo_children():
            child.destroy()

        max_visible = 6
        for pattern in patterns[:max_visible]:
            chip = tk.Frame(self.chips_box, bg='#f1f5f9', bd=1, relief='solid')
            chip.pack(side='left', padx=(0, 4), pady=1)

            lbl = tk.Label(chip, text=pattern, font=('Segoe UI', 8), bg='#f1f5f9', fg='#334155', padx=5, pady=1)
            lbl.pack(side='left')

            btn_del = tk.Label(
                chip,
                text='✕',
                font=('Segoe UI', 8, 'bold'),
                bg='#f1f5f9',
                fg='#94a3b8',
                padx=4,
                pady=1,
                cursor='hand2',
            )
            btn_del.pack(side='left')
            btn_del.bind('<Button-1>', lambda e, p=pattern: self._remove_single_exclusion(p))

        if len(patterns) > max_visible:
            remaining = len(patterns) - max_visible
            lbl_more = tk.Label(
                self.chips_box,
                text=f'+{remaining} more...',
                font=('Segoe UI', 8, 'bold'),
                bg='#e2e8f0',
                fg='#0369a1',
                padx=6,
                pady=1,
                relief='solid',
                bd=1,
                cursor='hand2',
            )
            lbl_more.pack(side='left', padx=2)
            lbl_more.bind('<Button-1>', lambda e: self.open_exclusions_manager())

    def set_enabled(self, enabled: bool):
        """Enable or disable interactive widgets in the paths panel."""
        state: Literal['normal', 'disabled'] = 'normal' if enabled else 'disabled'
        self.btn_add_path.configure(state=state)
        self.btn_manage_paths.configure(state=state)
        self.btn_check_targets.configure(state=state)
        self.btn_open_selected.configure(state=state)
        self.btn_add_exclusion.configure(state=state)
        self.btn_manage_exclusions.configure(state=state)
        self.cb_preset_junk.configure(state=state)
        self.cb_preset_dev.configure(state=state)
        self.cb_preset_temp.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_paths.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_exclusions.configure(state=state)
