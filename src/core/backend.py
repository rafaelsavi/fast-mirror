import contextlib
import datetime
import filecmp
import inspect
import os
import threading
import time
import tkinter as tk
from collections import Counter
from collections.abc import Callable
from copy import copy
from typing import Any

import pandas as pd

from core.file import CstmPath, File, compare_files
from core.file_ops import (
    robust_copy,
    robust_delete,
    robust_move,
)
from core.mirror import MirrorDatabase
from core.path_resolver import (
    _to_path,
    get_dirs_from_path,
)
from gui.confirmation_popup import ActionSelection
from gui.widgets import Action
from utils.logger import logger
from utils.utils import (
    CompareMethod,
    DirectoryPair,
    check_length,
    format_elapsed_time,
    format_size,
    get_size,
    log_progress,
)

__all__ = [
    'CompareDirs',
    'SyncDirs',
]


class CompareDirs:
    def __init__(
        self,
        mirror: MirrorDatabase,
        dirs: list[DirectoryPair],
        exclusions: list[str],
        save_report: bool = False,
        comparison_method: CompareMethod = CompareMethod.METADATA,
        use_mirror=False,
        increment_mirror=True,
        rebuild_mirror=False,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
        cancel_requested: threading.Event | None = None,
    ):
        logger.info('-----------------------------')
        logger.info('Initializing comparison')
        logger.info('Directories:\n  ' + '\n  '.join([f'{d1}  -->  {d2}' for d1, d2 in dirs]))
        start_time = time.time()
        timestamp_str = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        self.save_report_path = os.path.join(logger.log_dir, 'compare_report_' + timestamp_str + '.xlsx')

        self.mirror = mirror
        self.dirs = dirs
        self.exclusions = exclusions
        self.comparison_method = comparison_method
        self.progress_callback = progress_callback
        self.cancel_requested = cancel_requested

        # Initialize comparison variables
        filecmp.clear_cache()
        self.files_in_source: dict[str, set[CstmPath]] = {}
        self.files_in_target: dict[str, set[CstmPath]] = {}
        self.linked_files: list[File] = []

        self.files_to_copy: list[tuple[CstmPath, CstmPath]] = []
        self.files_to_move: list[tuple[CstmPath, CstmPath]] = []
        self.files_to_delete: list[CstmPath] = []

        total_items = len(self.dirs) * 2

        self.scan_source_files()
        if self.cancel_requested and self.cancel_requested.is_set():
            logger.info('Comparison stopped upon cancellation request')
            return
        self.scan_target_files(use_mirror, increment_mirror, rebuild_mirror)
        if self.cancel_requested and self.cancel_requested.is_set():
            logger.info('Comparison stopped upon cancellation request')
            return
        if self.progress_callback:
            self.progress_callback('Comparing', total_items, total_items, '')
        self.link_files()
        if self.cancel_requested and self.cancel_requested.is_set():
            logger.info('Comparison stopped upon cancellation request')
            return
        self.compare_files()
        if self.cancel_requested and self.cancel_requested.is_set():
            logger.info('Comparison stopped upon cancellation request')
            return
        self.remove_compare_failures()

        self.get_files_to_copy()
        self.get_files_to_move()
        self.get_files_to_delete()

        self.print_results()
        if save_report and not (self.cancel_requested and self.cancel_requested.is_set()):
            self._save_report()

        # Estimate synchronization actions
        logger.info(f'Finished comparing directories in {format_elapsed_time(start_time)}')

    def scan_source_files(self):
        logger.info('Starting to scan source files')
        start_time = time.time()
        self.files_in_source = {}
        total_items = len(self.dirs) * 2
        for i, dir_pair in enumerate(self.dirs, 1):
            if self.cancel_requested and self.cancel_requested.is_set():
                logger.info('Scanning source files aborted due to cancellation request')
                break
            if self.progress_callback:
                self.progress_callback('Scanning', i, total_items, str(dir_pair.source))
            self.files_in_source[dir_pair.source] = CstmPath.get_from_dir(dir_pair.source, exclude=self.exclusions)
        num_files = sum(len(files) for files in self.files_in_source.values())
        logger.info(
            f'Finished scanning all source files. Found {num_files:,} files in {format_elapsed_time(start_time)}'
        )

    def scan_target_files(self, use_mirror: bool, increment_mirror: bool, rebuild_mirror: bool):
        logger.info('Starting to scan target files')
        if use_mirror and rebuild_mirror:
            raise Exception('Cannot use mirror and rebuild it at the same time.')
        if rebuild_mirror and increment_mirror:
            raise Exception('Cannot increment mirror and rebuild it at the same time.')

        start_time = time.time()
        total_items = len(self.dirs) * 2
        source_offset = len(self.dirs)
        for i, dir_pair in enumerate(self.dirs, 1):
            if self.cancel_requested and self.cancel_requested.is_set():
                logger.info('Scanning target files aborted due to cancellation request')
                break
            current_step = source_offset + i
            if self.progress_callback:
                self.progress_callback('Scanning', current_step, total_items, str(dir_pair.target))
            mirror_exists = self.mirror.exists_table(dir_pair.target)
            if rebuild_mirror and mirror_exists:
                self.mirror.reset(dir_pair.target)

            if use_mirror and mirror_exists:
                logger.info(
                    f"Using mirror for '{dir_pair.target}'. Table has {self.mirror.size(dir_pair.target):,} entries"
                )
                self.files_in_target[dir_pair.target] = self.mirror.get_paths(root_dir=dir_pair.target)
                continue

            if use_mirror and not mirror_exists:
                logger.warning(
                    f"Mirror does not exist for target directory '{dir_pair.target}'. Using file system instead."
                )

            logger.info(f"Using file system to scan target directory '{dir_pair.target}'")
            self.files_in_target[dir_pair.target] = CstmPath.get_from_dir(dir_pair.target, exclude=self.exclusions)

            if increment_mirror or rebuild_mirror:
                logger.info(f'Adding {len(self.files_in_target[dir_pair.target]):,} files to mirror')
                self.mirror.add_path(dir_pair.target, self.files_in_target[dir_pair.target])
                size = self.mirror.size(dir_pair.target)
                logger.info(f"Mirror cache updated and saved for '{dir_pair.target}' ({size:,} entries)")

        num_files = sum(len(files) for files in self.files_in_target.values())
        logger.info(
            f'Finished scanning all target files. Found {num_files:,} files in {format_elapsed_time(start_time)}'
        )

    def link_files(self):
        """Link files in source and target directories to a single File object"""
        logger.info('Starting to link source and target files')
        self.linked_files = []

        for dir_pair in self.dirs:
            if self.cancel_requested and self.cancel_requested.is_set():
                logger.info('Linking files aborted due to cancellation request')
                break
            files_in_source = copy(self.files_in_source.get(dir_pair.source, set()))
            files_in_target = copy(self.files_in_target.get(dir_pair.target, set()))

            logger.info(
                f"Linking '{dir_pair.source}' ({len(files_in_source):,} files) and "
                f"'{dir_pair.target}' ({len(files_in_target):,} files)"
            )

            ################################
            logger.info('Searching for files that share the same relative path in both directories')
            start_time = time.time()
            linked_files: list[File] = []
            target_rel_paths = {f.rel_to_root: f for f in files_in_target}

            n_files = len(files_in_source)
            for i, source_file in enumerate(copy(files_in_source), 1):
                if self.cancel_requested and self.cancel_requested.is_set():
                    break
                log_progress('Linked', i, n_files, start_time, interval=10_000)
                target_file = target_rel_paths.get(source_file.rel_to_root, None)
                if target_file is not None:
                    linked_files.append(File(source=source_file, target=target_file))
                    # Remove linked files from both sets to avoid double counting
                    files_in_source.remove(source_file)
                    files_in_target.remove(target_file)

            logger.info(f'Found {len(linked_files):,} files that share the same relative path in both directories')
            self.linked_files += linked_files

            ################################
            logger.info('Searching for files that share the same name and are the same, but have different paths')
            start_time = time.time()
            linked_files: list[File] = []

            # Only use files with unique .name in source and target
            source_name_counts = Counter(f.name for f in files_in_source)
            target_name_counts = Counter(f.name for f in files_in_target)
            target_filenames = {
                f.name: f
                for f in files_in_target
                if target_name_counts[f.name] == 1 and source_name_counts.get(f.name, 0) == 1
            }

            n_files = len(files_in_source)
            for i, source_file in enumerate(copy(files_in_source), 1):
                if self.cancel_requested and self.cancel_requested.is_set():
                    break
                log_progress('Linked', i, n_files, start_time, interval=10_000)
                # Check if the file name exists in both source and target
                if source_file.name in target_filenames:
                    target_file = target_filenames[source_file.name]
                    success, same = compare_files(source_file, target_file, comparison_method=self.comparison_method)
                    if success and same:
                        if not target_file.has_cached_stats and source_file.has_cached_stats:
                            target_file.copy_stats_from(source_file)
                        linked_files.append(
                            File(source=source_file, target=target_file, compare_success=success, same=same)
                        )
                        files_in_source.remove(source_file)
                        files_in_target.remove(target_file)

            logger.info(f'Found {len(linked_files):,} files that share the same name and are the same')
            self.linked_files += linked_files

            ################################
            logger.info('Searching for files that exist only in source directory')
            linked_files = [
                File(source=source_file, target=None, missing_target_root_dir=dir_pair.target)
                for source_file in files_in_source
            ]
            logger.info(f'Found {len(linked_files):,} files that exist only in source directory')
            self.linked_files += linked_files

            ################################
            logger.info('Searching for files that exist only in target directory')
            linked_files = [File(source=None, target=target_file) for target_file in files_in_target]
            logger.info(f'Found {len(linked_files):,} files that exist only in target directory')
            self.linked_files += linked_files

        self.linked_files = list(sorted(self.linked_files, key=lambda x: x.any_path))

    def compare_files(self):
        """Compare files that exist in both places and check for newer versions in the source"""
        files_in_both = [f for f in self.linked_files if f.in_both and not f.moved]
        n_files = len(files_in_both)
        if not n_files:
            logger.info('Not comparing any file since there are no files existing in both directories')
            return

        start_time = time.time()
        logger.info(f'Comparing {n_files:,} files that exist in both directories')
        for i, file in enumerate(files_in_both):
            if self.cancel_requested and self.cancel_requested.is_set():
                logger.info('Comparing files aborted due to cancellation request')
                break
            log_progress('Compared', i, n_files, start_time, interval=5_000)
            file.compare(self.comparison_method)

    def remove_compare_failures(self):
        """
        After all files existing in both are compared, some comparisons failed.
        Remove such files from the repository
        """
        failed_files = [f for f in self.linked_files if f.in_both and f.compare_error]
        if failed_files:
            logger.info(f'Removing {len(failed_files):,} files with compare errors from linked_files')
            self.linked_files = [f for f in self.linked_files if not (f.in_both and f.compare_error)]

    def get_files_to_copy(self):
        """
        Get files that need to be copied from source to target.
        These are files that only exist in source or that were modified
        """
        self.files_to_copy = []

        for f in self.linked_files:
            if f.only_source:
                self.files_to_copy.append((f.source, f.source_as_target))
            elif f.in_both and not f.moved and f.modified:
                self.files_to_copy.append((f.source, f.target))

    def get_files_to_move(self):
        """
        Get files that need to be moved from source to target.
        These are files that were moved and modified
        """
        self.files_to_move = []

        for f in self.linked_files:
            if f.moved:
                self.files_to_move.append((f.target, f.source_as_target))

        logger.info(f'Found {len(self.files_to_move):,} files that need to be moved')

    def get_files_to_delete(self):
        """
        Get files that need to be deleted from target.
        These are files that only exist in target
        """
        self.files_to_delete = list(sorted([f.target for f in self.linked_files if f.only_target]))

    def _save_report(self):
        logger.info('Loading data to create comparison report (ignoring files in both that are the same)')

        # Load all linked files and store as a dataframe where columns are file attributes
        df = pd.DataFrame(
            [
                {
                    'source': str(file.source) if file.source else '-',
                    'target': str(file.target) if file.target else '-',
                    'ext': file.source.suffix.lower()
                    if file.source
                    else file.target.suffix.lower()
                    if file.target
                    else '',
                    'in both': 'X' if file.in_both else '',
                    'same': 'X' if file.same else '',
                    'moved': 'X' if file.moved else '',
                    'modified': 'X' if file.in_both and file.modified else '',
                    'only source': 'X' if file.only_source else '',
                    'only target': 'X' if file.only_target else '',
                    'size (source)': file.source.get_st_size(as_str=True)
                    if file.source is not None and (file.source.has_cached_stats or file.source.exists())
                    else '',
                    'size (target)': file.target.get_st_size(as_str=True)
                    if file.target is not None
                    and (file.target.has_cached_stats or (not file.target.is_new_target and file.target.exists()))
                    else '',
                    'modified (source)': file.source.get_st_mtime(as_date_str=True)
                    if file.source is not None and (file.source.has_cached_stats or file.source.exists())
                    else '',
                    'modified (target)': file.target.get_st_mtime(as_date_str=True)
                    if file.target is not None
                    and (file.target.has_cached_stats or (not file.target.is_new_target and file.target.exists()))
                    else '',
                    'compare error': file.compare_error,
                }
                for file in self.linked_files
                if not (file.in_both and not file.moved and file.same)  # Ignore all same files
            ]
        )

        logger.info('Starting to write comparison report')
        os.makedirs(os.path.dirname(self.save_report_path), exist_ok=True)
        df.to_excel(self.save_report_path, index=False)
        logger.info(f"Comparison report was saved to '{self.save_report_path}'")

    def print_results(self):
        logger.info('-------------------------')
        logger.info('Analyzing directory tree:')
        logger.info(f'Files in source: {len([f for f in self.linked_files if f.source]):,}')
        logger.info(f'Files only in source: {len([f for f in self.linked_files if f.only_source]):,}')
        logger.info(f'Files in target: {len([f for f in self.linked_files if f.target]):,}')
        logger.info(f'Files only in target: {len([f for f in self.linked_files if f.only_target]):,}')
        same_count = len([f for f in self.linked_files if f.in_both and not f.moved and f.same])
        logger.info(f'Files in both and are the same: {same_count:,}')
        moved_count = len([f for f in self.linked_files if f.in_both and f.moved])
        logger.info(f'Files in both and are the same but moved: {moved_count:,}')
        modified_count = len([f for f in self.linked_files if f.in_both and not f.same])
        logger.info(f'Files in both and are modified: {modified_count:,}')
        paths_compare_error = [str(f) for f in self.linked_files if f.compare_error]
        logger.info(
            f'Files with comparing error: {len(paths_compare_error)}'
            + str({True: ': \n  ' + '\n  '.join(paths_compare_error), False: ''}.get(len(paths_compare_error) > 0))
        )


