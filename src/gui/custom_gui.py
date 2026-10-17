import os
import tkinter as tk
from tkinter import messagebox

from gui.confirmation_popup import CustomCheckboxTreeView  # noqa: F401
from utils.logger import logger


class TrayableTk(tk.Tk):
    def __init__(self):
        super().__init__()
        self._has_tray_icon = False
        self.add_system_tray_icon()
        self.protocol('WM_DELETE_WINDOW', self.on_closing)
        self.bind('<Unmap>', self.on_minimizing)

    def on_minimizing(self, event):
        if event.widget == self and self._has_tray_icon:
            self.withdraw()

    def on_closing(self):
        if not self._has_tray_icon:
            self.destroy()
            return
        close_confirmation = messagebox.askyesno(
            'Warning', 'The application is still running in the system tray, are you sure you want to finalize it?'
        )
        if close_confirmation:
            self.destroy()
        else:  # Minimize to system tray.
            self.withdraw()

    def add_system_tray_icon(self):
        try:
            # Add the path to the Winico package so Tcl can find it
            winico_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'winico'))
            self.tk.call('lappend', 'auto_path', winico_path)
            self.tk.call('package', 'require', 'Winico')
            icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app_icon.ico'))
            icon = self.tk.call('winico', 'createfrom', icon_path)
            self.tk.call(
                'winico',
                'taskbar',
                'add',
                icon,
                '-callback',
                (self.register(self.menu_func), '%m', '%x', '%y'),
                '-pos',
                0,
                '-text',
                'Automatic Backup Tool',
            )

            # About menu
            self.tray_menu = tk.Menu(self, tearoff=False)
            self.tray_menu.add_command(label='Open', command=self.deiconify)
            self.tray_menu.add_command(label='Quit', command=self.destroy)
            self._has_tray_icon = True
        except Exception as e:
            logger.warning(f'Could not initialize system tray icon. Exception: {e}')

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
