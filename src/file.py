import datetime
import filecmp
import hashlib
import os
import time
from collections import namedtuple
from os import PathLike
from pathlib import Path
from typing import NewType, Union

from logger import logger
from utils import (
    CompareMethod,
    check_length,
    format_size,
    is_list_of_substr_in_str,
    log_progress,
    format_elapsed_time,
)

CstmPathType = Union[str, PathLike[str], 'CstmPath']
StatHash = NewType('StatHash', str)
StableStats = namedtuple('StableStats', ['st_size', 'st_mtime'])


class CustomException(Exception):
    pass


def _encode_stats(stats: StableStats) -> StatHash:
    return StatHash(hashlib.blake2b(str(stats).encode(), digest_size=8).hexdigest())


def _get_stats(path: CstmPathType) -> StableStats:
    try:
        stats = os.stat(path)
    except Exception as e:
        # logger.warning(f'Could not get stats of {path}. Exception: {e}')
        raise e

    stable_stats = StableStats(stats.st_size, stats.st_mtime)
    return stable_stats


def get_encoded_stats(path: CstmPathType) -> StatHash:
    return _encode_stats(_get_stats(path))


class CstmPath(Path):
    def __init__(self, *paths: CstmPathType, root_dir: CstmPathType | None = None):
        super().__init__(*paths)
        self._root_dir = Path(root_dir) if root_dir else None
        self._rel_to_root = Path(self).relative_to(self._root_dir) if self._root_dir else None

        if self._root_dir and self._root_dir not in self.parents:
            raise CustomException(f'Root directory {self._root_dir} is not a parent of {self}')
        self._stats: None | StableStats = None  # Cached stats
        self._encoded_stats: None | StatHash = None  # Cached encoded stats

    def check_length(self) -> str:
        return f'File path is too long ({len(str(self))}): {self}' if len(str(self)) > 255 else ''

    @property
    def rel_to_root(self) -> str:
        return str(self._rel_to_root)

    @property
    def stats(self) -> StableStats:
        if self._stats is None:
            try:
                self._stats = _get_stats(self)
            except Exception as e:
                # logger.warning(f'Could not get stats of {self}. Exception: {e}')
                raise e
        return self._stats

    @property
    def encoded_stats(self) -> StatHash:
        if self._encoded_stats is None:
            self._encoded_stats = _encode_stats(self.stats)
        return self._encoded_stats

    def get_st_size(self, as_str=False) -> str | int:
        size_ = self.stats.st_size
        return format_size(size_) if as_str else size_

    def get_st_mtime(self, as_date_str=False) -> str | float:
        time_ = self.stats.st_mtime
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
                        all_paths.add(CstmPath(abs_path, root_dir=dir_path))
                        log_progress(len(all_paths), None, t1, interval=5000)
        logger.info(f'Finished scanning {dir_path} with {len(all_paths):,} files in {format_elapsed_time(t1)}.')
        return all_paths

    def __truediv__(self, other: CstmPathType) -> 'CstmPath':
        """Override the / operator to ensure compatibility with Path objects."""
        combined_path = Path(self) / other
        return CstmPath(combined_path, root_dir=self._root_dir)

    def __rtruediv__(self, other: CstmPathType) -> 'CstmPath':
        """Handle reverse division to preserve CstmPath attributes."""
        combined_path = Path(other) / self
        return CstmPath(combined_path, root_dir=self._root_dir)


class File:
    """
    Class representing a file with source and/or target paths.
    Target path can be from target directory or a mirror
    """

    def __init__(
        self, source: CstmPathType | None = None, target: CstmPathType | None = None, missing_target_root_dir=None
    ):
        self.source = None if source is None else source if isinstance(source, CstmPath) else CstmPath(source)
        self.target = None if target is None else target if isinstance(target, CstmPath) else CstmPath(target)

        if source is None and target is None:
            raise CustomException('Both source and target cannot be None.')

        if self.source and self.target and self.source.rel_to_root != self.target.rel_to_root:
            raise CustomException(f'Source and target paths do not match: {self.source} vs {self.target}')

        self.missing_target: CstmPath | None = None
        if self.source is not None and self.target is None:
            if missing_target_root_dir is None:
                raise CustomException('Missing target root directory for missing target path.')
            self.missing_target = CstmPath(
                missing_target_root_dir, self.source.rel_to_root, root_dir=missing_target_root_dir
            )

        self.rel_path: str = self.source.rel_to_root if self.source else self.target.rel_to_root if self.target else ''
        self._compare_success: bool | None = None  # Placeholder for comparison success status
        self._same: bool | None = None  # Placeholder for change status

    @property
    def any_path(self) -> str:
        return str(self.source) if self.source else str(self.target) if self.target else ''

    @property
    def name(self) -> str:
        return self.source.name if self.source else self.target.name if self.target else ''

    def __str__(self):
        return f'File(source={self.source}, target={self.target})'

    def __repr__(self):
        return f'File(source={self.source}, target={self.target})'

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, File):
            return NotImplemented
        return self.source == other.source and self.target == other.target

    @property
    def only_source(self) -> bool:
        return self.source is not None and self.target is None

    @property
    def only_target(self) -> bool:
        return self.source is None and self.target is not None

    @property
    def in_both(self) -> bool:
        return self.source is not None and self.target is not None

    @property
    def same(self) -> bool:
        if self._same is None:
            raise CustomException('Comparison has not been performed yet.')
        return self._same

    @property
    def modified(self) -> bool:
        if self._same is None:
            raise CustomException('Comparison has not been performed yet.')
        return not self._same

    @property
    def compare_error(self) -> bool:
        if not self.in_both:
            return False
        if self._same is None:
            raise CustomException('Comparison has not been performed yet.')
        return not self._compare_success

    def compare(self, compare_method: CompareMethod = CompareMethod.METADATA) -> None:
        if self._compare_success is None:
            if self.source and self.target:
                self._compare_success, self._same = compare_files(
                    self.source, self.target, comparison_method=compare_method
                )
            else:
                raise CustomException(f'Cannot compare files {self.source} and {self.target}. One of them is None.')


def compare_files(
    f1: CstmPath, f2: CstmPath, comparison_method: CompareMethod = CompareMethod.METADATA
) -> tuple[bool, bool]:
    same = False
    success = False

    try:
        if comparison_method == CompareMethod.METADATA:
            same = f1.stats == f2.stats
        elif comparison_method == CompareMethod.CONTENT:
            same = filecmp.cmp(f1, f2, False)
        else:
            raise CustomException(f'Unknown comparison method: {comparison_method}')
        success = True
    except Exception as e:
        error_msg = check_length(f1) + '  ' + check_length(f2)
        error_msg = e if error_msg.strip() == '' else e
        logger.warning(f'Could not compare files <{f1}> and <{f2}>. Exception: {error_msg}')
    return success, same
