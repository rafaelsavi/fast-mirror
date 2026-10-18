import contextlib
import ctypes
import os
import subprocess
import sys

# Enable System DPI awareness on Windows to prevent DWM bitmap scaling blur without drag stutter
if hasattr(ctypes, 'windll'):
    with contextlib.suppress(Exception):
        if hasattr(ctypes.windll, 'user32') and hasattr(ctypes.windll.user32, 'SetProcessDpiAwarenessContext'):
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))
        elif hasattr(ctypes.windll, 'shcore') and hasattr(ctypes.windll.shcore, 'SetProcessDpiAwareness'):
            ctypes.windll.shcore.SetProcessDpiAwareness(1)

# Windows Single-Instance Guard: prevent duplicate concurrent GUI instances
MUTEX_NAME = 'Local\\FastMirror_SingleInstance'
kernel32 = getattr(ctypes, 'windll', None) and getattr(ctypes.windll, 'kernel32', None)
mutex = None
if kernel32:
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        user32 = getattr(ctypes.windll, 'user32', None)
        if user32:
            hwnd = user32.FindWindowW(None, 'FastMirror')
            if hwnd:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        sys.exit(0)

# Activate venv if not already active
venv_dir = os.path.join(os.path.dirname(__file__), '.venv', 'Scripts')
venv_pythonw = os.path.join(venv_dir, 'pythonw.exe')
venv_python = os.path.join(venv_dir, 'python.exe')

if (
    hasattr(sys, 'base_prefix')
    and sys.base_prefix == sys.prefix
    and os.path.exists(venv_pythonw)
    and os.path.abspath(sys.executable) not in [os.path.abspath(venv_pythonw), os.path.abspath(venv_python)]
):
    subprocess.Popen([venv_pythonw] + sys.argv)
    sys.exit(0)

# Ensure src is on sys.path for direct execution
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from gui.gui import Gui  # noqa: E402

gui = Gui()
