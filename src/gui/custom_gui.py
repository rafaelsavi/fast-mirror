import tkinter as tk
from tkinter import messagebox
from typing import Callable

import ttkwidgets

from file import CstmPath
from logger import logger
from utils import format_size


class TrayableTk(tk.Tk):
    def __init__(self):
        super().__init__()
        self.add_system_tray_icon()
        self.protocol('WM_DELETE_WINDOW', self.on_closing)
        self.bind('<Unmap>', self.on_minimizing)

    def on_minimizing(self, event):
        self.withdraw()

    def on_closing(self):
        close_confirmation = messagebox.askyesno(
            'Warning', 'The application is still running in the system tray, are you sure you want to finalize it?'
        )
        if close_confirmation:
            self.destroy()
        else:  # Minimize to system tray.
            self.withdraw()

    def add_system_tray_icon(self):
        # The work about "Winico"
        self.tk.call(
            'package', 'require', 'Winico'
        )  # use the tcl "winico", make sure the folder of "winico" is in the same path.
        icon = self.tk.call('winico', 'createfrom', 'src/gui/smiley.ico')  # this is the icon on the system tray.
        self.tk.call(
            'winico',
            'taskbar',
            'add',
            icon,  # set the icon
            '-callback',
            (self.register(self.menu_func), '%m', '%x', '%y'),  # refer to winico documentation.
            '-pos',
            0,
            '-text',
            'Automatic Backup Tool',
        )  # the hover text of the system tray.

        # About menu
        self.tray_menu = tk.Menu(self, tearoff=False)
        self.tray_menu.add_command(label='Open', command=self.deiconify)
        self.tray_menu.add_command(label='Quit', command=self.destroy)

        # You could also add a cascade menu
        # cascadeMenu = tk.Menu(self, tearoff=False)
        # cascadeMenu.add_command(label="Casacde one", command=lambda: print("You could define it by yourself"))
        # cascadeMenu.add_command(label="Cascade two")
        # self.trayMenu.add_cascade(label="Other", menu=cascadeMenu)
        # self.trayMenu.add_separator()  # you could add a separator

    def menu_func(self, event, x, y):
        if event == 'WM_RBUTTONDOWN':  # Mouse event, Right click on the tray.Mostly we will show it.
            self.tray_menu.tk_popup(x, y)  # pop it up on this position
        if event == 'WM_LBUTTONDOWN' or event == 'WM_LBUTTONDBLCLK':
            self.deiconify()  # show it.
        # WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK,
        # WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK


class CustomCheckboxTreeView(ttkwidgets.CheckboxTreeview):
    custom_headers = [
        'enable',
        'source',
        'target',
        'size (source)',
        'size (target)',
        'modification date (source)',
        'modification date (target)',
        'creation date (source)',
        'creation date (target)',
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._data = {}

        # Configure headers
        self['columns'] = self.custom_headers[1:]
        self.column('#0', width=170, minwidth=130)
        self.heading('#0', text=self.custom_headers[0])
        for column in self.custom_headers[1:]:
            self.heading(column, text=column)

    def _box_click(self, event):
        super()._box_click(event)
        self.refresh_group_stats()

    def refresh_group_stats(self):
        for group in self.get_children(''):
            total_number = len(self.get_children(group))
            selected_lines = [x for x in self.get_checked() if f'{group}::' in x]
            selected_number = len(selected_lines)
            selected_size = format_size(sum([self._data[group][x]['size in bytes'] for x in selected_lines]))
            # Update group item
            self.item(group, text=f'{group} {selected_size} ({selected_number} of {total_number})')

    def add_file_lists(
        self, file_lists: dict[str, list[tuple[CstmPath, CstmPath]] | list[CstmPath]], default_active=None
    ):
        if default_active is None:
            default_active = []

        for group, file_list in file_lists.items():
            self._data[group] = {}
            for file_entry in file_list:
                args = (None, file_entry) if isinstance(file_entry, CstmPath) else file_entry
                values = self.get_row(*args)
                self._data[group][f'{group}::{values["source"]}::{values["target"]}'] = values

        for group, rows in self._data.items():
            tag = 'checked' if group in default_active else 'unchecked'
            group_item = self.insert(parent='', index='end', iid=group, text=group, tags=(tag,))
            for key, row in rows.items():
                self.insert(
                    parent=group_item,
                    index='end',
                    iid=key,
                    values=[v for k, v in row.items() if k in self.custom_headers],
                )

    @staticmethod
    def get_row(source: CstmPath | None, target: CstmPath | None) -> dict[str, float | str]:
        def try_f(func: Callable, path: CstmPath | None, default: str | int = ''):
            if path is None:
                return default
            try:
                return func(path)
            except FileNotFoundError:
                return default
            except Exception as e:
                logger.warning(f'Failed to apply {func} on "{str(path)}". Exception: {e}')
                return default

        row = {}
        row['source'] = try_f(str, source)
        row['target'] = try_f(str, target)
        row['size (source)'] = try_f(lambda x: x.get_st_size(as_str=True), source, default=0)
        row['size (target)'] = try_f(lambda x: x.get_st_size(as_str=True), target, default=0)
        row['modification date (source)'] = try_f(lambda x: x.get_st_mtime(as_date_str=True), source)
        row['modification date (target)'] = try_f(lambda x: x.get_st_mtime(as_date_str=True), target)
        get_size_from = source if source is not None else target
        row['size in bytes'] = try_f(lambda x: x.get_st_size(as_str=False), get_size_from, default=0)

        return row
