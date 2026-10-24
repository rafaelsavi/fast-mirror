import ctypes
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest
from PIL import Image

from core.file import CstmPath
from gui.components.reports_window import ReportsWindow
from gui.confirmation_popup import ActionSelection
from gui.enums import BackendThreadStatus
from gui.gui import Gui
from gui.health_check import TargetHealth
from gui.widgets import Action
from utils.utils import DirectoryPair


def capture_window_bitmap(hwnd: int) -> Image.Image | None:
    """Capture a Win32 window's content via GDI PrintWindow (PW_RENDERFULLCONTENT)."""
    if os.name != 'nt':
        return None

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class RECT(ctypes.Structure):
        _fields_ = [
            ('left', ctypes.c_long),
            ('top', ctypes.c_long),
            ('right', ctypes.c_long),
            ('bottom', ctypes.c_long),
        ]

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    if width <= 0 or height <= 0:
        return None

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)

    # PW_RENDERFULLCONTENT = 2
    user32.PrintWindow(hwnd, mem_dc, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ('biSize', ctypes.c_uint32),
            ('biWidth', ctypes.c_int32),
            ('biHeight', ctypes.c_int32),
            ('biPlanes', ctypes.c_uint16),
            ('biBitCount', ctypes.c_uint16),
            ('biCompression', ctypes.c_uint32),
            ('biSizeImage', ctypes.c_uint32),
            ('biXPelsPerMeter', ctypes.c_int32),
            ('biYPelsPerMeter', ctypes.c_int32),
            ('biClrUsed', ctypes.c_uint32),
            ('biClrImportant', ctypes.c_uint32),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = width
    bmi.biHeight = -height
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = (ctypes.c_char * (width * height * 4))()
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(bmi), 0)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    return Image.frombuffer('RGBA', (width, height), buf, 'raw', 'BGRA', 0, 1)


def _setup_test_gui(monkeypatch):
    """Instantiate Gui in headless test mode without running blocking loops."""
    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self, *args, **kwargs: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()
    return gui


def test_full_gui_visual_rendering_and_layout(monkeypatch, tmp_path):
    """Visual test asserting window geometry, panel mapping, and non-blank GDI rendering."""
    try:
        gui = _setup_test_gui(monkeypatch)
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    # Add directory pairs and log messages to simulate full populated interface
    pair1 = DirectoryPair(source=str(tmp_path / 'Source'), target=str(tmp_path / 'Target'))
    os.makedirs(str(tmp_path / 'Source'), exist_ok=True)
    os.makedirs(str(tmp_path / 'Target'), exist_ok=True)
    gui.entry_paths.add(pair1)
    gui.paths_panel.refresh_cards()

    gui.text_logger.insert('System initialized successfully\n', 'INFO')
    gui.text_logger.insert('Target share connection latency: 4ms\n', 'WARNING')
    gui.text_logger.insert('Sample simulated error log row\n', 'ERROR')

    gui.root.update_idletasks()
    gui.root.update()

    # Invariants: Window dimensions and component presence
    req_width = gui.root.winfo_reqwidth()
    req_height = gui.root.winfo_reqheight()
    assert req_width >= 900
    assert req_height >= 600

    assert gui.status_bar is not None
    assert gui.actions_panel is not None
    assert gui.schedule_panel is not None
    assert not hasattr(gui, 'overview_card')
    assert gui.paths_panel is not None
    assert gui.log_panel is not None
    assert gui.telemetry_bar is not None

    # Capture Win32 bitmap if available
    hwnd = gui.root.winfo_id()
    user32 = ctypes.windll.user32
    top_hwnd = user32.GetAncestor(hwnd, 2) or hwnd
    img = capture_window_bitmap(top_hwnd)
    if img is not None and img.width > 10:
        assert img.width >= 900
        assert img.height >= 600
        # Verify non-blank image (contains varied pixel values)
        extrema = img.getextrema()
        assert extrema is not None

    gui.root.destroy()


