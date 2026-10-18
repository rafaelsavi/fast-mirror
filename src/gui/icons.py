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

_ICONS_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'icons')
_ICON_CACHE: dict[str, tk.PhotoImage] = {}


def get_icon(name: str, master: tk.Misc | None = None) -> tk.PhotoImage | None:
    """
    Retrieve or load a cached PhotoImage icon by name.

    Automatically handles Tkinter interpreter lifecycle across window re-creations
    and pytest test suites. Returns None gracefully if no Tk root window exists yet
    or if the icon file is missing.
    """
    if name in _ICON_CACHE:
        cached = _ICON_CACHE[name]
        try:
            cached.tk.call('image', 'width', cached.name)
            return cached
        except (tk.TclError, RuntimeError, AttributeError):
            _ICON_CACHE.pop(name, None)

    icon_path = os.path.join(_ICONS_DIR, f'{name}.png')
    if not os.path.isfile(icon_path):
        return None

    try:
        img = tk.PhotoImage(file=icon_path, master=master)
        _ICON_CACHE[name] = img
        return img
    except (tk.TclError, RuntimeError):
        return None


def apply_icon(
    button: ttk.Button | tk.Button,
    icon_name: str,
    text: str | None = None,
    compound: str = 'left',
) -> None:
    """
    Configure a button with a real icon and text safely.

    Maintains a persistent reference on the widget object to protect against
    Tkinter garbage collection transparent-bitmap bugs.
    """
    icon = get_icon(icon_name, master=button)
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
