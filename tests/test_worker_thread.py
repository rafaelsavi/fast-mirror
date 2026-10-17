import os
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.backend import CompareDirs, SyncDirs
from core.file import CstmPath, CustomException
from core.mirror import MirrorDatabase
from gui.worker_thread import KillableThread, WorkerThread
from utils.utils import DirectoryPair


def test_worker_thread_normal_execution():
    executed = False

    def target_fn():
        nonlocal executed
        executed = True

    thread = WorkerThread(target=target_fn)
    assert not thread.is_cancelled
    assert not thread.killed
    thread.start()
    thread.join(timeout=2.0)
    assert executed
    assert thread.exc is None


def test_worker_thread_exception_capture():
    def failing_fn():
        raise CustomException('Test custom error')

    thread = WorkerThread(target=failing_fn)
    thread.start()
    with pytest.raises(CustomException, match='Test custom error'):
        thread.join(timeout=2.0)
    assert isinstance(thread.exc, CustomException)


def test_worker_thread_generic_exception():
    def failing_fn():
        raise ValueError('Test generic error')

    thread = WorkerThread(target=failing_fn)
    thread.start()
    with pytest.raises(ValueError, match='Test generic error'):
        thread.join(timeout=2.0)
    assert isinstance(thread.exc, ValueError)


def test_worker_thread_cooperative_cancel():
    cancel_evt = threading.Event()
    thread = WorkerThread(cancel_event=cancel_evt)
    assert not thread.is_cancelled
    assert not thread.killed

    thread.cancel()
    assert thread.is_cancelled
    assert thread.killed
    assert cancel_evt.is_set()


def test_worker_thread_kill_alias():
    thread = WorkerThread()
    assert not thread.is_cancelled
    thread.kill()
    assert thread.is_cancelled
    assert thread.killed


def test_killable_thread_compatibility_alias():
    assert KillableThread is WorkerThread
    thread = KillableThread()
    assert not thread.is_cancelled
    thread.kill()
    assert thread.is_cancelled


def test_compare_dirs_cooperative_cancellation(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    for i in range(10):
        (source / f'file_{i}.txt').write_text(f'data_{i}')

    cancel_event = threading.Event()
    cancel_event.set()  # Pre-cancelled

    db_path = tmp_path / 'test_mirror.db'
    mirror = MirrorDatabase(path=str(db_path))

    compare = CompareDirs(
        mirror=mirror,
        dirs=[DirectoryPair(source=str(source), target=str(target))],
        exclusions=[],
        cancel_requested=cancel_event,
    )

    # Should have aborted early
    assert len(compare.files_to_copy) == 0


def test_sync_dirs_cooperative_cancellation(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    for i in range(5):
        (source / f'file_{i}.txt').write_text(f'content_{i}')

    db_path = tmp_path / 'test_mirror.db'
    mirror = MirrorDatabase(path=str(db_path))

    copy_list = [
        (
            CstmPath(source / f'file_{i}.txt', root_dir=source),
            CstmPath(target / f'file_{i}.txt', root_dir=target),
        )
        for i in range(5)
    ]

    cancel_event = threading.Event()
    cancel_event.set()  # Cancelled before start

    sync = SyncDirs(
        files_to_copy=copy_list,
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        dirs=[DirectoryPair(source=str(source), target=str(target))],
        confirm_sync=False,
        cancel_requested=cancel_event,
    )

    # All copy operations should be skipped due to cancellation
    assert len(sync.files_copied) == 0
