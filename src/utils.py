import datetime
import os
import time
from collections.abc import Iterator
from enum import Enum

from logger import logger


class CompareMethod(Enum):
    METADATA = 'metadata'
    CONTENT = 'content'


class DirectoryPair:
    def __init__(self, source: str, target: str):
        if not isinstance(source, str) or not isinstance(target, str):
            raise TypeError('Both source and target must be strings.')
        self.source = source
        self.target = target

    def __iter__(self) -> Iterator[str]:
        return iter((self.source, self.target))


def get_size(path: str | list[str], as_str=True) -> float | str:
    def get_single_size(path_) -> int:
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


def time_diff_to_min(start_time: float) -> str:
    return f'{int((time.time() - start_time) / 60)} minutes'


class Counter:
    def __init__(self, init_value=-1):
        self.v = init_value

    def get(self, increment=True):
        if increment:
            self.v += 1
        return self.v


def check_length(p):
    return f'File path of source and/or target is too long ({len(p)})' if len(p) > 259 else ''


def log_progress(progress: int, total: int | None, start_time: float, interval=1000, speed_type=''):
    if speed_type:
        speed_type += ' '

    if progress > 0 and progress % interval == 0:
        speed_files_p_min = int(60 * progress / (time.time() - start_time))
        msgs = []
        if total is not None:
            msgs.append(f'{progress} of {total} files so far.')
        else:
            msgs.append(f'{progress} files so far.')

        msgs.append(f'Avg. {speed_type}speed: {speed_files_p_min} files/min.')
        if total is not None:
            msgs.append(f'ETL: {int((total - progress) / speed_files_p_min)} min')
        logger.debug(' '.join(msgs))


def is_list_of_substr_in_str(l: list[str], s: str) -> bool:
    return any(substr in s for substr in l)