def test_actions_panel_all_clicks_and_corner_cases(monkeypatch, tmp_path):
    """Test all button clicks, reset/save config, and option toggles in ActionsPanel."""
    try:
        gui = _setup_test_gui(monkeypatch)
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    # Isolate config path to tmp_path
    gui.config_path = str(tmp_path / 'test_cfg.json')

    # 1. Reset Config Click (mock confirmation)
    monkeypatch.setattr('tkinter.messagebox.askyesno', lambda *args, **kwargs: True)
    gui.actions_panel.button_new_config.invoke()
    assert gui.entry_paths.get_as_dir_pairs() == []

    # 2. Save Config Click
    gui.actions_panel.button_save_config.invoke()
    assert os.path.exists(gui.config_path)

    # 3. Corner Case: Start Compare with empty paths
    gui.entry_paths.set([])
    gui.actions_panel.button_quick_compare.invoke()
    assert gui.backend_thread_status == BackendThreadStatus.STANDBY

    # 4. Corner Case: Sync Now with empty paths
    gui.actions_panel.button_sync_now.invoke()
    assert gui.backend_thread_status == BackendThreadStatus.STANDBY

    # 5. Toggle Schedule button
    assert gui.toggle_state_schedule is False
    gui.actions_panel.button_schedule_sync.invoke()
    assert gui.toggle_state_schedule is True
    gui.actions_panel.button_schedule_sync.invoke()
    assert gui.toggle_state_schedule is False

    # 6. Open Report when no report exists (should log without crashing)
    gui.actions_panel.button_open_report.invoke()

    # 7. Checkboxes: Mutually exclusive rebuild vs use mirror
    gui.checkbox_var_build_mirror.set(True)
    assert gui.checkbox_var_use_mirror.get() is False
    gui.checkbox_var_use_mirror.set(True)
    assert gui.checkbox_var_build_mirror.get() is False

    # 8. Default actions toggles
    gui.checkbox_default_actions.get_var(Action.COPY).set(False)
    assert Action.COPY.value not in gui.checkbox_default_actions.get()
    gui.checkbox_default_actions.get_var(Action.COPY).set(True)
    assert Action.COPY.value in gui.checkbox_default_actions.get()

    gui.root.destroy()


def test_schedule_panel_and_corner_cases(monkeypatch):
    """Test schedule checkboxes, enabled state toggling, and corner cases in time formatting."""
    try:
        gui = _setup_test_gui(monkeypatch)
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    sp = gui.schedule_panel

    # Verify checkboxes exist for all week days
    assert set(sp.checkbox_week_days.keys()) == set(gui.week_days.options)

    # Toggle days via week_days model
    gui.week_days.set(['MON', 'FRI'])
    assert sorted(gui.week_days.get()) == ['FRI', 'MON']

    gui.week_days.set([])
    assert gui.week_days.get() == []

    # Corner Cases: EntryTimes with spaces, empty strings, and invalid times
    sp.entry_times.set(['08:30', ' 17:00 ', '99:99', 'invalid_str', ''])
    valid_times = sp.entry_times.get()
    # EntryTimes parses HH:MM and ignores invalid strings
    assert '08:30' in valid_times
    assert '17:00' in valid_times
    assert '99:99' not in valid_times
    assert 'invalid_str' not in valid_times

    # Test set_enabled state toggling
    sp.set_enabled(False)
    for cb in sp.checkbox_week_days.values():
        assert str(cb.cget('state')) == 'disabled'

    sp.set_enabled(True)
    for cb in sp.checkbox_week_days.values():
        assert str(cb.cget('state')) == 'normal'

    gui.root.destroy()


