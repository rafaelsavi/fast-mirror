import os
from collections.abc import Iterable

from sqlitedict import SqliteDict

from file import CstmPathType, StatHash, get_encoded_stats
from logger import logger
from utils import is_list_of_substr_in_str

local_mirror_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../local_mirror.db'))


class MirrorDatabase:
    """
    A class to manage a local mirror database using SQLite.
    The database behaves like a dictionary, where keys are string paths and values are encoded stats as strings.
    """

    def __init__(self, path=local_mirror_path, exclusions: None | list[str] = None):
        self.path = path
        self.exclusions = exclusions or []
        if not os.path.exists(self.path):
            self.init()

    def _generate_table_name(self, root_dir: str) -> str:
        """
        Generate a table name based on root_dir and exclusions.

        :param root_dir: The root directory for which the table is being accessed.
        :return: A string representing the table name.
        """
        sanitized_root = root_dir.replace(os.sep, '_').replace(':', '_')
        sanitized_exclusions = '_'.join(e.replace(os.sep, '_').replace(':', '_') for e in self.exclusions)
        return f'{sanitized_root}__{sanitized_exclusions}' if sanitized_exclusions else sanitized_root

    def _get_db(self, root_dir: str) -> SqliteDict:
        table_name = self._generate_table_name(root_dir)
        try:
            return SqliteDict(self.path, tablename=table_name, autocommit=True)
        except Exception as e:
            raise Exception(f'Could not access database table "{table_name}". Exception: {e}') from e

    def exists_table(self, root_dir: str) -> bool:
        """Check if the table for the given root_dir exists in the database and is not empty."""
        try:
            with SqliteDict(self.path, autocommit=True) as db:
                table_name = self._generate_table_name(root_dir)
                return table_name in db and len(db[table_name]) > 0
        except Exception as e:
            logger.warning(f'Could not check if table exists. Exception: {e}')
            return False

    def exists(self, root_dir: str, path: CstmPathType) -> bool:
        """Check if the given path exists in the database for the specified root_dir."""
        try:
            with self._get_db(root_dir) as mirror_db:
                return str(path) in mirror_db
        except Exception as e:
            logger.warning(f'Could not check if path exists. Exception: {e}')
            return False

    def size(self, root_dir: str) -> int:
        try:
            with self._get_db(root_dir) as mirror_db:
                return len(mirror_db)
        except Exception as e:
            logger.warning(f'Could not get size of database. Exception: {e}')
            return 0

    def reset(self, root_dir: str) -> bool:
        """Reset the database for the given root_dir."""
        table_name = self._generate_table_name(root_dir)
        try:
            with SqliteDict(self.path, autocommit=True) as db:
                if table_name in db:
                    logger.info(f'Resetting mirror for {root_dir}')
                    del db[table_name]
                else:
                    logger.info(f'No mirror to reset for {root_dir}')
                return True
        except Exception as e:
            logger.warning(f'Could not reset database for {root_dir}. Exception: {e}')
            return False

    def init(self) -> bool:
        try:
            with SqliteDict(self.path, autocommit=True) as db:
                db.commit()
        except Exception as e:
            logger.warning(f'Could not create database. Exception: {e}')
            return False
        return True

    def add(self, root_dir: str, path: Iterable[CstmPathType] | CstmPathType):
        def add_single(db: SqliteDict, path_single: CstmPathType):
            try:
                encoded_stats = get_encoded_stats(path_single)
                db[str(path_single)] = encoded_stats
            except Exception as e:
                logger.error(f'Could not add file {path} to local mirror. Exception: {e}')

        try:
            with self._get_db(root_dir) as db:
                if isinstance(path, Iterable) and not isinstance(path, str):
                    for path_single in path:
                        add_single(db, path_single)
                else:
                    add_single(db, path)
        except Exception as e:
            logger.critical(f'Could not open DB to add file(s): {path} Exception: {e}')

    def get(self, root_dir: str, path: CstmPathType | list[CstmPathType]) -> StatHash | None | list[StatHash | None]:
        """
        Retrieve the value(s) associated with the given path(s) from the database.

        :param root_dir: The root directory for which the table is being accessed.
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
            with self._get_db(root_dir) as db:
                if isinstance(path, list):  # Must be list to match idx of in and outs
                    return [get_single(db, path_single) for path_single in path]
                return get_single(db, path)
        except Exception as e:
            logger.warning(f'Could not open DB to get keys {path}. Exception: {e}')
            return None

    def replace(self, root_dir: str, path: CstmPathType, new_path: CstmPathType):
        """Remove path and add new_path to the database."""
        self.remove(root_dir, path)
        self.add(root_dir, new_path)

    def get_keys(self, root_dir: str) -> set[str]:
        try:
            with self._get_db(root_dir) as mirror_db:
                keys = mirror_db.keys()
                if self.exclusions is not None:
                    return {k for k in keys if not is_list_of_substr_in_str(self.exclusions, k)}
                else:
                    return set(keys)
        except Exception as e:
            logger.warning(f'Could not open DB to get keys. Exception: {e}')
            return set()

    def remove(self, root_dir: str, path: CstmPathType | Iterable[CstmPathType]) -> bool:
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
            with self._get_db(root_dir) as db:
                if isinstance(path, Iterable) and not isinstance(path, str | bytes):
                    return all(remove_single(db, path_single) for path_single in path)
                return remove_single(db, path)
        except Exception as e:
            logger.warning(f'Could not open DB to remove file(s): {path} Exception: {e}')
            return False
