import os
import shutil
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.file_ops import robust_copy, robust_delete, robust_move, unlock_file_attributes


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