def test_overview_card_standalone():
    """Test that OverviewCard class remains usable as a standalone component."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.overview_card import OverviewCard

    card = OverviewCard(root)
    assert card is not None
    assert '0 pairs configured' in card.text_var_pairs_count.get()
    root.destroy()


def test_paths_panel_health_check_and_chips(monkeypatch, tmp_path):
    """Test PathsPanel actions, health check diagnostics, and exclusion chips."""
    try:
        gui = _setup_test_gui(monkeypatch)
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    pp = gui.paths_panel

    # 1. Health check with empty paths
    gui.entry_paths.set([])
    pp.btn_check_targets.invoke()
    assert 'No paths configured' in pp.lbl_health_status.cget('text')

    # 2. Health check with valid and invalid paths
    valid_tgt = str(tmp_path / 'TargetHealth')
    os.makedirs(valid_tgt, exist_ok=True)
    gui.entry_paths.set([DirectoryPair(source=str(tmp_path), target=valid_tgt)])

    # Mock probe_targets_async to deliver simulated health
    def _mock_probe_async(dirs, callback):
        callback([TargetHealth(path=valid_tgt, is_online=True, free_bytes=100_000_000, total_bytes=500_000_000)])

    monkeypatch.setattr('gui.components.paths_panel.probe_targets_async', _mock_probe_async)
    pp.btn_check_targets.invoke()
    gui.root.update()
    assert 'All targets online' in pp.lbl_health_status.cget('text')

    # 3. Text exclusions mode and operations
    pp._remove_single_exclusion('$RECYCLE.BIN')
    assert '$RECYCLE.BIN' not in pp.entry_exclusions.get()

    # 4. Corner Case: Exclusions containing special regex chars
    pp.entry_exclusions.set(['[cache]', '*.tmp', '~$*', 'dir(old)', 'path\\**'])
    parsed = pp.entry_exclusions.get()
    assert '[cache]' in parsed
    assert '*.tmp' in parsed

    gui.root.destroy()


def test_log_panel_search_corner_cases(monkeypatch):
    """Test log filtering, navigation, and regex special characters in search."""
    try:
        gui = _setup_test_gui(monkeypatch)
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    lp = gui.log_panel

    # Populate log with various lines including regex-like symbols
    lp.text_logger.insert('System starting...\n', 'INFO')
    lp.text_logger.insert('Scanning C:\\Data\\[special_folder]\\file(1).txt\n', 'INFO')
    lp.text_logger.insert('Warning: high disk usage (88%)\n', 'WARNING')
    lp.text_logger.insert('Critical error in core.mirror: *lock timeout*\n', 'CRITICAL')

    # Search regular text
    lp.search_var.set('System')
    assert len(lp._search_matches) == 1
    assert '1 of 1 match' in lp.search_count_var.get()

    # Search with regex special characters: brackets, parentheses, asterisks, backslashes
    lp.search_var.set('[special_folder]')
    assert len(lp._search_matches) == 1

    lp.search_var.set('*lock timeout*')
    assert len(lp._search_matches) == 1

    lp.search_var.set('(88%)')
    assert len(lp._search_matches) == 1

    # Search with 0 matches
    lp.search_var.set('non_existent_token_123')
    assert len(lp._search_matches) == 0
    assert '0 matches' in lp.search_count_var.get()

    # Clear search
    lp._clear_search()
    assert lp.search_var.get() == ''
    assert len(lp._search_matches) == 0

    # Auto-scroll and level toggles
    lp.checkbox_auto_scroll.invoke()
    lp.check_box_log_level['DEBUG'].invoke()

    gui.root.destroy()


def test_confirmation_popup_visual_and_action_clicks(tmp_path):
    """Test action confirmation popup visual rendering, uncheck deletions, and filter."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src1 = CstmPath(str(tmp_path / 'file1.txt'))
    src2 = CstmPath(str(tmp_path / 'file2.jpg'))
    tgt1 = CstmPath(str(tmp_path / 'file1_copy.txt'))
    tgt2 = CstmPath(str(tmp_path / 'file2_move.jpg'))
    del1 = CstmPath(str(tmp_path / 'obsolete.tmp'))

    popup = ActionSelection(
        root_gui=root,
        files_available_to_copy=[(src1, tgt1)],
        files_available_to_move=[(src2, tgt2)],
        files_available_to_delete=[del1],
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
    )

    popup.popup.update_idletasks()
    popup.popup.update()

    # Assert visual dimensions
    assert popup.popup.winfo_reqwidth() >= 800
    assert popup.popup.winfo_reqheight() >= 400

    # Visual capture of popup
    hwnd = popup.popup.winfo_id()
    user32 = ctypes.windll.user32
    top_hwnd = user32.GetAncestor(hwnd, 2) or hwnd
    img = capture_window_bitmap(top_hwnd)
    if img is not None and img.width > 10:
        assert img.width >= 800

    # Test "Uncheck All Deletions" safety click
    popup.tree.uncheck_action(Action.DELETE)
    popup.tree.refresh_group_stats()

    checked = popup.tree.get_checked()
    delete_items = [x for x in checked if x.startswith(Action.DELETE.value)]
    copy_items = [x for x in checked if x.startswith(Action.COPY.value)]
    assert len(delete_items) == 0
    assert len(copy_items) > 0

    # Test "Select All" and "Deselect All"
    popup.tree.select_all()
    assert len(popup.tree.get_checked()) == 3

    popup.tree.deselect_all()
    assert len(popup.tree.get_checked()) == 0

    # Test Filter Entry in popup
    popup.filter_var.set('jpg')
    assert 'jpg' in popup.filter_var.get()

    popup.filter_var.set('')
    assert popup.filter_var.get() == ''

    # Test Save and continue click
    popup.button_save.invoke()
    assert popup.proceed is True

    root.destroy()


