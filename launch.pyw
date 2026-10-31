import contextlib
import ctypes
import os
import subprocess
import sys

# Ensure src directory is in sys.path when running from source
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
if os.path.isdir(src_dir) and src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Enable System DPI awareness on Windows to prevent DWM bitmap scaling blur without drag stutter
if hasattr(ctypes, 'windll'):
    with contextlib.suppress(Exception):
        if hasattr(ctypes.windll, 'user32') and hasattr(ctypes.windll.user32, 'SetProcessDpiAwarenessContext'):
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))
        elif hasattr(ctypes.windll, 'shcore') and hasattr(ctypes.windll.shcore, 'SetProcessDpiAwareness'):
            ctypes.windll.shcore.SetProcessDpiAwareness(1)

# Handle CLI flags before GUI single-instance mutex
if any(arg in sys.argv for arg in ('--create-shortcut', '--shortcut')):
    from utils.shortcut import create_windows_shortcut  # noqa: E402

    try:
        path = create_windows_shortcut()
        print(f'Desktop shortcut created successfully:\n  {path}')
    except Exception as e:
        print(f'Error creating shortcut: {e}', file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

if any(arg in sys.argv for arg in ('--help', '-h')):
    print('FastMirror Launcher')
    print('Usage:')
    print('  pythonw launch.pyw                Launch FastMirror GUI (silent, no console)')
    print('  python launch.pyw --profile "NAS" Launch with a specific configuration profile')
    print('  python launch.pyw --config "path" Launch with an external configuration JSON file')
    print('  python launch.pyw --shortcut      Create a desktop shortcut with icon and launcher')
    print('  python launch.pyw --help          Show this help message')
    sys.exit(0)

# Windows Single-Instance Guard: prevent duplicate concurrent GUI instances
MUTEX_NAME = 'Local\\FastMirror_SingleInstance'
kernel32 = getattr(ctypes, 'windll', None) and getattr(ctypes.windll, 'kernel32', None)
mutex = None
if kernel32:
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        user32 = getattr(ctypes.windll, 'user32', None)
        if user32:
            from utils.constants import WINDOW_TITLE

            hwnd = user32.FindWindowW(None, WINDOW_TITLE) or user32.FindWindowW(None, 'FastMirror')
            if hwnd:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        sys.exit(0)

# Activate venv if not already active and not running as a frozen executable
if not getattr(sys, 'frozen', False):
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

# Parse optional profile or config parameters
profile_arg = None
config_arg = None
arg_idx = 1
while arg_idx < len(sys.argv):
    arg = sys.argv[arg_idx]
    if arg in ('--profile', '-p') and arg_idx + 1 < len(sys.argv):
        profile_arg = sys.argv[arg_idx + 1]
        arg_idx += 1
    elif arg in ('--config', '-c') and arg_idx + 1 < len(sys.argv):
        config_arg = sys.argv[arg_idx + 1]
        arg_idx += 1
    arg_idx += 1

gui = Gui(config_path=config_arg, profile_name=profile_arg)
