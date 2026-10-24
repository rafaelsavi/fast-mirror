"""Utility for creating Windows desktop and start menu shortcuts with native launcher and icon."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from utils.constants import ROOT_DIR


def get_desktop_dir() -> Path:
    """Return the current user's Windows Desktop directory path."""
    userprofile = os.environ.get('USERPROFILE')
    if userprofile:
        desktop = Path(userprofile) / 'Desktop'
        if desktop.is_dir():
            return desktop
    return Path.home() / 'Desktop'


def get_start_menu_dir() -> Path:
    """Return the current user's Start Menu Programs directory path."""
    appdata = os.environ.get('APPDATA')
    if appdata:
        sm = Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'
        if sm.is_dir():
            return sm
    return Path.home() / 'AppData' / 'Roaming' / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'


def get_launcher_targets() -> tuple[Path, Path, Path]:
    """
    Return (target_pythonw_executable, launch_script, icon_path).

    Prefers .venv/Scripts/pythonw.exe for silent execution without a console window.
    """
    root = Path(ROOT_DIR)
    venv_pythonw = root / '.venv' / 'Scripts' / 'pythonw.exe'
    if venv_pythonw.is_file():
        python_exe = venv_pythonw
    else:
        # Fall back to sys.executable directory's pythonw.exe if available
        pyw = Path(sys.executable).parent / 'pythonw.exe'
        python_exe = pyw if pyw.is_file() else Path(sys.executable)

    launch_script = root / 'launch.pyw'
    icon_path = root / 'src' / 'gui' / 'app_icon.ico'

    return python_exe, launch_script, icon_path


def create_windows_shortcut(
    destination_dir: str | Path | None = None,
    shortcut_name: str = 'FastMirror.lnk',
) -> str:
    """
    Create a Windows .lnk shortcut with native icon and silent launcher.

    Returns the absolute path string to the created shortcut file.
    """
    target_dir = get_desktop_dir() if destination_dir is None else Path(destination_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    shortcut_path = (target_dir / shortcut_name).resolve()

    python_exe, launch_script, icon_path = get_launcher_targets()
    work_dir = Path(ROOT_DIR).resolve()

    # Escape single quotes for PowerShell string literals
    def _ps_esc(p: Path | str) -> str:
        return str(p).replace("'", "''")

    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f"$s = $ws.CreateShortcut('{_ps_esc(shortcut_path)}'); "
        f"$s.TargetPath = '{_ps_esc(python_exe)}'; "
        f'$s.Arguments = \'"{_ps_esc(launch_script)}"\'; '
        f"$s.WorkingDirectory = '{_ps_esc(work_dir)}'; "
        f"$s.IconLocation = '{_ps_esc(icon_path)},0'; "
        f"$s.Description = 'FastMirror - Automated Directory Synchronization'; "
        f'$s.Save()'
    )

    proc = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', ps_script],
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0 or not shortcut_path.is_file():
        err = proc.stderr.strip() or proc.stdout.strip() or 'Unknown error'
        raise RuntimeError(f'Failed to create Windows shortcut at {shortcut_path}: {err}')

    return str(shortcut_path)
