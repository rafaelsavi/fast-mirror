"""Help, Quick Start guide, and keyboard shortcuts modal dialog for FastMirror."""

from __future__ import annotations

import contextlib
import os
import sys
import tkinter as tk
import webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from gui.components.base_modal import BaseModalDialog
from gui.icons import apply_icon, apply_window_icon
from gui.widgets import BadgeLabel, add_tooltip, open_path_in_explorer
from utils.constants import APP_VERSION, LOGS_DIR, PROFILES_DIR, ROOT_DIR
from utils.updater import ReleaseInfo, check_for_updates_async


class HelpModal(BaseModalDialog):
    """Interactive help, quick start guide, and keyboard shortcuts window."""

    def __init__(self, parent: tk.Tk | tk.Toplevel | None = None):
        super().__init__(
            parent=parent,
            title='FastMirror — Help & Quick Guide',
            width=800,
            height=600,
            min_width=720,
            min_height=500,
            modal=False,
        )
        apply_window_icon(self.window)
        self._create_widgets()
        self._center_and_reveal(modal=False)

    def _create_widgets(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        # 1. Header Banner
        banner = ttk.Frame(self.window, padding=(16, 12, 16, 8))
        banner.grid(row=0, column=0, sticky='ew')
        banner.columnconfigure(0, weight=1)

        header_top = ttk.Frame(banner)
        header_top.pack(fill='x')

        lbl_title = ttk.Label(
            header_top,
            text='📖 FastMirror — Quick Guide & Documentation',
            font=('Segoe UI', 12, 'bold'),
        )
        lbl_title.pack(side='left')

        self.lbl_version = BadgeLabel(
            header_top,
            text=f'v{APP_VERSION}',
            variant='info',
            font=('Segoe UI', 9, 'bold'),
        )
        self.lbl_version.pack(side='right')

        lbl_desc = ttk.Label(
            banner,
            text='High-performance automated directory mirroring, comparison, and backup with SQLite WAL caching.',
            font=('Segoe UI', 9),
            foreground='#555555',
        )
        lbl_desc.pack(anchor='w', pady=(3, 0))

        # 2. Main Tabbed Notebook
        notebook = ttk.Notebook(self.window)
        notebook.grid(row=1, column=0, sticky='nsew', padx=14, pady=(4, 8))
        self.notebook = notebook

        # Tab 1: Quick Start
        tab_quick = self._build_quick_start_tab(notebook)
        notebook.add(tab_quick, text='  🚀 Quick Start  ')

        # Tab 2: Features & Options
        tab_features = self._build_features_tab(notebook)
        notebook.add(tab_features, text='  ⚙️ Features & Options  ')

        # Tab 3: Keyboard Shortcuts
        tab_shortcuts = self._build_shortcuts_tab(notebook)
        notebook.add(tab_shortcuts, text='  ⌨️ Keyboard Shortcuts  ')

        # Tab 4: About & Diagnostics
        tab_about = self._build_about_tab(notebook)
        notebook.add(tab_about, text='  ℹ️ About & Support  ')

        # 3. Bottom Action Bar
        bottom = ttk.Frame(self.window, padding=(14, 6, 14, 10))
        bottom.grid(row=2, column=0, sticky='ew')
        bottom.columnconfigure(0, weight=1)

        lbl_tip = ttk.Label(
            bottom,
            text='Tip: Press F1 anywhere in FastMirror to bring up this help guide.',
            font=('Segoe UI', 9, 'italic'),
            foreground='#666666',
        )
        lbl_tip.pack(side='left')

        btn_box = ttk.Frame(bottom)
        btn_box.pack(side='right')

        self.btn_user_guide = ttk.Button(
            btn_box,
            text='User Guide (Docs)',
            command=self._open_user_guide,
            width=17,
        )
        apply_icon(self.btn_user_guide, 'document')
        add_tooltip(self.btn_user_guide, 'Open comprehensive user guide markdown documentation in default viewer.')
        self.btn_user_guide.pack(side='left', padx=(0, 6))

        self.btn_close = ttk.Button(
            btn_box,
            text='Close',
            command=self.on_close,
            width=10,
        )
        apply_icon(self.btn_close, 'check_circle')
        add_tooltip(self.btn_close, 'Close this help window (Esc).')
        self.btn_close.pack(side='left')

    def _build_quick_start_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=8)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        txt = ScrolledText(
            tab,
            wrap=tk.WORD,
            font=('Segoe UI', 9),
            relief='flat',
            padx=14,
            pady=12,
            background='#fafafa',
            foreground='#1e293b',
        )
        txt.grid(row=0, column=0, sticky='nsew')

        txt.tag_configure('h1', font=('Segoe UI', 11, 'bold'), foreground='#0f172a', spacing3=6)
        txt.tag_configure('step_num', font=('Segoe UI', 10, 'bold'), foreground='#0284c7')
        txt.tag_configure('step_title', font=('Segoe UI', 10, 'bold'), foreground='#0f172a', spacing1=6)
        txt.tag_configure('body', font=('Segoe UI', 9), foreground='#334155', lmargin1=16, lmargin2=16, spacing3=4)
        txt.tag_configure(
            'tip',
            font=('Segoe UI', 9, 'italic'),
            foreground='#047857',
            lmargin1=16,
            lmargin2=16,
            spacing3=8,
        )

        txt.insert(tk.END, 'Getting Started with FastMirror\n', 'h1')
        txt.insert(
            tk.END,
            'FastMirror performs reliable, multi-threaded one-way synchronization between local Windows drives '
            'and external disks or SMB/UNC network shares (e.g. NAS storage).\n\n',
            'body',
        )

        txt.insert(tk.END, '1. ', 'step_num')
        txt.insert(tk.END, 'Configure Directory Pairs\n', 'step_title')
        txt.insert(
            tk.END,
            'In the "Directory Pairs & Exclusions" panel, click "Manage Pairs..." to specify source folders '
            'and their backup destinations (e.g. D:\\Photos -> \\\\NAS\\Backup\\Photos). You can add multiple pairs '
            'per configuration profile.\n',
            'body',
        )
        txt.insert(
            tk.END,
            '💡 Tip: Target folders are created automatically if they do not yet exist on disk or network shares.\n\n',
            'tip',
        )

        txt.insert(tk.END, '2. ', 'step_num')
        txt.insert(tk.END, 'Verify Target Health\n', 'step_title')
        txt.insert(
            tk.END,
            'Click the "Health Check" button to probe remote network shares and external drives. FastMirror verifies '
            'connectivity, share permissions, and displays available free storage capacity.\n\n',
            'body',
        )

        txt.insert(tk.END, '3. ', 'step_num')
        txt.insert(tk.END, 'Perform a Quick Compare (Dry-Run)\n', 'step_title')
        txt.insert(
            tk.END,
            'Click "Start Compare" to inspect differences between source and target without modifying files on disk. '
            'FastMirror queries the local SQLite WAL cache and provides an instant calculation of changes.\n\n',
            'body',
        )

        txt.insert(tk.END, '4. ', 'step_num')
        txt.insert(tk.END, 'Review in Action Confirmation Dialog\n', 'step_title')
        txt.insert(
            tk.END,
            'When "Request confirmation before sync" is enabled, FastMirror presents an interactive review window '
            'before altering files:\n'
            '• Review individual Copy, Move, and Delete operations grouped by category.\n'
            '• Inspect side-by-side metadata comparisons (file size, timestamp differences).\n'
            '• Click "Uncheck Deletions" to safely protect destination files from being deleted.\n'
            '• Filter list by file name, path, or extension (Ctrl+F).\n\n',
            'body',
        )

        txt.insert(tk.END, '5. ', 'step_num')
        txt.insert(tk.END, 'Execute Synchronization\n', 'step_title')
        txt.insert(
            tk.END,
            'Click "Sync Now" to execute the synchronization. Files are copied atomically, modification times '
            'are preserved, and the local mirror database is updated.\n',
            'body',
        )

        txt.configure(state='disabled')
        return tab

    def _build_features_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=8)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        txt = ScrolledText(
            tab,
            wrap=tk.WORD,
            font=('Segoe UI', 9),
            relief='flat',
            padx=14,
            pady=12,
            background='#fafafa',
            foreground='#1e293b',
        )
        txt.grid(row=0, column=0, sticky='nsew')

        txt.tag_configure('section', font=('Segoe UI', 10, 'bold'), foreground='#0284c7', spacing1=8, spacing3=3)
        txt.tag_configure('title', font=('Segoe UI', 9, 'bold'), foreground='#0f172a')
        txt.tag_configure('body', font=('Segoe UI', 9), foreground='#334155', lmargin1=16, lmargin2=16, spacing3=4)

        txt.insert(tk.END, 'Comparison Methods\n', 'section')
        txt.insert(tk.END, '• Metadata (Fast: size & mtime): ', 'title')
        txt.insert(
            tk.END,
            'Compares file sizes and nanosecond modification timestamps. Highly efficient and fast, recommended '
            'for everyday backups across network shares.\n',
            'body',
        )
        txt.insert(tk.END, '• Content (SHA-256 Hash): ', 'title')
        txt.insert(
            tk.END,
            'Reads every byte and computes cryptographic SHA-256 hashes. Thoroughly verifies data integrity '
            'and catches silent bit rot.\n\n',
            'body',
        )

        txt.insert(tk.END, 'Synchronization Actions\n', 'section')
        txt.insert(tk.END, '• Copy: ', 'title')
        txt.insert(
            tk.END,
            'Transfers newly created and modified files from source to destination.\n',
            'body',
        )
        txt.insert(tk.END, '• Move: ', 'title')
        txt.insert(
            tk.END,
            'Detects files that were renamed or relocated within the folder hierarchy and moves them directly on '
            'the target without re-uploading.\n',
            'body',
        )
        txt.insert(tk.END, '• Delete: ', 'title')
        txt.insert(
            tk.END,
            'Mirror mode. Deletes files on the target that no longer exist in the source folder. Always requires '
            'explicit user confirmation.\n\n',
            'body',
        )

        txt.insert(tk.END, 'Local Mirror Database (SQLite WAL)\n', 'section')
        txt.insert(
            tk.END,
            'FastMirror caches target directory state in a local SQLite database (data/local_mirror.db) using '
            'Write-Ahead Logging (WAL). This eliminates the need to recursively traverse remote SMB shares on every '
            'backup, accelerating scans by up to 100x.\n',
            'body',
        )
        txt.insert(tk.END, '• Reset local mirror database: ', 'title')
        txt.insert(
            tk.END,
            'Check this box when destination files have been modified or reorganized outside of FastMirror to '
            'trigger a complete fresh rescan.\n\n',
            'body',
        )

        txt.insert(tk.END, 'Exclusion Patterns (Ignore List)\n', 'section')
        txt.insert(
            tk.END,
            'Filter out temporary, build, and system files using gitwildmatch wildcard rules:\n'
            '• *.tmp, *.bak — Exclude temporary and editor backup files\n'
            '• $RECYCLE.BIN, System Volume Information — Windows drive system folders\n'
            '• node_modules/, __pycache__/ — Development dependencies and byte code\n'
            '• \\~$* — Microsoft Office lock files\n\n',
            'body',
        )

        txt.insert(tk.END, 'Weekly Automation & System Tray\n', 'section')
        txt.insert(
            tk.END,
            'Configure automated schedules by checking active days of the week (Mon–Sun) and entering execution '
            'times in 24-hour HH:MM format (e.g. 14:30 or 20:00). When minimized, FastMirror docks into the '
            'Windows System Tray and runs automatically in the background.\n',
            'body',
        )

        txt.configure(state='disabled')
        return tab

    def _build_shortcuts_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        tree_frame = ttk.Frame(tab)
        tree_frame.grid(row=0, column=0, sticky='nsew')
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            tree_frame,
            columns=('key', 'context', 'action'),
            show='headings',
            selectmode='browse',
        )
        tree.grid(row=0, column=0, sticky='nsew')

        tree.heading('key', text='Key / Shortcut')
        tree.heading('context', text='Context')
        tree.heading('action', text='Action & Description')

        tree.column('key', width=110, anchor='center', stretch=False)
        tree.column('context', width=140, anchor='w', stretch=False)
        tree.column('action', width=450, anchor='w', stretch=True)

        vsb = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)

        shortcuts = [
            ('F1', 'Global', 'Open this Help & Documentation window'),
            ('Ctrl + S', 'Main Window', 'Save configuration settings to active profile'),
            ('Ctrl + R', 'Main Window', 'Reload active profile configuration from disk'),
            ('Ctrl + O', 'Main Window', 'Import configuration profile from JSON file'),
            ('Ctrl + F', 'Confirmation Dialog', 'Focus search & filter box to search planned operations'),
            ('Enter', 'Confirmation Dialog', 'Save changes and proceed with synchronization'),
            ('Escape', 'Dialogs / Popups', 'Close dialog or cancel pending operation'),
            ('Space', 'Confirmation Dialog', 'Toggle checkbox for selected file or folder group'),
            ('Shift + F10', 'Confirmation Dialog', 'Open right-click context menu for selected item'),
            ('Right-Click', 'Profiles Dropdown', 'Access profile actions (Clone, Rename, Import, Reset)'),
            ('Right-Click', 'Directory Pairs', 'Open selected folder in Windows File Explorer'),
            ('Right-Click', 'Activity Log', 'Jump to warnings or errors in log console'),
        ]

        for key, ctx, action in shortcuts:
            tree.insert('', 'end', values=(key, ctx, action))

        return tab

    def _build_about_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=14)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        # Overview card
        card = ttk.LabelFrame(tab, text=' Application Information ', padding=12)
        card.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        card.columnconfigure(1, weight=1)

        props = [
            ('Application:', 'FastMirror'),
            ('Version:', f'v{APP_VERSION}'),
            ('Runtime:', f'Python {sys.version.split()[0]} on Windows ({os.name.upper()})'),
            ('Database Engine:', 'SQLite3 with Write-Ahead Logging (WAL)'),
            ('Network Support:', 'Windows SMB / UNC Network Paths (\\\\server\\share)'),
            ('License:', 'MIT License'),
        ]

        for idx, (label, val) in enumerate(props):
            ttk.Label(card, text=label, font=('Segoe UI', 9, 'bold')).grid(
                row=idx, column=0, sticky='w', padx=(0, 10), pady=2
            )
            ttk.Label(card, text=val, font=('Segoe UI', 9)).grid(row=idx, column=1, sticky='w', pady=2)

        # Check for updates button alongside version
        self.btn_check_update = ttk.Button(
            card,
            text='Check for Updates',
            command=self._on_check_updates_click,
            width=18,
        )
        apply_icon(self.btn_check_update, 'sync')
        add_tooltip(self.btn_check_update, 'Check GitHub for newer FastMirror releases.')
        self.btn_check_update.grid(row=1, column=2, padx=(12, 0), sticky='w')

        self.lbl_update_status = ttk.Label(card, text='', font=('Segoe UI', 9))
        self.lbl_update_status.grid(row=1, column=3, padx=(8, 0), sticky='w')
        self._cached_release: ReleaseInfo | None = None

        # Diagnostics & Folder actions card
        diag_card = ttk.LabelFrame(tab, text=' Diagnostics & Folder Shortcuts ', padding=12)
        diag_card.grid(row=1, column=0, sticky='nsew')
        diag_card.columnconfigure(0, weight=1)

        lbl_diag_desc = ttk.Label(
            diag_card,
            text='Access local application data, profile configurations, and execution logs in Windows Explorer:',
            font=('Segoe UI', 9),
        )
        lbl_diag_desc.pack(anchor='w', pady=(0, 8))

        btn_row = ttk.Frame(diag_card)
        btn_row.pack(anchor='w', pady=4)

        btn_logs = ttk.Button(
            btn_row,
            text='Open Logs Folder',
            command=lambda: open_path_in_explorer(LOGS_DIR),
            width=18,
        )
        apply_icon(btn_logs, 'folder')
        add_tooltip(btn_logs, 'Open directory containing activity logs and Excel comparison reports.')
        btn_logs.pack(side='left', padx=(0, 6))

        btn_profiles = ttk.Button(
            btn_row,
            text='Open Profiles Folder',
            command=lambda: open_path_in_explorer(PROFILES_DIR),
            width=20,
        )
        apply_icon(btn_profiles, 'folder')
        add_tooltip(btn_profiles, 'Open directory containing profile configuration JSON files.')
        btn_profiles.pack(side='left', padx=(0, 6))

        return tab

    def _on_check_updates_click(self):
        if self._cached_release and self._cached_release.is_newer:
            from gui.components.update_modal import UpdateModal

            UpdateModal(self.window, self._cached_release)
            return

        self.btn_check_update.configure(state='disabled')
        self.lbl_update_status.configure(text='Checking GitHub...')

        def _on_result(info: ReleaseInfo | None, err: str | None):
            def _apply():
                self.btn_check_update.configure(state='normal')
                if info and info.is_newer:
                    self._cached_release = info
                    self.lbl_update_status.configure(text=f'⚡ v{info.version} available!', foreground='#16a34a')
                    self.btn_check_update.configure(text='View Update Details')
                elif info:
                    self.lbl_update_status.configure(text='✓ You have the latest version.', foreground='#15803d')
                else:
                    self.lbl_update_status.configure(text=err or 'Check failed.', foreground='#dc2626')

            self.window.after(0, _apply)

        check_for_updates_async(_on_result)

    def _open_user_guide(self):
        """Open user guide markdown documentation in default system viewer or browser."""
        guide_path = os.path.join(ROOT_DIR, 'docs', 'USER_GUIDE.md')
        readme_path = os.path.join(ROOT_DIR, 'README.md')

        if os.path.isfile(guide_path):
            open_path_in_explorer(guide_path)
        elif os.path.isfile(readme_path):
            open_path_in_explorer(readme_path)
        else:
            with contextlib.suppress(Exception):
                webbrowser.open('https://github.com/rafaelsavi/fast-mirror#readme')
