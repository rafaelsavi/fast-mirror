import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.file import CstmPath
from core.mirror import MirrorDatabase


@pytest.fixture
def temp_db_path(tmp_path) -> str:
    """Fixture to provide a temporary database path."""
    return os.path.join(tmp_path, 'test_mirror.db')


@pytest.fixture
def mirror_db(temp_db_path) -> MirrorDatabase:
    """Fixture to provide a MirrorDatabase instance."""
    return MirrorDatabase(path=temp_db_path)


@pytest.fixture
def test_data_dir(tmp_path) -> str:
    """Fixture to provide a TestData directory."""
    test_data = os.path.join(tmp_path, 'TestData')
    os.makedirs(test_data, exist_ok=True)
    # Create some test files
    with open(os.path.join(test_data, 'file1.txt'), 'w') as f:
        f.write('Test file 1')
    with open(os.path.join(test_data, 'file2.txt'), 'w') as f:
        f.write('Test file 2')
    return test_data


def test_init_creates_db(temp_db_path):
    MirrorDatabase(path=temp_db_path)
    assert os.path.exists(temp_db_path)


def test_add_and_exists_path(mirror_db, test_data_dir):
    root_dir = test_data_dir
    path = os.path.join(test_data_dir, 'file1.txt')
    mirror_db.add_path(root_dir, path)
    assert mirror_db.exists(root_dir, path)


def test_remove_path(mirror_db, test_data_dir):
    root_dir = test_data_dir
    path = os.path.join(test_data_dir, 'file1.txt')
    mirror_db.add_path(root_dir, path)
    assert mirror_db.exists(root_dir, path)
    mirror_db.remove_path(root_dir, path)
    assert not mirror_db.exists(root_dir, path)


def test_get_paths(mirror_db, test_data_dir):
    root_dir = test_data_dir
    paths = [os.path.join(test_data_dir, 'file1.txt'), os.path.join(test_data_dir, 'file2.txt')]
    mirror_db.add_path(root_dir, paths)
    retrieved_paths = mirror_db.get_paths(root_dir)
    assert set(retrieved_paths) == {CstmPath(p, root_dir=root_dir) for p in paths}


def test_reset(mirror_db, test_data_dir):
    root_dir = test_data_dir
    path = os.path.join(test_data_dir, 'file1.txt')
    mirror_db.add_path(root_dir, path)
    assert mirror_db.exists(root_dir, path)
    mirror_db.reset(root_dir)
    assert not mirror_db.exists(root_dir, path)


def test_replace_path(mirror_db, test_data_dir):
    root_dir = test_data_dir
    old_path = os.path.join(test_data_dir, 'file1.txt')
    new_path = os.path.join(test_data_dir, 'file3.txt')
    with open(new_path, 'w') as f:
        f.write('Test file 3')
    mirror_db.add_path(root_dir, old_path)
    mirror_db.replace_path(root_dir, old_path, new_path)
    assert not mirror_db.exists(root_dir, old_path)
    assert mirror_db.exists(root_dir, new_path)


def test_vacuum(mirror_db):
    assert mirror_db.vacuum() is True


def test_wal_and_vacuum_close_connections(tmp_path):
    db_path = str(tmp_path / 'lock_test.db')
    mirror = MirrorDatabase(path=db_path)
    assert mirror.vacuum() is True
    # If connection was leaked, os.remove on Windows would raise PermissionError [WinError 32]
    os.remove(db_path)
    assert not os.path.exists(db_path)


def test_exclusions_invalidation(tmp_path, test_data_dir):
    db_path = str(tmp_path / 'invalidation_test.db')
    root_dir = test_data_dir
    path = os.path.join(test_data_dir, 'file1.txt')

    # Build mirror with exclusions
    mirror1 = MirrorDatabase(path=db_path, exclusions=['*.tmp', '.git/*'])
    mirror1.add_path(root_dir, path)
    assert mirror1.exists_table(root_dir) is True

    # Same exclusions (different order) -> still valid
    mirror_same = MirrorDatabase(path=db_path, exclusions=['.git/*', '*.tmp'])
    assert mirror_same.exists_table(root_dir) is True

    # Modified exclusions -> invalidated!
    mirror2 = MirrorDatabase(path=db_path, exclusions=['*.log'])
    assert mirror2.exists_table(root_dir) is False

    # When new scan with new exclusions is added, old files are purged
    path2 = os.path.join(test_data_dir, 'file2.txt')
    mirror2.add_path(root_dir, path2)
    assert mirror2.exists_table(root_dir) is True
    assert mirror2.exists(root_dir, path2) is True
    assert mirror2.exists(root_dir, path) is False
    assert mirror2.size(root_dir) == 1


def test_unc_path_support(tmp_path):
    db_path = str(tmp_path / 'unc_test.db')
    mirror = MirrorDatabase(path=db_path)
    root_dir = r'\\192.168.1.100\Share'
    file_path = r'\\192.168.1.100\Share\sub\doc.pdf'

    # Inject path using CstmPath with pre-computed hash
    cstm = CstmPath(file_path, root_dir=root_dir, stats_hash='feedface12345678')
    mirror.add_path(root_dir, cstm)

    assert mirror.exists(root_dir, file_path) is True
    assert mirror.size(root_dir) == 1
    paths = mirror.get_paths(root_dir)
    assert len(paths) == 1
    p = next(iter(paths))
    assert str(p) == file_path
    assert p.stats_hash == 'feedface12345678'


