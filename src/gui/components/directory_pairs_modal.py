import contextlib
import os
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk

from gui.icons import apply_icon, apply_window_icon
from gui.widgets import DirectoryPair, EntryPaths
from utils.utils import sanitize_path


class DirectoryPairsModal:
    """Interactive management modal for reviewing, adding, editing, and validating directory backup pairs."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | None,
        entry_paths: EntryPaths,
        on_changed: Callable[[], None] | None = None,
    ):
        self.parent = parent
        self.entry_paths = entry_paths
        self.on_changed = on_changed

        self.window = tk.Toplevel(parent)
        self.window.title('Directory Backup Pairs Manager')
        apply_window_icon(self.window)
        self.window.minsize(840, 480)
        if parent is not None:
            self.window.transient(parent)

        self._pairs: list[tuple[str, str]] = list(self.entry_paths.get())
        self._center_window(width=880, height=520)
        self._create_widgets()
        self._populate_table()

    def _center_window(self, width: int, height: int):
        try:
            self.window.update_idletasks()
            screen_w = self.window.winfo_screenwidth()
            screen_h = self.window.winfo_screenheight()
            pos_x = max(0, (screen_w - width) // 2)
            pos_y = max(0, (screen_h - height) // 2)
            self.window.geometry(f'{width}x{height}+{pos_x}+{pos_y}')
        except Exception:
            self.window.geometry(f'{width}x{height}')

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

        self.lbl_stats = tk.Label(
            header_top,
            text=f'{len(self._pairs)} configured pairs',
            font=('Segoe UI', 8, 'bold'),
            bg='#e2e8f0',
            fg='#1e293b',
            padx=8,
            pady=2,
            relief='solid',
            bd=1,
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

        self.btn_explorer = ttk.Button(
            toolbar,
            text='Explorer',
            command=self._handle_open_explorer,
            width=12,
        )
        apply_icon(self.btn_explorer, 'folder')
        self.btn_explorer.pack(side='left', padx=4)

        self.btn_probe = ttk.Button(
            toolbar,
            text='Check Status',
            command=self._handle_check_status,
            width=14,
        )
        apply_icon(self.btn_probe, 'pulse')
        self.btn_probe.pack(side='left', padx=4)

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
        self.tree.column('source', width=310, anchor='w', stretch=True)
        self.tree.column('target', width=310, anchor='w', stretch=True)
        self.tree.column('status', width=120, anchor='center', stretch=False)

        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.bind('<Double-1>', lambda e: self._handle_edit_pair())

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
            if not os.path.exists(src):
                status = '🔴 Missing Src'
            elif not os.path.isdir(src):
                status = '⚠️ Src Not Dir'

            self.tree.insert(
                '',
                'end',
                iid=str(idx - 1),
                values=(idx, src, tgt, status),
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

    def _handle_open_explorer(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(
                'Selection Required', 'Please select a directory pair to open in Explorer.', parent=self.window
            )
            return
        idx = int(selected[0])
        src, tgt = self._pairs[idx]
        target_to_open = src if os.path.exists(src) else tgt
        if os.path.exists(target_to_open):
            try:
                if hasattr(os, 'startfile'):
                    os.startfile(target_to_open)
                else:
                    import subprocess

                    subprocess.Popen(['explorer', target_to_open])
            except Exception as e:
                messagebox.showerror('Explorer Error', f'Could not open directory: {e}', parent=self.window)
        else:
            messagebox.showerror(
                'Not Found', f'Directory does not exist on disk:\n{target_to_open}', parent=self.window
            )

    def _handle_check_status(self):
        self._populate_table()
        self.lbl_msg.config(text='Updated directory reachability and status.')

    def _open_pair_editor(self, default_src: str | None, default_tgt: str | None, edit_idx: int | None):
        dialog = tk.Toplevel(self.window)
        is_edit = edit_idx is not None
        dialog.title('Edit Directory Pair' if is_edit else 'Add New Directory Pair')
        apply_window_icon(dialog)
        dialog.transient(self.window)
        dialog.resizable(False, False)

        width, height = 620, 230
        dialog.minsize(width, height)
        dialog.geometry(f'{width}x{height}')
        with contextlib.suppress(Exception):
            screen_w = dialog.winfo_screenwidth()
            screen_h = dialog.winfo_screenheight()
            dialog.geometry(f'{width}x{height}+{(screen_w - width) // 2}+{(screen_h - height) // 2}')

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

        entry_src.focus_set()

    def _apply_and_close(self):
        pair_objects = [DirectoryPair(source=src, target=tgt) for src, tgt in self._pairs]
        self.entry_paths.set(pair_objects)
        if self.on_changed:
            self.on_changed()
        self.window.destroy()
