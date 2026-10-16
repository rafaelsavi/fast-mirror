import json
import os
import shutil
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.backend import (
    ActionSelection,
    CompareDirs,
    SyncDirs,
    get_dirs_from_path,
    robust_copy,
    robust_delete,
    robust_move,
    unlock_file_attributes,
)
from core.file import CstmPath, File
from core.mirror import MirrorDatabase
from gui.custom_gui import CustomCheckboxTreeView
from gui.enums import BackendThreadStatus
from gui.widgets import Action, EntryPaths, LogLevels, TextLogger
from utils.utils import DirectoryPair, format_elapsed_time, sanitize_path


def test_format_elapsed_time_under_hour():
    start = time.time() - 45
    result = format_elapsed_time(start)
    assert result == '45s'


def test_format_elapsed_time_multiple_hours():
    start = time.time() - (2 * 3600 + 15 * 60 + 30)
    result = format_elapsed_time(start)
    assert '2h' in result
    assert '15m' in result
    assert '30s' in result


def test_format_elapsed_time_over_24_hours():
    # Verify that >24 hours does not roll over to 0h
    start = time.time() - (25 * 3600 + 10 * 60 + 5)
    result = format_elapsed_time(start)
    assert '25h' in result
    assert '10m' in result
    assert '5s' in result


def test_get_dirs_from_path_exact_and_subfolder(tmp_path):
    source_dir = str(tmp_path / 'Source')
    target_dir = str(tmp_path / 'Target')
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(target_dir, exist_ok=True)

    dirs = [
        DirectoryPair(source_dir, target_dir),
    ]

    nested_file = os.path.join(source_dir, 'sub', 'file.txt')
    matched_pair = get_dirs_from_path(nested_file, dirs)
    assert matched_pair.source == source_dir
    assert matched_pair.target == target_dir


def test_get_dirs_from_path_avoids_prefix_collision(tmp_path):
    dir_a = str(tmp_path / 'Data')
    dir_b = str(tmp_path / 'Data_Extended')
    target_a = str(tmp_path / 'Backup_A')
    target_b = str(tmp_path / 'Backup_B')
    os.makedirs(dir_a, exist_ok=True)
    os.makedirs(dir_b, exist_ok=True)
    os.makedirs(target_a, exist_ok=True)
    os.makedirs(target_b, exist_ok=True)

    dirs = [
        DirectoryPair(dir_a, target_a),
        DirectoryPair(dir_b, target_b),
    ]

    test_file_in_b = os.path.join(dir_b, 'sub', 'test.txt')
    matched = get_dirs_from_path(test_file_in_b, dirs)
    assert matched.source == dir_b
    assert matched.target == target_b


def test_get_dirs_from_path_missing_raises(tmp_path):
    dirs = [DirectoryPair(str(tmp_path / 'A'), str(tmp_path / 'B'))]
    with pytest.raises(FileNotFoundError):
        get_dirs_from_path(str(tmp_path / 'NonExistent' / 'file.txt'), dirs)


def test_get_dirs_from_path_unc_paths():
    dirs = [
        DirectoryPair(r'E:\Photos', r'\\192.168.1.100\Photos'),
        DirectoryPair(r'D:\Arquivos', r'\\192.168.1.100\Backup\D'),
    ]
    path = r'\\192.168.1.100\Photos\2025\Vacation\20251007_101158 [Qatar, Tanzania].mp4'
    matched = get_dirs_from_path(path, dirs)
    assert matched.source == r'E:\Photos'
    assert matched.target == r'\\192.168.1.100\Photos'


def test_get_dirs_from_path_nested_prefers_most_specific():
    dirs = [
        DirectoryPair('D:\\', r'\\192.168.1.100\Backup\D'),
        DirectoryPair(r'D:\Photos', r'\\192.168.1.100\Photos'),
    ]
    # File in D:\Photos should match D:\Photos, not D:\
    matched_specific = get_dirs_from_path(r'D:\Photos\sub\pic.jpg', dirs)
    assert matched_specific.source == r'D:\Photos'

    # File in other D:\ folder should match D:\
    matched_root = get_dirs_from_path(r'D:\Other\file.txt', dirs)
    assert matched_root.source == 'D:\\'


