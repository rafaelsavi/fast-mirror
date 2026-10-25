import contextlib
import os
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk

from gui.components.base_modal import BaseModalDialog
from gui.health_check import TargetHealth, probe_single_target
from gui.icons import apply_icon, apply_window_icon
from gui.widgets import BadgeLabel, DirectoryPair, EntryPaths, add_tooltip
from utils.utils import sanitize_path


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
        self.btn_add.pack(side='left', padx=(0, 4))

        self.btn_edit = ttk.Button(
            toolbar,
            text='Edit Selected...',
            command=self._handle_edit_pair,
            width=15,
        )
        apply_icon(self.btn_edit, 'pencil')
        self.btn_edit.pack(side='left', padx=4)

        self.btn_remove = ttk.Button(
            toolbar,
            text='Remove',
            command=self._handle_remove_pair,
            width=11,
        )
        apply_icon(self.btn_remove, 'trash')
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
        for idx, (src, tgt) in enumerate(self._pairs, start=1):
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
                elif th.warning:
                    status = f'🟡 Low Space ({th.free_str})'
                    tag = 'status_warning'

            self.tree.insert(
                '',
                'end',
                iid=str(idx - 1),
                values=(idx, src, tgt, status),
                tags=(tag,),
            )
        self.lbl_stats.config(text=f'{len(self._pairs)} configured pairs')

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
            for idx, (src, tgt) in enumerate(pairs_to_check, start=1):
                src_exists = os.path.exists(src)
                src_isdir = os.path.isdir(src) if src_exists else False
                tgt_health = probe_single_target(tgt)
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
                    status = '🔴 Target Offline'
                    tag = 'status_error'
                    is_online = False
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
        with contextlib.suppress(Exception):
            dialog.attributes('-alpha', 0.0)
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
                self._pairs[edit_idx] = (s, t)
            else:
                self._pairs.append((s, t))

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

        with contextlib.suppress(Exception):
            dialog.update_idletasks()
            dialog.attributes('-alpha', 1.0)
            dialog.grab_set()

        entry_src.focus_set()

    def _apply_and_close(self):
        pair_objects = [DirectoryPair(source=src, target=tgt) for src, tgt in self._pairs]
        self.entry_paths.set(pair_objects)
        if self.on_changed:
            self.on_changed()
        self.window.destroy()
