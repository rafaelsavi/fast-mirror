import contextlib
import ctypes
import os
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox

import pystray
from PIL import Image

from utils.logger import is_test_or_agent_mode, logger


class TrayableTk(tk.Tk):
    """Tkinter root window with modern cross-platform system tray integration via pystray."""

    def __init__(self):
        # Enable Per-Monitor v2 DPI awareness on Windows to prevent DWM bitmap scaling lag
        if hasattr(ctypes, 'windll'):
            with contextlib.suppress(Exception):
                # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
                if hasattr(ctypes.windll, 'user32') and hasattr(ctypes.windll.user32, 'SetProcessDpiAwarenessContext'):
                    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
                elif hasattr(ctypes.windll, 'shcore') and hasattr(ctypes.windll.shcore, 'SetProcessDpiAwareness'):
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)

        super().__init__()
        self._tray_icon: pystray.Icon | None = None
        self._is_closing = False
        self._on_sync_now: Callable[[], None] | None = None
        self._on_quick_compare: Callable[[], None] | None = None
        self._on_stop_operation: Callable[[], None] | None = None
        self._on_open_report: Callable[[], None] | None = None
        self._is_running_check: Callable[[], bool] | None = None

        self.add_system_tray_icon()
        self.protocol('WM_DELETE_WINDOW', self.on_closing)
        self.bind('<Unmap>', self.on_minimizing)

    def set_tray_callbacks(
        self,
        on_sync_now: Callable[[], None] | None = None,
        on_quick_compare: Callable[[], None] | None = None,
        on_stop_operation: Callable[[], None] | None = None,
        on_open_report: Callable[[], None] | None = None,
        is_running: Callable[[], bool] | None = None,
    ):
        """Register callbacks for quick actions triggered from the system tray menu."""
        self._on_sync_now = on_sync_now
        self._on_quick_compare = on_quick_compare
        self._on_stop_operation = on_stop_operation
        self._on_open_report = on_open_report
        self._is_running_check = is_running
        self._update_tray_menu()

    # Alias for flexibility
    set_tray_actions = set_tray_callbacks

    def update_tray_tooltip(self, text: str):
        """Update the tooltip text displayed when hovering over the tray icon."""
        if self._tray_icon is not None:
            # Win32 NOTIFYICONDATA szTip limit is 128 characters including null terminator
            safe_text = text[:127] if len(text) > 127 else text
            with contextlib.suppress(Exception):
                self._tray_icon.title = safe_text

    def notify(self, message: str, title: str | None = None):
        """Display a system notification balloon/toast from the system tray icon."""
        if self._tray_icon is not None:
            with contextlib.suppress(Exception):
                self._tray_icon.notify(message=message, title=title or 'Automatic Backup')

    def _is_operation_running(self, item=None) -> bool:
        if self._is_running_check is not None:
            try:
                return self._is_running_check()
            except Exception:
                return False
        return False

    def _is_idle(self, item=None) -> bool:
        return not self._is_operation_running(item)

    def _dispatch_action(self, callback: Callable[[], None] | None):
        if callback is not None:
            self.after(0, callback)

    def _build_tray_menu(self) -> pystray.Menu:
        """Construct the contextual menu for the tray icon with dynamic item state."""
        return pystray.Menu(
            pystray.MenuItem('Show Window', lambda icon, item: self.show_window(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                'Sync Now',
                lambda icon, item: self._dispatch_action(self._on_sync_now),
                enabled=lambda item: self._on_sync_now is not None and self._is_idle(item),
            ),
            pystray.MenuItem(
                'Quick Compare',
                lambda icon, item: self._dispatch_action(self._on_quick_compare),
                enabled=lambda item: self._on_quick_compare is not None and self._is_idle(item),
            ),
            pystray.MenuItem(
                'Stop Operation',
                lambda icon, item: self._dispatch_action(self._on_stop_operation),
                enabled=lambda item: self._on_stop_operation is not None and self._is_operation_running(item),
            ),
            pystray.MenuItem(
                'Open Last Report',
                lambda icon, item: self._dispatch_action(self._on_open_report),
                enabled=lambda item: self._on_open_report is not None,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit', lambda icon, item: self.after(0, self.finalize_quit)),
        )

    def _update_tray_menu(self):
        """Update live tray icon menu descriptors."""
        if self._tray_icon is not None:
            with contextlib.suppress(Exception):
                self._tray_icon.menu = self._build_tray_menu()
                self._tray_icon.update_menu()

    def on_minimizing(self, event):
        """Minimize window to system tray when the user minimizes the root window."""
        if event.widget == self and self._tray_icon and not self._is_closing and self.state() == 'iconic':
            self.withdraw()

    def show_window(self):
        """Restore root window to the foreground."""
        self.after(0, self._restore_window)

    def _restore_window(self):
        self.deiconify()
        self.lift()
        with contextlib.suppress(Exception):
            if hasattr(ctypes, 'windll') and hasattr(ctypes.windll, 'user32'):
                ctypes.windll.user32.SetForegroundWindow(self.winfo_id())
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
            menu = self._build_tray_menu()
            self._tray_icon = pystray.Icon('automatic_backup', image, 'Automatic Backup Tool', menu)
            self._tray_icon.run_detached()
        except Exception as e:
            logger.warning(f'Could not initialize system tray icon. Exception: {e}')
