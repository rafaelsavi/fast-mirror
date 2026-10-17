import contextlib
import datetime
import os
import tkinter as tk
from tkinter import messagebox, ttk

from utils.logger import logger
from utils.utils import format_size


class ReportsWindow:
    """Interactive report history browser displaying past comparison reports."""

    def __init__(self, parent: tk.Tk | tk.Toplevel | None):
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title('Backup Reports History')
        self.window.minsize(680, 420)
        self.window.transient(parent)

        self._center_window(width=720, height=480)
        self._create_widgets()
        self._load_reports()

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

        # Header description
        header = ttk.Frame(self.window, padding=(10, 8, 10, 4))
        header.grid(row=0, column=0, sticky='ew')
        lbl_title = ttk.Label(
            header,
            text='Past Synchronization Reports',
            font=('Segoe UI', 11, 'bold'),
        )
        lbl_title.pack(anchor='w')
        lbl_desc = ttk.Label(
            header,
            text='Browse past comparison reports. Double-click or select an item to open it in Microsoft Excel.',
            font=('Segoe UI', 8),
            foreground='#555555',
        )
        lbl_desc.pack(anchor='w')

        # Treeview table
        table_frame = ttk.Frame(self.window, padding=(10, 4, 10, 6))
        table_frame.grid(row=1, column=0, sticky='nsew')
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=('date', 'size', 'filename'),
            show='headings',
            selectmode='browse',
        )
        self.tree.heading('date', text='Generated Date & Time')
        self.tree.heading('size', text='File Size')
        self.tree.heading('filename', text='Filename')

        self.tree.column('date', width=220, anchor='w')
        self.tree.column('size', width=100, anchor='e')
        self.tree.column('filename', width=340, anchor='w')

        scroll_y = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_y.set)

        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll_y.grid(row=0, column=1, sticky='ns')

        self.tree.bind('<Double-1>', lambda e: self.open_selected())

        # Bottom Actions Bar
        bottom = ttk.Frame(self.window, padding=(10, 6, 10, 10))
        bottom.grid(row=2, column=0, sticky='ew')

        self.lbl_count = ttk.Label(bottom, text='0 reports found', font=('Segoe UI', 8))
        self.lbl_count.pack(side='left', padx=(4, 0))

        self.btn_close = ttk.Button(bottom, text='Close', command=self.window.destroy, width=10)
        self.btn_close.pack(side='right', padx=(4, 0))

        self.btn_open = ttk.Button(
            bottom,
            text='Open in Excel',
            command=self.open_selected,
            style='Accent.TButton',
            width=14,
        )
        self.btn_open.pack(side='right', padx=(4, 4))

        self.btn_folder = ttk.Button(
            bottom,
            text='📂 Open Folder',
            command=self.open_folder,
            width=14,
        )
        self.btn_folder.pack(side='right', padx=(4, 4))

        self.btn_clean = ttk.Button(
            bottom,
            text='🧹 Clean Old (>30d)',
            command=self.clean_old_reports,
            width=18,
        )
        self.btn_clean.pack(side='right', padx=(4, 4))

    def _load_reports(self):
        self.tree.delete(*self.tree.get_children())
        if not os.path.isdir(logger.log_dir):
            self.lbl_count.config(text='Log directory does not exist')
            return

        report_files: list[tuple[datetime.datetime, str, int]] = []
        prefix = 'compare_report_'
        suffix = '.xlsx'

        for name in os.listdir(logger.log_dir):
            if name.startswith(prefix) and name.endswith(suffix):
                date_part = name[len(prefix) : -len(suffix)]
                try:
                    dt = datetime.datetime.strptime(date_part, '%Y-%m-%d_%H-%M-%S')
                    full_path = os.path.join(logger.log_dir, name)
                    size = os.path.getsize(full_path) if os.path.isfile(full_path) else 0
                    report_files.append((dt, name, size))
                except (ValueError, OSError):
                    continue

        # Sort newest first
        report_files.sort(key=lambda x: x[0], reverse=True)

        for dt, filename, size in report_files:
            date_str = dt.strftime('%Y/%m/%d %H:%M:%S')
            size_str = format_size(size)
            self.tree.insert('', 'end', iid=filename, values=(date_str, size_str, filename))

        self.lbl_count.config(text=f'{len(report_files)} report{"s" if len(report_files) != 1 else ""} available')
        if report_files:
            first_id = report_files[0][1]
            self.tree.selection_set(first_id)

    def open_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        filename = selected[0]
        filepath = os.path.join(logger.log_dir, filename)
        if os.path.isfile(filepath):
            logger.info(f'Opening past report: {filepath}')
            with contextlib.suppress(OSError):
                os.startfile(filepath)

    def open_folder(self):
        if os.path.isdir(logger.log_dir):
            with contextlib.suppress(OSError):
                os.startfile(logger.log_dir)

    def clean_old_reports(self):
        if not messagebox.askyesno(
            'Confirm Cleanup',
            'Are you sure you want to delete comparison reports older than 30 days?',
            parent=self.window,
        ):
            return

        cutoff = datetime.datetime.now() - datetime.timedelta(days=30)
        deleted = 0
        prefix = 'compare_report_'
        suffix = '.xlsx'

        for name in os.listdir(logger.log_dir):
            if name.startswith(prefix) and name.endswith(suffix):
                date_part = name[len(prefix) : -len(suffix)]
                try:
                    dt = datetime.datetime.strptime(date_part, '%Y-%m-%d_%H-%M-%S')
                    if dt < cutoff:
                        os.remove(os.path.join(logger.log_dir, name))
                        deleted += 1
                except (ValueError, OSError):
                    continue

        logger.info(f'Cleaned {deleted} old reports')
        self._load_reports()
