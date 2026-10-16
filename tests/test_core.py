import os
import shutil
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.backend import (
    get_dirs_from_path,
    robust_copy,
    robust_delete,
    robust_move,
    unlock_file_attributes,
)
from core.file import CstmPath
from gui.widgets import EntryPaths
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
