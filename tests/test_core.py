import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.backend import get_dirs_from_path
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
