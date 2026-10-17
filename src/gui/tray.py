import contextlib
import os
import tkinter as tk
from tkinter import messagebox

import pystray
from PIL import Image

from utils.logger import is_test_or_agent_mode, logger


class TrayableTk(tk.Tk):
    """Tkinter root window with modern cross-platform system tray integration via pystray."""

    def __init__(self):
        super().__init__()
        self._tray_icon: pystray.Icon | None = None
        self._is_closing = False
        self.add_system_tray_icon()
        self.protocol('WM_DELETE_WINDOW', self.on_closing)
        self.bind('<Unmap>', self.on_minimizing)

    def on_minimizing(self, event):
        if event.widget == self and self._tray_icon and not self._is_closing:
            self.withdraw()

    def show_window(self):
        self.after(0, self._restore_window)

    def _restore_window(self):
        self.deiconify()
        self.lift()
        with contextlib.suppress(Exception):
            self.focus_force()

    def destroy(self):
        self._is_closing = True
        if self._tray_icon is not None:
            with contextlib.suppress(Exception):
                self._tray_icon.stop()
            self._tray_icon = None
        super().destroy()

    def finalize_quit(self):
        self._is_closing = True
        if self._tray_icon is not None:
            with contextlib.suppress(Exception):
                self._tray_icon.stop()
            self._tray_icon = None
        with contextlib.suppress(Exception):
            self.destroy()

    def on_closing(self):
        if not self._tray_icon:
            self.finalize_quit()
            return
        close_confirmation = messagebox.askyesno(
            'Warning', 'The application is still running in the system tray, are you sure you want to finalize it?'
        )
        if close_confirmation:
            self.finalize_quit()
        else:
            self.withdraw()

    def add_system_tray_icon(self):
        if is_test_or_agent_mode():
            return
        try:
            icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app_icon.ico'))
            if not os.path.isfile(icon_path):
                return

            image = Image.open(icon_path)
            menu = pystray.Menu(
                pystray.MenuItem('Open', lambda icon, item: self.show_window(), default=True),
                pystray.MenuItem('Quit', lambda icon, item: self.after(0, self.finalize_quit)),
            )
            self._tray_icon = pystray.Icon('automatic_backup', image, 'Automatic Backup Tool', menu)
            self._tray_icon.run_detached()
        except Exception as e:
            logger.warning(f'Could not initialize system tray icon. Exception: {e}')
