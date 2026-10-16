import datetime
import os
import time
from collections.abc import Iterator
from enum import Enum
from os import PathLike

from utils.logger import logger


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

    def __repr__(self) -> str:
        return f'DirectoryPair(source={self.source!r}, target={self.target!r})'

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DirectoryPair):
            return self.source == other.source and self.target == other.target
        return False

    def __hash__(self) -> int:
        return hash((self.source, self.target))


def get_size(path: str | list[str]) -> float:
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

    return size_bytes


def get_size_as_str(path: str | list[str]) -> str:
    return format_size(get_size(path))


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


def format_elapsed_time(start_time: float) -> str:
    """Format the time difference from start_time to now, showing only nonzero hours/minutes."""
    elapsed = int(time.time() - start_time)
    h, rem = divmod(elapsed, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h > 0:
        parts.append(f'{h}h')
    if m > 0 or h > 0:  # show minutes if hours > 0, even if minutes == 0
        parts.append(f'{m}m')
    parts.append(f'{s}s')
    return ' '.join(parts)


def check_length(p):
    return f'File path of source and/or target is too long ({len(str(p))})' if len(str(p)) > 259 else ''


def log_progress(
    action: str, progress: int, total: int | None, start_time: float, interval=10000, cstm_msg: str | None = None
):
    if progress == 0 or progress % interval != 0:
        return

    if action:
        action += ' '
    total_str = f' of {total:,}' if total is not None else ''

    speed_files_p_min = int(60 * progress / (time.time() - start_time))
    msgs = []
    msgs.append(f'{action}{progress:,}{total_str} files so far.')
    msgs.append(f'Average speed: {speed_files_p_min:,} files/min.')
    if cstm_msg:
        msgs.append(cstm_msg)

    if total is not None:
        msgs.append(f'ETL: {int((total - progress) / speed_files_p_min):,} min')

    logger.info(' '.join(msgs))


def sanitize_path(path: str | PathLike) -> str:
    return str(path).replace('/', '\\')