def test_get_dirs_from_path_case_and_slash_variations():
    dirs = [
        DirectoryPair(r'E:\Photos', r'\\192.168.1.100\Photos'),
    ]
    # Forward slashes and lower case
    matched = get_dirs_from_path('//192.168.1.100/photos/2025/test.mp4', dirs)
    assert matched.source == r'E:\Photos'


def test_directory_pair_repr_and_equality():
    dp1 = DirectoryPair('D:\\Source', 'E:\\Target')
    dp2 = DirectoryPair('D:\\Source', 'E:\\Target')
    dp3 = DirectoryPair('D:\\Other', 'E:\\Target')

    assert dp1 == dp2
    assert dp1 != dp3
    assert hash(dp1) == hash(dp2)
    assert "source='D:\\\\Source'" in repr(dp1)


def test_config_json_entry_paths_resolution():
    """Verify that all real-world entry paths configured in config.json resolve without error."""
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../config.json'))
    if not os.path.isfile(config_path):
        pytest.skip('config.json not found')

    with open(config_path, encoding='utf-8') as f:
        config = json.load(f)

    raw_pairs = config.get('entry_paths', [])
    dirs = [DirectoryPair(source, target) for source, target in raw_pairs]

    for source, target in raw_pairs:
        # Test synthetic nested file under source
        sample_src_file = os.path.join(source, 'subfolder', 'test_sample.txt')
        matched_src = get_dirs_from_path(sample_src_file, dirs)
        assert matched_src.source == source

        # Test synthetic nested file under target (UNC share or local drive)
        sample_tgt_file = os.path.join(target, 'subfolder', 'test_sample.txt')
        matched_tgt = get_dirs_from_path(sample_tgt_file, dirs)
        assert matched_tgt.target == target


def test_cstmpath_get_from_dir_exclusions_on_windows(tmp_path):
    root = tmp_path / 'ScanRoot'
    sub1 = root / 'SubFolder'
    sub2 = root / 'IgnoredFolder'
    sub1.mkdir(parents=True)
    sub2.mkdir(parents=True)

    keep_file = sub1 / 'keep.txt'
    keep_file.write_text('keep')
    ignored_file = sub2 / 'skip.txt'
    ignored_file.write_text('skip')
    ext_ignored = sub1 / 'skip.tmp'
    ext_ignored.write_text('skip')

    exclude = ['IgnoredFolder/*', '*.tmp']
    scanned = CstmPath.get_from_dir(str(root), exclude=exclude)
    scanned_names = {p.name for p in scanned}

    assert 'keep.txt' in scanned_names
    assert 'skip.txt' not in scanned_names
    assert 'skip.tmp' not in scanned_names


def test_entry_paths_parse_line(tmp_path):
    source = tmp_path / 'ValidSource'
    target = tmp_path / 'ValidTarget'
    source.mkdir()
    target.mkdir()

    # Valid existing source and target
    line = f'{source} -> {target}'
    parsed = EntryPaths.parse_line(line)
    assert parsed is not None
    assert parsed[0] == os.path.realpath(str(source))
    assert parsed[1] == os.path.realpath(str(target))

    # New target directory where parent exists
    new_target = target / 'NewSubFolder'
    line_new = f'{source} -> {new_target}'
    parsed_new = EntryPaths.parse_line(line_new)
    assert parsed_new is not None
    assert parsed_new[1] == os.path.realpath(str(new_target))

    # Invalid line with missing arrow
    assert EntryPaths.parse_line('invalid path format') is None

    # Invalid non-existent source
    non_existent = tmp_path / 'DoesNotExist'
    assert EntryPaths.parse_line(f'{non_existent} -> {target}') is None


def test_robust_copy_success(tmp_path):
    source = tmp_path / 'source.txt'
    target = tmp_path / 'sub' / 'target.txt'
    source.write_text('backup data payload')

    robust_copy(source, target)
    assert target.is_file()
    assert target.read_text() == 'backup data payload'


