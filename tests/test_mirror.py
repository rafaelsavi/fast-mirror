import os
from pathlib import Path

import pytest

from mirror import MirrorDatabase

ARTIFACTS_DIR = Path(__file__).parent / 'artifacts'
ARTIFACTS_DIR.mkdir(exist_ok=True)


@pytest.fixture
def temp_db_path():
    """Fixture to provide a temporary database path."""
    return ARTIFACTS_DIR / 'test_local_mirror.db'


@pytest.fixture
def mirror_db(temp_db_path) -> MirrorDatabase:
    """Fixture to provide a fresh instance of MirrorDatabase."""
    return MirrorDatabase(path=temp_db_path, reset=True)


def test_initialization(temp_db_path):
    """Test initialization of the MirrorDatabase."""
    db = MirrorDatabase(path=temp_db_path, reset=False)
    assert os.path.exists(temp_db_path) is True

    db = MirrorDatabase(path=temp_db_path, reset=True)
    assert os.path.exists(temp_db_path) is True


def test_add_and_get_single(mirror_db):
    """Test adding and retrieving a single path."""
    test_path = ARTIFACTS_DIR / 'test_file.txt'
    test_path.touch()  # Create a dummy file
    mirror_db.add(str(test_path))

    result = mirror_db.get(str(test_path))
    assert result is not None
    test_path.unlink()


def test_add_and_get_multiple(mirror_db):
    """Test adding and retrieving multiple paths."""
    test_paths = [ARTIFACTS_DIR / 'file1.txt', ARTIFACTS_DIR / 'file2.txt']
    for path in test_paths:
        path.touch()  # Create dummy files

    mirror_db.add([str(path) for path in test_paths])
    results = mirror_db.get([str(path) for path in test_paths])

    assert len(results) == len(test_paths)
    for path in test_paths:
        assert mirror_db.get(str(path)) is not None
        path.unlink()


def test_remove_single(mirror_db):
    """Test removing a single path."""
    test_path = ARTIFACTS_DIR / 'test_file.txt'
    test_path.touch()  # Create a dummy file
    mirror_db.add(str(test_path))

    assert mirror_db.remove(str(test_path)) is True
    assert mirror_db.get(str(test_path)) is None
    test_path.unlink()


def test_remove_multiple(mirror_db):
    """Test removing multiple paths."""
    test_paths = [ARTIFACTS_DIR / 'file1.txt', ARTIFACTS_DIR / 'file2.txt']
    for path in test_paths:
        path.touch()  # Create dummy files

    mirror_db.add([str(path) for path in test_paths])
    assert mirror_db.remove([str(path) for path in test_paths]) is True

    for path in test_paths:
        assert mirror_db.get(str(path)) is None
        path.unlink()


def test_get_keys(mirror_db):
    """Test retrieving keys from the database."""
    test_paths = [ARTIFACTS_DIR / 'file1.txt', ARTIFACTS_DIR / 'file2.txt']
    for path in test_paths:
        path.touch()  # Create dummy files

    mirror_db.add([str(path) for path in test_paths])
    keys = mirror_db.get_keys()

    assert len(keys) == len(test_paths)
    for path in test_paths:
        assert str(path) in keys
        path.unlink()


def test_reset(mirror_db):
    """Test resetting the database."""
    test_path = ARTIFACTS_DIR / 'test_file.txt'
    test_path.touch()  # Create a dummy file
    mirror_db.add(str(test_path))

    assert mirror_db.size() > 0
    mirror_db.reset()
    assert mirror_db.size() == 0
    test_path.unlink()


if __name__ == '__main__':
    temp_db_path = ARTIFACTS_DIR / 'test_local_mirror.db'
    if temp_db_path.exists():
        temp_db_path.unlink()

    # Initialize a temporary MirrorDatabase instance
    mirror_db = MirrorDatabase(path=temp_db_path, reset=True)

    # Call all test functions for debugging
    test_initialization(temp_db_path)
    test_add_and_get_single(mirror_db)
    test_add_and_get_multiple(mirror_db)
    test_remove_single(mirror_db)
    test_remove_multiple(mirror_db)
    test_get_keys(mirror_db)
    test_reset(mirror_db)

    if temp_db_path.exists():
        temp_db_path.unlink()

    print('All test functions executed for debugging.')
