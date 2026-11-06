import contextlib
import os
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk

from gui.components.base_modal import BaseModalDialog
from gui.health_check import TargetHealth, probe_single_target
from gui.icons import apply_icon, apply_window_icon, conceal_window, reveal_window
from gui.widgets import BadgeLabel, DirectoryPair, EntryPaths, add_tooltip
from utils.utils import sanitize_path
from utils.volume import (
    extract_endpoint_root,
    get_volume_info,
    matches_root_prefix,
    normalize_root_path,
    replace_root_prefix,
)


class DirectoryPairsModal(BaseModalDialog):
    """Interactive management modal for reviewing, adding, editing, and validating directory backup pairs."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | None,
        entry_paths: EntryPaths,
        on_changed: Callable[[], None] | None = None,
        health_cache: dict[str, TargetHealth] | None = None,
    ):
        self.entry_paths = entry_paths
        self.on_changed = on_changed
        self._health_cache: dict[str, TargetHealth] = health_cache if health_cache is not None else {}

        if hasattr(self.entry_paths, 'get_configured_pairs'):
            self._pairs = list(self.entry_paths.get_configured_pairs())
        else:
            self._pairs = list(self.entry_paths.get())

        super().__init__(
            parent=parent,
            title='Directory Backup Pairs Manager',
            width=880,
            height=520,
            min_width=840,
            min_height=480,
            modal=True,
        )
        apply_window_icon(self.window)

        self._create_widgets()
        self._populate_table()
        self._center_and_reveal()

    def _create_widgets(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)

        # 1. Header Banner
        banner = ttk.Frame(self.window, padding=(12, 10, 12, 6))
        banner.grid(row=0, column=0, sticky='ew')
        banner.columnconfigure(0, weight=1)

        header_top = ttk.Frame(banner)
        header_top.pack(fill='x')

        lbl_title = ttk.Label(
            header_top,
            text='📁 Directory Backup Pairs',
            font=('Segoe UI', 12, 'bold'),
        )
        lbl_title.pack(side='left')

        self.lbl_stats = BadgeLabel(
            header_top,
            text=f'{len(self._pairs)} configured pairs',
            variant='neutral_bold',
        )
        self.lbl_stats.pack(side='right')

        lbl_desc = ttk.Label(
            banner,
            text='Manage source-to-destination backup mappings. Double-click or select a pair to edit or explore.',
            font=('Segoe UI', 9),
            foreground='#555555',
        )
        lbl_desc.pack(anchor='w', pady=(2, 0))

        # 2. Action Toolbar
        toolbar = ttk.Frame(self.window, padding=(12, 4, 12, 6))
        toolbar.grid(row=1, column=0, sticky='ew')

        self.btn_add = ttk.Button(
            toolbar,
            text='Add Pair...',
            command=self._handle_add_pair,
            width=13,
        )
        apply_icon(self.btn_add, 'plus')
        add_tooltip(self.btn_add, 'Add a new source and target directory pair to backup.')
        self.btn_add.pack(side='left', padx=(0, 4))

        self.btn_edit = ttk.Button(
            toolbar,
            text='Edit Selected...',
            command=self._handle_edit_pair,
            width=15,
        )
        apply_icon(self.btn_edit, 'pencil')
        add_tooltip(self.btn_edit, 'Edit the selected directory pair paths.')
        self.btn_edit.pack(side='left', padx=4)

        self.btn_remove = ttk.Button(
            toolbar,
            text='Remove',
            command=self._handle_remove_pair,
            width=11,
        )
        apply_icon(self.btn_remove, 'trash')
        add_tooltip(self.btn_remove, 'Remove the selected directory pair from the configuration.')
        self.btn_remove.pack(side='left', padx=4)

        self.btn_open_source = ttk.Button(
            toolbar,
            text='Open Source',
            command=self._handle_open_source,
            width=13,
        )
        apply_icon(self.btn_open_source, 'folder')
        self.btn_open_source.pack(side='left', padx=4)
        add_tooltip(self.btn_open_source, 'Open source directory in Windows File Explorer')

        self.btn_open_target = ttk.Button(
            toolbar,
            text='Open Target',
            command=self._handle_open_target,
            width=13,
        )
        apply_icon(self.btn_open_target, 'folder')
        self.btn_open_target.pack(side='left', padx=4)
        add_tooltip(self.btn_open_target, 'Open target directory or network share in Windows File Explorer')

        # Backward compatibility alias
        self.btn_explorer = self.btn_open_source

        self.btn_probe = ttk.Button(
            toolbar,
            text='Health Check',
            command=self._handle_health_check,
            width=15,
        )
        apply_icon(self.btn_probe, 'pulse')
        self.btn_probe.pack(side='left', padx=4)
        add_tooltip(self.btn_probe, 'Probe reachability and status for all directory pairs')

        self.btn_change_drive = ttk.Button(
            toolbar,
            text='Change Drive...',
            command=self._handle_change_drive,
            width=15,
        )
        apply_icon(self.btn_change_drive, 'sync')
        self.btn_change_drive.pack(side='left', padx=4)
        add_tooltip(
            self.btn_change_drive,
            'Replace a drive letter or server address across all pairs that use it (e.g. E:\\ -> F:\\).',
        )
        self.btn_roots = self.btn_change_drive

        # Backward compatibility aliases
        self.btn_health_check = self.btn_probe
        self._handle_check_status = self._handle_health_check

        # 3. Treeview Table
        table_frame = ttk.Frame(self.window, padding=(12, 0, 12, 6))
        table_frame.grid(row=2, column=0, sticky='nsew')
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ('idx', 'source', 'target', 'status')
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show='headings',
            selectmode='browse',
        )
        self.tree.grid(row=0, column=0, sticky='nsew')

        self.tree.heading('idx', text='#')
        self.tree.heading('source', text='Source Directory (Local / Drive)')
        self.tree.heading('target', text='Target Directory (Backup / Share)')
        self.tree.heading('status', text='Status')

        self.tree.column('idx', width=40, anchor='center', stretch=False)
        self.tree.column('source', width=300, anchor='w', stretch=True)
        self.tree.column('target', width=300, anchor='w', stretch=True)
        self.tree.column('status', width=140, anchor='center', stretch=False)

        # Row status styling tags
        self.tree.tag_configure('status_online', foreground='#2e7d32')
        self.tree.tag_configure('status_error', foreground='#c62828')
        self.tree.tag_configure('status_warning', foreground='#e65100')
        self.tree.tag_configure('status_info', foreground='#0284c7')

        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.bind('<Double-1>', lambda e: self._handle_edit_pair())
        self.tree.bind('<Button-3>', self._show_context_menu)

        # 4. Bottom Footer & Apply
        footer = ttk.Frame(self.window, padding=(12, 8, 12, 12))
        footer.grid(row=3, column=0, sticky='ew')

        self.lbl_msg = ttk.Label(
            footer,
            text='Click "Apply Changes" to save edits to the main window.',
            font=('Segoe UI', 9),
            foreground='#666666',
        )
        self.lbl_msg.pack(side='left')

        btn_cancel = ttk.Button(footer, text='Cancel', command=self.window.destroy, width=11)
        btn_cancel.pack(side='right', padx=(6, 0))

        btn_apply = ttk.Button(
            footer,
            text='Apply Changes',
            command=self._apply_and_close,
            width=15,
        )
        apply_icon(btn_apply, 'save')
        btn_apply.pack(side='right')

    def _populate_table(self):
        self.tree.delete(*self.tree.get_children())
        for idx, pair in enumerate(self._pairs, start=1):
            src, tgt = pair[0], pair[1]
            status = '🟢 Online'
            tag = 'status_online'

            if not os.path.exists(src):
                status = '🔴 Missing Src'
                tag = 'status_error'
            elif not os.path.isdir(src):
                status = '⚠️ Src Not Dir'
                tag = 'status_warning'
            elif tgt in self._health_cache:
                th = self._health_cache[tgt]
                if not th.is_online:
                    status = '🔴 Target Offline'
                    tag = 'status_error'
                elif th.warning and 'Relocated' in th.warning:
                    status = f'🔵 {th.warning}'
                    tag = 'status_info'
                elif th.warning:
                    status = f'🟡 Low Space ({th.free_str})'
                    tag = 'status_warning'
            elif len(tgt) >= 2 and tgt[1] == ':' and not os.path.isdir(tgt[:2] + '\\'):
                status = '🔴 Target Offline'
                tag = 'status_error'

            self.tree.insert(
                '',
                'end',
                iid=str(idx - 1),
                values=(idx, src, tgt, status),
                tags=(tag,),
            )
        self.lbl_stats.config(text=f'{len(self._pairs)} configured pairs')

    def _handle_change_drive(self):
        """Open a simple dialog to batch-replace a drive letter or server address across all matching pairs."""
        if not self._pairs:
            messagebox.showinfo('No Pairs', 'No directory pairs are configured yet.', parent=self.window)
            return

        # Collect unique drives and network servers used across current pairs
        endpoint_counts: dict[str, int] = {}
        for pair in self._pairs:
            s, t = pair[0], pair[1]
            roots_in_pair = {r for r in (extract_endpoint_root(s), extract_endpoint_root(t)) if r}
            for r in roots_in_pair:
                endpoint_counts[r] = endpoint_counts.get(r, 0) + 1

        dropdown_items: list[str] = []
        for r_path in sorted(endpoint_counts.keys()):
            count = endpoint_counts[r_path]
            pair_word = 'pair' if count == 1 else 'pairs'
            if r_path.startswith('\\\\'):
                dropdown_items.append(f'{r_path}  (Network Server — {count} {pair_word})')
            else:
                v_info = get_volume_info(r_path)
                lbl = f'{v_info.label} — ' if (v_info and v_info.label) else ''
                dropdown_items.append(f'{r_path}  ({lbl}{count} {pair_word})')

        dialog = tk.Toplevel(self.window)
        conceal_window(dialog)
        dialog.title('Change Drive or Server Across Pairs')
        apply_window_icon(dialog)
        dialog.transient(self.window)
        dialog.resizable(False, False)

        width, height = 600, 240
        dialog.minsize(width, height)
        dialog.columnconfigure(1, weight=1)

        old_var = tk.StringVar(value=dropdown_items[0] if dropdown_items else '')
        new_var = tk.StringVar(value='')

        lbl_instruct = ttk.Label(
            dialog,
            text='Replace a drive letter or server address in all matching directory pairs:',
            font=('Segoe UI', 9, 'bold'),
        )
        lbl_instruct.grid(row=0, column=0, columnspan=3, sticky='w', padx=14, pady=(12, 10))

        ttk.Label(dialog, text='Current Drive / Server:').grid(row=1, column=0, sticky='w', padx=(14, 8), pady=6)
        combo_old = ttk.Combobox(dialog, textvariable=old_var, values=dropdown_items)
        combo_old.grid(row=1, column=1, columnspan=2, sticky='ew', padx=(4, 14), pady=6)

        ttk.Label(dialog, text='Replace With:').grid(row=2, column=0, sticky='w', padx=(14, 8), pady=6)
        entry_new = ttk.Entry(dialog, textvariable=new_var)
        entry_new.grid(row=2, column=1, sticky='ew', padx=4, pady=6)

        def _browse_new():
            folder = filedialog.askdirectory(title='Select New Drive or Base Folder', parent=dialog)
            if folder:
                new_var.set(normalize_root_path(folder))

        ttk.Button(dialog, text='Browse...', command=_browse_new, width=11).grid(
            row=2, column=2, sticky='w', padx=(4, 14), pady=6
        )

        lbl_preview = ttk.Label(dialog, text='', font=('Segoe UI', 9))
        lbl_preview.grid(row=3, column=0, columnspan=3, sticky='w', padx=14, pady=(6, 4))

        def _parse_old() -> str:
            raw = old_var.get().split('  (', 1)[0].strip().strip('"\'')
            return normalize_root_path(raw) if raw else ''

        def _update_preview(*_args):
            old_r = _parse_old()
            new_r = normalize_root_path(new_var.get()) if new_var.get().strip() else ''
            if not old_r:
                lbl_preview.config(text='Select or enter the current drive/path to replace.', foreground='#666666')
                return

            matches: list[tuple[str, str]] = [
                (p[0], p[1])
                for p in self._pairs
                if matches_root_prefix(p[0], old_r) or matches_root_prefix(p[1], old_r)
            ]
            if not matches:
                lbl_preview.config(text=f"No configured pairs start with '{old_r}'", foreground='#e65100')
                return

            if not new_r:
                lbl_preview.config(
                    text=f"Matches {len(matches)} pair(s) starting with '{old_r}'. Enter or browse the new drive/path.",
                    foreground='#1565c0',
                )
                return

            s0, t0 = matches[0]
            sample_old = s0 if matches_root_prefix(s0, old_r) else t0
            sample_new = replace_root_prefix(sample_old, old_r, new_r)
            lbl_preview.config(
                text=f'✓ Will update {len(matches)} pair(s)   (e.g. {sample_old} ➔ {sample_new})',
                foreground='#2e7d32',
            )

        old_var.trace_add('write', _update_preview)
        new_var.trace_add('write', _update_preview)
        _update_preview()

        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=4, column=0, columnspan=3, sticky='e', padx=14, pady=(12, 12))

        def _apply_replace():
            old_r = _parse_old()
            new_r = normalize_root_path(new_var.get())
            if not old_r or not new_r:
                messagebox.showerror(
                    'Validation Error', 'Please specify both the current and new drive/path.', parent=dialog
                )
                return
            if old_r.lower() == new_r.lower():
                messagebox.showinfo('No Change', 'Current and new paths are identical.', parent=dialog)
                return

            updated_count = 0
            new_pairs: list[DirectoryPair] = []
            for p in self._pairs:
                s, t = p[0], p[1]
                new_s = replace_root_prefix(s, old_r, new_r)
                new_t = replace_root_prefix(t, old_r, new_r)
                if new_s != s or new_t != t:
                    updated_count += 1
                new_pairs.append(DirectoryPair(source=new_s, target=new_t))

            if updated_count == 0:
                messagebox.showwarning('No Matches', f"No directory pairs start with '{old_r}'.", parent=dialog)
                return

            self._pairs = new_pairs
            self._populate_table()
            dialog.destroy()
            self.lbl_msg.config(
                text=f"Updated {updated_count} pair(s) from '{old_r}' to '{new_r}'. Click 'Apply Changes' to save.",
                foreground='#2e7d32',
            )

        ttk.Button(btn_frame, text='Cancel', command=dialog.destroy, width=11).pack(side='right', padx=(6, 0))
        ttk.Button(btn_frame, text='Update Pairs', command=_apply_replace, width=14).pack(side='right')

        try:
            dialog.update_idletasks()
            pw = self.window.winfo_width()
            ph = self.window.winfo_height()
            px = self.window.winfo_rootx()
            py = self.window.winfo_rooty()
            if pw > 100 and ph > 100:
                pos_x = px + max(0, (pw - width) // 2)
                pos_y = py + max(0, (ph - height) // 2)
            else:
                sw = dialog.winfo_screenwidth()
                sh = dialog.winfo_screenheight()
                pos_x = max(0, (sw - width) // 2)
                pos_y = max(0, (sh - height) // 2)
            dialog.geometry(f'{width}x{height}+{pos_x}+{pos_y}')
        except Exception:
            dialog.geometry(f'{width}x{height}')

        reveal_window(dialog)
        with contextlib.suppress(Exception):
            dialog.grab_set()

        entry_new.focus_set()

    # Alias for backward compatibility
    _handle_manage_roots = _handle_change_drive

    def _handle_add_pair(self):
        self._open_pair_editor(None, None, None)

    def _handle_edit_pair(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('Selection Required', 'Please select a directory pair to edit.', parent=self.window)
            return
        idx = int(selected[0])
        src, tgt = self._pairs[idx]
        self._open_pair_editor(src, tgt, idx)

    def _handle_remove_pair(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('Selection Required', 'Please select a directory pair to remove.', parent=self.window)
            return
        idx = int(selected[0])
        src, tgt = self._pairs[idx]
        confirm = messagebox.askyesno(
            'Remove Directory Pair',
            f'Remove backup mapping:\n\n{src} ➔ {tgt}\n\nAre you sure?',
            parent=self.window,
        )
        if confirm:
            del self._pairs[idx]
            self._populate_table()
            self.lbl_msg.config(text=f'Removed pair #{idx + 1}. Remember to click "Apply Changes".')

    def _open_directory(self, target_to_open: str, side_label: str):
        """Open the given path in Windows File Explorer with error handling."""
        if not target_to_open or not target_to_open.strip():
            messagebox.showinfo(
                'Invalid Path',
                f'No valid {side_label.lower()} directory path specified.',
                parent=self.window,
            )
            return

        target_to_open = target_to_open.strip().strip('"\'')
        if os.path.exists(target_to_open):
            try:
                if hasattr(os, 'startfile'):
                    os.startfile(target_to_open)
                else:
                    import subprocess

                    subprocess.Popen(['explorer', target_to_open])
            except Exception as e:
                messagebox.showerror(
                    'Explorer Error',
                    f'Could not open {side_label.lower()} directory: {e}',
                    parent=self.window,
                )
        else:
            messagebox.showerror(
                'Not Found',
                f'{side_label} directory does not exist or is unreachable:\n\n{target_to_open}',
                parent=self.window,
            )

    def _get_selected_pair(self) -> tuple[int, str, str] | None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('Selection Required', 'Please select a directory pair first.', parent=self.window)
            return None
        try:
            idx = int(selected[0])
            if 0 <= idx < len(self._pairs):
                src, tgt = self._pairs[idx]
                return idx, src, tgt
        except (ValueError, IndexError):
            pass
        return None

    def _handle_open_source(self):
        pair = self._get_selected_pair()
        if pair:
            _, src, _ = pair
            self._open_directory(src, 'Source')

    def _handle_open_target(self):
        pair = self._get_selected_pair()
        if pair:
            _, _, tgt = pair
            self._open_directory(tgt, 'Target')

    def _handle_open_explorer(self):
        """Backwards compatibility: opens source directory."""
        self._handle_open_source()

    def _show_context_menu(self, event: tk.Event):
        """Show right-click context menu for the clicked directory pair row."""
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return

        self.tree.selection_set(row_id)
        selected = self.tree.selection()
        if not selected:
            return

        try:
            idx = int(selected[0])
            if not (0 <= idx < len(self._pairs)):
                return
        except (ValueError, IndexError):
            return

        menu = tk.Menu(self.window, tearoff=0)
        menu.add_command(label='📂 Open Source in Explorer', command=self._handle_open_source)
        menu.add_command(label='📂 Open Target in Explorer', command=self._handle_open_target)
        menu.add_separator()
        menu.add_command(label='✏️ Edit Pair...', command=self._handle_edit_pair)
        menu.add_command(label='🗑️ Remove Pair', command=self._handle_remove_pair)
        menu.add_separator()
        menu.add_command(label='🩺 Health Check (All Pairs)', command=self._handle_health_check)

        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _handle_health_check(self):
        """Asynchronously probe all directory pairs (sources and targets), not only selected ones."""
        if not self._pairs:
            self.lbl_msg.config(text='No directory pairs configured to check.', foreground='#e65100')
            return

        total_pairs = len(self._pairs)
        self.lbl_msg.config(
            text=f'⏳ Health Check: Scanning all {total_pairs} directory pairs...',
            foreground='#1565c0',
        )
        self.btn_probe.config(state='disabled')

        pairs_to_check = list(self._pairs)

        def _worker(*_args):
            results = []
            roots = getattr(self.entry_paths, 'storage_roots', {})
            sorted_roots = sorted(
                roots.items(),
                key=lambda item: (
                    sanitize_path(item[1].path).rstrip('\\').count('\\'),
                    len(sanitize_path(item[1].path).rstrip('\\')),
                ),
                reverse=True,
            )
            for idx, pair in enumerate(pairs_to_check, start=1):
                src, tgt = pair[0], pair[1]
                src_exists = os.path.exists(src)
                src_isdir = os.path.isdir(src) if src_exists else False

                exp_serial = getattr(pair, 'target_serial', None) if isinstance(pair, DirectoryPair) else None
                exp_name = getattr(pair, 'target_root_name', None) if isinstance(pair, DirectoryPair) else None
                if not exp_serial and sorted_roots:
                    tgt_clean = sanitize_path(tgt).rstrip('\\').lower()
                    for r_name, r_obj in sorted_roots:
                        r_clean = sanitize_path(r_obj.path).rstrip('\\').lower()
                        if r_clean and (tgt_clean == r_clean or tgt_clean.startswith(r_clean + '\\')):
                            exp_serial = r_obj.serial
                            exp_name = r_name
                            break

                tgt_health = probe_single_target(tgt, expected_serial=exp_serial, expected_root_name=exp_name)
                self._health_cache[tgt] = tgt_health

                if not src_exists:
                    status = '🔴 Missing Src'
                    tag = 'status_error'
                    is_online = False
                elif not src_isdir:
                    status = '⚠️ Src Not Dir'
                    tag = 'status_warning'
                    is_online = False
                elif not tgt_health.is_online:
                    status = (
                        f'🔴 {tgt_health.error}'
                        if tgt_health.error and 'Wrong drive' in tgt_health.error
                        else '🔴 Target Offline'
                    )
                    tag = 'status_error'
                    is_online = False
                elif tgt_health.warning and 'Relocated' in tgt_health.warning:
                    status = f'🔵 {tgt_health.warning}'
                    tag = 'status_info'
                    is_online = True
                elif tgt_health.warning:
                    status = f'🟡 Low Space ({tgt_health.free_str})'
                    tag = 'status_warning'
                    is_online = True
                else:
                    status = '🟢 Online'
                    tag = 'status_online'
                    is_online = True

                results.append((idx - 1, idx, src, tgt, status, tag, is_online))

            def _update_ui():
                try:
                    if not self.window.winfo_exists():
                        return
                    self.btn_probe.config(state='normal')
                    for iid_int, idx, src, tgt, status, tag, _ in results:
                        iid = str(iid_int)
                        if self.tree.exists(iid):
                            self.tree.item(iid, values=(idx, src, tgt, status), tags=(tag,))

                    online_count = sum(1 for r in results if r[6])
                    if online_count == total_pairs:
                        self.lbl_msg.config(
                            text=f'🟢 Health Check: All {online_count} directory pairs online and healthy.',
                            foreground='#2e7d32',
                        )
                    else:
                        offline_count = total_pairs - online_count
                        msg = (
                            f'🔴 Health Check: {online_count}/{total_pairs} online '
                            f'({offline_count} unreachable/missing).'
                        )
                        self.lbl_msg.config(
                            text=msg,
                            foreground='#c62828',
                        )
                except Exception:
                    pass

            with contextlib.suppress(Exception):
                self.window.after(0, _update_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _open_pair_editor(self, default_src: str | None, default_tgt: str | None, edit_idx: int | None):
        dialog = tk.Toplevel(self.window)
        conceal_window(dialog)
        is_edit = edit_idx is not None
        dialog.title('Edit Directory Pair' if is_edit else 'Add New Directory Pair')
        apply_window_icon(dialog)
        dialog.transient(self.window)
        dialog.resizable(False, False)

        width, height = 620, 230
        dialog.minsize(width, height)

        dialog.columnconfigure(1, weight=1)

        src_var = tk.StringVar(value=default_src or '')
        tgt_var = tk.StringVar(value=default_tgt or '')

        lbl_instruct = ttk.Label(
            dialog,
            text='Specify the source and target folders for synchronization:',
            font=('Segoe UI', 9, 'bold'),
        )
        lbl_instruct.grid(row=0, column=0, columnspan=3, sticky='w', padx=14, pady=(12, 10))

        # Source row
        ttk.Label(dialog, text='Source Folder:').grid(row=1, column=0, sticky='w', padx=(14, 8), pady=6)
        entry_src = ttk.Entry(dialog, textvariable=src_var)
        entry_src.grid(row=1, column=1, sticky='ew', padx=4, pady=6)

        def _browse_src():
            folder = filedialog.askdirectory(title='Select Source Folder', parent=dialog)
            if folder:
                src_var.set(sanitize_path(folder))

        ttk.Button(dialog, text='Browse...', command=_browse_src, width=11).grid(
            row=1, column=2, sticky='w', padx=(4, 14), pady=6
        )

        # Target row
        ttk.Label(dialog, text='Target Folder:').grid(row=2, column=0, sticky='w', padx=(14, 8), pady=6)
        entry_tgt = ttk.Entry(dialog, textvariable=tgt_var)
        entry_tgt.grid(row=2, column=1, sticky='ew', padx=4, pady=6)

        def _browse_tgt():
            folder = filedialog.askdirectory(title='Select Target Destination Folder', parent=dialog)
            if folder:
                tgt_var.set(sanitize_path(folder))

        ttk.Button(dialog, text='Browse...', command=_browse_tgt, width=11).grid(
            row=2, column=2, sticky='w', padx=(4, 14), pady=6
        )

        # Buttons
        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=3, column=0, columnspan=3, sticky='e', padx=14, pady=(16, 12))

        def _save():
            s = sanitize_path(src_var.get().strip().strip('"\''))
            t = sanitize_path(tgt_var.get().strip().strip('"\''))
            if not s or not t:
                messagebox.showerror(
                    'Validation Error', 'Both source and target folders must be specified.', parent=dialog
                )
                return
            if s.lower() == t.lower():
                messagebox.showerror(
                    'Validation Error', 'Source and target folders cannot be identical.', parent=dialog
                )
                return

            if is_edit:
                self._pairs[edit_idx] = DirectoryPair(source=s, target=t)
            else:
                self._pairs.append(DirectoryPair(source=s, target=t))

            self._populate_table()
            dialog.destroy()
            action_desc = 'Updated' if is_edit else 'Added'
            self.lbl_msg.config(text=f'{action_desc} directory pair. Click "Apply Changes" to save.')

        ttk.Button(btn_frame, text='Cancel', command=dialog.destroy, width=11).pack(side='right', padx=(6, 0))
        ttk.Button(btn_frame, text='OK', command=_save, width=11).pack(side='right')

        # Center relative to parent window and smoothly reveal
        try:
            dialog.update_idletasks()
            pw = self.window.winfo_width()
            ph = self.window.winfo_height()
            px = self.window.winfo_rootx()
            py = self.window.winfo_rooty()
            if pw > 100 and ph > 100:
                pos_x = px + max(0, (pw - width) // 2)
                pos_y = py + max(0, (ph - height) // 2)
            else:
                sw = dialog.winfo_screenwidth()
                sh = dialog.winfo_screenheight()
                pos_x = max(0, (sw - width) // 2)
                pos_y = max(0, (sh - height) // 2)
            dialog.geometry(f'{width}x{height}+{pos_x}+{pos_y}')
        except Exception:
            dialog.geometry(f'{width}x{height}')

        reveal_window(dialog)
        with contextlib.suppress(Exception):
            dialog.grab_set()

        entry_src.focus_set()

    def _apply_and_close(self):
        pair_objects: list[DirectoryPair] = []
        for p in self._pairs:
            if isinstance(p, DirectoryPair):
                pair_objects.append(p)
            else:
                pair_objects.append(DirectoryPair(source=str(p[0]), target=str(p[1])))
        self.entry_paths.set(pair_objects)
        if self.on_changed:
            self.on_changed()
        self.window.destroy()
