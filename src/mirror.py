import os
from collections.abc import Iterable

from sqlitedict import SqliteDict

from src.logger import logger
from src.utils import encode_stats, is_list_of_substr_in_str

local_mirror_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../local_mirror.db'))


class MirrorDatabase:
    def __init__(self, path=local_mirror_path, reset=False):
        self.path = path
        if reset:
            self.reset()

    def _get_db(self):
        try:
            return SqliteDict(self.path, autocommit=True)
        except Exception as e:
            raise Exception(f'Could not access database. Exception: {e}') from e

    def size(self):
        try:
            with self._get_db() as mirror_db:
                return len(mirror_db)
        except Exception as e:
            logger.warning(f'Could not get size of database. Exception: {e}')
            return 0

    def reset(self):
        try:
            os.remove(self.path)
            self._get_db()
            return True
        except Exception as e:
            logger.warning(f'Could not reset database. Exception: {e}')
            return False

    def process_and_add(self, file_path: str | list[str] | set[str]):
        def add_stats(self_, p):
            try:
                stats = os.stat(p)
                stats = encode_stats(stats)
                self_.add(os.path.normpath(p), stats)
            except Exception as e:
                logger.error(f'Could not add file {p} to local mirror. Exception: {e}')

        if isinstance(file_path, Iterable) and not isinstance(file_path, str):
            for _file_path in file_path:
                add_stats(self, _file_path)
        else:
            add_stats(self, file_path)

    def add(self, key=None, value=None, dictionary=None):
        try:
            with self._get_db() as mirror_db:
                if dictionary is not None:
                    mirror_db.update(dictionary)
                elif key is not None and value is not None:
                    mirror_db[key] = value
                else:
                    raise Exception('Missing arguments to set database')
            return True
        except Exception as e:
            logger.warning(f'Could not save to database ({key}: {value}). Exception: {e}')
            return False

    def get(self, key, fallback=None):
        def get_from_dict(d, k, f):
            try:
                if f:
                    return d.get(k, f)
                else:
                    return d[k]
            except KeyError:
                logger.warning(f'Could not read key from database because it does not exist: {k}')
                return None

        try:
            with self._get_db() as mirror_db:
                if isinstance(key, Iterable) and not isinstance(key, str):
                    return {get_from_dict(mirror_db, k, fallback) for k in key}
                else:
                    return get_from_dict(mirror_db, key, fallback)
        except Exception as e:
            logger.warning(f'Could not read from database (Key {key}). Exception: {e}')
            return None

    def get_keys(self, exclude: list[str] | None = None) -> set:
        if exclude is None:
            exclude = []
        try:
            with self._get_db() as mirror_db:
                keys = mirror_db.keys()
                if exclude is not None:
                    return {k for k in keys if not is_list_of_substr_in_str(exclude, k)}
                else:
                    return set(keys)
        except Exception as e:
            logger.warning(f'Could not read from database. Exception: {e}')
            return set()

    def remove(self, key):
        try:
            with self._get_db() as mirror_db:
                if key in mirror_db:
                    del mirror_db[key]
                return True
        except Exception as e:
            logger.warning(f'Could not remove key from database (Key {key}). Exception: {e}')
            return False
