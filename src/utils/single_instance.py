r"""
Windows Single-Instance guard and named mutex management for FastMirror.

Controls application concurrency using a Win32 Named Mutex ('Local\\FastMirror_SingleInstance'),
allowing automatic activation of existing GUI instances and explicit kernel mutex cleanup
during application shutdown or update installation handoffs.
"""

from __future__ import annotations

import contextlib
import ctypes
from typing import Any

from utils.constants import WINDOW_TITLE
from utils.logger import logger

MUTEX_NAME = 'Local\\FastMirror_SingleInstance'

_mutex_handle: Any = None


def acquire_single_instance(activate_existing: bool = True) -> bool:
    """
    Attempt to acquire the Windows named single-instance mutex.

    If an instance is already running:
    - Brings the existing instance window to foreground if activate_existing is True.
    - Returns False.

    If no instance is running:
    - Acquires the mutex handle and returns True.
    """
    global _mutex_handle

    kernel32 = getattr(ctypes, 'windll', None) and getattr(ctypes.windll, 'kernel32', None)
    if not kernel32:
        return True

    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True

    last_error = kernel32.GetLastError()
    if last_error == 183:  # ERROR_ALREADY_EXISTS
        with contextlib.suppress(Exception):
            kernel32.CloseHandle(handle)

        if activate_existing:
            user32 = getattr(ctypes.windll, 'user32', None)
            if user32:
                with contextlib.suppress(Exception):
                    hwnd = user32.FindWindowW(None, WINDOW_TITLE) or user32.FindWindowW(None, 'FastMirror')
                    if hwnd:
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        user32.SetForegroundWindow(hwnd)
        return False

    _mutex_handle = handle
    return True


def release_single_instance() -> None:
    """
    Explicitly release and close the Win32 single-instance mutex handle.

    Guarantees immediate removal of the named mutex from the OS kernel namespace
    before launching updates or terminating the application.
    """
    global _mutex_handle

    if _mutex_handle is not None:
        kernel32 = getattr(ctypes, 'windll', None) and getattr(ctypes.windll, 'kernel32', None)
        if kernel32:
            try:
                kernel32.CloseHandle(_mutex_handle)
                logger.debug('Win32 single-instance mutex released successfully.')
            except Exception as e:
                logger.debug(f'Error releasing Win32 single-instance mutex: {e}')
        _mutex_handle = None


def is_single_instance_acquired() -> bool:
    """Return True if this process currently holds the Win32 single-instance mutex."""
    return _mutex_handle is not None
