"""Base class for modal dialogs providing flicker-free alpha concealment, parent centering, and lifecycle management."""

import contextlib
import tkinter as tk

from gui.icons import apply_window_icon


class BaseModalDialog(tk.Toplevel):
    """
    Architectural template base class for all modal windows in FastMirror.

    Eliminates initial top-left flicker by initializing with alpha=0, assembling
    widgets in memory, centering over parent or primary display, and smoothly
    revealing at alpha=1.0.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | None,
        title: str,
        width: int,
        height: int,
        min_width: int | None = None,
        min_height: int | None = None,
        resizable: bool = True,
        modal: bool = True,
    ):
        super().__init__(parent)
        self.parent = parent
        self.modal_width = width
        self.modal_height = height
        self._is_modal = modal

        # Backward-compatibility alias so code/tests accessing self.window work seamlessly
        self.window = self

        # Conceal immediately with alpha=0 to prevent the Win32 top-left flicker
        with contextlib.suppress(Exception):
            self.attributes('-alpha', 0.0)

        # Setup window decorations & styling
        self.title(title)
        with contextlib.suppress(Exception):
            self.configure(bg='SystemButtonFace')
        apply_window_icon(self)

        min_w = min_width or width
        min_h = min_height or height
        self.minsize(min_w, min_h)

        if not resizable:
            self.resizable(False, False)

        if parent is not None:
            with contextlib.suppress(Exception):
                self.transient(parent)

        # Bind standard window close protocols
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.bind('<Escape>', lambda _e: self.on_close())

    def _center_and_reveal(self, modal: bool | None = None):
        """Calculate coordinates relative to parent or screen, apply geometry, and reveal."""
        if modal is None:
            modal = self._is_modal

        try:
            self.update_idletasks()
            pos_x, pos_y = self._calculate_coordinates(self.modal_width, self.modal_height)
            self.geometry(f'{self.modal_width}x{self.modal_height}+{pos_x}+{pos_y}')
        except Exception:
            self.geometry(f'{self.modal_width}x{self.modal_height}')

        # Ensure layout is settled before revealing
        with contextlib.suppress(Exception):
            self.update_idletasks()
            self.attributes('-alpha', 1.0)
            self.deiconify()

        if modal:
            with contextlib.suppress(Exception):
                self.grab_set()

        with contextlib.suppress(Exception):
            self.focus_set()

    def _calculate_coordinates(self, width: int, height: int) -> tuple[int, int]:
        """Compute top-left coordinates centered over parent window or the primary display."""
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        pos_x: int | None = None
        pos_y: int | None = None

        if self.parent is not None:
            try:
                pw = self.parent.winfo_width()
                ph = self.parent.winfo_height()
                px = self.parent.winfo_rootx()
                py = self.parent.winfo_rooty()
                if pw > 100 and ph > 100:
                    pos_x = px + (pw - width) // 2
                    pos_y = py + (ph - height) // 2
            except Exception:
                pass

        if pos_x is None or pos_y is None:
            pos_x = (screen_w - width) // 2
            pos_y = (screen_h - height) // 2

        # Clamp inside visible screen bounds with comfortable margins
        pos_x = max(10, min(pos_x, screen_w - width - 10))
        pos_y = max(10, min(pos_y, screen_h - height - 40))
        return pos_x, pos_y

    def on_close(self):
        """Release modal grab and destroy window."""
        with contextlib.suppress(Exception):
            self.grab_release()
        self.destroy()
