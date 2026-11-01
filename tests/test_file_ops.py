import os
import shutil
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.file_ops import (
    ensure_directory_case,
    get_actual_case_name,
    rename_case_safe,
    robust_copy,
    robust_delete,
    robust_move,
    unlock_file_attributes,
)


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
        with open(dst, 'w') as f:
            f.write('partial')
        raise OSError(59, 'An unexpected network error occurred.')

    monkeypatch.setattr(shutil, 'copy2', failing_copy_that_leaves_partial)

    with pytest.raises(OSError, match='unexpected network error'):
        robust_copy(source, target, max_retries=2, initial_delay=0.001, backoff_factor=1.0)

    # Incomplete target file must be cleaned up to prevent corrupted backups
    assert not target.exists()


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

    assert not target.exists()
    tmp_files = list(tmp_path.glob('*.tmp*'))
    assert len(tmp_files) == 0


def test_robust_copy_pre_cleans_stale_temp_file(tmp_path):
    source = tmp_path / 'source.txt'
    target = tmp_path / 'target.txt'
    stale_tmp = tmp_path / 'target.txt.tmp'

    source.write_text('fresh clean content')
    stale_tmp.write_text('corrupt stale content from past power cut')

    robust_copy(source, target)

    assert target.exists()
    assert target.read_text() == 'fresh clean content'
    assert not stale_tmp.exists()


def test_robust_copy_and_move_fail_fast_on_missing_source(tmp_path, monkeypatch):
    source = tmp_path / 'non_existent_source.txt'
    target = tmp_path / 'target.txt'

    sleep_calls: list[float] = []
    monkeypatch.setattr(time, 'sleep', lambda delay: sleep_calls.append(delay))

    with pytest.raises(FileNotFoundError):
        robust_copy(source, target, max_retries=3, initial_delay=1.0)
    assert len(sleep_calls) == 0

    with pytest.raises(FileNotFoundError):
        robust_move(source, target, max_retries=3, initial_delay=1.0)
    assert len(sleep_calls) == 0


def test_robust_copy_fails_fast_when_copy_raises_file_not_found(tmp_path, monkeypatch):
    source = tmp_path / 'source.txt'
    target = tmp_path / 'target.txt'
    source.write_text('content')

    sleep_calls: list[float] = []
    monkeypatch.setattr(time, 'sleep', lambda delay: sleep_calls.append(delay))

    def missing_copy2(src, dst):
        raise FileNotFoundError(2, 'The system cannot find the file specified')

    monkeypatch.setattr(shutil, 'copy2', missing_copy2)

    with pytest.raises(FileNotFoundError):
        robust_copy(source, target, max_retries=3, initial_delay=1.0)
    assert len(sleep_calls) == 0


def test_robust_delete_fails_fast_on_missing_file(tmp_path, monkeypatch):
    file_to_del = tmp_path / 'vanished.txt'
    file_to_del.write_text('content')

    sleep_calls: list[float] = []
    monkeypatch.setattr(time, 'sleep', lambda delay: sleep_calls.append(delay))

    def missing_remove(path):
        raise FileNotFoundError(2, 'The system cannot find the file specified')

    monkeypatch.setattr(os, 'remove', missing_remove)
    robust_delete(file_to_del, max_retries=3, initial_delay=1.0)
    assert len(sleep_calls) == 0


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


def test_unlock_file_attributes_non_existent_path(tmp_path):
    missing_path = tmp_path / 'does_not_exist.txt'
    assert unlock_file_attributes(missing_path) is False


def test_robust_copy_overwrites_existing_file(tmp_path):
    source = tmp_path / 'source.txt'
    target = tmp_path / 'target.txt'
    source.write_text('new updated version')
    target.write_text('old obsolete version')

    robust_copy(source, target)
    assert target.is_file()
    assert target.read_text() == 'new updated version'


