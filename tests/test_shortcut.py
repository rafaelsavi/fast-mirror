"""Tests for Windows shortcut creation utility and launcher integration."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from utils.constants import ROOT_DIR
from utils.shortcut import (
    create_windows_shortcut,
    get_desktop_dir,
    get_launcher_targets,
    get_start_menu_dir,
)


def test_get_desktop_dir():
    """Verify get_desktop_dir returns an existing directory path."""
    desktop = get_desktop_dir()
    assert isinstance(desktop, Path)
    assert desktop.is_dir()


def test_get_start_menu_dir():
    """Verify get_start_menu_dir returns an existing directory path."""
    sm = get_start_menu_dir()
    assert isinstance(sm, Path)
    assert sm.is_dir()


def test_get_launcher_targets():
    """Verify launcher targets resolve existing launch.pyw and app_icon.ico."""
    python_exe, launch_script, icon_path = get_launcher_targets()
    assert isinstance(python_exe, Path)
    assert isinstance(launch_script, Path)
    assert isinstance(icon_path, Path)

    assert launch_script.is_file(), f'launch.pyw missing at {launch_script}'
    assert icon_path.is_file(), f'app_icon.ico missing at {icon_path}'


def test_create_windows_shortcut(tmp_path):
    """Test actual creation of a Windows .lnk shortcut in a temporary directory."""
    shortcut_name = 'TestFastMirror.lnk'
    result_path = create_windows_shortcut(destination_dir=tmp_path, shortcut_name=shortcut_name)

    created_file = Path(result_path)
    assert created_file.is_file()
    assert created_file.name == shortcut_name
    assert created_file.stat().st_size > 0


def test_create_windows_shortcut_failure(tmp_path, monkeypatch):
    """Verify RuntimeError is raised when powershell shortcut generation fails."""
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = 'COM error: access denied'
    mock_proc.stdout = ''
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: mock_proc)

    with pytest.raises(RuntimeError, match='Failed to create Windows shortcut'):
        create_windows_shortcut(destination_dir=tmp_path, shortcut_name='Fail.lnk')


def test_launcher_cli_help():
    """Verify launch.pyw --help output."""
    root = Path(ROOT_DIR)
    proc = subprocess.run(
        [sys.executable, str(root / 'launch.pyw'), '--help'],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert 'FastMirror Launcher' in proc.stdout
    assert '--shortcut' in proc.stdout
