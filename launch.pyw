import ctypes
import os
import subprocess
import sys

# Windows Single-Instance Guard: prevent duplicate concurrent GUI instances
MUTEX_NAME = 'Local\\AutomaticBackupTool_SingleInstance'
kernel32 = getattr(ctypes, 'windll', None) and getattr(ctypes.windll, 'kernel32', None)
mutex = None
if kernel32:
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        user32 = getattr(ctypes.windll, 'user32', None)
        if user32:
            hwnd = user32.FindWindowW(None, 'Automatic Backup Tool')
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

from gui.gui import Gui  # noqa: E402

gui = Gui()
