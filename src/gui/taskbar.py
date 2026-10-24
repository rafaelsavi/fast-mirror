"""
Windows Taskbar Progress integration via the ITaskbarList3 COM interface.

Provides native Windows 7 through 11 taskbar progress bar states:
- Indeterminate scrolling marquee during file scanning and comparisons
- Determinate green progress bar during active file synchronization
- Yellow paused indicator when interactive confirmation popups require user input
- Red error indicator on critical failure
- Zero external third-party dependencies: uses Python standard ctypes.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from ctypes import wintypes

from utils.logger import is_test_or_agent_mode, logger

# Windows Taskbar Progress Flags (TBPFLAG)
TBPF_NOPROGRESS = 0x0
TBPF_INDETERMINATE = 0x1
TBPF_NORMAL = 0x2
TBPF_ERROR = 0x4
TBPF_PAUSED = 0x8


class _GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', wintypes.BYTE * 8),
    ]

    @classmethod
    def from_str(cls, guid_str: str) -> _GUID:
        import uuid

        u = uuid.UUID(guid_str.strip('{}'))
        return cls.from_buffer_copy(u.bytes_le)


_CLSID_TaskbarList = _GUID.from_str('{56FDF344-FD6D-11d0-958A-006097C9A090}')
_IID_ITaskbarList3 = _GUID.from_str('{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}')


class TaskbarProgress:
    """Manages Windows taskbar button progress states and progress values."""

    def __init__(self, hwnd: int | None = None):
        self._hwnd = hwnd
        self._ptr: ctypes.c_void_p | None = None
        self._fn_set_value = None
        self._fn_set_state = None
        self._initialized = False

        if sys.platform != 'win32' or is_test_or_agent_mode():
            return

        self._initialize_com()

    def set_hwnd(self, hwnd: int):
        """Update top-level window handle for taskbar progress dispatch."""
        self._hwnd = self._get_root_hwnd(hwnd)

    @staticmethod
    def _get_root_hwnd(hwnd: int) -> int:
        if sys.platform == 'win32':
            with contextlib.suppress(Exception):
                # GA_ROOT = 2: retrieve root ancestor window handle
                ancestor = ctypes.windll.user32.GetAncestor(hwnd, 2)
                if ancestor:
                    return ancestor
        return hwnd

    def _initialize_com(self):
        try:
            ole32 = ctypes.windll.ole32
            ole32.CoInitialize(None)

            self._ptr = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(_CLSID_TaskbarList),
                None,
                1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(_IID_ITaskbarList3),
                ctypes.byref(self._ptr),
            )
            if hr == 0 and self._ptr:
                # Resolve vtable functions from interface pointer
                vtbl_ptr = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
                vtbl = vtbl_ptr.contents

                # HrInit (vtable index 3)
                hr_init_fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtbl[3])
                hr_init_fn(self._ptr)

                # SetProgressValue (vtable index 9)
                self._fn_set_value = ctypes.WINFUNCTYPE(
                    ctypes.HRESULT,
                    ctypes.c_void_p,
                    wintypes.HWND,
                    ctypes.c_ulonglong,
                    ctypes.c_ulonglong,
                )(vtbl[9])

                # SetProgressState (vtable index 10)
                self._fn_set_state = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, wintypes.DWORD)(
                    vtbl[10]
                )

                self._initialized = True
        except Exception as e:
            logger.debug(f'TaskbarProgress COM initialization skipped: {e}')

    def set_indeterminate(self):
        """Switch taskbar button to continuous scrolling marquee animation."""
        if not self._initialized or not self._hwnd or not self._fn_set_state:
            return
        with contextlib.suppress(Exception):
            self._fn_set_state(self._ptr, self._hwnd, TBPF_INDETERMINATE)

    def set_determinate(self, current: int, total: int):
        """Update determinate green progress bar on taskbar button."""
        if not self._initialized or not self._hwnd or not self._fn_set_state or not self._fn_set_value:
            return
        if total <= 0:
            return
        with contextlib.suppress(Exception):
            self._fn_set_state(self._ptr, self._hwnd, TBPF_NORMAL)
            self._fn_set_value(self._ptr, self._hwnd, max(0, current), total)

    def set_paused(self):
        """Display yellow paused progress state when waiting on user confirmation."""
        if not self._initialized or not self._hwnd or not self._fn_set_state:
            return
        with contextlib.suppress(Exception):
            self._fn_set_state(self._ptr, self._hwnd, TBPF_PAUSED)

    def set_error(self):
        """Display red error progress bar on taskbar button."""
        if not self._initialized or not self._hwnd or not self._fn_set_state:
            return
        with contextlib.suppress(Exception):
            self._fn_set_state(self._ptr, self._hwnd, TBPF_ERROR)

    def clear(self):
        """Clear taskbar progress bar and return to standard window icon."""
        if not self._initialized or not self._hwnd or not self._fn_set_state:
            return
        with contextlib.suppress(Exception):
            self._fn_set_state(self._ptr, self._hwnd, TBPF_NOPROGRESS)
