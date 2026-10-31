import contextlib
import os
import re
import sys
import tempfile
import tkinter as tk
import winsound

src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../src'))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

_TEST_LOG_DIR = os.path.join(tempfile.gettempdir(), 'autobackup_pytest_logs')
_OFFSCREEN_COORDS = '+25000+25000'


def _suppress_window_flashing() -> None:
    """
    Abstract and suppress all GUI window mapping, taskbar flashing, and focus stealing during tests.

    Tkinter/Tcl widget logic, layout calculations (update_idletasks), Treeviews, and virtual
    events operate fully in-memory. By forcing windows to remain off-screen (+25000+25000),
    suppressing OS-level grab_set/focus_force, and silencing winsound.PlaySound, the test suite
    executes 100% silently and invisibly in the background without disturbing the user.
    """
    # 1. Silence all system sound chimes during test execution
    winsound.PlaySound = lambda *args, **kwargs: None

    # 2. Hook tk.Tk._loadtk so root windows immediately start offscreen and withdrawn
    orig_loadtk = tk.Tk._loadtk

    def headless_loadtk(self: tk.Tk) -> None:
        orig_loadtk(self)
        with contextlib.suppress(Exception):
            self.geometry(_OFFSCREEN_COORDS)
            self.withdraw()

    tk.Tk._loadtk = headless_loadtk

    # 3. Hook geometry / wm_geometry so any positioning remains off-screen (+25000+25000)
    orig_wm_geometry = tk.Wm.wm_geometry

    def headless_geometry(self: tk.Wm, newGeometry: str | None = None) -> str | None:
        if newGeometry is None:
            return orig_wm_geometry(self)
        geom_str = str(newGeometry).strip()
        match = re.match(r'^(\d+x\d+)?([+-].+)?$', geom_str)
        if match:
            size_part = match.group(1) or ''
            new_geom = f'{size_part}{_OFFSCREEN_COORDS}' if size_part else _OFFSCREEN_COORDS
            return orig_wm_geometry(self, new_geom)
        return orig_wm_geometry(self, _OFFSCREEN_COORDS)

    tk.Wm.wm_geometry = headless_geometry  # type: ignore[assignment]
    tk.Wm.geometry = headless_geometry  # type: ignore[assignment]

    # 4. Hook tk.Toplevel.__init__ so newly created dialogs start off-screen
    orig_toplevel_init = tk.Toplevel.__init__

    def headless_toplevel_init(self: tk.Toplevel, *args: object, **kwargs: object) -> None:
        orig_toplevel_init(self, *args, **kwargs)
        with contextlib.suppress(Exception):
            self.geometry(_OFFSCREEN_COORDS)

    tk.Toplevel.__init__ = headless_toplevel_init  # type: ignore[assignment]

    # 5. Suppress focus-stealing and modal grabbing from the Windows desktop
    tk.Wm.grab_set = lambda self: None  # type: ignore[assignment]
    tk.Wm.grab_set_global = lambda self: None  # type: ignore[assignment]
    tk.Wm.focus_force = lambda self: None  # type: ignore[assignment]


def pytest_configure(config: object) -> None:
    """Ensure test mode and disable file logging flags are active before tests are loaded."""
    os.environ['AUTOMATIC_BACKUP_TESTING'] = '1'
    os.environ['AUTOMATIC_BACKUP_DISABLE_FILE_LOG'] = '1'
    os.environ['AUTOMATIC_BACKUP_LOG_DIR'] = _TEST_LOG_DIR
    os.makedirs(_TEST_LOG_DIR, exist_ok=True)
    _suppress_window_flashing()