def test_size_and_metadata_sync(tmp_path, test_data_dir):
    db_path = str(tmp_path / 'size_test.db')
    mirror = MirrorDatabase(path=db_path)
    root_dir = test_data_dir
    p1 = os.path.join(test_data_dir, 'file1.txt')
    p2 = os.path.join(test_data_dir, 'file2.txt')

    assert mirror.size(root_dir) == 0
    mirror.add_path(root_dir, [p1, p2])
    assert mirror.size(root_dir) == 2

    mirror.remove_path(root_dir, p1)
    assert mirror.size(root_dir) == 1
    mirror.reset(root_dir)
    assert mirror.size(root_dir) == 0


def test_empty_target_mirror_saved(tmp_path):
    db_path = str(tmp_path / 'empty_target_test.db')
    mirror = MirrorDatabase(path=db_path)
    root_dir = str(tmp_path / 'empty_dir')
    os.makedirs(root_dir, exist_ok=True)

    assert mirror.exists_table(root_dir) is False
    mirror.add_path(root_dir, [])
    assert mirror.exists_table(root_dir) is True
    assert mirror.size(root_dir) == 0
    assert mirror.get_paths(root_dir) == set()


def test_mirror_saved_when_sync_popup_cancelled(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from core.backend import CompareDirs, SyncDirs
    from utils.utils import DirectoryPair

    monkeypatch.setattr(SyncDirs, 'open_confirmation_popup', lambda self: False)

    db_path = str(tmp_path / 'cancel_sync_test.db')
    mirror = MirrorDatabase(path=db_path)

    src = tmp_path / 'source'
    tgt = tmp_path / 'target'
    src.mkdir()
    tgt.mkdir()
    (src / 'new_file.txt').write_text('content')
    (tgt / 'existing.txt').write_text('existing')

    dir_pair = DirectoryPair(source=str(src), target=str(tgt))

    # Initial compare with rebuild_mirror=True
    compare = CompareDirs(
        mirror=mirror,
        dirs=[dir_pair],
        exclusions=[],
        use_mirror=False,
        increment_mirror=False,
        rebuild_mirror=True,
    )
    assert mirror.exists_table(str(tgt)) is True
    assert mirror.size(str(tgt)) == 1

    # Simulate SyncDirs with mock root_gui where confirmation popup is cancelled
    SyncDirs(
        files_to_copy=compare.files_to_copy,
        files_to_move=compare.files_to_move,
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        root_gui=MagicMock(),
        dirs=[dir_pair],
        confirm_sync=True,
    )
    # Target mirror database must still exist and retain the scanned records
    assert mirror.exists_table(str(tgt)) is True
    assert mirror.size(str(tgt)) == 1
    paths = {str(p) for p in mirror.get_paths(str(tgt))}
    assert str(tgt / 'existing.txt') in paths


def test_mirror_persists_size_and_mtime_and_migration(tmp_path):
    """Verify that mirror_cache stores and returns size and mtime, and safely migrates legacy databases."""
    import contextlib
    import sqlite3

    from core.file import Stats

    db_path = str(tmp_path / 'legacy.db')
    root_dir = str(tmp_path / 'target')
    os.makedirs(root_dir, exist_ok=True)

    # 1. Create a legacy table without size and mtime columns
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute("""
            CREATE TABLE mirror_cache (
                root_dir TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                stats_hash TEXT NOT NULL,
                PRIMARY KEY (root_dir, rel_path)
            );
        """)
        conn.execute(
            """
            INSERT INTO mirror_cache (root_dir, rel_path, stats_hash)
            VALUES (?, ?, ?);
        """,
            (root_dir, 'legacy.txt', 'hash123'),
        )
        conn.commit()

    # 2. Open with MirrorDatabase - should auto-migrate
    mirror = MirrorDatabase(path=db_path)
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cols = [c[1] for c in conn.execute('PRAGMA table_info(mirror_cache);').fetchall()]
        assert 'size' in cols
        assert 'mtime' in cols

    # 3. Verify legacy row has NULL stats and cached_stats is None
    retrieved_legacy = {p.rel_to_root: p for p in mirror.get_paths(root_dir)}
    assert 'legacy.txt' in retrieved_legacy
    assert retrieved_legacy['legacy.txt'].cached_stats is None

    # 4. Add path with stats and verify get_paths retrieves size and mtime
    file_path = os.path.join(root_dir, 'new_file.txt')
    with open(file_path, 'w') as f:
        f.write('Hello World')

    cstm_p = CstmPath(file_path, root_dir=root_dir, stats=Stats(1234, 5678.0))
    # Also test an empty file (0 bytes) with a valid modification timestamp
    empty_path = os.path.join(root_dir, 'empty.txt')
    with open(empty_path, 'w') as f:
        pass
    cstm_empty = CstmPath(empty_path, root_dir=root_dir, stats=Stats(0, 9999.0))

    mirror.add_path(root_dir, [cstm_p, cstm_empty])

    retrieved = {p.rel_to_root: p for p in mirror.get_paths(root_dir)}
    assert 'new_file.txt' in retrieved
    new_cstm = retrieved['new_file.txt']
    assert new_cstm.cached_stats is not None
    assert new_cstm.cached_stats.st_size == 1234
    assert new_cstm.cached_stats.st_mtime == 5678.0

    # Ensure empty file (0 bytes) has its stats preserved and not treated as missing
    assert 'empty.txt' in retrieved
    empty_cstm = retrieved['empty.txt']
    assert empty_cstm.cached_stats is not None
    assert empty_cstm.cached_stats.st_size == 0
    assert empty_cstm.cached_stats.st_mtime == 9999.0