def test_robust_copy_retries_transient_network_error(tmp_path, monkeypatch):
    source = tmp_path / 'source.txt'
    target = tmp_path / 'target.txt'
    source.write_text('network test')

    attempts = 0
    orig_copy2 = shutil.copy2

    def flaky_copy2(src, dst):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError(64, 'The specified network name is no longer available.')
        return orig_copy2(src, dst)

    monkeypatch.setattr(shutil, 'copy2', flaky_copy2)
    robust_copy(source, target, max_retries=3, initial_delay=0.001, backoff_factor=1.0)
    assert attempts == 3
    assert target.is_file()
    assert target.read_text() == 'network test'


def test_robust_copy_cleans_up_corrupted_partial_target_on_failure(tmp_path, monkeypatch):
    source = tmp_path / 'source.txt'
    target = tmp_path / 'partial_target.txt'
    source.write_text('full content of twenty bytes')

    def failing_copy_that_leaves_partial(src, dst):
        # Write partial file then simulate connection severance
        with open(dst, 'w') as f:
            f.write('partial')
        raise OSError(59, 'An unexpected network error occurred.')

    monkeypatch.setattr(shutil, 'copy2', failing_copy_that_leaves_partial)

    with pytest.raises(OSError, match='unexpected network error'):
        robust_copy(source, target, max_retries=2, initial_delay=0.001, backoff_factor=1.0)

    # Incomplete target file must be cleaned up to prevent corrupted backups
    assert not target.exists()


def test_robust_move_retries_and_succeeds(tmp_path, monkeypatch):
    source = tmp_path / 'move_source.txt'
    target = tmp_path / 'move_sub' / 'move_target.txt'
    source.write_text('move data')

    attempts = 0
    orig_move = shutil.move

    def flaky_move(src, dst):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError(53, 'The network path was not found.')
        return orig_move(src, dst)

    monkeypatch.setattr(shutil, 'move', flaky_move)
    robust_move(source, target, max_retries=2, initial_delay=0.001)
    assert attempts == 2
    assert target.is_file()
    assert not source.exists()