def test_cstmpath_refresh_stats_after_overwrite(tmp_path):
    from core.file import CstmPath

    source = tmp_path / 'source.txt'
    target = tmp_path / 'target.txt'
    source.write_text('longer content for updated file')
    target.write_text('short')

    cstm_target = CstmPath(target, root_dir=tmp_path)
    old_size = cstm_target.get_st_size()
    assert old_size == len('short')

    robust_copy(source, target)
    # Target file on disk has changed
    assert target.read_text() == 'longer content for updated file'

    # Calling refresh_stats updates in-memory cache to new file stats
    new_stats = cstm_target.refresh_stats()
    assert new_stats.st_size == len('longer content for updated file')
    assert cstm_target.get_st_size() == len('longer content for updated file')


def test_cstmpath_stats_encapsulation_and_copy(tmp_path):
    from core.file import CstmPath, Stats

    file1 = tmp_path / 'file1.txt'
    file1.write_text('content1')

    # Path with explicit cached stats
    st = Stats(8, 1000.0)
    p1 = CstmPath(file1, stats=st)
    assert p1.has_cached_stats is True
    assert p1.cached_stats == st
    assert p1.is_new_target is False
    assert p1.stat_failed is False

    # New target path
    p2 = CstmPath('//nas/share/new.txt', is_new_target=True)
    assert p2.has_cached_stats is False
    assert p2.cached_stats is None
    assert p2.is_new_target is True
    assert p2.stat_failed is True

    # Clean copy_stats_from
    p2.copy_stats_from(p1)
    assert p2.has_cached_stats is True
    assert p2.cached_stats == st


def test_get_actual_case_name_and_rename_case_safe(tmp_path):
    d = tmp_path / 'folder_lower'
    d.mkdir()
    f = d / 'file_lower.txt'
    f.write_text('content')

    assert get_actual_case_name(d) == 'folder_lower'
    assert get_actual_case_name(f) == 'file_lower.txt'

    # Case rename folder
    d_upper = tmp_path / 'Folder_Upper'
    rename_case_safe(d, d_upper)
    assert get_actual_case_name(d_upper) == 'Folder_Upper'
    assert 'Folder_Upper' in os.listdir(tmp_path)

    # Case rename file
    f_upper = d_upper / 'FILE_LOWER.TXT'
    rename_case_safe(d_upper / 'file_lower.txt', f_upper)
    assert get_actual_case_name(f_upper) == 'FILE_LOWER.TXT'
    assert 'FILE_LOWER.TXT' in os.listdir(d_upper)


def test_ensure_directory_case_nested(tmp_path):
    root = tmp_path / 'root'
    sub1 = root / '04 - encontro vendraminis'
    sub2 = sub1 / 'raw'
    sub2.mkdir(parents=True)
    (sub2 / 'photo.jpg').write_text('img')

    assert get_actual_case_name(sub1) == '04 - encontro vendraminis'
    assert get_actual_case_name(sub2) == 'raw'

    target_sub2 = root / '04 - Encontro Vendraminis' / 'RAW'
    cache = set()
    ensure_directory_case(target_sub2, verified_cache=cache)

    assert get_actual_case_name(root / '04 - Encontro Vendraminis') == '04 - Encontro Vendraminis'
    assert get_actual_case_name(target_sub2) == 'RAW'
    assert (target_sub2 / 'photo.jpg').is_file()
    assert str(target_sub2) in cache


def test_robust_move_parent_dir_and_file_case_rename(tmp_path):
    d_old = tmp_path / 'folder_old'
    d_old.mkdir()
    src_file = d_old / 'image.jpg'
    src_file.write_text('pixels')

    d_new = tmp_path / 'Folder_Old'
    dst_file = d_new / 'IMAGE.JPG'

    cache = set()
    robust_move(src_file, dst_file, verified_dir_cache=cache)

    assert 'Folder_Old' in os.listdir(tmp_path)
    assert 'folder_old' not in os.listdir(tmp_path)
    assert 'IMAGE.JPG' in os.listdir(d_new)
    assert dst_file.is_file()
    assert dst_file.read_text() == 'pixels'