class SyncDirs:
    def __init__(
        self,
        files_to_copy: list[tuple[CstmPath, CstmPath]],
        files_to_move: list[tuple[CstmPath, CstmPath]],
        files_to_delete: list[CstmPath],
        mirror: MirrorDatabase,
        root_gui=None,
        dirs: list[DirectoryPair] | None = None,
        default_actions: list[Action] | None = None,
        increment_mirror=True,
        confirm_sync=True,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        backoff_factor: float = 2.0,
        progress_callback: Callable[[str, int, int, int, str, str], None] | None = None,
        cancel_requested: threading.Event | None = None,
    ):
        logger.info('---------------------------')
        logger.info('Initializing synchronization')

        # Input variables
        self.root_gui = root_gui
        self.mirror = mirror
        self.increment_mirror = increment_mirror
        self.dirs = dirs
        self.default_actions = default_actions if default_actions is not None else [Action.COPY]
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.backoff_factor = backoff_factor
        self.progress_callback = progress_callback
        self.cancel_requested = cancel_requested if cancel_requested is not None else threading.Event()

        # Initialize variables
        self.files_available_to_copy: list[tuple[CstmPath, CstmPath]] = files_to_copy
        self.files_available_to_move: list[tuple[CstmPath, CstmPath]] = files_to_move
        self.files_available_to_delete: list[CstmPath] = files_to_delete
        self.files_requested_to_copy: list[tuple[str, str]] = list()
        self.files_requested_to_move: list[tuple[str, str]] = list()
        self.files_requested_to_delete: list[str] = list()
        self.files_copied: list[tuple[tuple[str, str], bool]] = list()
        self.files_moved: list[tuple[tuple[str, str], bool]] = list()
        self.files_deleted: list[tuple[str, bool]] = list()

        if not self.files_available_to_copy and not self.files_available_to_move and not self.files_available_to_delete:
            logger.info('No files to synchronize')
            return

        if confirm_sync:
            if self.root_gui is None:
                raise ValueError('Cannot confirm sync without a valid root_gui')
            if not self.open_confirmation_popup():
                logger.info('Synchronization canceled by user. Mirror cache for target directories remains up-to-date.')
                return
        else:
            if Action.COPY in self.default_actions:
                self.files_requested_to_copy = [(str(f1), str(f2)) for f1, f2 in self.files_available_to_copy]
            if Action.MOVE in self.default_actions:
                self.files_requested_to_move = [(str(f1), str(f2)) for f1, f2 in self.files_available_to_move]
            if Action.DELETE in self.default_actions:
                self.files_requested_to_delete = [str(f) for f in self.files_available_to_delete]

        if self.cancel_requested.is_set():
            logger.info('Synchronization aborted due to cancellation request')
            return

        self.move_files()
        if self.cancel_requested.is_set():
            logger.info('Synchronization aborted due to cancellation request')
            return

        self.delete_files()
        if self.cancel_requested.is_set():
            logger.info('Synchronization aborted due to cancellation request')
            return

        self.copy_files()
        if self.cancel_requested.is_set():
            logger.info('Synchronization aborted due to cancellation request')
            return

        self.delete_empty_dirs()
        logger.info('Finished synchronizing directories')
        self.print_errors()

    def open_confirmation_popup(self):
        result_event = threading.Event()
        popup_holder: dict[str, ActionSelection] = {}

        def create_popup():
            popup = ActionSelection(
                self.root_gui,
                self.files_available_to_copy,
                self.files_available_to_move,
                self.files_available_to_delete,
                self.default_actions,
                on_close_callback=result_event.set,
            )
            popup_holder['popup'] = popup

        # Delegate widget creation to the main GUI thread
        self.root_gui.after(0, create_popup)

        try:
            while not result_event.is_set():
                if hasattr(self, 'cancel_requested') and self.cancel_requested.is_set():
                    return False
                result_event.wait(0.2)
        finally:
            if not result_event.is_set() or (hasattr(self, 'cancel_requested') and self.cancel_requested.is_set()):

                def cleanup_popup():
                    p = popup_holder.get('popup')
                    if p and hasattr(p, 'popup'):
                        try:
                            if p.popup.winfo_exists():
                                p.popup.destroy()
                        except Exception:
                            pass

                self.root_gui.after(0, cleanup_popup)

        popup = popup_holder.get('popup')
        if popup and popup.finished:
            self.files_requested_to_copy, self.files_requested_to_move, self.files_requested_to_delete = (
                popup.get_outputs()
            )
            return popup.proceed

        self.files_requested_to_copy = list()
        self.files_requested_to_move = list()
        self.files_requested_to_delete = list()
        return False

    def cancel(self):
        """Signal cooperative cancellation to stop processing after current file."""
        self.cancel_requested.set()

    def _execute_batch(
        self,
        items: list[Any],
        action_name: str,
        action_fn: Callable[..., tuple[bool, int | float] | bool],
        output_list: list[tuple[Any, bool]] | None = None,
    ) -> list[tuple[Any, bool]]:
        """
        Execute a batch of file actions (copy, move, delete) with unified cancellation checking,
        progress logging, error reporting, and progress callbacks.
        """
        meta_map = {
            'copy': {'title': 'Copying', 'gerund': 'copying', 'past': 'Copied'},
            'move': {'title': 'Moving', 'gerund': 'moving', 'past': 'Moved'},
            'delete': {'title': 'Deleting', 'gerund': 'deleting', 'past': 'Deleted'},
        }
        meta = meta_map.get(
            action_name,
            {'title': action_name.capitalize(), 'gerund': action_name, 'past': action_name.capitalize()},
        )

        n_files = len(items)
        start_time = time.time()
        counter_size = 0
        copy_speed = ''
        log_interval = min(100, max(1, n_files // 10))
        results: list[tuple[Any, bool]] = output_list if output_list is not None else []

        try:
            num_params = len(inspect.signature(action_fn).parameters)
        except (ValueError, TypeError):
            num_params = 3

        for i, item in enumerate(items, 1):
            if hasattr(self, 'cancel_requested') and self.cancel_requested.is_set():
                logger.info(f'{meta["title"]} aborted due to user cancellation request')
                break

            if isinstance(item, tuple):
                primary_path = item[0]
                length_check = str(check_length(item[0]) + '  ' + check_length(item[1])).strip()
            else:
                primary_path = item
                length_check = check_length(item).strip()

            success = False
            bytes_transferred: int | float = 0
            try:
                res = action_fn(item) if num_params == 1 else action_fn(item, i, n_files)
                if isinstance(res, tuple):
                    success, bytes_transferred = res
                else:
                    success, bytes_transferred = bool(res), 0

                if success:
                    if action_name == 'copy':
                        counter_size += int(bytes_transferred)
                        elapsed = max(0.001, time.time() - start_time)
                        copy_speed = f'Avg. copy speed: {format_size(counter_size / elapsed)}/s'
                        log_progress('Copied', i, n_files, start_time, interval=log_interval, cstm_msg=copy_speed)
                    else:
                        log_progress(meta['past'], i, n_files, start_time, interval=log_interval)
            except Exception as e:
                error_msg = e if length_check == '' else length_check
                logger.error(f"There was an error while {meta['gerund']} file '{primary_path}'. Exception: {error_msg}")

            results.append((item, success))
            if self.progress_callback is not None:
                with contextlib.suppress(Exception):
                    self.progress_callback(action_name, i, n_files, counter_size, str(primary_path), copy_speed)

        return results

    def _copy_file(self, item: tuple[CstmPath | str, CstmPath | str], i: int, n_files: int) -> tuple[bool, int | float]:
        source, target = item
        # Pre-resolve dir_pair before any filesystem changes
        dir_pair = get_dirs_from_path(target, self.dirs or [])

        # Skip copy if source file no longer exists (e.g. transient file removed)
        if not os.path.isfile(source):
            logger.warning(f"Copy skipped because source file no longer exists: '{source}'")
            return False, 0

        # JIT Self-Healing: If target file already physically exists and matches source, avoid re-copying
        if os.path.isfile(target):
            try:
                source_stat = os.stat(source)
                target_stat = os.stat(target)
                if (
                    source_stat.st_size == target_stat.st_size
                    and abs(source_stat.st_mtime - target_stat.st_mtime) < 2.0
                ):
                    logger.info(f"Target already exists and matches source: '{target}'. Self-healing mirror entry.")
                    if self.increment_mirror:
                        self.mirror.add_path(root_dir=dir_pair.target, path=target)
                    return True, target_stat.st_size
            except Exception as jit_err:
                logger.debug(f"JIT self-heal check skipped for '{target}': {jit_err}")

        size = get_size(str(source))
        logger.debug(f"Copying file {i:,} of {n_files:,}: '{source}' -> '{target}' ({format_size(size)})")
        robust_copy(
            source,
            target,
            max_retries=self.max_retries,
            initial_delay=self.retry_delay,
            backoff_factor=self.backoff_factor,
        )
        if isinstance(target, CstmPath):
            with contextlib.suppress(Exception):
                target.refresh_stats()

        if self.increment_mirror:
            self.mirror.add_path(root_dir=dir_pair.target, path=target)
        return True, size

    def _move_file(self, item: tuple[CstmPath | str, CstmPath | str], i: int, n_files: int) -> tuple[bool, int | float]:
        source, target = item
        # Pre-resolve dir_pair before any filesystem changes
        dir_pair = get_dirs_from_path(target, self.dirs or [])

        # JIT Self-Healing & Phantom handling
        if not os.path.isfile(source):
            if os.path.isfile(target):
                try:
                    logger.info(f"Source is already missing and target exists: '{target}'. Self-healing mirror entry.")
                    if self.increment_mirror:
                        self.mirror.replace_path(root_dir=dir_pair.target, path=source, new_path=target)
                    return True, 0
                except Exception as jit_err:
                    logger.debug(f"JIT move self-heal check skipped for '{target}': {jit_err}")
            else:
                logger.warning(
                    f"Move skipped because file is missing at both source and target: '{source}'. "
                    'Purging phantom mirror record.'
                )
                try:
                    if self.increment_mirror:
                        self.mirror.remove_path(root_dir=dir_pair.target, path=source)
                except Exception as rm_err:
                    logger.debug(f'Could not remove phantom move source from mirror: {rm_err}')
                return False, 0

        size = (
            source.cached_stats.st_size
            if (isinstance(source, CstmPath) and source.has_cached_stats)
            else get_size(source)
        )
        logger.debug(f"Moving file {i:,} of {n_files:,}: '{source}' -> '{target}' ({format_size(size)})")
        robust_move(
            source,
            target,
            max_retries=self.max_retries,
            initial_delay=self.retry_delay,
            backoff_factor=self.backoff_factor,
        )
        if isinstance(target, CstmPath):
            with contextlib.suppress(Exception):
                target.refresh_stats()
        if self.increment_mirror:
            self.mirror.replace_path(root_dir=dir_pair.target, path=source, new_path=target)
        return True, size

    def _delete_file(self, path: CstmPath | str, i: int, n_files: int) -> tuple[bool, int | float]:
        size = path.cached_stats.st_size if (isinstance(path, CstmPath) and path.has_cached_stats) else get_size(path)
        logger.debug(f"Deleting file {i:,} of {n_files:,}: '{path}' ({format_size(size)})")

        try:
            dir_pair = get_dirs_from_path(path, self.dirs or [])
        except Exception as e:
            logger.error(f"Could not identify root directory for deletion target '{path}': {e}")
            return False, 0

        if not os.path.lexists(path):
            logger.warning(f"Skipping deletion of file because it is already missing: '{path}'")
            try:
                if self.increment_mirror:
                    self.mirror.remove_path(root_dir=dir_pair.target, path=path)
            except Exception as e:
                logger.debug(f'Could not remove phantom path from mirror: {e}')
            return True, 0

        robust_delete(
            path,
            max_retries=self.max_retries,
            initial_delay=self.retry_delay,
            backoff_factor=self.backoff_factor,
        )
        if self.increment_mirror:
            self.mirror.remove_path(root_dir=dir_pair.target, path=path)
        return True, size

    def copy_files(self):
        self.files_copied = []
        self._execute_batch(self.files_requested_to_copy, 'copy', self._copy_file, self.files_copied)

    def move_files(self):
        self.files_moved = []
        self._execute_batch(self.files_requested_to_move, 'move', self._move_file, self.files_moved)

    def delete_files(self):
        self.files_deleted = []
        self._execute_batch(self.files_requested_to_delete, 'delete', self._delete_file, self.files_deleted)

    def delete_empty_dirs(self):
        """Delete empty directories from folders where files were deleted or moved from"""
        removed_files = [f for f, success in self.files_deleted if success] + [
            f_source for (f_source, _), success in self.files_moved if success
        ]
        if not removed_files:
            logger.info('No files were removed, so no directories to delete')
            return

        # Protected root folders that must never be removed
        protected_roots = {_to_path(dir_pair.target) for dir_pair in (self.dirs or [])}
        protected_roots.update({_to_path(dir_pair.source) for dir_pair in (self.dirs or [])})

        relevant_dirs = set(os.path.dirname(f) for f in removed_files)
        # Sort by length to remove subdirectories first
        relevant_dirs = sorted(relevant_dirs, key=len, reverse=True)
        logger.info('Deleting empty directories from folders where files were deleted or moved from')

        for dir_path in relevant_dirs:
            if self.cancel_requested and self.cancel_requested.is_set():
                logger.info('Directory cleanup aborted due to user cancellation request')
                break
            current = dir_path
            while True:
                curr_path = _to_path(current)
                if curr_path in protected_roots or any(curr_path == root for root in protected_roots):
                    break
                if not os.path.exists(current):
                    parent = os.path.dirname(current)
                    if parent == current:
                        break
                    current = parent
                    continue
                if not os.listdir(current):
                    try:
                        os.rmdir(current)
                        logger.info(f"Removed empty directory '{current}'")
                    except Exception as e:
                        logger.error(f"Could not remove empty directory '{current}'. Exception: {e}")
                        break
                    parent = os.path.dirname(current)
                    if parent == current:
                        break
                    current = parent
                else:
                    break

    def print_errors(self):
        failed_copy = [p for p, success in self.files_copied if not success]
        if failed_copy:
            logger.warning(
                'Summary of files that failed to be copied:\n    '
                + '\n    '.join([f"'{s}' -> '{t}'" for s, t in failed_copy])
            )
        failed_move = [p for p, success in self.files_moved if not success]
        if failed_move:
            logger.warning(
                'Summary of files that failed to be moved:\n    '
                + '\n    '.join([f"'{s}' -> '{t}'" for s, t in failed_move])
            )
        failed_delete = [p for p, success in self.files_deleted if not success]
        if failed_delete:
            logger.warning(
                'Summary of files that failed to be deleted:\n    ' + '\n    '.join([f"'{p}'" for p in failed_delete])
            )


if __name__ == '__main__':
    from utils.constants import ROOT_DIR

    # Example usage CompareDirs
    compare_dirs = CompareDirs(
        dirs=[
            DirectoryPair(
                source=os.path.join(ROOT_DIR, 'tests/TestData/Source'),
                target=os.path.join(ROOT_DIR, 'tests/TestData/Target'),
            )
        ],
        mirror=MirrorDatabase(path=os.path.join(ROOT_DIR, 'tests/TestData/mirror.db')),
        exclusions=['.DS_Store', 'Thumbs.db', '__pycache__'],
        comparison_method=CompareMethod.METADATA,
        use_mirror=False,
        increment_mirror=True,
        rebuild_mirror=False,
    )

    sync_dirs = SyncDirs(
        files_to_copy=compare_dirs.files_to_copy,
        files_to_move=compare_dirs.files_to_move,
        files_to_delete=compare_dirs.files_to_delete,
        mirror=compare_dirs.mirror,
        root_gui=tk.Tk(),
        dirs=compare_dirs.dirs,
        default_actions=Action.get_options(),
    )
