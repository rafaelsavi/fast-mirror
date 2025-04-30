import os
from collections.abc import Iterable

from sqlitedict import SqliteDict

from logger import logger
from utils import CstmPathType, StatHash, get_encoded_stats, is_list_of_substr_in_str

local_mirror_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../local_mirror.db'))


class MirrorDatabase:
    """
    A class to manage a local mirror database using SQLite.
    The database behaves like a dictionary, where keys are string paths and values are encoded stats as strings.
    """

    def __init__(self, path=local_mirror_path, reset=False):
        self.path = path
        if reset or not os.path.exists(self.path):
            self.reset()

    def _get_db(self) -> SqliteDict:
        try:
            return SqliteDict(self.path, autocommit=True)
        except Exception as e:
            raise Exception(f'Could not access database. Exception: {e}') from e

    def size(self) -> int:
        try:
            with self._get_db() as mirror_db:
                return len(mirror_db)
        except Exception as e:
            logger.warning(f'Could not get size of database. Exception: {e}')
            return 0

    def reset(self) -> bool:
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except Exception as e:
                logger.warning(f'Could not reset database. Exception: {e}')
                return False

        try:
            with SqliteDict(self.path, autocommit=True) as db:
                db.commit()
        except Exception as e:
            logger.warning(f'Could not create database. Exception: {e}')
            return False
        return True

    def add(self, path: Iterable[CstmPathType] | CstmPathType):
        def add_single(db: SqliteDict, path_single: CstmPathType):
            try:
                encoded_stats = get_encoded_stats(path_single)
                db[str(path_single)] = encoded_stats
            except Exception as e:
                logger.error(f'Could not add file {path} to local mirror. Exception: {e}')

        try:
            with self._get_db() as db:
                if isinstance(path, Iterable) and not isinstance(path, str):
                    for path_single in path:
                        add_single(db, path_single)
                else:
                    add_single(db, path)
        except Exception as e:
            logger.critical(f'Could not open DB to add file(s): {path} Exception: {e}')

    def get(self, path: CstmPathType | Iterable[CstmPathType]) -> StatHash | None | set[StatHash | None]:
        """
        Retrieve the value(s) associated with the given path(s) from the database.

        :param path: A single path or an iterable of paths.
        :return: A single value, None, or a set of values/None for multiple paths.
        """

        def get_single(db: SqliteDict, path_single: CstmPathType) -> StatHash | None:
            try:
                return db[str(path_single)]
            except KeyError:
                logger.warning(f'Key does not exist in database: {path_single}')
                return None

        try:
            with self._get_db() as db:
                if isinstance(path, Iterable) and not isinstance(path, str | bytes):
                    return {get_single(db, path_single) for path_single in path}
                return get_single(db, path)
        except Exception as e:
            logger.warning(f'Could not open DB to get keys {path}. Exception: {e}')
            return None

    def replace(self, path: CstmPathType, new_path: CstmPathType):
        """Remove path and add new_path to the database."""
        try:
            with self._get_db() as db:
                self.remove(path)
                self.add(new_path)
        except Exception as e:
            logger.warning(f'Could not open DB to replace key {path}. Exception: {e}')

    def get_keys(self, exclude: list[str] | set[str] | None = None) -> set[str]:
        exclude = [] if exclude is None else list(exclude)

        try:
            with self._get_db() as mirror_db:
                keys = mirror_db.keys()
                if exclude is not None:
                    return {k for k in keys if not is_list_of_substr_in_str(exclude, k)}
                else:
                    return set(keys)
        except Exception as e:
            logger.warning(f'Could not open DB to get keys. Exception: {e}')
            return set()

    def remove(self, path: CstmPathType | Iterable[CstmPathType]) -> bool:
        def remove_single(db: SqliteDict, path_single: CstmPathType) -> bool:
            try:
                if path_single in db:
                    del db[str(path_single)]
                    return True
                else:
                    logger.warning(f'Key does not exist in database: {path_single}')
                    return False
            except Exception as e:
                logger.warning(f'Could not remove key from database (Key {path_single}). Exception: {e}')
                return False

        try:
            with self._get_db() as db:
                if isinstance(path, Iterable) and not isinstance(path, str | bytes):
                    return all(remove_single(db, path_single) for path_single in path)
                return remove_single(db, path)
        except Exception as e:
            logger.warning(f'Could not open DB to remove file(s): {path} Exception: {e}')
            return False
