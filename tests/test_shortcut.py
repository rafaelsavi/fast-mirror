"""Tests for Windows shortcut creation utility and launcher integration."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from utils.shortcut import (
    create_windows_shortcut,
    get_desktop_dir,
    get_launcher_targets,
    get_start_menu_dir,
)


def test_get_desktop_dir():
    """Verify get_desktop_dir returns a valid path ending in Desktop."""
    desktop = get_desktop_dir()
    assert isinstance(desktop, Path)
    assert desktop.name == 'Desktop'


def test_get_start_menu_dir():
    """Verify get_start_menu_dir returns a valid path ending in Programs."""
    sm = get_start_menu_dir()
    assert isinstance(sm, Path)
    assert sm.name == 'Programs'


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


def test_gui_create_shortcut_success(monkeypatch, tmp_path):
    """Verify GUI button_action_create_shortcut displays success dialog."""
    import tkinter as tk

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.gui import Gui

    monkeypatch.setattr(Gui, '__init__', lambda self: None)
    gui = Gui()
    gui.root = root

    info_called = []
    monkeypatch.setattr('tkinter.messagebox.showinfo', lambda title, msg: info_called.append((title, msg)))
    monkeypatch.setattr('utils.shortcut.create_windows_shortcut', lambda: str(tmp_path / 'FastMirror.lnk'))

    gui.button_action_create_shortcut()

    assert len(info_called) == 1
    assert 'Desktop Shortcut' in info_called[0][0]
    root.destroy()


def test_gui_create_shortcut_error(monkeypatch):
    """Verify GUI button_action_create_shortcut displays error dialog on failure."""
    import tkinter as tk

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.gui import Gui

    monkeypatch.setattr(Gui, '__init__', lambda self: None)
    gui = Gui()
    gui.root = root

    error_called = []
    monkeypatch.setattr('tkinter.messagebox.showerror', lambda title, msg: error_called.append((title, msg)))

    def _fail():
        raise RuntimeError('Simulated COM failure')

    monkeypatch.setattr('utils.shortcut.create_windows_shortcut', _fail)

    gui.button_action_create_shortcut()

    assert len(error_called) == 1
    assert 'Shortcut Error' in error_called[0][0]
    root.destroy()