def test_robust_delete_retries_and_succeeds(tmp_path, monkeypatch):
    file_to_del = tmp_path / 'del.txt'
    file_to_del.write_text('to be deleted')

    attempts = 0
    orig_remove = os.remove

    def flaky_remove(path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(5, 'Access is denied')
        return orig_remove(path)

    monkeypatch.setattr(os, 'remove', flaky_remove)
    robust_delete(file_to_del, max_retries=2, initial_delay=0.001)
    assert attempts == 2
    assert not file_to_del.exists()


def test_unlock_file_attributes(tmp_path):
    target = tmp_path / 'locked.txt'
    target.write_text('content')
    assert unlock_file_attributes(target) is True


def test_syncdirs_execution_order(monkeypatch, tmp_path):
    from core.backend import SyncDirs

    call_order = []

    monkeypatch.setattr(SyncDirs, 'move_files', lambda self: call_order.append('move'))
    monkeypatch.setattr(SyncDirs, 'delete_files', lambda self: call_order.append('delete'))
    monkeypatch.setattr(SyncDirs, 'copy_files', lambda self: call_order.append('copy'))
    monkeypatch.setattr(SyncDirs, 'delete_empty_dirs', lambda self: call_order.append('prune'))
    monkeypatch.setattr(SyncDirs, 'print_errors', lambda self: None)

    source = tmp_path / 's'
    target = tmp_path / 't'
    source.mkdir()
    target.mkdir()
    f_src = CstmPath(source / 'a.txt', root_dir=source)
    f_tgt = CstmPath(target / 'a.txt', root_dir=target)

    SyncDirs(
        files_to_copy=[(f_src, f_tgt)],
        files_to_move=[],
        files_to_delete=[],
        mirror=None,  # type: ignore
        root_gui=None,
        dirs=[DirectoryPair(str(source), str(target))],
        confirm_sync=False,
    )

    assert call_order == ['move', 'delete', 'copy', 'prune']


def test_file_class_properties(tmp_path):
    root_s = tmp_path / 's'
    root_t = tmp_path / 't'
    root_s.mkdir()
    root_t.mkdir()

    f_s = root_s / 'file.txt'
    f_t = root_t / 'file.txt'
    f_s.write_text('content')
    shutil.copy2(f_s, f_t)

    cp_s = CstmPath(f_s, root_dir=root_s)
    cp_t = CstmPath(f_t, root_dir=root_t)

    # only source
    f_only_s = File(source=cp_s, target=None)
    assert f_only_s.only_source is True
    assert f_only_s.only_target is False
    assert f_only_s.in_both is False

    # only target
    f_only_t = File(source=None, target=cp_t)
    assert f_only_t.only_source is False
    assert f_only_t.only_target is True
    assert f_only_t.in_both is False

    # in both, same relative path
    f_both = File(source=cp_s, target=cp_t)
    assert f_both.in_both is True
    assert f_both.moved is False
    f_both.compare()
    assert f_both.same is True
    assert f_both.modified is False
    assert f_both.compare_error is False

    # moved (different rel_to_root)
    f_sub = root_t / 'sub' / 'file.txt'
    f_sub.parent.mkdir()
    f_sub.write_text('content')
    cp_sub = CstmPath(f_sub, root_dir=root_t)
    f_moved = File(source=cp_s, target=cp_sub)
    assert f_moved.in_both is True
    assert f_moved.moved is True


def test_compare_dirs_classifies_copy_move_delete(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    # 1. Unchanged file (identical content and mtime)
    unchanged_src = source / 'unchanged.txt'
    unchanged_tgt = target / 'unchanged.txt'
    unchanged_src.write_text('same')
    shutil.copy2(unchanged_src, unchanged_tgt)

    # 2. New file (source only)
    new_src = source / 'new.txt'
    new_src.write_text('new')

    # 3. Obsolete file (target only)
    obsolete_tgt = target / 'obsolete.txt'
    obsolete_tgt.write_text('obsolete')

    # 4. Modified file (exists in both, but content differs)
    mod_src = source / 'modified.txt'
    mod_tgt = target / 'modified.txt'
    mod_src.write_text('source version v2')
    mod_tgt.write_text('target version v1')
    os.utime(mod_src, (time.time() - 10, time.time() - 10))
    os.utime(mod_tgt, (time.time() - 500, time.time() - 500))

    # 5. Moved file (source is in subfolder, target has same name/content in root)
    moved_src = source / 'subfolder' / 'moved.txt'
    moved_src.parent.mkdir()
    moved_src.write_text('unique moved content')
    moved_tgt = target / 'moved.txt'
    shutil.copy2(moved_src, moved_tgt)

    mirror_db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=mirror_db_path)

    dirs = [DirectoryPair(str(source), str(target))]
    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])

    copy_sources = [str(s) for s, _ in compare.files_to_copy]
    assert str(new_src) in copy_sources
    assert str(mod_src) in copy_sources
    assert str(unchanged_src) not in copy_sources

    assert len(compare.files_to_move) == 1
    move_src, move_dst = compare.files_to_move[0]
    assert str(move_src) == str(moved_tgt)
    assert str(move_dst) == str(target / 'subfolder' / 'moved.txt')

    delete_targets = [str(t) for t in compare.files_to_delete]
    assert str(obsolete_tgt) in delete_targets
    assert str(unchanged_tgt) not in delete_targets


def test_syncdirs_end_to_end_execution(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    # Create test files
    new_src = source / 'new.txt'
    new_src.write_text('new content')

    mod_src = source / 'mod.txt'
    mod_tgt = target / 'mod.txt'
    mod_src.write_text('updated mod')
    mod_tgt.write_text('old mod')
    os.utime(mod_src, (time.time() - 10, time.time() - 10))
    os.utime(mod_tgt, (time.time() - 500, time.time() - 500))

    obs_tgt = target / 'obsolete.txt'
    obs_tgt.write_text('old obsolete')

    moved_src = source / 'sub' / 'moved.txt'
    moved_src.parent.mkdir()
    moved_src.write_text('moved file')
    moved_tgt = target / 'old_sub' / 'moved.txt'
    moved_tgt.parent.mkdir()
    shutil.copy2(moved_src, moved_tgt)

    mirror_db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=mirror_db_path)
    dirs = [DirectoryPair(str(source), str(target))]

    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])

    SyncDirs(
        files_to_copy=compare.files_to_copy,
        files_to_move=compare.files_to_move,
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        confirm_sync=False,
    )

    # Verify synchronization effects
    assert (target / 'new.txt').is_file()
    assert (target / 'new.txt').read_text() == 'new content'
    assert (target / 'mod.txt').read_text() == 'updated mod'
    assert not obs_tgt.exists()
    assert (target / 'sub' / 'moved.txt').is_file()
    assert not moved_tgt.exists()

    # Empty old directory was pruned
    assert not (target / 'old_sub').exists()
    # Roots are preserved
    assert target.is_dir()
    assert source.is_dir()


