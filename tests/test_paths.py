import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.path_resolver import get_dirs_from_path
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
        DirectoryPair(r'D:\Files', r'\\192.168.1.100\Backup\D'),
    ]
    path = r'\\192.168.1.100\Photos\2025\Vacation\sample.mp4'
    matched = get_dirs_from_path(path, dirs)
    assert matched.source == r'E:\Photos'
    assert matched.target == r'\\192.168.1.100\Photos'


def test_get_dirs_from_path_nested_prefers_most_specific():
    dirs = [
        DirectoryPair('D:\\', r'\\192.168.1.100\Backup\D'),
        DirectoryPair(r'D:\Photos', r'\\192.168.1.100\Photos'),
    ]
    matched_specific = get_dirs_from_path(r'D:\Photos\sub\pic.jpg', dirs)
    assert matched_specific.source == r'D:\Photos'

    matched_root = get_dirs_from_path(r'D:\Other\file.txt', dirs)
    assert matched_root.source == 'D:\\'


def test_get_dirs_from_path_case_and_slash_variations():
    dirs = [
        DirectoryPair(r'E:\Photos', r'\\192.168.1.100\Photos'),
    ]
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
        sample_src_file = os.path.join(source, 'subfolder', 'test_sample.txt')
        matched_src = get_dirs_from_path(sample_src_file, dirs)
        assert matched_src.source == source

        sample_tgt_file = os.path.join(target, 'subfolder', 'test_sample.txt')
        matched_tgt = get_dirs_from_path(sample_tgt_file, dirs)
        assert matched_tgt.target == target


def test_entry_paths_parse_line(tmp_path):
    source = tmp_path / 'ValidSource'
    target = tmp_path / 'ValidTarget'
    source.mkdir()
    target.mkdir()

    line = f'{source} -> {target}'
    parsed = EntryPaths.parse_line(line)
    assert parsed is not None
    assert parsed[0] == os.path.realpath(str(source))
    assert parsed[1] == os.path.realpath(str(target))

    new_target = target / 'NewSubFolder'
    line_new = f'{source} -> {new_target}'
    parsed_new = EntryPaths.parse_line(line_new)
    assert parsed_new is not None
    assert parsed_new[1] == os.path.realpath(str(new_target))

    non_existent = tmp_path / 'DoesNotExist'
    assert EntryPaths.parse_line(f'{non_existent} -> {target}') is None


def test_entry_paths_get_raw_pairs(tmp_path):
    import tkinter as tk

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    entry = EntryPaths(root)
    valid_src = tmp_path / 'ValidSrc'
    valid_src.mkdir()
    tgt = tmp_path / 'Target'
    tgt.mkdir()

    missing_src = tmp_path / 'MissingSrc'

    raw_text = f'{valid_src} -> {tgt}\n{missing_src} -> {tgt}\ninvalid_format_line\n'
    entry.insert('1.0', raw_text)

    raw_pairs = entry.get_raw_pairs()
    assert len(raw_pairs) == 3
    assert raw_pairs[0][2] == ''
    assert 'does not exist or disconnected' in raw_pairs[1][2]
    assert 'Invalid format' in raw_pairs[2][2]

    root.destroy()


def test_entry_paths_quote_handling(tmp_path):
    source = tmp_path / 'QuotedSource'
    source.mkdir()
    target = tmp_path / 'QuotedTarget'
    target.mkdir()

    # Double quotes (like Windows 11 "Copy as path")
    line_double = f'"{source}" -> "{target}"'
    parsed_double = EntryPaths.parse_line(line_double)
    assert parsed_double is not None
    assert parsed_double[0] == os.path.realpath(str(source))
    assert parsed_double[1] == os.path.realpath(str(target))

    # Single quotes
    line_single = f"'{source}' -> '{target}'"
    parsed_single = EntryPaths.parse_line(line_single)
    assert parsed_single is not None
    assert parsed_single[0] == os.path.realpath(str(source))
    assert parsed_single[1] == os.path.realpath(str(target))