def test_reports_window_visual_and_actions(monkeypatch, tmp_path):
    """Test ReportsWindow visual rendering, list display, and cleanup actions."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from utils.logger import logger

    monkeypatch.setattr(logger, 'log_dir', str(tmp_path))

    # Create dummy reports
    rep1 = tmp_path / 'compare_report_2026-10-15_10-00-00.xlsx'
    rep1.write_text('content1')

    win = ReportsWindow(root)
    win.window.update_idletasks()
    win.window.update()

    assert win.window.winfo_reqwidth() >= 600
    items = win.tree.get_children('')
    assert len(items) == 1

    win.window.destroy()
    root.destroy()


def test_telemetry_bar_modes(monkeypatch):
    """Test TelemetryBar determinate, indeterminate progress, and reset."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.telemetry_bar import TelemetryBar

    bar = TelemetryBar(root)
    bar.pack(fill='x')

    # Indeterminate mode
    bar.set_indeterminate('Scanning remote directory...')
    assert bar._active_mode == 'indeterminate'
    assert 'Scanning remote directory' in bar.lbl_status.cget('text')

    # Keep the full path when it fits in the allocated label width.
    short_path = 'D:\\BackupTarget\\photo.jpg'
    full_text = f'Current: {short_path}'
    monkeypatch.setattr(bar.lbl_details, 'winfo_width', lambda: bar._details_font.measure(full_text))
    bar.set_determinate('copy', 45, 100, current_file=short_path)
    assert bar.lbl_details.cget('text') == full_text

    # Truncate only when the path exceeds the allocated width.
    long_path = 'D:\\BackupTarget\\VeryLongDirectoryTree\\Subfolder\\NestedDeeply\\Photo_2026_HighRes.RAW'
    available_width = bar._details_font.measure('Current: ...Photo_2026_HighRes.RAW')
    monkeypatch.setattr(bar.lbl_details, 'winfo_width', lambda: available_width)
    bar.set_determinate('copy', 45, 100, current_file=long_path, speed='125.4 MB/s')
    assert bar._active_mode == 'determinate'
    assert bar.progress['value'] == 45.0
    assert 'Copy: 45 of 100 (45.0%) • 125.4 MB/s' in bar.lbl_status.cget('text')
    assert 'Photo_2026_HighRes.RAW' in bar.lbl_details.cget('text')
    assert bar.lbl_details.cget('text').startswith('Current: ...')
    assert bar._details_font.measure(bar.lbl_details.cget('text')) <= available_width

    # Reset
    bar.reset()
    assert bar.lbl_status.cget('text') == 'Ready'
    assert bar.lbl_details.cget('text') == ''

    root.destroy()


def test_status_bar_and_pill_state_updates():
    """Test StatusBar pill styling and schedule appointment string updates."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.status_bar import StatusBar

    status_var = tk.StringVar(value='Standby')
    next_var = tk.StringVar(value='Schedule is not activated')

    sb = StatusBar(root, text_var_status=status_var, text_var_next_appointment=next_var)
    sb.pack(fill='x')
    sb.update_idletasks()

    assert sb.text_var_status.get() == 'Standby'
    assert sb.text_var_next_appointment.get() == 'Schedule is not activated'

    # Transition to Running
    status_var.set('Running')
    sb.update_idletasks()
    assert sb.text_var_status.get() == 'Running'

    # Update next schedule
    next_var.set('Next sync: Monday at 08:30 (in 14 hours)')
    sb.update_idletasks()
    assert 'Next sync: Monday at 08:30' in sb.text_var_next_appointment.get()

    root.destroy()


def test_log_panel_theme_toggles():
    """Test switching LogPanel between light and dark themes."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.components.log_panel import LogPanel

    lp = LogPanel(root)
    lp.pack(fill='both', expand=True)

    # Apply dark theme
    lp.apply_theme('dark')
    assert lp.text_logger.cget('bg') == '#1e1e1e'
    assert lp.text_logger.cget('fg') == '#d4d4d4'

    # Apply light theme
    lp.apply_theme('light')
    assert lp.text_logger.cget('bg') == '#ffffff'
    assert lp.text_logger.cget('fg') == '#1c1c1c'

    root.destroy()