def test_delete_empty_dirs_preserves_root_directory(tmp_path):
    source = tmp_path / 'source_root'
    target = tmp_path / 'target_root'
    source.mkdir()
    target.mkdir()

    nested = target / 'level1' / 'level2'
    nested.mkdir(parents=True)

    mirror = MirrorDatabase(path=str(tmp_path / 'mirror.db'))
    dirs = [DirectoryPair(str(source), str(target))]

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )

    sync.files_deleted = [(str(nested / 'fake_file.txt'), True)]
    sync.delete_empty_dirs()

    assert not nested.exists()
    assert not (target / 'level1').exists()
    assert target.is_dir()
    assert source.is_dir()


def test_compare_dirs_respects_exclusions(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    keep = source / 'keep.txt'
    keep.write_text('keep')
    ignored = source / 'temp.log'
    ignored.write_text('log')
    git_file = source / '.git' / 'config'
    git_file.parent.mkdir()
    git_file.write_text('git')

    mirror = MirrorDatabase(path=str(tmp_path / 'mirror.db'))
    dirs = [DirectoryPair(str(source), str(target))]
    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=['*.log', '.git/*'])

    copy_paths = [str(s) for s, _ in compare.files_to_copy]
    assert str(keep) in copy_paths
    assert str(ignored) not in copy_paths
    assert str(git_file) not in copy_paths


def test_open_confirmation_popup_approved(monkeypatch):
    class DummyPopup:
        def __init__(self, *args, **kwargs):
            self.finished = True
            self.proceed = True
            if 'on_close_callback' in kwargs and kwargs['on_close_callback']:
                kwargs['on_close_callback']()

        def get_outputs(self):
            return [('s1', 't1')], [('s2', 't2')], ['t3']

    class DummyRoot:
        def after(self, delay, func):
            func()

    monkeypatch.setattr('core.backend.ActionSelection', DummyPopup)

    sync = SyncDirs.__new__(SyncDirs)
    sync.root_gui = DummyRoot()
    sync.files_available_to_copy = []
    sync.files_available_to_move = []
    sync.files_available_to_delete = []
    sync.default_actions = []

    res = sync.open_confirmation_popup()
    assert res is True
    assert sync.files_requested_to_copy == [('s1', 't1')]
    assert sync.files_requested_to_move == [('s2', 't2')]
    assert sync.files_requested_to_delete == ['t3']


def test_open_confirmation_popup_cancelled(monkeypatch):
    class DummyPopup:
        def __init__(self, *args, **kwargs):
            self.finished = True
            self.proceed = False
            if 'on_close_callback' in kwargs and kwargs['on_close_callback']:
                kwargs['on_close_callback']()

        def get_outputs(self):
            return [], [], []

    class DummyRoot:
        def after(self, delay, func):
            func()

    monkeypatch.setattr('core.backend.ActionSelection', DummyPopup)

    sync = SyncDirs.__new__(SyncDirs)
    sync.root_gui = DummyRoot()
    sync.files_available_to_copy = []
    sync.files_available_to_move = []
    sync.files_available_to_delete = []
    sync.default_actions = []

    res = sync.open_confirmation_popup()
    assert res is False
    assert sync.files_requested_to_copy == []


