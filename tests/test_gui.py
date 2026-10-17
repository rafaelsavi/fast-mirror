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


def test_trayable_tk_menu_and_action_states():
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.tray import TrayableTk

    tray_window = TrayableTk()
    tray_window.withdraw()

    # In test mode, _tray_icon is None
    assert tray_window._tray_icon is None

    sync_called = []
    compare_called = []
    stop_called = []
    report_called = []
    is_running = False

    tray_window.set_tray_callbacks(
        on_sync_now=lambda: sync_called.append(True),
        on_quick_compare=lambda: compare_called.append(True),
        on_stop_operation=lambda: stop_called.append(True),
        on_open_report=lambda: report_called.append(True),
        is_running=lambda: is_running,
    )

    menu = tray_window._build_tray_menu()
    items = list(menu)
    assert len(items) == 8

    # Item labels: Show Window, Separator, Sync Now, Quick Compare, Stop Operation, Open Last Report, Separator, Quit
    item_labels = [item.text if hasattr(item, 'text') else str(item) for item in items]
    assert 'Show Window' in item_labels
    assert 'Sync Now' in item_labels
    assert 'Quick Compare' in item_labels
    assert 'Stop Operation' in item_labels
    assert 'Open Last Report' in item_labels
    assert 'Quit' in item_labels

    # When idle: Sync and Compare are enabled, Stop is disabled
    sync_item = next(it for it in items if getattr(it, 'text', '') == 'Sync Now')
    compare_item = next(it for it in items if getattr(it, 'text', '') == 'Quick Compare')
    stop_item = next(it for it in items if getattr(it, 'text', '') == 'Stop Operation')
    report_item = next(it for it in items if getattr(it, 'text', '') == 'Open Last Report')

    assert sync_item.enabled is True
    assert compare_item.enabled is True
    assert stop_item.enabled is False
    assert report_item.enabled is True

    # When running: Sync and Compare are disabled, Stop is enabled
    is_running = True
    assert sync_item.enabled is False
    assert compare_item.enabled is False
    assert stop_item.enabled is True

    # Safe operations when _tray_icon is None
    tray_window.update_tray_tooltip('A' * 200)
    tray_window.notify('test message', 'test title')

    tray_window.destroy()


def test_trayable_tk_mock_icon():
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from unittest.mock import MagicMock

    from gui.tray import TrayableTk

    tray_window = TrayableTk()
    tray_window.withdraw()

    mock_icon = MagicMock()
    tray_window._tray_icon = mock_icon

    # Tooltip truncation test
    tray_window.update_tray_tooltip('A' * 200)
    assert len(mock_icon.title) == 127

    # Notify test
    tray_window.notify('Backup done', 'Success')
    mock_icon.notify.assert_called_once_with(message='Backup done', title='Success')

    # Menu update test
    tray_window._update_tray_menu()
    assert mock_icon.menu is not None
    mock_icon.update_menu.assert_called_once()

    tray_window.finalize_quit()


def test_gui_tray_status_and_actions(monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.enums import BackendThreadStatus
    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()

    # Verify tray actions are registered
    assert gui.root._on_sync_now is not None
    assert gui.root._on_quick_compare is not None
    assert gui.root._on_stop_operation is not None
    assert gui.root._on_open_report is not None

    # Test tray_action_sync_now
    assert not gui.toggle_state_sync_now
    gui.tray_action_sync_now()
    assert gui.toggle_state_sync_now

    # Test tray_action_quick_compare
    assert not gui.toggle_state_quick_compare
    gui.tray_action_quick_compare()
    assert gui.toggle_state_quick_compare

    # Test request_stop_operation
    gui.backend_thread_status = BackendThreadStatus.RUNNING
    gui.request_stop_operation()
    assert gui.backend_thread_status == BackendThreadStatus.STOPPING
    assert not gui.toggle_state_sync_now
    assert not gui.toggle_state_quick_compare

    gui.root.destroy()


def test_calculate_next_run_edge_cases():
    import datetime

    from gui.scheduler import calculate_next_run

    # Empty inputs
    assert calculate_next_run([], ['10:00']) is None
    assert calculate_next_run([0], []) is None
    assert calculate_next_run([0], ['invalid_time', '99:99']) is None

    # Reference time: Monday 2026-10-19 at 10:15
    ref_monday = datetime.datetime(2026, 10, 19, 10, 15)

    # 1. Later today (Monday 14:00)
    res = calculate_next_run(days=[0], times=['09:00', '14:00'], now=ref_monday)
    assert res == datetime.datetime(2026, 10, 19, 14, 0)

    # 2. Earlier today has passed -> next scheduled day (Wednesday 08:30)
    res2 = calculate_next_run(days=[0, 2], times=['08:30'], now=ref_monday)
    assert res2 == datetime.datetime(2026, 10, 21, 8, 30)

    # 3. Exactly now -> triggers now if not yet run
    res3 = calculate_next_run(days=[0], times=['10:15'], now=ref_monday)
    assert res3 == datetime.datetime(2026, 10, 19, 10, 15)

    # 4. Exactly now, but already executed at this timestamp -> schedules next week
    res4 = calculate_next_run(days=[0], times=['10:15'], now=ref_monday, last_run=ref_monday)
    assert res4 == datetime.datetime(2026, 10, 26, 10, 15)


def test_panels_set_enabled():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.actions_panel import ActionsPanel
    from gui.components.paths_panel import PathsPanel
    from gui.components.schedule_panel import SchedulePanel
    from gui.widgets import DefaultActions

    p_panel = PathsPanel(root)
    s_panel = SchedulePanel(root)
    a_panel = ActionsPanel(
        root,
        checkbox_default_actions=DefaultActions(),
        checkbox_var_save_report=tk.BooleanVar(),
        checkbox_var_build_mirror=tk.BooleanVar(),
        checkbox_var_use_mirror=tk.BooleanVar(),
        checkbox_var_metadata_comparison=tk.BooleanVar(),
        checkbox_var_confirm_sync=tk.BooleanVar(),
        on_reset_config=lambda: None,
        on_save_config=lambda: None,
        on_quick_compare=lambda: None,
        on_open_report=lambda: None,
        on_sync_now=lambda: None,
        on_schedule_sync=lambda: None,
    )

    p_panel.set_enabled(False)
    assert str(p_panel.btn_add_path.cget('state')) == 'disabled'
    p_panel.set_enabled(True)
    assert str(p_panel.btn_add_path.cget('state')) == 'normal'

    s_panel.set_enabled(False)
    for cb in s_panel.checkbox_week_days.values():
        assert str(cb.cget('state')) == 'disabled'
    s_panel.set_enabled(True)
    for cb in s_panel.checkbox_week_days.values():
        assert str(cb.cget('state')) == 'normal'

    a_panel.set_enabled(False)
    assert str(a_panel.button_sync_now.cget('state')) == 'disabled'
    a_panel.set_enabled(True)
    assert str(a_panel.button_sync_now.cget('state')) == 'normal'

    root.destroy()
