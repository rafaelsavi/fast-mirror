"""
Paths and exclusions configuration panel.
Displays compact, syntax-highlighted text editors for directory pairs and exclusions on the main screen,
backed by dedicated management windows (DirectoryPairsModal & ExclusionsModal).
"""

import contextlib
import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Literal

from gui.health_check import TargetHealth, probe_targets_async
from gui.icons import apply_icon
from gui.widgets import EntryExclusions, EntryPaths
from utils.utils import DirectoryPair


class PathsPanel(ttk.LabelFrame):
    """Panel managing configured directory backup pairs, target health diagnostics, and file exclusions."""

    def __init__(
        self,
        master: tk.Misc,
        entry_paths: EntryPaths | None = None,
        entry_exclusions: EntryExclusions | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' Directory Pairs & Exclusions ', **kwargs)

        self._pair_health_cache: dict[str, TargetHealth] = {}

        self._create_widgets(entry_paths, entry_exclusions)

    def _create_widgets(
        self,
        entry_paths: EntryPaths | None,
        entry_exclusions: EntryExclusions | None,
    ):
        self.columnconfigure(0, weight=1)

        # Row 0: Action Toolbar (Header label + Count badge + Action buttons)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky='ew', padx=8, pady=(4, 2))

        lbl_paths = ttk.Label(toolbar, text='Directory Pairs:', font=('Segoe UI', 9, 'bold'))
        lbl_paths.pack(side='left', padx=(0, 6))

        self.lbl_pair_count = tk.Label(
            toolbar,
            text='0 configured',
            font=('Segoe UI', 8, 'bold'),
            bg='#e2e8f0',
            fg='#1e293b',
            padx=6,
            pady=1,
            relief='solid',
            bd=1,
        )
        self.lbl_pair_count.pack(side='left', padx=(0, 8))

        self.btn_manage_paths = ttk.Button(
            toolbar,
            text='Manage Pairs...',
            command=self.open_pairs_manager,
            width=16,
        )
        apply_icon(self.btn_manage_paths, 'gear')
        self.btn_manage_paths.pack(side='left', padx=2)

        self.btn_check_targets = ttk.Button(
            toolbar,
            text='Health Check',
            command=self.run_target_health_check,
            width=15,
        )
        apply_icon(self.btn_check_targets, 'pulse')
        self.btn_check_targets.pack(side='left', padx=2)

        self.btn_open_selected = ttk.Button(
            toolbar,
            text='Explorer',
            command=self.open_selected_folder,
            width=12,
        )
        apply_icon(self.btn_open_selected, 'folder')
        self.btn_open_selected.pack(side='left', padx=2)

        # Row 1: Non-Editable Syntax-Highlighted Directory Pairs Display (ScrolledText)
        if entry_paths is not None:
            self.entry_paths = entry_paths
        else:
            self.entry_paths = EntryPaths(self, width=90, height=5)

        self.entry_paths.configure(state=tk.DISABLED, cursor='arrow')
        self.entry_paths.grid(row=1, column=0, sticky='ew', padx=8, pady=(2, 2))
        self.entry_paths.on_changed = self._update_pair_stats

        # Row 2: Health Diagnostic Status Line
        self.lbl_health_status = ttk.Label(
            self,
            text='Targets not verified. Click "Health Check" to probe reachability and storage.',
            font=('Segoe UI', 9),
            foreground='#666666',
        )
        self.lbl_health_status.grid(row=2, column=0, sticky='w', padx=8, pady=(1, 5))

        # Row 3: Exclusions Header Toolbar
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
            padx=6,
            pady=1,
            relief='solid',
            bd=1,
        )
        self.lbl_excl_count.pack(side='left', padx=(0, 8))

        self.btn_manage_exclusions = ttk.Button(
            excl_header,
            text='Manage List...',
            command=self.open_exclusions_manager,
            width=15,
        )
        apply_icon(self.btn_manage_exclusions, 'gear')
        self.btn_manage_exclusions.pack(side='left', padx=2)

        # Row 4: Non-Editable Full-Width Exclusions Entry
        if entry_exclusions is not None:
            self.entry_exclusions = entry_exclusions
        else:
            self.entry_exclusions = EntryExclusions(self, width=90)
        self.entry_exclusions.configure(state='readonly')
        self.entry_exclusions.grid(row=4, column=0, sticky='ew', padx=8, pady=(2, 4))

        # Traces for real-time count badges
        self.entry_exclusions.var.trace_add('write', lambda *args: self._update_exclusion_count())
        self._update_exclusion_count()
        self._update_pair_stats()

    def _update_pair_stats(self):
        """Update the directory pair count badge."""
        if not hasattr(self, 'lbl_pair_count') or not hasattr(self, 'entry_paths'):
            return
        pairs = self.entry_paths.get_raw_pairs()
        valid_count = sum(1 for s, t, _ in pairs if s and t)
        self.lbl_pair_count.config(text=f'{valid_count} configured')

    def _update_exclusion_count(self):
        """Update the exclusion pattern count badge."""
        if not hasattr(self, 'lbl_excl_count') or not hasattr(self, 'entry_exclusions'):
            return
        patterns = self.entry_exclusions.get()
        self.lbl_excl_count.config(text=f'{len(patterns)} patterns')

    def open_pairs_manager(self):
        """Open the interactive directory pairs manager modal."""
        from gui.components.directory_pairs_modal import DirectoryPairsModal

        def _on_pairs_changed():
            top = self.winfo_toplevel()
            if hasattr(top, 'update_overview_stats'):
                top.update_overview_stats()
            self._update_pair_stats()
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
            text=f'⏳ Checking {len(dirs)} backup targets...',
            foreground='#1565c0',
        )

        def _on_health_results(results: list[TargetHealth]):
            def _update_ui():
                online_count = sum(1 for r in results if r.is_online)
                offline_count = len(results) - online_count
                warnings = [r for r in results if r.warning]

                for r in results:
                    self._pair_health_cache[r.path] = r

                if offline_count == 0 and not warnings:
                    msg = '🟢 All targets online and healthy.'
                    color = '#2e7d32'
                elif offline_count == 0 and warnings:
                    msg = f'🟡 All {online_count} targets online ({len(warnings)} storage warnings).'
                    color = '#e65100'
                else:
                    msg = f'🔴 Health Check: {online_count}/{len(results)} online ({offline_count} unreachable).'
                    color = '#c62828'

                self.lbl_health_status.config(text=msg, foreground=color)
                top = self.winfo_toplevel()
                if hasattr(top, 'update_overview_stats'):
                    with contextlib.suppress(Exception):
                        top.update_overview_stats()

            self.after(0, _update_ui)

        target_paths = [p.target for p in dirs]
        probe_targets_async(target_paths, _on_health_results)

    def refresh_cards(self):
        """Syntax highlight and refresh pair statistics."""
        with contextlib.suppress(Exception):
            self.entry_paths.highlight_syntax()
        self._update_pair_stats()

    def _remove_single_pair(self, source: str, target: str):
        pairs = [(s, t) for s, t, _ in self.entry_paths.get_raw_pairs() if s and t]
        remaining = [p for p in pairs if not (p[0] == source and p[1] == target)]
        self.entry_paths.set(remaining)
        top = self.winfo_toplevel()
        if hasattr(top, 'update_overview_stats'):
            with contextlib.suppress(Exception):
                top.update_overview_stats()

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
            elif self.entry_paths.get():
                first_src, first_tgt = self.entry_paths.get()[0]
                target_to_open = first_tgt if os.path.exists(first_tgt) else first_src

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

    def open_exclusions_manager(self):
        """Open the interactive ignore patterns manager modal."""
        from gui.components.exclusions_modal import ExclusionsModal

        ExclusionsModal(self.winfo_toplevel(), self.entry_exclusions, on_changed=self._update_exclusion_count)

    def _remove_single_exclusion(self, pattern: str):
        current = self.entry_exclusions.get()
        if pattern in current:
            remaining = [p for p in current if p != pattern]
            self.entry_exclusions.set(remaining)

    def add_dropped_paths(self, paths: list[str]):
        """Handle folders dragged and dropped onto the paths panel."""
        valid_dirs = [p for p in paths if os.path.isdir(p)]
        if not valid_dirs:
            return
        if len(valid_dirs) >= 2:
            self.entry_paths.add(DirectoryPair(source=valid_dirs[0], target=valid_dirs[1]))
            top = self.winfo_toplevel()
            if hasattr(top, 'update_overview_stats'):
                with contextlib.suppress(Exception):
                    top.update_overview_stats()
            self._update_pair_stats()
            pair_str = f'{os.path.basename(valid_dirs[0])} -> {os.path.basename(valid_dirs[1])}'
            self.lbl_health_status.config(
                text=f'Added pair from drag & drop: {pair_str}',
                foreground='#15803d',
            )
        elif len(valid_dirs) == 1:
            from tkinter import filedialog

            target = filedialog.askdirectory(title=f'Select destination folder for {os.path.basename(valid_dirs[0])}')
            if target:
                self.entry_paths.add(DirectoryPair(source=valid_dirs[0], target=target))
                top = self.winfo_toplevel()
                if hasattr(top, 'update_overview_stats'):
                    with contextlib.suppress(Exception):
                        top.update_overview_stats()
                self._update_pair_stats()

    def set_enabled(self, enabled: bool):
        """Enable or disable interactive widgets in the paths panel."""
        state: Literal['normal', 'disabled'] = 'normal' if enabled else 'disabled'
        self.btn_manage_paths.configure(state=state)
        self.btn_check_targets.configure(state=state)
        self.btn_open_selected.configure(state=state)
        self.btn_manage_exclusions.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_paths.configure(state=tk.DISABLED)
        with contextlib.suppress(Exception):
            self.entry_exclusions.configure(state='readonly')