def test_action_selection_no_timer_and_cancel(monkeypatch):
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    callback_called = False

    def on_close():
        nonlocal callback_called
        callback_called = True

    action_sel = ActionSelection(
        root_gui=root,
        files_available_to_copy=[],
        files_available_to_move=[],
        files_available_to_delete=[],
        default_actions=[],
        on_close_callback=on_close,
    )

    # Verify no timer attributes or wait buttons exist
    assert not hasattr(action_sel, 'is_timer_active')
    assert not hasattr(action_sel, 'countdown_size')
    assert not hasattr(action_sel, 'button_wait')
    assert action_sel.button_save.cget('text') == 'Save and continue'

    # Test cancel
    action_sel.button_cancel_click()
    assert action_sel.finished is True
    assert action_sel.proceed is False
    assert callback_called is True
    root.destroy()


def test_text_logger_filters_by_active_log_levels():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    logger_widget = TextLogger(root)
    # Initially active: INFO and WARNING
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

    # Simulate unchecking INFO and WARNING, and checking ERROR
    logger_widget.set_log_levels(['ERROR'])
    content_after_filter = logger_widget.get('1.0', tk.END)
    assert 'error msg' in content_after_filter
    assert 'info msg' not in content_after_filter
    assert 'warn msg' not in content_after_filter
    assert 'debug msg' not in content_after_filter

    # Simulate unchecking all levels
    logger_widget.set_log_levels([])
    content_empty = logger_widget.get('1.0', tk.END).strip()
    assert content_empty == ''

    # Re-enable all levels
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

    # Scroll down to a middle position
    logger_widget.yview_moveto(0.4)
    pos_before = logger_widget.yview()[0]

    # Re-filter should preserve scroll view position
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
    # Default excludes DEBUG
    assert 'DEBUG' not in log_levels.get()
    assert 'INFO' in log_levels.get()
    assert 'WARNING' in log_levels.get()
    assert 'ERROR' in log_levels.get()
    assert 'CRITICAL' in log_levels.get()

    # Set custom levels
    log_levels.set(['DEBUG', 'CRITICAL'])
    assert sorted(log_levels.get()) == ['CRITICAL', 'DEBUG']

    # Reset restores default
    log_levels.reset()
    assert 'DEBUG' not in log_levels.get()
    assert 'INFO' in log_levels.get()

    root.destroy()


def test_custom_checkbox_treeview_headers():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    tree = CustomCheckboxTreeView(root)
    # Check that phantom creation date columns are removed
    assert 'creation date (source)' not in tree.custom_headers
    assert 'creation date (target)' not in tree.custom_headers
    assert tree['columns'] == (
        'source',
        'target',
        'size (source)',
        'size (target)',
        'modification date (source)',
        'modification date (target)',
    )
    root.destroy()


def test_action_selection_popup_title_and_scrollbars():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    popup = ActionSelection(root, [], [], [], [])
    assert popup.popup.title() == 'Automatic Backup - Confirm Actions'

    # Check horizontal scrollbar is attached to the treeview
    xscroll = popup.tree.cget('xscrollcommand')
    yscroll = popup.tree.cget('yscrollcommand')
    assert xscroll != ''
    assert yscroll != ''

    # Cancel popup
    popup.button_cancel_click()
    assert popup.finished is True
    assert popup.proceed is False
    root.destroy()


def test_sync_dirs_cancels_cleanly_when_popup_canceled(tmp_path, monkeypatch):
    source = tmp_path / 'src'
    target = tmp_path / 'dst'
    source.mkdir()
    target.mkdir()
    f1 = source / 'file1.txt'
    f1.write_text('content')

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    monkeypatch.setattr(SyncDirs, 'open_confirmation_popup', lambda self: False)

    sync = SyncDirs(
        files_to_copy=[(CstmPath(f1), CstmPath(target / 'file1.txt'))],
        files_to_move=[],
        files_to_delete=[],
        mirror=MirrorDatabase(path=str(tmp_path / 'mirror.db')),
        root_gui=root,
        dirs=[DirectoryPair(source=str(source), target=str(target))],
        confirm_sync=True,
    )

    # When canceled, no files should have been copied or moved
    assert len(sync.files_copied) == 0
    assert not (target / 'file1.txt').exists()
    root.destroy()


