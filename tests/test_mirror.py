import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest
from sqlitedict import SqliteDict

from core.file import CstmPathType, StatsHash
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
    db = MirrorDatabase(path=temp_db_path)
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
    assert set(retrieved_paths) == set(paths)


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


def test_get_all_tables_as_dict(mirror_db, test_data_dir):
    root_dir = test_data_dir
    path = os.path.join(test_data_dir, 'file1.txt')
    mirror_db.add_path(root_dir, path)
    tables = mirror_db.get_all_tables_as_dict()
    assert len(tables) > 0


def test_replace_path(mirror_db, test_data_dir):
    root_dir = test_data_dir
    old_path = os.path.join(test_data_dir, 'file1.txt')
    new_path = os.path.join(test_data_dir, 'file3.txt')
    mirror_db.add_path(root_dir, old_path)
    mirror_db.replace_path(root_dir, old_path, new_path)
    assert not mirror_db.exists(root_dir, old_path)
    assert mirror_db.exists(root_dir, new_path)
