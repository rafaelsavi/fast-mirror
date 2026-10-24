import datetime
import filecmp
import hashlib
import os
import time
from collections import namedtuple
from os import PathLike
from pathlib import Path
from typing import NewType, Union

import pathspec

from utils.logger import logger
from utils.utils import (
    CompareMethod,
    check_length,
    format_elapsed_time,
    format_size,
    log_progress,
)

CstmPathType = Union[str, PathLike[str], 'CstmPath']
StatsHash = NewType('StatsHash', str)
Stats = namedtuple('Stats', ['st_size', 'st_mtime'])


class CustomException(Exception):
    pass


def _encode_stats(stats: Stats) -> StatsHash:
    return StatsHash(hashlib.blake2b(str(stats).encode(), digest_size=8).hexdigest())


def _get_stats(path: CstmPathType) -> Stats:
    try:
        stats = os.stat(path)
    except Exception as e:
        # logger.warning(f'Could not get stats of {path}. Exception: {e}')
        raise e

    stable_stats = Stats(stats.st_size, stats.st_mtime)
    return stable_stats


def get_stats_hash(path: CstmPathType) -> StatsHash:
    return _encode_stats(_get_stats(path))


class CstmPath(Path):
    def __init__(
        self,
        *paths: CstmPathType,
        root_dir: CstmPathType | None = None,
        stats_hash: StatsHash | None = None,
        stats: Stats | None = None,
        is_new_target: bool = False,
    ):
        super().__init__(*paths)
        self.root_dir = Path(root_dir) if root_dir else None
        self._rel_to_root = Path(self).relative_to(self.root_dir) if self.root_dir else None

        if self.root_dir and self.root_dir not in self.parents:
            raise CustomException(f'Root directory {self.root_dir} is not a parent of {self}')
        self._stats: Stats | None = stats  # Cached stats
        self._stats_hash: StatsHash | None = stats_hash  # Cached encoded stats
        self._is_new_target: bool = is_new_target
        self._stat_failed: bool = is_new_target

    def check_length(self) -> str:
        return f'File path is too long ({len(str(self))}): {self}' if len(str(self)) > 255 else ''

    @property
    def rel_to_root(self) -> str:
        return str(self._rel_to_root)

    @property
    def stats(self) -> Stats:
        if self._stats is None:
            if getattr(self, '_stat_failed', False) or getattr(self, '_is_new_target', False):
                raise FileNotFoundError(f'Stats not available for non-existent path: {self}')
            try:
                self._stats = _get_stats(self)
            except Exception as e:
                self._stat_failed = True
                raise e
        return self._stats

    @property
    def stats_hash(self) -> StatsHash:
        if self._stats_hash is None:
            self._stats_hash = _encode_stats(self.stats)
        return self._stats_hash

    def refresh_stats(self) -> Stats:
        """Reset cached stats and re-read fresh metadata from disk."""
        self._stats = None
        self._stats_hash = None
        self._is_new_target = False
        self._stat_failed = False
        return self.stats

    def get_st_size(self, as_str=False) -> str | int:
        size_ = self.stats.st_size
        return format_size(size_) if as_str else size_

    def get_st_mtime(self, as_date_str=False) -> str | float:
        time_ = self.stats.st_mtime
        return self.to_date_str(time_) if as_date_str else time_

    def as_target(self, dirs: list[tuple[CstmPathType, CstmPathType]]) -> 'CstmPath':
        dirs_dict = {Path(source_dir): Path(target_dir) for source_dir, target_dir in dirs}
        if self.root_dir is None or self._rel_to_root is None:
            raise CustomException('Root directory is not set. Cannot convert to target path.')
        if self.root_dir not in dirs_dict:
            raise CustomException(f'Root directory {self.root_dir} is not in the list of directories.')

        target_root_dir = dirs_dict[self.root_dir]
        return CstmPath(target_root_dir / self._rel_to_root)

    @staticmethod
    def to_date_str(timestamp):
        if timestamp == 0:
            return ''
        else:
            return datetime.datetime.fromtimestamp(timestamp).strftime('%Y/%m/%d %H:%M:%S')

    @staticmethod
    def get_from_dir(dir_path: CstmPathType, exclude: list[str]) -> set['CstmPath']:
        logger.info(f"Scanning files from '{dir_path}'. This may take a while")
        # pathspec needs frontslashes
        spec = pathspec.PathSpec.from_lines('gitwildmatch', map(lambda x: x.replace('\\', '/'), exclude))
        all_paths: set[CstmPath] = set()
        start_time = time.time()

        base_path = Path(dir_path)
        stack = [base_path]

        while stack:
            curr_dir = stack.pop()
            rel_dir = curr_dir.relative_to(base_path)

            try:
                with os.scandir(curr_dir) as entries:
                    for entry in entries:
                        name = entry.name
                        if name.endswith('.tmp') or '.tmp.' in name:
                            continue

                        rel_entry = rel_dir / name
                        rel_posix = rel_entry.as_posix()

                        try:
                            if entry.is_dir(follow_symlinks=False):
                                # Skip directory if excluded by pattern
                                if not (spec.match_file(rel_posix) or spec.match_file(rel_posix + '/')):
                                    stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False) and not spec.match_file(rel_posix):
                                st = entry.stat()
                                stable_stats = Stats(st.st_size, st.st_mtime)
                                p = CstmPath(entry.path, root_dir=dir_path, stats=stable_stats)
                                all_paths.add(p)
                                log_progress('Scanned', len(all_paths), None, start_time, interval=10_000)
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, OSError) as e:
                logger.warning(f"Could not scan directory '{curr_dir}': {e}")

        logger.info(
            f"Finished scanning '{dir_path}' with {len(all_paths):,} files in {format_elapsed_time(start_time)}."
        )
        return all_paths

    def __truediv__(self, other: CstmPathType) -> 'CstmPath':
        """Override the / operator to ensure compatibility with Path objects."""
        combined_path = Path(self) / other
        return CstmPath(combined_path, root_dir=self.root_dir)

    def __rtruediv__(self, other: CstmPathType) -> 'CstmPath':
        """Handle reverse division to preserve CstmPath attributes."""
        combined_path = Path(other) / self
        return CstmPath(combined_path, root_dir=self.root_dir)


