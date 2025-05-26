import os
import sys

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
    os.execv(venv_pythonw, [venv_pythonw] + sys.argv)

from gui.gui import Gui  # noqa: E402

gui = Gui()
