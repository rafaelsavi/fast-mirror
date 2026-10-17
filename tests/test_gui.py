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


def test_status_bar_updates():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.status_bar import StatusBar

    status_var = tk.StringVar(value='STANDBY')
    sched_var = tk.StringVar(value='Tomorrow 10:00')

    bar = StatusBar(
        root,
        text_var_status=status_var,
        text_var_next_appointment=sched_var,
    )

    assert bar.text_var_status.get() == 'STANDBY'
    assert bar.text_var_next_appointment.get() == 'Tomorrow 10:00'
    status_var.set('RUNNING')
    sched_var.set('Next Week')
    assert bar.text_var_status.get() == 'RUNNING'
    assert bar.text_var_next_appointment.get() == 'Next Week'

    root.destroy()


def test_paths_panel_interactions(tmp_path):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.paths_panel import PathsPanel

    add_path_clicked = []
    panel = PathsPanel(root, on_add_path=lambda: add_path_clicked.append(True))

    panel.btn_add_path.invoke()
    assert len(add_path_clicked) == 1

    panel.entry_exclusions.set(['*.tmp', '.git'])
    assert '*.tmp' in panel.entry_exclusions.get()

    root.destroy()


def test_schedule_panel_interactions():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.schedule_panel import SchedulePanel
    from gui.widgets import WeekDays

    week_days = WeekDays()
    panel = SchedulePanel(root, week_days=week_days)

    assert len(panel.week_days.get()) == 0
    panel.week_days.set(['MON', 'FRI'])
    assert sorted(panel.week_days.get()) == ['FRI', 'MON']

    panel.entry_times.set(['09:30', '18:00'])
    assert panel.entry_times.get() == ['09:30', '18:00']

    root.destroy()


def test_actions_panel_interactions():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.actions_panel import ActionsPanel
    from gui.widgets import Action, DefaultActions

    actions_called = []
    default_actions = DefaultActions()
    var_save = tk.BooleanVar(value=False)
    var_build = tk.BooleanVar(value=False)
    var_use = tk.BooleanVar(value=True)
    var_meta = tk.BooleanVar(value=True)
    var_confirm = tk.BooleanVar(value=True)

    panel = ActionsPanel(
        root,
        checkbox_default_actions=default_actions,
        checkbox_var_save_report=var_save,
        checkbox_var_build_mirror=var_build,
        checkbox_var_use_mirror=var_use,
        checkbox_var_metadata_comparison=var_meta,
        checkbox_var_confirm_sync=var_confirm,
        on_reset_config=lambda: actions_called.append('reset'),
        on_save_config=lambda: actions_called.append('save'),
        on_quick_compare=lambda: actions_called.append('compare'),
        on_open_report=lambda: actions_called.append('report'),
        on_sync_now=lambda: actions_called.append('sync'),
        on_schedule_sync=lambda: actions_called.append('schedule'),
    )

    panel.button_new_config.invoke()
    panel.button_save_config.invoke()
    panel.button_quick_compare.invoke()
    panel.button_open_report.invoke()
    panel.button_sync_now.invoke()
    panel.button_schedule_sync.invoke()

    assert actions_called == ['reset', 'save', 'compare', 'report', 'sync', 'schedule']
    assert default_actions.get_as_actions() == [Action.COPY]

    root.destroy()


def test_log_panel_clear_and_styling():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.log_panel import LogPanel

    log_panel = LogPanel(root)
    log_panel.text_logger.insert('info line', 'INFO')
    assert 'info line' in log_panel.text_logger.get('1.0', tk.END)

    log_panel.clear_log()
    assert log_panel.text_logger.get('1.0', tk.END).strip() == ''
    assert len(log_panel.text_logger.lines) == 0

    log_panel.apply_theme('light')
    assert log_panel.text_logger.cget('bg') == '#ffffff'

    root.destroy()


def test_gui_initialization_with_light_theme(monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    import sv_ttk

    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()
    assert sv_ttk.get_theme() == 'light'
    assert gui.status_bar is not None
    assert gui.paths_panel is not None
    assert gui.actions_panel is not None
    assert gui.schedule_panel is not None
    assert gui.log_panel is not None

    gui.root.destroy()
