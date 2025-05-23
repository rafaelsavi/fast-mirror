import os
import sys

# Activate venv if not already active
venv_path = os.path.join(os.path.dirname(__file__), '.venv', 'Scripts', 'python.exe')
if (
    hasattr(sys, 'base_prefix')
    and sys.base_prefix == sys.prefix
    and os.path.exists(venv_path)
    and os.path.abspath(sys.executable) != os.path.abspath(venv_path)
):
    os.execv(venv_path, [venv_path] + sys.argv)

from gui import Gui

gui = Gui()
