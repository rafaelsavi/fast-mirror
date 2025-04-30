import base64
import datetime
import filecmp
import hashlib
import os
import time
from os import PathLike, stat_result
from pathlib import Path
from typing import NewType, Union

from logger import logger

StatHash = NewType('StatHash', str)


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
    if isinstance(path, str):
        size_bytes = get_single_size(path)
    elif isinstance(path, list):
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


def round_time_to_minutes(time_: datetime.datetime) -> datetime.datetime:
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


CstmPathType = Union[str, PathLike[str], 'CstmPath']


def encode_stats(stats: stat_result) -> StatHash:
    return StatHash(hashlib.blake2b(str(stats).encode(), digest_size=8).hexdigest())


def get_encoded_stats(path: CstmPathType) -> StatHash:
    try:
        stats = os.stat(path)
        return encode_stats(stats)
    except Exception as e:
        logger.warning(f'Could not get stats of {path}. Exception: {e}')
        raise e


def log_progress(progress: int, total: int | None, start_time: float, interval=1000):
    if progress > 0 and progress % interval == 0:
        speed_files_p_min = int(60 * progress / (time.time() - start_time))
        msgs = []
        if total is not None:
            msgs.append(f'{progress} of {total} files scanned so far.')
        else:
            msgs.append(f'{progress} files scanned so far.')
        msgs.append(f'Avg. read speed: {speed_files_p_min} files/min.')
        if total is not None:
            msgs.append(f'ETL: {int((total - progress) / speed_files_p_min)} min')
        logger.debug(' '.join(msgs))


class CustomException(Exception):
    pass


class CstmPath(Path):
    def __init__(self, path: CstmPathType, root_dir: CstmPathType | None = None):
        super().__init__(path)
        self._root_dir = Path(root_dir) if root_dir else None
        self._rel_to_root = Path(self).relative_to(self._root_dir) if self._root_dir else None

        if self._root_dir and self._root_dir not in self.parents:
            raise CustomException(f'Root directory {self._root_dir} is not a parent of {self}')
        self._stats: None | str = None  # Cached stats
        self._encoded_stats: None | str = None  # Cached encoded stats

    def check_length(self):
        return f'File path is too long ({len(str(self))}): {self}' if len(str(self)) > 255 else ''

    def get_rel(self):
        return str(self._rel_to_root)

    def get_encoded_stats(self) -> StatHash:
        if self._encoded_stats is None:
            self._encoded_stats = encode_stats(self.stat())
        return self._encoded_stats

    def getsize(self, as_str=False) -> str | int:
        size_ = self.stat().st_size
        return format_size(size_) if as_str else size_

    def getmtime(self, as_date_str=False) -> str | float:
        time_ = self.stat().st_mtime
        return self.to_date_str(time_) if as_date_str else time_

    def getctime(self, as_date_str=False) -> str | float:
        time_ = self.stat().st_ctime
        return self.to_date_str(time_) if as_date_str else time_

    def as_target(self, dirs: list[tuple[CstmPathType, CstmPathType]]) -> 'CstmPath':
        dirs_dict = {Path(source_dir): Path(target_dir) for source_dir, target_dir in dirs}
        if self._root_dir is None or self._rel_to_root is None:
            raise CustomException('Root directory is not set. Cannot convert to target path.')
        if self._root_dir not in dirs_dict:
            raise CustomException(f'Root directory {self._root_dir} is not in the list of directories.')

        target_root_dir = dirs_dict[self._root_dir]
        return CstmPath(target_root_dir / self._rel_to_root)

    @staticmethod
    def to_date_str(timestamp):
        if timestamp == 0:
            return ''
        else:
            return datetime.datetime.fromtimestamp(timestamp).strftime('%Y/%m/%d %H:%M:%S')

    @classmethod
    def get_from_dir(cls, dir_path: CstmPathType, exclude: list[str]) -> set['CstmPath']:
        logger.info(f'Scanning files from {dir_path}. This may take a while')
        all_paths = set()
        t1 = time.time()
        for root, _dirs, files in os.walk(dir_path):
            if not is_list_of_substr_in_str(exclude, root):
                for file in files:
                    abs_path = Path(root) / file
                    if not is_list_of_substr_in_str(exclude, str(abs_path)):
                        all_paths.add(CstmPath(abs_path, dir_path))
                        log_progress(len(all_paths), None, t1, interval=5000)
        logger.info(
            f'Finished scanning {dir_path} with {len(all_paths)} files in {int((time.time() - t1) / 60)} minutes'
        )
        return all_paths

    def __truediv__(self, other: CstmPathType) -> 'CstmPath':
        """Override the / operator to ensure compatibility with Path objects."""
        combined_path = Path(self) / other
        return CstmPath(combined_path, root_dir=self._root_dir)

    def __rtruediv__(self, other: CstmPathType) -> 'CstmPath':
        """Handle reverse division to preserve CstmPath attributes."""
        combined_path = Path(other) / self
        return CstmPath(combined_path, root_dir=self._root_dir)


def is_list_of_substr_in_str(l: list[str], s: str) -> bool:
    return any(substr in s for substr in l)


def compare_files(f1: CstmPathType, f2: CstmPathType, light=False) -> tuple[bool, bool]:
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
