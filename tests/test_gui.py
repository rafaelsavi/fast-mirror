import datetime
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
    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    try:
        gui = Gui()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

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
    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    try:
        gui = Gui()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

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

    panel = PathsPanel(root)

    assert panel.btn_manage_paths is not None
    assert panel.btn_manage_exclusions is not None

    panel.entry_exclusions.set(['*.tmp', '.git'])
    assert '*.tmp' in panel.entry_exclusions.get()

    root.destroy()


def test_paths_panel_open_selected_and_source_validation(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.paths_panel import PathsPanel

    src = tmp_path / 'SourceFolder'
    src.mkdir()
    tgt = tmp_path / 'TargetFolder'
    tgt.mkdir()

    paths_panel = PathsPanel(root)
    paths_panel.entry_paths.set([(str(src), str(tgt))])

    # Test open_selected_folder
    opened = []
    if hasattr(os, 'startfile'):
        monkeypatch.setattr(os, 'startfile', lambda p: opened.append(p))
    paths_panel.entry_paths.tag_add('sel', '1.0', '1.end')
    paths_panel.open_selected_folder()
    if hasattr(os, 'startfile'):
        assert len(opened) == 1

    # Test pre-flight validation warning
    missing = tmp_path / 'MissingSourceFolder'
    paths_panel.entry_paths.insert(tk.END, f'\n{missing} -> {tgt}\n')
    paths_panel.run_target_health_check()
    assert 'Missing/Invalid Source' in paths_panel.lbl_health_status.cget('text')

    # Test truncation when more than 2 missing sources
    missing2 = tmp_path / 'MissingSourceFolder2'
    missing3 = tmp_path / 'MissingSourceFolder3'
    paths_panel.entry_paths.insert(tk.END, f'\n{missing2} -> {tgt}\n{missing3} -> {tgt}\n')
    paths_panel.run_target_health_check()
    assert 'and 1 more' in paths_panel.lbl_health_status.cget('text')

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

    # Test mirror options mutual exclusion via reactive trace
    var_use.set(True)
    assert var_use.get() is True
    var_build.set(True)
    assert var_use.get() is False
    var_use.set(True)
    assert var_build.get() is False

    # Test disabling options frame
    panel.set_enabled(False)
    assert str(panel.cb_report.cget('state')) == 'disabled'
    assert str(panel.button_sync_now.cget('state')) == 'disabled'

    panel.set_enabled(True)
    assert str(panel.cb_report.cget('state')) == 'normal'
    assert str(panel.button_sync_now.cget('state')) == 'normal'

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


def test_log_panel_export_and_open_folder(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from tkinter import filedialog, messagebox

    from gui.components.log_panel import LogPanel

    log_panel = LogPanel(root)
    log_panel.text_logger.insert('exported log test line', 'INFO')

    # Test export_log
    export_file = tmp_path / 'exported_log.txt'
    monkeypatch.setattr(filedialog, 'asksaveasfilename', lambda **kwargs: str(export_file))
    monkeypatch.setattr(messagebox, 'showinfo', lambda *args: None)
    log_panel.export_log()

    assert export_file.is_file()
    assert 'exported log test line' in export_file.read_text(encoding='utf-8')

    # Test open_log_folder
    opened_paths = []
    if hasattr(os, 'startfile'):
        monkeypatch.setattr(os, 'startfile', lambda p: opened_paths.append(p))
    log_panel.open_log_folder()
    if hasattr(os, 'startfile'):
        assert len(opened_paths) == 1

    root.destroy()


def test_log_panel_severity_counters():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.log_panel import LogPanel

    log_panel = LogPanel(root)
    assert 'Info: 0' in log_panel.lbl_stat_info.cget('text')
    assert 'Warnings: 0' in log_panel.lbl_stat_warning.cget('text')
    assert 'Errors: 0' in log_panel.lbl_stat_error.cget('text')

    log_panel.text_logger.insert('Regular info message', 'INFO')
    log_panel.text_logger.insert('First warning message', 'WARNING')
    log_panel.text_logger.insert('First error message', 'ERROR')

    assert 'Info: 1' in log_panel.lbl_stat_info.cget('text')
    assert 'Warnings: 1' in log_panel.lbl_stat_warning.cget('text')
    assert 'Errors: 1' in log_panel.lbl_stat_error.cget('text')

    # Test clear_log resets counts
    log_panel.clear_log()
    assert 'Info: 0' in log_panel.lbl_stat_info.cget('text')
    assert 'Warnings: 0' in log_panel.lbl_stat_warning.cget('text')
    assert 'Errors: 0' in log_panel.lbl_stat_error.cget('text')

    root.destroy()


def test_log_smart_autoscroll_position():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.log_panel import LogPanel

    log_panel = LogPanel(root)
    for i in range(100):
        log_panel.text_logger.insert(f'Log trace row {i}', 'INFO')

    log_panel.text_logger.yview(tk.END)
    assert log_panel.text_logger.yview()[1] >= 0.95

    log_panel.text_logger.yview_moveto(0.0)
    assert log_panel.text_logger.yview()[1] < 0.95

    root.destroy()


def test_gui_log_queue_watchdog_batching_and_autoscroll(monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    import logging

    from gui.gui import Gui
    from utils.logger import logger

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    orig_watchdog = Gui.log_queue_watchdog
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()

    # Pre-populate log with lines to establish scroll height
    for i in range(100):
        gui.text_logger.insert(f'Existing row {i}', 'INFO')

    # Case 1: was at bottom, auto-scroll is True -> scrolls to bottom
    gui.text_logger.yview(tk.END)
    assert gui.text_logger.yview()[1] >= 0.95
    gui.toggle_auto_scroll.set(True)

    rec = logging.LogRecord('test', logging.INFO, '', 0, 'New incoming log record', (), None)
    logger.log_queue.put(rec)

    after_called = []
    monkeypatch.setattr(gui.root, 'after', lambda ms, cb: after_called.append((ms, cb)))

    orig_watchdog(gui)
    assert len(after_called) == 1
    assert gui.text_logger.yview()[1] >= 0.95

    # Case 2: was scrolled up to top (0.0) -> does NOT scroll to bottom
    gui.text_logger.yview_moveto(0.0)
    assert gui.text_logger.yview()[1] < 0.95

    rec2 = logging.LogRecord('test', logging.INFO, '', 0, 'Another incoming log while reading history', (), None)
    logger.log_queue.put(rec2)

    orig_watchdog(gui)
    assert gui.text_logger.yview()[1] < 0.95

    gui.root.destroy()


def test_gui_initialization_with_light_theme(monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()
    assert gui.current_theme == 'native'
    # Test theme toggle
    gui.button_action_toggle_theme()
    assert gui.current_theme == 'sv_ttk'
    gui.button_action_toggle_theme()
    assert gui.current_theme == 'native'

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
    assert str(p_panel.btn_manage_paths.cget('state')) == 'disabled'
    p_panel.set_enabled(True)
    assert str(p_panel.btn_manage_paths.cget('state')) == 'normal'

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


def test_telemetry_bar_states_and_callbacks():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.telemetry_bar import TelemetryBar

    bar = TelemetryBar(root)

    assert bar.lbl_status.cget('text') == 'Ready'

    # 1. Indeterminate mode
    bar.set_indeterminate('Scanning files...')
    assert bar.lbl_status.cget('text') == 'Scanning files...'
    assert str(bar.progress.cget('mode')) == 'indeterminate'

    # 2. Determinate mode
    bar.set_determinate(
        action='copy',
        current=5,
        total=10,
        bytes_transferred=1024,
        current_file='D:\\long\\nested\\folder\\path\\to\\my_sample_backup_file.txt',
        speed='50.0 MB/s',
    )
    assert bar.progress['value'] == 50.0
    assert 'Copy: 5 of 10 (50.0%)' in bar.lbl_status.cget('text')
    assert '50.0 MB/s' in bar.lbl_status.cget('text')
    assert 'my_sample_backup_file.txt' in bar.lbl_details.cget('text')

    # 3. Reset
    bar.reset('Ready')
    assert bar.lbl_status.cget('text') == 'Ready'
    assert bar.progress['value'] == 0

    root.destroy()


def test_log_panel_search_and_copy():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.log_panel import LogPanel

    log_panel = LogPanel(root)
    log_panel.text_logger.insert('Error 404 file not found\n', 'ERROR')
    log_panel.text_logger.insert('Info synchronization finished successfully\n', 'INFO')
    log_panel.text_logger.insert('Warning slow network share access\n', 'WARNING')

    # Test search query matching
    log_panel.search_var.set('network')
    assert len(log_panel._search_matches) == 1
    assert '1 of 1 match' in log_panel.search_count_var.get()

    # Test next / prev navigation
    log_panel.search_var.set('file')
    assert len(log_panel._search_matches) >= 1
    log_panel._next_match()
    log_panel._prev_match()

    # Test clear search
    log_panel._clear_search()
    assert log_panel.search_var.get() == ''
    assert len(log_panel._search_matches) == 0

    # Test copy log
    log_panel.copy_log()

    root.destroy()


def test_health_check_probes(tmp_path):
    from gui.health_check import TargetHealth, probe_single_target

    valid_dir = str(tmp_path / 'backup_target')
    os.makedirs(valid_dir, exist_ok=True)

    # Valid local target
    health_ok = probe_single_target(valid_dir)
    assert isinstance(health_ok, TargetHealth)
    assert health_ok.is_online is True
    assert health_ok.free_bytes >= 0
    assert health_ok.free_str != 'N/A'

    # Invalid / missing target
    invalid_dir = str(tmp_path / 'does_not_exist_anywhere')
    health_bad = probe_single_target(invalid_dir)
    assert health_bad.is_online is False
    assert health_bad.free_bytes == 0


def test_reports_window_listing_and_cleanup(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.reports_window import ReportsWindow
    from utils.logger import logger

    # Point logger.log_dir to temporary directory
    monkeypatch.setattr(logger, 'log_dir', str(tmp_path))

    # Create dummy reports
    rep1 = tmp_path / 'compare_report_2026-10-15_10-00-00.xlsx'
    rep2 = tmp_path / 'compare_report_2026-09-01_08-30-00.xlsx'  # Old report (> 30 days)
    rep1.write_text('dummy1')
    rep2.write_text('dummy2')

    # Fake os.path.getmtime for old report
    old_time = (datetime.datetime.now() - datetime.timedelta(days=45)).timestamp()
    os.utime(str(rep2), (old_time, old_time))

    win = ReportsWindow(root)
    items = win.tree.get_children('')
    assert len(items) == 2

    # Clean reports older than 30 days
    monkeypatch.setattr('tkinter.messagebox.askyesno', lambda *args, **kwargs: True)
    win.btn_clean.invoke()

    assert os.path.exists(str(rep1))
    assert not os.path.exists(str(rep2))

    win.window.destroy()
    root.destroy()


def test_confirmation_popup_file_type_badges():
    from gui.confirmation_popup import get_file_type_badge

    icon, name = get_file_type_badge('D:\\test\\photo.jpg')
    assert icon == '🖼️'
    assert 'Image' in name

    icon, name = get_file_type_badge('D:\\test\\script.py')
    assert icon == '💻'
    assert 'Code' in name

    icon, name = get_file_type_badge('D:\\test\\data.pdf')
    assert icon == '📄'
    assert 'Document' in name

    icon, name = get_file_type_badge('D:\\test\\archive.zip')
    assert icon == '📦'
    assert 'Archive' in name

    icon, name = get_file_type_badge('D:\\test\\movie.mp4')
    assert icon == '🎬'
    assert 'Media' in name

    icon, name = get_file_type_badge('')
    assert icon == '📄'


def test_text_logger_insert_batch_and_o1_line_check():
    """Verify that TextLogger.insert_batch efficiently inserts multiple records with O(1) line checks."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.enums import TkinterCfgState
    from gui.widgets import TextLogger

    logger_widget = TextLogger(root, state=TkinterCfgState.DISABLED.value, height=10, width=50)
    logger_widget.set_log_levels(['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    logger_widget.limit_lines = 50

    # Insert batch of 60 records
    records = [(f'Batch message {i}', 'INFO' if i % 2 == 0 else 'WARNING') for i in range(60)]
    logger_widget.insert_batch(records)

    assert len(logger_widget.lines) <= 60
    assert logger_widget.level_counts['INFO'] == 30
    assert logger_widget.level_counts['WARNING'] == 30

    # Insert another batch exceeding limit to trigger rewrite via O(1) check
    overflow_records = [(f'Overflow {i}', 'ERROR') for i in range(100)]
    logger_widget.insert_batch(overflow_records)

    assert len(logger_widget.lines) <= 50  # Pruned to limit_lines
    assert logger_widget.level_counts['ERROR'] > 0

    root.destroy()


def test_directory_pairs_modal_and_syntax_highlighting(tmp_path):
    """Verify EntryPaths syntax tags and DirectoryPairsModal workflow."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.directory_pairs_modal import DirectoryPairsModal
    from gui.widgets import DirectoryPair, EntryPaths

    src_dir = tmp_path / 'source'
    src_dir.mkdir()
    tgt_dir = tmp_path / 'target'
    tgt_dir.mkdir()

    ep = EntryPaths(root)
    ep.set([DirectoryPair(source=str(src_dir), target=str(tgt_dir))])

    # Check syntax highlighting tags
    tags = ep.tag_names()
    assert 'pair_arrow' in tags
    assert 'pair_source' in tags
    assert 'pair_target' in tags

    # Test modal
    changed_flag = []
    modal = DirectoryPairsModal(root, ep, on_changed=lambda: changed_flag.append(True))
    assert len(modal._pairs) == 1
    assert modal.tree.get_children()

    # Add a second pair
    src_dir2 = tmp_path / 'source2'
    src_dir2.mkdir()
    tgt_dir2 = tmp_path / 'target2'
    tgt_dir2.mkdir()
    modal._pairs.append((str(src_dir2), str(tgt_dir2)))
    modal._populate_table()
    assert len(modal.tree.get_children()) == 2

    modal._apply_and_close()
    assert len(ep.get()) == 2
    assert changed_flag == [True]

    root.destroy()


def test_exclusions_modal_and_chips_workflow():
    """Verify ExclusionsModal pattern management, live tester sandbox, and chip updates."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.exclusions_modal import ExclusionsModal
    from gui.components.paths_panel import PathsPanel
    from gui.widgets import EntryExclusions

    excl = EntryExclusions(root)
    excl.set(['Thumbs.db', '*.tmp', '.git'])

    # Test modal
    changed_flag = []
    modal = ExclusionsModal(root, excl, on_changed=lambda: changed_flag.append(True))
    assert len(modal._patterns) == 3
    assert len(modal.tree.get_children()) == 3

    # Test pattern testing sandbox
    modal.test_path_var.set('photos/vacation/Thumbs.db')
    assert 'Ignored' in modal.lbl_test_result.cget('text')
    assert 'Thumbs.db' in modal.lbl_test_result.cget('text')

    modal.test_path_var.set('photos/vacation/family.jpg')
    assert 'Included' in modal.lbl_test_result.cget('text')

    # Add a new pattern via modal
    modal.new_pattern_var.set('*.bak')
    modal._handle_add_pattern()
    assert '*.bak' in modal._patterns

    # Apply changes
    modal._apply_and_close()
    assert '*.bak' in excl.get()
    assert changed_flag == [True]

    # Test PathsPanel text exclusions rendering
    panel = PathsPanel(root, entry_exclusions=excl)
    assert panel.lbl_excl_count.cget('text') == f'{len(excl.get())} patterns'
    assert panel.entry_exclusions.get() == excl.get()

    # Test removing a single exclusion
    panel._remove_single_exclusion('*.bak')
    assert '*.bak' not in excl.get()

    root.destroy()


def test_actions_panel_rebuild_mirror_confirmation(monkeypatch):
    """Test that toggling Rebuild local mirror database prompts for confirmation."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.actions_panel import ActionsPanel
    from gui.widgets import DefaultActions

    rebuild_confirmed = []
    var_build = tk.BooleanVar(master=root, value=False)
    var_use = tk.BooleanVar(master=root, value=True)

    panel = ActionsPanel(
        root,
        checkbox_default_actions=DefaultActions(),
        checkbox_var_save_report=tk.BooleanVar(master=root),
        checkbox_var_build_mirror=var_build,
        checkbox_var_use_mirror=var_use,
        checkbox_var_metadata_comparison=tk.BooleanVar(master=root),
        checkbox_var_confirm_sync=tk.BooleanVar(master=root),
        on_reset_config=lambda: None,
        on_save_config=lambda: None,
        on_quick_compare=lambda: None,
        on_open_report=lambda: None,
        on_sync_now=lambda: None,
        on_schedule_sync=lambda: None,
        on_rebuild_confirmation=lambda val: rebuild_confirmed.append(val),
    )
    panel.pack()
    root.update_idletasks()

    # 1. User clicks rebuild checkbutton but CANCELS confirmation
    monkeypatch.setattr('gui.components.actions_panel.messagebox.askyesno', lambda *args, **kwargs: False)
    panel.cb_rebuild.invoke()
    root.update_idletasks()

    assert var_build.get() is False
    assert var_use.get() is True
    assert rebuild_confirmed[-1] is False

    # 2. User clicks rebuild checkbutton and ACCEPTS confirmation
    monkeypatch.setattr('gui.components.actions_panel.messagebox.askyesno', lambda *args, **kwargs: True)
    panel.cb_rebuild.invoke()
    root.update_idletasks()

    assert var_build.get() is True
    assert var_use.get() is False
    assert rebuild_confirmed[-1] is True

    # 3. User unchecks rebuild checkbutton (no popup required)
    panel.cb_rebuild.invoke()
    root.update_idletasks()
    assert var_build.get() is False
    assert rebuild_confirmed[-1] is False

    root.destroy()


def test_gui_call_backend_thread_rebuild_prompt(tmp_path, monkeypatch):
    """Test that Gui prompts before resetting DB if build_mirror was not pre-confirmed."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    import datetime

    from core.backend import DirectoryPair
    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    src = tmp_path / 'src'
    tgt = tmp_path / 'tgt'
    src.mkdir()
    tgt.mkdir()

    gui = Gui()
    gui.entry_paths.set([DirectoryPair(source=str(src), target=str(tgt))])
    gui.checkbox_var_build_mirror.set(True)
    gui._build_mirror_confirmed = False

    # 1. User clicks No -> execution aborted
    monkeypatch.setattr('gui.gui.messagebox.askyesno', lambda *args, **kwargs: False)
    gui.call_backend_thread(also_sync=False, timestamp=datetime.datetime.now())

    assert gui.checkbox_var_build_mirror.get() is False
    assert gui.checkbox_var_use_mirror.get() is True
    assert gui.backend_thread_holder is None

    # 2. User clicks Yes -> execution proceeds
    gui.checkbox_var_build_mirror.set(True)
    gui._build_mirror_confirmed = False
    monkeypatch.setattr('gui.gui.messagebox.askyesno', lambda *args, **kwargs: True)

    # Prevent thread execution
    monkeypatch.setattr('gui.worker_thread.WorkerThread.start', lambda self: None)
    gui.call_backend_thread(also_sync=False, timestamp=datetime.datetime.now())

    assert gui._build_mirror_confirmed is True
    assert gui.backend_thread_holder is not None

    gui.root.destroy()


def test_gui_backend_thread_rebuild_mirror_cleanup(tmp_path, monkeypatch):
    """Test that after a rebuild mirror execution, flags are safely reset in finally block."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from core.backend import CompareMethod, DirectoryPair
    from gui.gui import Gui

    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()
    src = tmp_path / 'src'
    tgt = tmp_path / 'tgt'
    src.mkdir()
    tgt.mkdir()

    gui.checkbox_var_build_mirror.set(True)
    gui._build_mirror_confirmed = True

    # Run backend_thread synchronously with mock CompareDirs
    class DummyCompare:
        def __init__(self, *args, **kwargs):
            self.files_to_copy = []
            self.files_to_move = []
            self.files_to_delete = []

    monkeypatch.setattr('gui.gui.CompareDirs', DummyCompare)

    gui.backend_thread(
        also_sync=False,
        dirs=[DirectoryPair(source=str(src), target=str(tgt))],
        exclusions=[],
        comparison_method=CompareMethod.METADATA,
        save_report=False,
        use_mirror=False,
        build_mirror=True,
        confirm_sync=False,
        default_actions=[],
    )

    # Process pending root.after calls
    gui.root.update()

    assert gui.checkbox_var_build_mirror.get() is False
    assert gui.checkbox_var_use_mirror.get() is True
    assert gui._build_mirror_confirmed is False

    gui.root.destroy()


def test_smooth_drag_interceptor_lifecycle():
    from gui.window_drag import install_smooth_drag_interceptor, uninstall_smooth_drag_interceptor

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    # In test/agent mode or headless, it gracefully returns False without error
    res = install_smooth_drag_interceptor(root)
    assert isinstance(res, bool)
    uninstall_smooth_drag_interceptor(root)
    root.destroy()


def test_paths_panel_text_mode_lifecycle(tmp_path):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.paths_panel import PathsPanel

    panel = PathsPanel(root)

    # Empty state count
    assert '0 configured' in panel.lbl_pair_count.cget('text')

    # Add pairs
    src1 = tmp_path / 'Src1'
    tgt1 = tmp_path / 'Tgt1'
    src1.mkdir()
    tgt1.mkdir()

    panel.entry_paths.set([(str(src1), str(tgt1))])
    panel.refresh_cards()
    assert '1 configured' in panel.lbl_pair_count.cget('text')

    # Drag and drop folder addition
    src2 = tmp_path / 'Src2'
    tgt2 = tmp_path / 'Tgt2'
    src2.mkdir()
    tgt2.mkdir()
    panel.add_dropped_paths([str(src2), str(tgt2)])
    assert len(panel.entry_paths.get()) == 2
    assert '2 configured' in panel.lbl_pair_count.cget('text')

    # Remove single pair
    panel._remove_single_pair(str(src2), str(tgt2))
    assert len(panel.entry_paths.get()) == 1
    assert '1 configured' in panel.lbl_pair_count.cget('text')

    root.destroy()
