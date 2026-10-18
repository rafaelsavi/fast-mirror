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


def test_generate_table_name(mirror_db, test_data_dir):
    table_name = mirror_db._generate_table_name(test_data_dir)
    assert 'TestData' in table_name


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


def test_get_stat_hash(mirror_db, test_data_dir):
    root_dir = test_data_dir
    path = os.path.join(test_data_dir, 'file1.txt')
    mirror_db.add_path(root_dir, path)
    stat_hash = mirror_db.get_stat_hash(root_dir, path)
    assert stat_hash is not None


def test_reset(mirror_db, test_data_dir):
    root_dir = test_data_dir
    path = os.path.join(test_data_dir, 'file1.txt')
    mirror_db.add_path(root_dir, path)
    assert mirror_db.exists(root_dir, path)
    mirror_db.reset(root_dir)
    assert not mirror_db.exists(root_dir, path)


def test_get_table_as_dict(mirror_db, test_data_dir):
    root_dir = test_data_dir
    path = os.path.join(test_data_dir, 'file1.txt')
    mirror_db.add_path(root_dir, path)
    tables = mirror_db.get_table_as_dict(root_dir)
    assert len(tables) > 0


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
