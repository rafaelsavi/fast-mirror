import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from gui.enums import BackendThreadStatus
from gui.widgets import LogLevels, TextLogger


def test_text_logger_filters_by_active_log_levels():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    logger_widget = TextLogger(root)
    logger_widget.set_log_levels(['INFO', 'WARNING'])

    logger_widget.insert('info msg', 'INFO')
    logger_widget.insert('debug msg', 'DEBUG')
    logger_widget.insert('warn msg', 'WARNING')
    logger_widget.insert('error msg', 'ERROR')

    content = logger_widget.get('1.0', tk.END)
    assert 'info msg' in content
    assert 'warn msg' in content
    assert 'debug msg' not in content
    assert 'error msg' not in content

    logger_widget.set_log_levels(['ERROR'])
    content_after_filter = logger_widget.get('1.0', tk.END)
    assert 'error msg' in content_after_filter
    assert 'info msg' not in content_after_filter
    assert 'warn msg' not in content_after_filter
    assert 'debug msg' not in content_after_filter

    logger_widget.set_log_levels([])
    content_empty = logger_widget.get('1.0', tk.END).strip()
    assert content_empty == ''

    logger_widget.set_log_levels(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
    content_all = logger_widget.get('1.0', tk.END)
    assert 'info msg' in content_all
    assert 'debug msg' in content_all
    assert 'warn msg' in content_all
    assert 'error msg' in content_all

    root.destroy()


def test_text_logger_rewrite_preserves_scroll_position():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    logger_widget = TextLogger(root, height=5)
    logger_widget.set_log_levels(['INFO'])
    for i in range(100):
        logger_widget.insert(f'message {i}', 'INFO')

    logger_widget.yview_moveto(0.4)
    pos_before = logger_widget.yview()[0]

    logger_widget.set_log_levels(['INFO'])
    pos_after = logger_widget.yview()[0]
    assert abs(pos_before - pos_after) < 0.05

    root.destroy()


def test_log_levels_selection():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    log_levels = LogLevels()
    assert 'DEBUG' not in log_levels.get()
    assert 'INFO' in log_levels.get()
    assert 'WARNING' in log_levels.get()
    assert 'ERROR' in log_levels.get()
    assert 'CRITICAL' in log_levels.get()

    log_levels.set(['DEBUG', 'CRITICAL'])
    assert sorted(log_levels.get()) == ['CRITICAL', 'DEBUG']

    log_levels.reset()
    assert 'DEBUG' not in log_levels.get()
    assert 'INFO' in log_levels.get()

    root.destroy()


def test_gui_scheduler_persistence_on_standby(monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()
    gui.toggle_state_schedule = True
    gui.toggle_state_sync_now = True
    gui.toggle_state_quick_compare = True
    gui._current_run_trigger = 'sync_now'

    gui.backend_thread_status = BackendThreadStatus.STANDBY
    assert gui.toggle_state_quick_compare is False
    assert gui.toggle_state_sync_now is False
    assert gui.toggle_state_schedule is True
    assert gui._current_run_trigger is None

    gui.root.destroy()


def test_gui_reset_config_restores_safe_defaults(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()
    gui.config_path = str(tmp_path / 'config.json')
    gui.button_action_reset_config(ask_confirmation=False)

    assert gui.checkbox_var_use_mirror.get() is True
    assert gui.checkbox_var_confirm_sync.get() is True
    assert gui.checkbox_var_metadata_comparison.get() is True
    assert gui.checkbox_var_build_mirror.get() is False
    assert gui.checkbox_var_save_report.get() is False
    assert gui.text_var_status.get() == BackendThreadStatus.STANDBY.value

    gui.root.destroy()