def test_gui_scheduler_persistence_on_standby(monkeypatch):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    from gui.gui import Gui

    # Prevent mainloop from blocking
    monkeypatch.setattr(tk.Tk, 'mainloop', lambda self: None)
    monkeypatch.setattr(Gui, 'load_config', lambda self: None)
    monkeypatch.setattr(Gui, 'backend_watchdog', lambda self: None)
    monkeypatch.setattr(Gui, 'log_queue_watchdog', lambda self: None)

    gui = Gui()
    # Turn schedule on
    gui.toggle_state_schedule = True
    gui.toggle_state_sync_now = True
    gui.toggle_state_quick_compare = True
    gui._current_run_trigger = 'sync_now'

    # When backend transitions to STANDBY, one-off triggers reset, but schedule remains ON
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
    # Call reset
    gui.button_action_reset_config(ask_confirmation=False)

    # Critical safety defaults
    assert gui.checkbox_var_use_mirror.get() is True
    assert gui.checkbox_var_confirm_sync.get() is True
    assert gui.checkbox_var_metadata_comparison.get() is True
    assert gui.checkbox_var_build_mirror.get() is False
    assert gui.checkbox_var_save_report.get() is False
    assert gui.text_var_status.get() == BackendThreadStatus.STANDBY.value

    gui.root.destroy()


def test_robust_copy_cleans_up_temp_on_system_exit(tmp_path, monkeypatch):
    source = tmp_path / 'source_abort.txt'
    target = tmp_path / 'target_abort.txt'
    source.write_text('important data that must not be corrupted')

    def aborting_copy(src, dst):
        with open(dst, 'w') as f:
            f.write('partial corrupted data')
        raise SystemExit('User aborted thread')

    monkeypatch.setattr(shutil, 'copy2', aborting_copy)

    with pytest.raises(SystemExit):
        robust_copy(source, target)

    # Neither the final target nor any temporary .tmp file should exist
    assert not target.exists()
    tmp_files = list(tmp_path.glob('*.tmp*'))
    assert len(tmp_files) == 0


def test_copy_files_jit_self_healing(tmp_path):
    source_dir = tmp_path / 'Source'
    target_dir = tmp_path / 'Target'
    source_dir.mkdir()
    target_dir.mkdir()

    source_file = source_dir / 'photo.jpg'
    target_file = target_dir / 'photo.jpg'
    payload = b'image payload content'
    source_file.write_bytes(payload)
    target_file.write_bytes(payload)

    # Ensure mtimes match
    s_stat = os.stat(source_file)
    os.utime(target_file, (s_stat.st_atime, s_stat.st_mtime))

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    # Ensure target is NOT yet in the mirror
    assert not mirror.exists(str(target_dir), str(target_file))

    dirs = [DirectoryPair(source=str(source_dir), target=str(target_dir))]
    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_copy = [(str(source_file), str(target_file))]

    # Run copy_files - it should self-heal without modifying the file
    old_target_mtime = os.stat(target_file).st_mtime
    sync.copy_files()

    assert len(sync.files_copied) == 1
    assert sync.files_copied[0][1] is True
    # Mirror must now have the entry
    assert mirror.exists(str(target_dir), str(target_file))
    # Target mtime should be unchanged (no re-copying took place)
    assert os.stat(target_file).st_mtime == old_target_mtime


def test_delete_files_jit_phantom_cleanup(tmp_path):
    target_dir = tmp_path / 'Target'
    target_dir.mkdir()
    phantom_file = target_dir / 'deleted_externally.txt'

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)

    # Simulate phantom record: entry exists in mirror, but file is missing on disk
    with mirror._get_db(str(target_dir)) as db:
        db[sanitize_path(phantom_file)] = 'stats_hash_123'
    assert mirror.exists(str(target_dir), str(phantom_file))

    dirs = [DirectoryPair(source=str(tmp_path / 'Source'), target=str(target_dir))]
    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_delete = [str(phantom_file)]
    sync.delete_files()

    assert len(sync.files_deleted) == 1
    assert sync.files_deleted[0][1] is True
    # Mirror must have purged the phantom record
    assert not mirror.exists(str(target_dir), str(phantom_file))


