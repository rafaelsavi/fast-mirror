import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, simpledialog, ttk

import pathspec

from gui.icons import apply_icon, apply_window_icon
from gui.widgets import EntryExclusions
from utils.utils import sanitize_path


class ExclusionsModal:
    """Interactive management modal for reviewing, adding, removing, editing, and testing ignore patterns."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | None,
        entry_exclusions: EntryExclusions,
        on_changed: Callable[[], None] | None = None,
    ):
        self.parent = parent
        self.entry_exclusions = entry_exclusions
        self.on_changed = on_changed

        self.window = tk.Toplevel(parent)
        self.window.title('Ignore & Exclusion Patterns Manager')
        apply_window_icon(self.window)
        self.window.minsize(840, 520)
        if parent is not None:
            self.window.transient(parent)

        self._patterns: list[str] = list(self.entry_exclusions.get())
        self._center_window(width=900, height=560)
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
        self.window.rowconfigure(1, weight=1)

        # 1. Header Banner
        banner = ttk.Frame(self.window, padding=(14, 10, 14, 6))
        banner.grid(row=0, column=0, sticky='ew')
        banner.columnconfigure(0, weight=1)

        header_top = ttk.Frame(banner)
        header_top.pack(fill='x')

        lbl_title = ttk.Label(
            header_top,
            text='🛡️ Ignore & Exclusion Patterns',
            font=('Segoe UI', 12, 'bold'),
        )
        lbl_title.pack(side='left')

        self.lbl_stats = tk.Label(
            header_top,
            text=f'{len(self._patterns)} active patterns',
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
            text='Files and directories matching these gitwildmatch patterns are excluded from scanning and syncing.',
            font=('Segoe UI', 9),
            foreground='#555555',
        )
        lbl_desc.pack(anchor='w', pady=(2, 0))

        # 2. Main Content Split (Left: Pattern Table, Right: Tester & Syntax Guide)
        content_frame = ttk.Frame(self.window, padding=(14, 4, 14, 6))
        content_frame.grid(row=1, column=0, sticky='nsew')
        content_frame.columnconfigure(0, weight=3)
        content_frame.columnconfigure(1, weight=2)
        content_frame.rowconfigure(0, weight=1)

        # --- Left Side: Patterns Table & Controls ---
        left_box = ttk.LabelFrame(content_frame, text=' Configured Patterns ', padding=8)
        left_box.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        left_box.columnconfigure(0, weight=1)
        left_box.rowconfigure(2, weight=1)

        # Row 0: Add pattern bar
        add_frame = ttk.Frame(left_box)
        add_frame.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        add_frame.columnconfigure(1, weight=1)

        ttk.Label(add_frame, text='Pattern:').grid(row=0, column=0, sticky='w', padx=(0, 4))
        self.new_pattern_var = tk.StringVar()
        entry_new = ttk.Entry(add_frame, textvariable=self.new_pattern_var)
        entry_new.grid(row=0, column=1, sticky='ew', padx=4)
        entry_new.bind('<Return>', lambda e: self._handle_add_pattern())

        btn_add = ttk.Button(add_frame, text='Add', command=self._handle_add_pattern, width=9)
        apply_icon(btn_add, 'plus')
        btn_add.grid(row=0, column=2, sticky='e', padx=(4, 0))

        # Row 1: Search / Filter bar
        filter_frame = ttk.Frame(left_box)
        filter_frame.grid(row=1, column=0, sticky='ew', pady=(0, 6))
        filter_frame.columnconfigure(1, weight=1)

        ttk.Label(filter_frame, text='Filter:').grid(row=0, column=0, sticky='w', padx=(0, 4))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', lambda *args: self._populate_table())
        entry_filter = ttk.Entry(filter_frame, textvariable=self.filter_var)
        entry_filter.grid(row=0, column=1, sticky='ew', padx=4)

        btn_clear_filter = ttk.Button(
            filter_frame,
            text='✕',
            command=lambda: self.filter_var.set(''),
            width=3,
        )
        btn_clear_filter.grid(row=0, column=2, sticky='e', padx=(4, 0))

        # Row 2: Patterns Table
        table_frame = ttk.Frame(left_box)
        table_frame.grid(row=2, column=0, sticky='nsew')
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=('idx', 'pattern'),
            show='headings',
            selectmode='extended',
        )
        self.tree.grid(row=0, column=0, sticky='nsew')

        self.tree.heading('idx', text='#')
        self.tree.heading('pattern', text='Pattern')

        self.tree.column('idx', width=35, anchor='center', stretch=False)
        self.tree.column('pattern', width=370, anchor='w')

        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.bind('<Double-1>', lambda e: self._handle_edit_selected())

        # Row 3: Toolbar below table
        table_toolbar = ttk.Frame(left_box)
        table_toolbar.grid(row=3, column=0, sticky='ew', pady=(6, 0))

        btn_edit = ttk.Button(table_toolbar, text='Edit...', command=self._handle_edit_selected, width=10)
        apply_icon(btn_edit, 'pencil')
        btn_edit.pack(side='left', padx=(0, 4))

        btn_remove = ttk.Button(table_toolbar, text='Remove', command=self._handle_remove_selected, width=11)
        apply_icon(btn_remove, 'trash')
        btn_remove.pack(side='left', padx=4)

        btn_clear = ttk.Button(table_toolbar, text='Clear All', command=self._handle_clear_all, width=11)
        btn_clear.pack(side='left', padx=4)

        btn_reset = ttk.Button(table_toolbar, text='Reset Default', command=self._handle_reset_default, width=13)
        btn_reset.pack(side='left', padx=4)

        # --- Right Side: Live Tester Sandbox & Syntax Guide ---
        right_box = ttk.Frame(content_frame)
        right_box.grid(row=0, column=1, sticky='nsew')
        right_box.columnconfigure(0, weight=1)
        right_box.rowconfigure(1, weight=1)

        # 1. Live Pattern Testing Sandbox Card
        tester_card = ttk.LabelFrame(right_box, text=' 🔍 Pattern Testing Sandbox ', padding=8)
        tester_card.grid(row=0, column=0, sticky='ew', pady=(0, 8))

        ttk.Label(
            tester_card,
            text='Test if a sample path will be ignored or included:',
            font=('Segoe UI', 8),
            foreground='#555555',
        ).pack(anchor='w', pady=(0, 4))

        self.test_path_var = tk.StringVar(value='MyFolder/Thumbs.db')
        entry_test = ttk.Entry(tester_card, textvariable=self.test_path_var)
        entry_test.pack(fill='x', pady=(0, 6))

        self.lbl_test_result = tk.Label(
            tester_card,
            text='🔴 Ignored',
            font=('Segoe UI', 9, 'bold'),
            bg='#fee2e2',
            fg='#b91c1c',
            padx=8,
            pady=3,
            relief='solid',
            bd=1,
        )
        self.lbl_test_result.pack(anchor='w')

        self.test_path_var.trace_add('write', self._evaluate_test_path)

        # 2. Syntax & Examples Guide Card
        guide_card = ttk.LabelFrame(right_box, text=' 📖 Pattern Syntax Guide ', padding=10)
        guide_card.grid(row=1, column=0, sticky='nsew')

        lbl_guide_intro = ttk.Label(
            guide_card,
            text='Exclusions follow Git wildmatch pattern syntax:',
            font=('Segoe UI', 8, 'bold'),
            foreground='#334155',
        )
        lbl_guide_intro.pack(anchor='w', pady=(0, 6))

        # Common pattern examples table
        examples = [
            ('*.ext', 'Ignore file extension', 'e.g. *.tmp, *.iso, *.bak'),
            ('folder/**', 'Ignore folder & subfiles', 'e.g. build/**, dist/**'),
            ('**/cache/**', 'Ignore folder anywhere', 'e.g. **/.git/**, **/cache/**'),
            ('~$*', 'Ignore temporary Office files', 'e.g. ~$Doc.docx, ~$Book.xlsx'),
            ('Thumbs.db', 'Exact file name anywhere', 'e.g. Thumbs.db, desktop.ini'),
            ('!keep.txt', 'Negation / whitelist', 'Re-includes previously ignored'),
        ]

        grid_frame = ttk.Frame(guide_card)
        grid_frame.pack(fill='both', expand=True)
        grid_frame.columnconfigure(0, weight=0)
        grid_frame.columnconfigure(1, weight=1)

        for r_idx, (pat, desc, note) in enumerate(examples):
            btn_pat = tk.Label(
                grid_frame,
                text=pat,
                font=('Consolas', 9, 'bold'),
                bg='#f1f5f9',
                fg='#0f172a',
                padx=5,
                pady=1,
                relief='solid',
                bd=1,
                cursor='hand2',
            )
            btn_pat.grid(row=r_idx * 2, column=0, sticky='w', pady=(3, 1))

            lbl_d = ttk.Label(grid_frame, text=desc, font=('Segoe UI', 8, 'bold'), foreground='#1e293b')
            lbl_d.grid(row=r_idx * 2, column=1, sticky='w', padx=(8, 0), pady=(3, 1))

            lbl_n = ttk.Label(grid_frame, text=note, font=('Segoe UI', 8), foreground='#64748b')
            lbl_n.grid(row=r_idx * 2 + 1, column=1, sticky='w', padx=(8, 0), pady=(0, 3))

            def _insert_sample(p=pat):
                self.new_pattern_var.set(p)
                sample_test = f'Folder/{p.replace("**", "sub")}' if '*' in p else f'Folder/{p}'
                self.test_path_var.set(sample_test)

            btn_pat.bind('<Button-1>', lambda e, p=pat: _insert_sample(p))

        lbl_hint = ttk.Label(
            guide_card,
            text='💡 Tip: Click any badge to test it. Double-click pattern to edit.',
            font=('Segoe UI', 8, 'italic'),
            foreground='#64748b',
        )
        lbl_hint.pack(anchor='w', pady=(6, 0))

        # 3. Bottom Footer
        footer = ttk.Frame(self.window, padding=(14, 8, 14, 12))
        footer.grid(row=2, column=0, sticky='ew')

        self.lbl_msg = ttk.Label(
            footer,
            text='Click "Apply Changes" to save exclusions to the main window.',
            font=('Segoe UI', 9),
            foreground='#666666',
        )
        self.lbl_msg.pack(side='left')

        btn_cancel = ttk.Button(footer, text='Cancel', command=self.window.destroy, width=11)
        btn_cancel.pack(side='right', padx=(6, 0))

        btn_apply = ttk.Button(footer, text='Apply Changes', command=self._apply_and_close, width=15)
        apply_icon(btn_apply, 'save')
        btn_apply.pack(side='right')

    def _populate_table(self):
        self.tree.delete(*self.tree.get_children())
        query = getattr(self, 'filter_var', None)
        filter_text = query.get().strip().lower() if query else ''

        displayed_count = 0
        for idx, pattern in enumerate(self._patterns, start=1):
            if filter_text and filter_text not in pattern.lower():
                continue
            displayed_count += 1
            self.tree.insert('', 'end', iid=str(idx - 1), values=(displayed_count, pattern))

        if filter_text:
            self.lbl_stats.config(text=f'{displayed_count}/{len(self._patterns)} matched')
        else:
            self.lbl_stats.config(text=f'{len(self._patterns)} active patterns')
        self._evaluate_test_path()

    def _handle_add_pattern(self):
        raw = self.new_pattern_var.get().strip()
        if not raw:
            return
        sanitized = sanitize_path(raw)
        if sanitized not in self._patterns:
            self._patterns.append(sanitized)
            self._patterns.sort()
            self._populate_table()
            self.new_pattern_var.set('')
            self.lbl_msg.config(text=f'Added "{sanitized}". Click "Apply Changes" to save.')
        else:
            messagebox.showinfo(
                'Duplicate Pattern', f'Pattern "{sanitized}" is already in the ignore list.', parent=self.window
            )

    def _handle_edit_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('Selection Required', 'Please select a pattern to edit.', parent=self.window)
            return

        item_id = selected[0]
        item_vals = self.tree.item(item_id, 'values')
        if not item_vals or len(item_vals) < 2:
            return
        current_pattern = str(item_vals[1])

        new_val = simpledialog.askstring(
            'Edit Ignore Pattern',
            'Modify glob pattern:',
            initialvalue=current_pattern,
            parent=self.window,
        )
        if new_val is not None:
            sanitized = sanitize_path(new_val.strip())
            if not sanitized:
                messagebox.showerror('Validation Error', 'Pattern cannot be empty.', parent=self.window)
                return
            if sanitized != current_pattern and sanitized in self._patterns:
                messagebox.showinfo(
                    'Duplicate Pattern', f'Pattern "{sanitized}" is already in the ignore list.', parent=self.window
                )
                return

            try:
                real_idx = self._patterns.index(current_pattern)
                self._patterns[real_idx] = sanitized
            except ValueError:
                self._patterns.append(sanitized)

            self._patterns.sort()
            self._populate_table()
            self.lbl_msg.config(text=f'Updated to "{sanitized}". Click "Apply Changes" to save.')

    def _handle_remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(
                'Selection Required', 'Please select one or more patterns to remove.', parent=self.window
            )
            return

        patterns_to_remove = set()
        for item_id in selected:
            item_vals = self.tree.item(item_id, 'values')
            if item_vals and len(item_vals) >= 2:
                patterns_to_remove.add(str(item_vals[1]))

        self._patterns = [p for p in self._patterns if p not in patterns_to_remove]
        self._populate_table()
        self.lbl_msg.config(text=f'Removed {len(patterns_to_remove)} pattern(s). Click "Apply Changes" to save.')

    def _handle_clear_all(self):
        if not self._patterns:
            return
        if messagebox.askyesno('Clear Exclusions', 'Remove all ignore patterns?', parent=self.window):
            self._patterns.clear()
            self._populate_table()
            self.lbl_msg.config(text='Cleared all ignore patterns. Click "Apply Changes" to save.')

    def _handle_reset_default(self):
        self._patterns = ['$RECYCLE.BIN', r'\~$']
        self._populate_table()
        self.lbl_msg.config(text='Reset to defaults ($RECYCLE.BIN, \\~$).')

    def _evaluate_test_path(self, *args):
        path = self.test_path_var.get().strip()
        if not path or not self._patterns:
            self.lbl_test_result.config(
                text='⚪ No Pattern Evaluated',
                bg='#f1f5f9',
                fg='#64748b',
            )
            return

        try:
            clean_path = path.replace('\\', '/')
            spec = pathspec.PathSpec.from_lines('gitwildmatch', [p.replace('\\', '/') for p in self._patterns])
            is_matched = spec.match_file(clean_path) or spec.match_file(clean_path + '/')

            if is_matched:
                # Find which specific pattern matched
                matching_pat = None
                for pat in self._patterns:
                    single_spec = pathspec.PathSpec.from_lines('gitwildmatch', [pat.replace('\\', '/')])
                    if single_spec.match_file(clean_path) or single_spec.match_file(clean_path + '/'):
                        matching_pat = pat
                        break

                pat_str = f' (matches: {matching_pat})' if matching_pat else ''
                self.lbl_test_result.config(
                    text=f'🔴 Ignored{pat_str}',
                    bg='#fee2e2',
                    fg='#b91c1c',
                )
            else:
                self.lbl_test_result.config(
                    text='🟢 Included in backup',
                    bg='#dcfce7',
                    fg='#15803d',
                )
        except Exception as e:
            self.lbl_test_result.config(
                text=f'⚠️ Syntax Error: {e}',
                bg='#fef3c7',
                fg='#b45309',
            )

    def _apply_and_close(self):
        self.entry_exclusions.set(self._patterns)
        if self.on_changed:
            self.on_changed()
        self.window.destroy()
