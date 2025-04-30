import base64
import datetime
import filecmp
import hashlib
import os
import time
from collections.abc import Iterable

from src.logger import logger


def get_size(path: str | list[str], as_str=True) -> float | str:
    def get_single_size(path_):
        try:
            return os.path.getsize(path_)
        except FileNotFoundError:
            return 0
        except Exception as e:
            logger.warning(f'Could not get size of {path_}. Exception: {e}')
            return 0

    size_bytes = 0
    if type(path) == str:
        size_bytes = get_single_size(path)
    elif type(path) == list:
        size_bytes = sum([get_single_size(x) for x in path])

    if as_str:
        return format_size(size_bytes)
    else:
        return size_bytes


def format_size(size_bytes: float) -> str:
    if size_bytes < 1024**2:
        msg = f'{size_bytes / (1024**1):.2f}KB'
    elif 1024**2 <= size_bytes < 1024**3:
        msg = f'{size_bytes / (1024**2):.2f}MB'
    else:
        msg = f'{size_bytes / (1024**3):.2f}GB'

    return msg


def round_time_to_minutes(time_: datetime) -> datetime:
    return time_ - datetime.timedelta(seconds=time_.second, microseconds=time_.microsecond)


class Counter:
    def __init__(self, init_value=-1):
        self.v = init_value

    def get(self, increment=True):
        if increment:
            self.v += 1
        return self.v


def check_length(p):
    return f'File path of origin and/or destination is too long ({len(p)})' if len(p) > 259 else ''


def encode_stats(stats):
    return base64.b64encode(hashlib.md5(str(stats).encode()).digest())[:8]


class CustomException(Exception):
    pass


class Path:
    def __init__(self, abs_path=None, root_dir='', rel_path=None):
        if rel_path is not None:
            abs_path = os.path.join(root_dir, rel_path)
        if type(abs_path) == Path:
            abs_path = abs_path.get()
        self._abs_path = os.path.normpath(os.path.realpath(abs_path))
        self._root_dir = os.path.normpath(os.path.realpath(root_dir))
        self._rel_path = os.path.relpath(abs_path, root_dir)
        self._stats = None  # Filled when called first time
        self._encoded_stats = None  # Filled when called first time

    def check_length(self):
        return f'File path is too long ({len(self.get())}): {self.get()}' if len(self.get()) > 259 else ''

    def get(self):
        return self._abs_path

    def get_rel(self):
        return self._rel_path

    def get_basename(self):
        return os.path.basename(self._abs_path)

    def exists(self):
        return os.path.exists(self._abs_path)

    def get_stats(self) -> dict:
        if self._stats is None:
            if self.exists():
                stats = os.stat(self._abs_path)
                self._stats = {k: getattr(stats, k) for k in dir(stats) if k.startswith('st_')}
            else:
                self._stats = {}

        return self._stats

    def get_encoded_stats(self) -> str:
        if self._encoded_stats is None:
            self._encoded_stats = encode_stats(self.get_stats())

        return self._encoded_stats

    def getsize(self, as_str=False):
        size_ = self.get_stats().get('st_size', 0)
        if as_str:
            return format_size(size_)
        else:
            return size_

    def getmtime(self, as_date_str=False):
        time_ = self.get_stats().get('st_mtime', 0)
        if as_date_str:
            return self.to_date_str(time_)
        else:
            return time_

    def getctime(self, as_date_str=False):
        time_ = self.get_stats().get('st_ctime', 0)
        if as_date_str:
            return self.to_date_str(time_)
        else:
            return time_

    def remove(self):
        os.remove(self._abs_path)

    def change_root_dir(self, new_root_dir: str) -> 'Path':
        return Path(root_dir=new_root_dir, rel_path=self._rel_path)

    def __repr__(self):
        return str(self._abs_path)

    def as_target(self, dirs: list[tuple[str, str]]) -> 'Path':
        dirs = {k: v for k, v in dirs}
        target_root_dir = dirs.get(self._root_dir, self._root_dir)
        return self.change_root_dir(target_root_dir)

    def is_in_list_of_lists(self, l: Iterable[Iterable['Path']], check_relative_paths=False):
        if check_relative_paths:
            return self.get_rel() in [f.get_rel() for sub_l in l for f in sub_l]
        else:
            return self in [f for sub_l in l for f in sub_l]

    @staticmethod
    def to_date_str(timestamp):
        if timestamp == 0:
            return ''
        else:
            return datetime.datetime.fromtimestamp(timestamp).strftime('%Y/%m/%d %H:%M:%S')

    @classmethod
    def get_from_dir(cls, dir_path: str, exclude: list[str]) -> set['Path']:
        logger.info(f'Scanning files from {dir_path}. This may take a while')
        all_paths = set()
        t1 = time.time()
        for root, _dirs, files in os.walk(dir_path):
            if not is_list_of_substr_in_str(exclude, root):
                for file in files:
                    abs_path = os.path.join(root, file)
                    if not is_list_of_substr_in_str(exclude, abs_path):
                        all_paths.add(Path(abs_path, dir_path))
                        if len(all_paths) % 5000 == 0:
                            logger.debug(
                                f'{len(all_paths)} files found so far. '
                                f'Average read speed: {int(60 * len(all_paths) / (time.time() - t1))} files/min'
                            )
        logger.info(
            f'Finished scanning {dir_path} with {len(all_paths)} files in {int((time.time() - t1) / 60)} minutes'
        )
        return all_paths


def is_list_of_substr_in_str(l, s):
    return any([substr in s for substr in l])


def compare_files(f1, f2, light=False) -> tuple[bool, bool]:
    same = False
    success = False
    try:
        if light:
            same_metadata = os.path.getmtime(f1) == os.path.getmtime(f2) and os.path.getsize(f1) == os.path.getsize(f2)
            same = True if same_metadata else filecmp.cmp(f1, f2, False)
        else:
            same = filecmp.cmp(f1, f2, False)
        success = True
    except Exception as e:
        error_msg = check_length(f1) + '  ' + check_length(f2)
        error_msg = e if error_msg.strip() == '' else e
        logger.warning(f'Could not compare files <{f1}> and <{f2}>. Exception: {error_msg}')
    return success, same


def fake_task(task_name):
    logger.warning(f'Taking longer to {task_name}')
    for i in range(7000000):
        i**2
    logger.warning(f'{task_name} finished')