def test_deep_mixed_case_renames(tmp_path):
    """Test simultaneous case changes at grandparent, parent, and file levels."""
    root = tmp_path / 'deep_root'
    old_dir = root / '01 - Vacation Trip' / 'SubFolder' / 'raw'
    old_dir.mkdir(parents=True)
    f = old_dir / 'image_one.jpg'
    f.write_text('deep content')

    new_dir = root / '01 - VACATION TRIP' / 'subfolder' / 'RAW'
    new_f = new_dir / 'IMAGE_ONE.JPG'

    cache: set[str] = set()
    robust_move(f, new_f, verified_dir_cache=cache)

    assert '01 - VACATION TRIP' in os.listdir(root)
    assert '01 - Vacation Trip' not in os.listdir(root)
    assert 'subfolder' in os.listdir(root / '01 - VACATION TRIP')
    assert 'RAW' in os.listdir(root / '01 - VACATION TRIP' / 'subfolder')
    assert 'IMAGE_ONE.JPG' in os.listdir(new_dir)
    assert new_f.read_text() == 'deep content'


def test_two_step_rename_fallback_on_oserror(tmp_path, monkeypatch):
    """Simulate SMB/FAT collision where os.replace raises OSError initially."""
    d = tmp_path / 'folder_case'
    d.mkdir()
    d_upper = tmp_path / 'Folder_Case'

    real_replace = os.replace
    calls: list[tuple[str, str]] = []

    def mock_replace(src: str, dst: str) -> None:
        calls.append((src, dst))
        if src.lower() == dst.lower() and '__fm_case_' not in dst and '__fm_case_' not in src:
            raise OSError(183, 'Cannot create a file when that file already exists')
        real_replace(src, dst)

    monkeypatch.setattr(os, 'replace', mock_replace)
    rename_case_safe(d, d_upper)

    assert get_actual_case_name(d_upper) == 'Folder_Case'
    assert 'Folder_Case' in os.listdir(tmp_path)
    assert any('__fm_case_' in dst for _, dst in calls)


def test_special_characters_and_accents(tmp_path):
    """Verify case renames handle Portuguese / Unicode accents and special characters."""
    old_folder = tmp_path / '04 - Encontro vendraminis Caeté (São Paulo)'
    old_folder.mkdir()
    f = old_folder / 'foto_família.jpg'
    f.write_text('familia')

    new_folder = tmp_path / '04 - Encontro Vendraminis Caeté (São Paulo)'
    new_f = new_folder / 'Foto_Família.JPG'

    cache: set[str] = set()
    robust_move(f, new_f, verified_dir_cache=cache)

    entries = os.listdir(tmp_path)
    assert '04 - Encontro Vendraminis Caeté (São Paulo)' in entries
    assert '04 - Encontro vendraminis Caeté (São Paulo)' not in entries
    assert 'Foto_Família.JPG' in os.listdir(new_folder)
    assert new_f.read_text() == 'familia'


def test_robust_copy_reconciles_existing_target_dir_case(tmp_path):
    """When copying a new file to a target whose directory exists with different case, reconcile it."""
    src_dir = tmp_path / 'Src' / 'MyPhotos'
    src_dir.mkdir(parents=True)
    (src_dir / 'pic.jpg').write_text('pic data')

    tgt_dir = tmp_path / 'Tgt' / 'myphotos'
    tgt_dir.mkdir(parents=True)

    desired_tgt_file = tmp_path / 'Tgt' / 'MyPhotos' / 'pic.jpg'
    cache: set[str] = set()
    robust_copy(src_dir / 'pic.jpg', desired_tgt_file, verified_dir_cache=cache)

    assert 'MyPhotos' in os.listdir(tmp_path / 'Tgt')
    assert 'myphotos' not in os.listdir(tmp_path / 'Tgt')
    assert desired_tgt_file.is_file()
    assert desired_tgt_file.read_text() == 'pic data'
