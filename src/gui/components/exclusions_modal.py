import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

import pathspec

from gui.widgets import EntryExclusions
from utils.utils import sanitize_path


class ExclusionsModal:
    """Interactive management modal for reviewing, adding, removing, and testing ignore patterns."""

    PRESETS = {
        'OS Junk': ['Thumbs.db', 'desktop.ini', '$RECYCLE.BIN', '.DS_Store'],
        'Developer': [
            '.git',
            'node_modules',
            '__pycache__',
            '.venv',
            '.idea',
            '.vscode',
            '.pytest_cache',
            '.mypy_cache',
        ],
        'Temp & Backups': ['*.tmp', '*.~*', '~$*', '*.bak', '*.swp'],
        'Cache Folders': ['*Previews.lrdata*', '*.joblib_cache*', '*.cache*'],
    }

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
        self.window.minsize(820, 500)
        if parent is not None:
            self.window.transient(parent)

        self._patterns: list[str] = list(self.entry_exclusions.get())
        self._center_window(width=880, height=540)
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

        # 2. Main Content Split (Left: Pattern Table, Right: Presets & Tester)
        content_frame = ttk.Frame(self.window, padding=(14, 4, 14, 6))
        content_frame.grid(row=1, column=0, sticky='nsew')
        content_frame.columnconfigure(0, weight=3)
        content_frame.columnconfigure(1, weight=2)
        content_frame.rowconfigure(0, weight=1)

        # --- Left Side: Patterns Table & Controls ---
        left_box = ttk.LabelFrame(content_frame, text=' Configured Patterns ', padding=8)
        left_box.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        left_box.columnconfigure(0, weight=1)
        left_box.rowconfigure(1, weight=1)

        # Add pattern bar
        add_frame = ttk.Frame(left_box)
        add_frame.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        add_frame.columnconfigure(1, weight=1)

        ttk.Label(add_frame, text='Pattern:').grid(row=0, column=0, sticky='w', padx=(0, 4))
        self.new_pattern_var = tk.StringVar()
        entry_new = ttk.Entry(add_frame, textvariable=self.new_pattern_var)
        entry_new.grid(row=0, column=1, sticky='ew', padx=4)
        entry_new.bind('<Return>', lambda e: self._handle_add_pattern())

        btn_add = ttk.Button(add_frame, text='➕ Add', command=self._handle_add_pattern, width=8)
        btn_add.grid(row=0, column=2, sticky='e', padx=(4, 0))

        # Patterns Table
        table_frame = ttk.Frame(left_box)
        table_frame.grid(row=1, column=0, sticky='nsew')
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=('idx', 'pattern', 'type'),
            show='headings',
            selectmode='extended',
        )
        self.tree.grid(row=0, column=0, sticky='nsew')

        self.tree.heading('idx', text='#')
        self.tree.heading('pattern', text='Pattern')
        self.tree.heading('type', text='Classification')

        self.tree.column('idx', width=35, anchor='center', stretch=False)
        self.tree.column('pattern', width=260, anchor='w')
        self.tree.column('type', width=110, anchor='center', stretch=False)

        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=vsb.set)

        # Toolbar below table
        table_toolbar = ttk.Frame(left_box)
        table_toolbar.grid(row=2, column=0, sticky='ew', pady=(6, 0))

        btn_remove = ttk.Button(table_toolbar, text='🗑️ Remove', command=self._handle_remove_selected, width=12)
        btn_remove.pack(side='left', padx=(0, 4))

        btn_clear = ttk.Button(table_toolbar, text='Clear All', command=self._handle_clear_all, width=10)
        btn_clear.pack(side='left', padx=4)

        btn_reset = ttk.Button(table_toolbar, text='Reset Default', command=self._handle_reset_default, width=13)
        btn_reset.pack(side='left', padx=4)

        # --- Right Side: Presets & Live Tester Sandbox ---
        right_box = ttk.Frame(content_frame)
        right_box.grid(row=0, column=1, sticky='nsew')
        right_box.columnconfigure(0, weight=1)

        # Presets Card
        presets_card = ttk.LabelFrame(right_box, text=' Quick Preset Packs ', padding=8)
        presets_card.pack(fill='x', pady=(0, 8))

        self._preset_vars: dict[str, tk.BooleanVar] = {}
        for category, patterns in self.PRESETS.items():
            var = tk.BooleanVar(value=all(p in self._patterns for p in patterns))
            self._preset_vars[category] = var
            cb = ttk.Checkbutton(
                presets_card,
                text=f'{category} ({len(patterns)} rules)',
                variable=var,
                command=lambda cat=category, pts=patterns, v=var: self._on_preset_pack_toggled(pts, v),
            )
            cb.pack(anchor='w', pady=2)

        # Live Pattern Testing Sandbox Card
        tester_card = ttk.LabelFrame(right_box, text=' 🔍 Pattern Testing Sandbox ', padding=8)
        tester_card.pack(fill='x')

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

        btn_cancel = ttk.Button(footer, text='Cancel', command=self.window.destroy, width=10)
        btn_cancel.pack(side='right', padx=(6, 0))

        btn_apply = ttk.Button(footer, text='💾 Apply Changes', command=self._apply_and_close, width=16)
        btn_apply.pack(side='right')

    def _classify_pattern(self, pattern: str) -> str:
        if pattern.startswith('$') or pattern in ('Thumbs.db', 'desktop.ini', '.DS_Store'):
            return 'OS System'
        if pattern.startswith('.git') or 'node_modules' in pattern or '__pycache__' in pattern:
            return 'Dev Artifact'
        if pattern.startswith('*.'):
            return 'File Ext'
        if '/' in pattern or '\\' in pattern:
            return 'Path Pattern'
        return 'Glob'

    def _populate_table(self):
        self.tree.delete(*self.tree.get_children())
        for idx, pattern in enumerate(self._patterns, start=1):
            ptype = self._classify_pattern(pattern)
            self.tree.insert('', 'end', iid=str(idx - 1), values=(idx, pattern, ptype))
        self.lbl_stats.config(text=f'{len(self._patterns)} active patterns')
        self._update_preset_checkboxes()
        self._evaluate_test_path()

    def _update_preset_checkboxes(self):
        for category, patterns in self.PRESETS.items():
            if category in self._preset_vars:
                all_present = all(p in self._patterns for p in patterns)
                self._preset_vars[category].set(all_present)

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

    def _handle_remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(
                'Selection Required', 'Please select one or more patterns to remove.', parent=self.window
            )
            return
        indices = sorted([int(x) for x in selected], reverse=True)
        for idx in indices:
            del self._patterns[idx]
        self._populate_table()
        self.lbl_msg.config(text=f'Removed {len(indices)} pattern(s). Click "Apply Changes" to save.')

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

    def _on_preset_pack_toggled(self, patterns: list[str], var: tk.BooleanVar):
        if var.get():
            new_pts = [p for p in patterns if p not in self._patterns]
            self._patterns.extend(new_pts)
        else:
            self._patterns = [p for p in self._patterns if p not in patterns]
        self._patterns.sort()
        self._populate_table()

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
