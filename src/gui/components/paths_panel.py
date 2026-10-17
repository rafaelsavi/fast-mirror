import contextlib
import os
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Literal

from gui.health_check import TargetHealth, probe_targets_async
from gui.widgets import DirectoryPair, EntryExclusions, EntryPaths


class PathsPanel(ttk.LabelFrame):
    """Panel managing configured directory backup pairs, target health diagnostics, and file exclusions."""

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

        self._pair_health_cache: dict[str, TargetHealth] = {}
        self._view_mode: str = 'cards'

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

        self.btn_toggle_view = ttk.Button(
            toolbar,
            text='📝 Raw Text',
            command=self._toggle_view,
            width=12,
        )
        self.btn_toggle_view.pack(side='right', padx=2)

        # Row 1: Cards View (Scrollable Canvas Container) & Raw Text Editor
        self.cards_container = ttk.Frame(self)
        self.cards_container.grid(row=1, column=0, sticky='ew', padx=8, pady=(2, 2))
        self.cards_container.columnconfigure(0, weight=1)

        self.cards_canvas = tk.Canvas(
            self.cards_container,
            bg='#f8fafc',
            bd=1,
            relief='solid',
            highlightthickness=0,
            height=215,
        )
        self.cards_canvas.grid(row=0, column=0, sticky='nsew')

        self.cards_scrollbar = ttk.Scrollbar(
            self.cards_container,
            orient='vertical',
            command=self.cards_canvas.yview,
        )
        self.cards_scrollbar.grid(row=0, column=1, sticky='ns')
        self.cards_canvas.configure(yscrollcommand=self.cards_scrollbar.set)

        self.cards_scrollable_frame = tk.Frame(self.cards_canvas, bg='#f8fafc')
        self.cards_canvas_window = self.cards_canvas.create_window(
            (0, 0),
            window=self.cards_scrollable_frame,
            anchor='nw',
        )

        self.cards_scrollable_frame.bind(
            '<Configure>',
            lambda e: self._on_cards_frame_configure(),
        )
        self.cards_canvas.bind(
            '<Configure>',
            lambda e: self.cards_canvas.itemconfig(self.cards_canvas_window, width=e.width),
        )

        def _on_mousewheel(event):
            self.cards_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

        self.cards_canvas.bind('<Enter>', lambda e: self.cards_canvas.bind_all('<MouseWheel>', _on_mousewheel))
        self.cards_canvas.bind('<Leave>', lambda e: self.cards_canvas.unbind_all('<MouseWheel>'))

        # Maintain cards_frame as cards_scrollable_frame for seamless compatibility
        self.cards_frame = self.cards_scrollable_frame

        if entry_paths is not None:
            self.entry_paths = entry_paths
        else:
            self.entry_paths = EntryPaths(self, width=90, height=3)

        self.entry_paths.on_changed = self.refresh_cards
        self.refresh_cards()

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

        self.btn_toggle_excl_view = ttk.Button(
            excl_header,
            text='📝 Raw Text',
            command=self._toggle_exclusions_view,
            width=11,
        )
        self.btn_toggle_excl_view.pack(side='right', padx=2)

        # Row 4: Full-Width Exclusions Entry (hidden by default to avoid duplicate clutter)
        if entry_exclusions is not None:
            self.entry_exclusions = entry_exclusions
        else:
            self.entry_exclusions = EntryExclusions(self, width=90)
        self.entry_exclusions.grid(row=4, column=0, sticky='ew', padx=8, pady=(2, 3))
        self.entry_exclusions.grid_remove()
        self._exclusions_view_mode = 'chips'

        # Row 5: Interactive Exclusion Tag Chips
        self.chips_box = ttk.Frame(self)
        self.chips_box.grid(row=5, column=0, sticky='w', padx=8, pady=(0, 4))

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

                for r in results:
                    self._pair_health_cache[r.path] = r
                self.refresh_cards()

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

    def _toggle_view(self):
        """Toggle between modern visual cards view and raw monospace text editor."""
        if self._view_mode == 'cards':
            self.cards_container.grid_remove()
            self.entry_paths.grid(row=1, column=0, sticky='ew', padx=8, pady=(2, 2))
            self.btn_toggle_view.config(text='🗂️ Cards View')
            self._view_mode = 'text'
        else:
            self.entry_paths.grid_remove()
            self.cards_container.grid(row=1, column=0, sticky='ew', padx=8, pady=(2, 2))
            self.btn_toggle_view.config(text='📝 Raw Text')
            self._view_mode = 'cards'
            self.refresh_cards()

    def _toggle_exclusions_view(self):
        """Toggle between modern tag chips view and raw text box for exclusions."""
        if getattr(self, '_exclusions_view_mode', 'chips') == 'chips':
            self.entry_exclusions.grid()
            self.btn_toggle_excl_view.config(text='🏷️ Chips View')
            self._exclusions_view_mode = 'text'
        else:
            self.entry_exclusions.grid_remove()
            self.btn_toggle_excl_view.config(text='📝 Raw Text')
            self._exclusions_view_mode = 'chips'

    def _on_cards_frame_configure(self):
        """Adjust canvas scrollable region and dynamic height based on pair count."""
        if not hasattr(self, 'cards_canvas'):
            return
        self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox('all'))
        req_h = self.cards_scrollable_frame.winfo_reqheight()
        if req_h > 0:
            target_h = max(70, min(req_h + 4, 215))
            self.cards_canvas.configure(height=target_h)

    def refresh_cards(self):
        """Render modern interactive cards for each directory backup pair."""
        if not hasattr(self, 'cards_frame'):
            return

        for child in self.cards_frame.winfo_children():
            child.destroy()

        raw_pairs = self.entry_paths.get_raw_pairs()
        pairs = [(s, t) for s, t, _ in raw_pairs if s and t]
        if not pairs:
            empty_frame = tk.Frame(self.cards_frame, bg='#f8fafc', bd=1, relief='solid', padx=12, pady=10)
            empty_frame.pack(fill='x', padx=2, pady=3)
            lbl = tk.Label(
                empty_frame,
                text='📂 No directory backup pairs configured yet.\nClick "➕ Add Pair" or drag folders here.',
                font=('Segoe UI', 9),
                bg='#f8fafc',
                fg='#64748b',
                justify='center',
            )
            lbl.pack(pady=4)
            return

        for idx, (source, target) in enumerate(pairs):
            card = tk.Frame(self.cards_frame, bg='#ffffff', bd=1, relief='solid', padx=6, pady=3)
            card.pack(fill='x', padx=2, pady=2)
            card.columnconfigure(1, weight=1)

            lbl_idx = tk.Label(
                card,
                text=f'#{idx + 1}',
                font=('Segoe UI', 8, 'bold'),
                bg='#e2e8f0',
                fg='#334155',
                padx=5,
                pady=1,
            )
            lbl_idx.grid(row=0, column=0, rowspan=2, padx=(0, 6), sticky='n')

            path_row = tk.Frame(card, bg='#ffffff')
            path_row.grid(row=0, column=1, sticky='w')

            src_exists = os.path.isdir(source)
            src_icon = '📁' if src_exists else '⚠️'
            lbl_src = tk.Label(
                path_row,
                text=f'{src_icon} {source}',
                font=('Segoe UI', 9, 'bold'),
                bg='#ffffff',
                fg='#0f172a' if src_exists else '#dc2626',
                cursor='hand2',
            )
            lbl_src.pack(side='left')
            lbl_src.bind('<Double-1>', lambda e, p=source: self._open_folder_path(p))

            lbl_arrow = tk.Label(path_row, text=' ──▶ ', font=('Segoe UI', 9, 'bold'), bg='#ffffff', fg='#0d9488')
            lbl_arrow.pack(side='left', padx=3)

            is_unc = target.startswith('\\\\') or target.startswith('//')
            tgt_icon = '🖥️' if is_unc else '📁'
            lbl_tgt = tk.Label(
                path_row,
                text=f'{tgt_icon} {target}',
                font=('Segoe UI', 9),
                bg='#ffffff',
                fg='#0284c7',
                cursor='hand2',
            )
            lbl_tgt.pack(side='left')
            lbl_tgt.bind('<Double-1>', lambda e, p=target: self._open_folder_path(p))

            meta_row = tk.Frame(card, bg='#ffffff')
            meta_row.grid(row=1, column=1, sticky='ew', pady=(2, 0))
            meta_row.columnconfigure(0, weight=1)

            cached = self._pair_health_cache.get(target)
            if cached is not None:
                if cached.is_online:
                    h_text = f'🟢 Online ({cached.free_str} free)'
                    h_bg, h_fg = '#dcfce7', '#15803d'
                    if cached.warning:
                        h_text += f' • {cached.warning}'
                        h_bg, h_fg = '#fef3c7', '#b45309'
                else:
                    h_text = f'🔴 {cached.error or "Offline"}'
                    h_bg, h_fg = '#fee2e2', '#b91c1c'
            elif not src_exists:
                h_text = '🔴 Source Missing'
                h_bg, h_fg = '#fee2e2', '#b91c1c'
            else:
                h_text = '⚪ Unchecked'
                h_bg, h_fg = '#f1f5f9', '#475569'

            lbl_health = tk.Label(
                meta_row,
                text=h_text,
                font=('Segoe UI', 8),
                bg=h_bg,
                fg=h_fg,
                padx=5,
                pady=1,
                relief='solid',
                bd=1,
            )
            lbl_health.pack(side='left')

            btn_box = tk.Frame(meta_row, bg='#ffffff')
            btn_box.pack(side='right')

            btn_exp = ttk.Button(
                btn_box,
                text='📂 Explorer',
                width=10,
                command=lambda s=source, t=target: self._open_pair_in_explorer(s, t),
            )
            btn_exp.pack(side='left', padx=1)

            btn_prb = ttk.Button(
                btn_box,
                text='🩺 Probe',
                width=8,
                command=lambda s=source, t=target: self._probe_single_pair(s, t),
            )
            btn_prb.pack(side='left', padx=1)

            btn_del = ttk.Button(
                btn_box,
                text='✕',
                width=3,
                command=lambda s=source, t=target: self._remove_single_pair(s, t),
            )
            btn_del.pack(side='left', padx=1)

    def _probe_single_pair(self, source: str, target: str):
        self.lbl_health_status.config(
            text=f'⏳ Probing target {target}...',
            foreground='#1565c0',
        )

        def _on_single_result(results: list[TargetHealth]):
            def _update():
                if results:
                    r = results[0]
                    self._pair_health_cache[r.path] = r
                    self.refresh_cards()
                    if r.is_online:
                        msg = f'🟢 {r.path}: {r.free_str} free'
                        if r.warning:
                            msg += f' ({r.warning})'
                        self.lbl_health_status.config(text=msg, foreground='#2e7d32' if not r.warning else '#e65100')
                    else:
                        self.lbl_health_status.config(
                            text=f'🔴 {r.path}: {r.error or "Offline"}',
                            foreground='#c62828',
                        )

            self.after(0, _update)

        probe_targets_async([target], _on_single_result)

    def _remove_single_pair(self, source: str, target: str):
        pairs = [(s, t) for s, t, _ in self.entry_paths.get_raw_pairs() if s and t]
        remaining = [p for p in pairs if not (p[0] == source and p[1] == target)]
        self.entry_paths.set(remaining)
        top = self.winfo_toplevel()
        if hasattr(top, 'update_overview_stats'):
            with contextlib.suppress(Exception):
                top.update_overview_stats()

    def _open_folder_path(self, path: str):
        target = path.strip('"\'')
        if not os.path.exists(target) and os.path.exists(os.path.dirname(target)):
            target = os.path.dirname(target)
        if target and os.path.exists(target):
            with contextlib.suppress(Exception):
                if hasattr(os, 'startfile'):
                    os.startfile(target)
                else:
                    import subprocess

                    subprocess.Popen(['explorer', target])

    def _open_pair_in_explorer(self, source: str, target: str):
        to_open = target if os.path.exists(target) else source
        self._open_folder_path(to_open)

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
        if hasattr(self, 'btn_toggle_view'):
            self.btn_toggle_view.configure(state=state)
        self.btn_add_exclusion.configure(state=state)
        self.btn_manage_exclusions.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_paths.configure(state=state)
        with contextlib.suppress(Exception):
            self.entry_exclusions.configure(state=state)