def test_move_files_jit_self_healing(tmp_path):
    target_dir = tmp_path / 'Target'
    target_dir.mkdir()
    old_target = target_dir / 'old_sub' / 'file.txt'
    new_target = target_dir / 'new_sub' / 'file.txt'
    new_target.parent.mkdir(parents=True)
    new_target.write_text('moved file data')

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)

    # Mirror still has old path, not new path
    mirror.add_path(str(target_dir), str(new_target))
    # Replace entry to simulate old state
    with mirror._get_db(str(target_dir)) as db:
        del db[sanitize_path(new_target)]
        db[sanitize_path(old_target)] = 'old_hash'

    assert mirror.exists(str(target_dir), str(old_target))
    assert not mirror.exists(str(target_dir), str(new_target))

    dirs = [DirectoryPair(source=str(tmp_path / 'Source'), target=str(target_dir))]
    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_move = [(str(old_target), str(new_target))]
    sync.move_files()

    assert len(sync.files_moved) == 1
    assert sync.files_moved[0][1] is True
    # Mirror must have moved the key to new_target
    assert not mirror.exists(str(target_dir), str(old_target))
    assert mirror.exists(str(target_dir), str(new_target))


def test_preflight_directory_pair_validation(tmp_path):
    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    dirs = [DirectoryPair(source=str(tmp_path / 'Source'), target=str(tmp_path / 'Target'))]

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )

    # An invalid target outside of configured dirs
    invalid_target = 'Z:\\Unmapped\\outside.txt'
    sync.files_requested_to_delete = [invalid_target]
    sync.delete_files()

    # Must fail gracefully without raising an uncaught exception
    assert len(sync.files_deleted) == 1
    assert sync.files_deleted[0] == (invalid_target, False)


def test_sync_dirs_cancel_cooperative(tmp_path):
    source_dir = tmp_path / 'Source'
    target_dir = tmp_path / 'Target'
    source_dir.mkdir()
    target_dir.mkdir()

    f1 = source_dir / '1.txt'
    f2 = source_dir / '2.txt'
    f1.write_text('1')
    f2.write_text('2')

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    dirs = [DirectoryPair(source=str(source_dir), target=str(target_dir))]

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_copy = [
        (str(f1), str(target_dir / '1.txt')),
        (str(f2), str(target_dir / '2.txt')),
    ]

    # Pre-emptively signal cancel
    sync.cancel()
    sync.copy_files()

    # Cancel was set before starting, so 0 files were copied
    assert len(sync.files_copied) == 0
    assert not (target_dir / '1.txt').exists()
    assert not (target_dir / '2.txt').exists()


def test_robust_copy_pre_cleans_stale_temp_file(tmp_path):
    source = tmp_path / 'source.txt'
    target = tmp_path / 'target.txt'
    stale_tmp = tmp_path / 'target.txt.tmp'

    source.write_text('fresh clean content')
    stale_tmp.write_text('corrupt stale content from past power cut')

    # Copy should succeed, pre-cleaning the stale .tmp file and creating target.txt
    robust_copy(source, target)

    assert target.exists()
    assert target.read_text() == 'fresh clean content'
    assert not stale_tmp.exists()


def test_cstm_path_get_from_dir_ignores_tmp_files(tmp_path):
    source_dir = tmp_path / 'scan_dir'
    source_dir.mkdir()
    valid_file = source_dir / 'real_photo.jpg'
    tmp_file1 = source_dir / 'video.mp4.tmp'
    tmp_file2 = source_dir / 'backup.zip.tmp.1234_1'

    valid_file.write_text('valid')
    tmp_file1.write_text('tmp1')
    tmp_file2.write_text('tmp2')

    scanned = CstmPath.get_from_dir(source_dir, exclude=[])
    scanned_names = {Path(p).name for p in scanned}

    assert 'real_photo.jpg' in scanned_names
    assert 'video.mp4.tmp' not in scanned_names
    assert 'backup.zip.tmp.1234_1' not in scanned_names
