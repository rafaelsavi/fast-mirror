"""
Centralized icon management for FastMirror GUI controls.

Provides cached, high-fidelity PNG icons loaded into Tkinter PhotoImage instances,
avoiding raw Unicode/emoji font fallback artifacts on Windows GDI.
"""

from __future__ import annotations

import contextlib
import os
import tkinter as tk
from tkinter import ttk
from typing import Any

_APP_ICON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app_icon.ico'))
_ICONS_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'icons')
_ICON_CACHE: dict[str, tk.PhotoImage] = {}


def get_app_icon_path() -> str | None:
    """Return the absolute path to the app icon (.ico), or None if not found."""
    return _APP_ICON_PATH if os.path.isfile(_APP_ICON_PATH) else None


def apply_window_icon(window: tk.Tk | tk.Toplevel) -> None:
    """
    Apply the unified application icon (.ico) to any window, dialog, or popup modal.

    Sets both the default icon for child Toplevel windows and the explicit icon for
    the given window handle, ensuring titlebar, taskbar, and Alt+Tab display consistency.
    """
    icon_path = get_app_icon_path()
    if not icon_path:
        return

    with contextlib.suppress(Exception):
        window.iconbitmap(default=icon_path)
    with contextlib.suppress(Exception):
        window.iconbitmap(icon_path)


def get_dpi_scale(widget: tk.Misc | None = None) -> float:
    """Calculate current display DPI scaling factor safely."""
    if widget is None:
        return 1.0
    try:
        scaling = float(widget.tk.call('tk', 'scaling'))
        # Standard 96 DPI corresponds to Tk scaling ratio 96 / 72 = 1.33333333
        return max(1.0, scaling / 1.33333333)
    except Exception:
        return 1.0


def get_icon(name: str, master: tk.Misc | None = None, auto_scale: bool = False) -> tk.PhotoImage | None:
    """
    Retrieve or load a cached PhotoImage icon by name.

    Automatically handles Tkinter interpreter lifecycle across window re-creations
    and pytest test suites. Returns None gracefully if no Tk root window exists yet
    or if the icon file is missing.
    """
    cache_key = f'{name}_2x' if auto_scale and master and get_dpi_scale(master) >= 1.75 else name
    if cache_key in _ICON_CACHE:
        cached = _ICON_CACHE[cache_key]
        try:
            cached.tk.call('image', 'width', cached.name)
            return cached
        except (tk.TclError, RuntimeError, AttributeError):
            _ICON_CACHE.pop(cache_key, None)

    icon_path = os.path.join(_ICONS_DIR, f'{name}.png')
    if not os.path.isfile(icon_path):
        return None

    try:
        img = tk.PhotoImage(file=icon_path, master=master)
        if auto_scale and master and get_dpi_scale(master) >= 1.75:
            with contextlib.suppress(Exception):
                img = img.zoom(2, 2)
        _ICON_CACHE[cache_key] = img
        return img
    except (tk.TclError, RuntimeError):
        return None


def apply_icon(
    button: ttk.Button | tk.Button,
    icon_name: str,
    text: str | None = None,
    compound: str = 'left',
    auto_scale: bool = False,
) -> None:
    """
    Configure a button with a real icon and text safely.

    Maintains a persistent reference on the widget object to protect against
    Tkinter garbage collection transparent-bitmap bugs.
    """
    icon = get_icon(icon_name, master=button, auto_scale=auto_scale)
    config_kwargs: dict[str, Any] = {}

    if text is not None:
        config_kwargs['text'] = text

    if icon is not None:
        config_kwargs['image'] = icon
        config_kwargs['compound'] = compound
        # Bind reference to the button instance so Tkinter never garbage collects it
        button._icon_ref = icon  # type: ignore[union-attr]

    with contextlib.suppress(Exception):
        button.configure(**config_kwargs)


def clear_icon(button: ttk.Button | tk.Button, text: str | None = None) -> None:
    """
    Remove any icon image from a button safely.

    Clears the image attribute and compound layout, resetting widget reference.
    """
    config_kwargs: dict[str, Any] = {'image': '', 'compound': 'none'}
    if text is not None:
        config_kwargs['text'] = text

    with contextlib.suppress(Exception):
        button.configure(**config_kwargs)
    button._icon_ref = None  # type: ignore[union-attr]
