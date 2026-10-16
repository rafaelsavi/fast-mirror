import os
import shutil
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.backend import (
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
from gui.widgets import Action, EntryPaths
from utils.utils import DirectoryPair, format_elapsed_time


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