class File:
    """
    Class representing a file with source and/or target paths.
    Target path can be from target directory or a mirror
    """

    def __init__(
        self,
        source: CstmPathType | None = None,
        target: CstmPathType | None = None,
        missing_target_root_dir: str | None = None,
        compare_success: bool | None = None,
        same: bool | None = None,
    ):
        self.source = None if source is None else source if isinstance(source, CstmPath) else CstmPath(source)
        self.target = None if target is None else target if isinstance(target, CstmPath) else CstmPath(target)
        self.missing_target_root_dir = missing_target_root_dir

        if source is None and target is None:
            raise CustomException('Both source and target cannot be None at the same time.')

        self._compare_success: bool | None = compare_success  # Placeholder for comparison success status
        self._same: bool | None = same  # Placeholder for change status

    @property
    def source_as_target(self) -> CstmPath:
        if self.source is None:
            raise CustomException('Source is not set. Cannot convert source to target path.')

        if self.missing_target_root_dir is not None:
            target_root_dir = Path(self.missing_target_root_dir)
        elif self.target is not None:
            if self.target.root_dir is None:
                raise CustomException('Target root directory is not set. Cannot convert source to target path.')
            target_root_dir = self.target.root_dir
        else:
            raise CustomException(
                'Neither target nor missing_target_root_dir is set. Cannot convert source to target path.'
            )
        return CstmPath(target_root_dir / self.source.rel_to_root, root_dir=target_root_dir, is_new_target=True)

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
    def moved(self) -> bool:
        return (
            self.source is not None and self.target is not None and self.source.rel_to_root != self.target.rel_to_root
        )

    @property
    def same(self) -> bool:
        if not self.in_both:
            return False
        if self._same is None:
            raise CustomException('Comparison has not been performed yet.')
        return self._same

    @property
    def modified(self) -> bool:
        if not self.in_both:
            return False
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
                raise CustomException(f"Cannot compare files '{self.source}' and '{self.target}'. One of them is None.")


def compare_files(
    f1: CstmPath, f2: CstmPath, comparison_method: CompareMethod = CompareMethod.METADATA
) -> tuple[bool, bool]:
    same = False
    success = False

    try:
        if comparison_method == CompareMethod.METADATA:
            same = f1.stats_hash == f2.stats_hash
        elif comparison_method == CompareMethod.CONTENT:
            same = filecmp.cmp(f1, f2, False)
        else:
            raise CustomException(f'Unknown comparison method: {comparison_method}')
        success = True
    except Exception as e:
        error_msg = check_length(f1) + '  ' + check_length(f2)
        error_msg = e if error_msg.strip() == '' else e
        logger.warning(f"Could not compare files '{f1}' and '{f2}'. Exception: {error_msg}")
    return success, same
