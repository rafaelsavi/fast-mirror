import os
import re
import time
from collections.abc import Iterable

from sqlitedict import SqliteDict

from core.file import CstmPathType, StatsHash, get_stats_hash
from utils.constants import ROOT_DIR
from utils.logger import logger
from utils.utils import is_list_of_substr_in_str, log_progress

local_mirror_path = os.path.join(ROOT_DIR, 'local_mirror.db')


def sanitize_path(path: str | CstmPathType) -> str:
    return str(path).replace('/', '\\')


class MirrorDatabase:
    """
    A class to manage a local mirror database using SQLite.
    The database behaves like a dictionary, where keys are string paths and values are encoded stats (hash) as strings.
    """

    def __init__(self, path=local_mirror_path, exclusions: None | list[str] = None):
        self.path = path
        self.exclusions = [sanitize_path(ex) for ex in exclusions] if exclusions else []
        if not os.path.exists(self.path):
            self.init()

    def init(self) -> bool:
        try:
            with SqliteDict(self.path, autocommit=True) as db:
                db.commit()
        except Exception as e:
            logger.warning(f'Could not create database. Exception: {e}')
            return False
        return True

    def _generate_table_name(self, root_dir: CstmPathType) -> str:
        """
        Generate a table name based on root_dir and exclusions.

        :param root_dir: The root directory for which the table is being accessed.
        :return: A string representing the table name.
        """
        sanitized_root = sanitize_path(root_dir).replace(os.sep, '_').replace(':', '_')
        sanitized_exclusions = '_'.join(e.replace(os.sep, '_').replace(':', '_') for e in self.exclusions)
        allowed_pattern = r'[^a-zA-Z0-9_]'
        sanitized_root = re.sub(allowed_pattern, '_', sanitized_root)
        sanitized_exclusions = re.sub(allowed_pattern, '_', sanitized_exclusions)
        return f'{sanitized_root}__{sanitized_exclusions}'

    def _get_db(self, root_dir: CstmPathType) -> SqliteDict:
        table_name = self._generate_table_name(root_dir)
        try:
            logger.debug(f'Accessing database table "{table_name}"')
            return SqliteDict(self.path, tablename=table_name, autocommit=True)
        except Exception as e:
            raise Exception(f'Could not access database table "{table_name}". Exception: {e}') from e

    def exists_table(self, root_dir: CstmPathType) -> bool:
        """Check if the table for the given root_dir exists in the database and is not empty."""
        try:
            with self._get_db(root_dir) as db:
                return bool(db)  # Check if the table is not empty
        except Exception as e:
            logger.warning(f'Could not check if table exists. Exception: {e}')
            return False

    def exists(self, root_dir: CstmPathType, path: CstmPathType) -> bool:
        """Check if the given path exists in the database for the specified root_dir."""
        try:
            with self._get_db(root_dir) as mirror_db:
                return sanitize_path(path) in mirror_db
        except Exception as e:
            logger.warning(f'Could not check if path exists. Exception: {e}')
            return False

    def size(self, root_dir: CstmPathType) -> int:
        try:
            with self._get_db(root_dir) as mirror_db:
                return len(mirror_db)
        except Exception as e:
            logger.warning(f'Could not get size of database. Exception: {e}')
            return 0

    def reset(self, root_dir: CstmPathType) -> bool:
        """Reset the database for the given root_dir."""
        try:
            with self._get_db(root_dir) as db:
                if db:
                    logger.info(f'Resetting mirror for <{root_dir}>')
                    db.clear()
                else:
                    logger.info(f'No mirror to reset for <{root_dir}>')
            return True
        except Exception as e:
            logger.warning(f'Could not reset database for <{root_dir}>. Exception: {e}')
            return False

    def get_table_as_dict(self, root_dir: CstmPathType) -> dict[str, StatsHash]:
        """Retrieve the entire table as a dictionary."""
        try:
            with self._get_db(root_dir) as db:
                return dict(db)
        except Exception as e:
            logger.warning(f'Could not open DB to get table. Exception: {e}')
            return {}

    def get_paths(self, root_dir: CstmPathType) -> set[str]:
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

    def get_stat_hash(
        self, root_dir: CstmPathType, path: CstmPathType | list[CstmPathType]
    ) -> StatsHash | None | list[StatsHash | None]:
        """
        Retrieve the value(s) associated with the given path(s) from the database.

        :param root_dir: The root directory for which the table is being accessed.
        :param path: A single path or an iterable of paths.
        :return: A single value, None, or a set of values/None for multiple paths.
        """

        def get_single(db: SqliteDict, path_single: CstmPathType) -> StatsHash | None:
            try:
                return db[sanitize_path(path_single)]
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

    def add_path(self, root_dir: CstmPathType, path: Iterable[CstmPathType] | CstmPathType):
        def add_single(db: SqliteDict, path_single: CstmPathType):
            try:
                stats_hash = get_stats_hash(path_single)
                db[sanitize_path(path_single)] = stats_hash
            except Exception as e:
                logger.error(f'Could not add file {path} to local mirror. Exception: {e}')

        try:
            with self._get_db(root_dir) as db:
                if isinstance(path, Iterable) and not isinstance(path, str):
                    start_time = time.time()
                    number_files = len(path)
                    for i, path_single in enumerate(path):
                        add_single(db, path_single)
                        log_progress(i, number_files, start_time, interval=10000)
                else:
                    add_single(db, path)
        except Exception as e:
            logger.critical(f'Could not open DB to add file(s): {path} Exception: {e}')

    def remove_path(self, root_dir: CstmPathType, path: CstmPathType | Iterable[CstmPathType]) -> bool:
        def remove_single(db: SqliteDict, path_single: CstmPathType) -> bool:
            try:
                if path_single in db:
                    del db[sanitize_path(path_single)]
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

    def replace_path(self, root_dir: CstmPathType, path: CstmPathType, new_path: CstmPathType):
        """Remove path and add new_path to the database."""
        self.remove_path(root_dir, path)
        self.add_path(root_dir, new_path)
