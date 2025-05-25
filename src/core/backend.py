from copy import copy
import filecmp
import os
import shutil
import stat
import time
import tkinter as tk
import winsound

import pandas as pd
from collections import Counter
import datetime

from core.file import CstmPath, CstmPathType, File, compare_files
from core.mirror import MirrorDatabase
from gui.custom_gui import CustomCheckboxTreeView
from gui.widgets import Action
from utils.logger import logger
from utils.utils import (
    CompareMethod,
    DirectoryPair,
    check_length,
    format_elapsed_time,
    format_size,
    get_size,
    get_size_as_str,
    log_progress,
)


class CompareDirs:
    def __init__(
        self,
        mirror: MirrorDatabase,
        dirs: list[DirectoryPair],
        exclusions: list[str],
        save_report: bool = False,
        comparison_method: CompareMethod = CompareMethod.METADATA,
        care_about_moved_files=True,
        use_mirror=False,
        increment_mirror=True,
        rebuild_mirror=False,
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

        # Initialize comparison variables
        filecmp.clear_cache()
        self.files_in_source: dict[str, set[CstmPath]] = {}
        self.files_in_target: dict[str, set[CstmPath]] = {}
        self.linked_files: list[File] = []

        self.files_to_copy: list[tuple[CstmPath, CstmPath]] = []
        self.files_to_move: list[tuple[CstmPath, CstmPath]] = []
        self.files_to_delete: list[CstmPath] = []

        self.scan_source_files()
        self.scan_target_files(use_mirror, increment_mirror, rebuild_mirror)
        self.link_files()
        self.compare_files()

        self.get_files_to_copy()
        self.get_files_to_delete()
        if care_about_moved_files:
            self.get_files_to_move()

        self.print_results()
        if save_report:
            self._save_report()

        # Estimate synchronization actions
        logger.info(f'Finished comparing directories in {format_elapsed_time(start_time)}')

    def scan_source_files(self):
        logger.info('Starting to scan source files')
        start_time = time.time()
        self.files_in_source = {
            dir_pair.source: CstmPath.get_from_dir(dir_pair.source, exclude=self.exclusions) for dir_pair in self.dirs
        }
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
        for dir_pair in self.dirs:
            mirror_exists = self.mirror.exists_table(dir_pair.target)
            if rebuild_mirror and mirror_exists:
                self.mirror.reset(dir_pair.target)

            if use_mirror and mirror_exists:
                logger.info(
                    f'Using mirror for <{dir_pair.target}>. Table has {self.mirror.size(dir_pair.target):,} entries'
                )
                self.files_in_target[dir_pair.target] = {
                    CstmPath(p, root_dir=dir_pair.target) for p in self.mirror.get_paths(root_dir=dir_pair.target)
                }
                continue

            if use_mirror and not mirror_exists:
                logger.warning(
                    f'Mirror does not exist for target directory <{dir_pair.target}>. Using file system instead'
                )

            logger.info(f'Using file system to scan target directory <{dir_pair.target}>')
            self.files_in_target[dir_pair.target] = CstmPath.get_from_dir(dir_pair.target, exclude=self.exclusions)

            if increment_mirror or rebuild_mirror:
                logger.info(f'Adding {len(self.files_in_target[dir_pair.target]):,} files to mirror')
                self.mirror.add_path(dir_pair.target, self.files_in_target[dir_pair.target])

        num_files = sum(len(files) for files in self.files_in_target.values())
        logger.info(
            f'Finished scanning all target files. Found {num_files:,} files in {format_elapsed_time(start_time)}'
        )

    def link_files(self):
        """Link files in source and target directories to a single File object"""
        logger.info('Starting to link source and target files')
        self.linked_files = []

        for dir_pair in self.dirs:
            files_in_source = copy(self.files_in_source.get(dir_pair.source, set()))
            files_in_target = copy(self.files_in_target.get(dir_pair.target, set()))

            logger.info(
                f'Linking <{dir_pair.source}> ({len(files_in_source):,} files) and '
                f'<{dir_pair.target}> ({len(files_in_target):,} files)'
            )

            ################################
            logger.info('Searching for files that share the same relative path in both directories')
            start_time = time.time()
            linked_files: list[File] = []
            target_rel_paths = {f.rel_to_root: f for f in files_in_target}

            for i, source_file in enumerate(copy(files_in_source), 1):
                log_progress(i, len(files_in_source), start_time, interval=10000)
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

            for i, source_file in enumerate(copy(files_in_source), 1):
                log_progress(i, len(files_in_source), start_time, interval=10000)
                # Check if the file name exists in both source and target
                if source_file.name in target_filenames:
                    target_file = target_filenames[source_file.name]
                    success, same = compare_files(source_file, target_file, comparison_method=self.comparison_method)
                    if success and same:
                        linked_files.append(
                            File(source=source_file, target=target_file, compare_success=success, same=same)
                        )
                        files_in_source.remove(source_file)
                        files_in_target.remove(target_file)

            logger.info(f'Found {len(linked_files):,} files that share the same name and are the same')
            self.linked_files += linked_files

            ################################
            logger.info('Searching for files that exist only in source directory')
            linked_files: list[File] = [
                File(source=source_file, target=None, missing_target_root_dir=dir_pair.target)
                for source_file in files_in_source
            ]
            logger.info(f'Found {len(linked_files):,} files that exist only in source directory')
            self.linked_files += linked_files

            ################################
            logger.info('Searching for files that exist only in target directory')
            linked_files: list[File] = [File(source=None, target=target_file) for target_file in files_in_target]
            logger.info(f'Found {len(linked_files):,} files that exist only in target directory')
            self.linked_files += linked_files

        self.linked_files = list(sorted(self.linked_files, key=lambda x: x.any_path))

    def compare_files(self):
        """Compare files that exist in both places and check for newer versions in the source"""
        files_in_both = [f for f in self.linked_files if f.in_both and not f.moved]
        number_files = len(files_in_both)
        if not number_files:
            logger.info('Not comparing any file since there are no files existing in both directories')
            return

        start_time = time.time()
        logger.info(f'Comparing {number_files:,} files that exist in both directories')
        for i, file in enumerate(files_in_both):
            log_progress(i, number_files, start_time, interval=1000)
            file.compare(self.comparison_method)

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
        logger.info('Loading data to create comparison report')

        # Load all linked files and store as a dataframe where columns are file attributes
        df = pd.DataFrame(
            [
                {
                    'source': str(file.source) if file.source else '-',
                    'target': str(file.target) if file.target else '-',
                    'in both': 'X' if file.in_both else '',
                    'moved': 'X' if file.moved else '',
                    'modified': 'X' if file.in_both and file.modified else '',
                    'only source': 'X' if file.only_source else '',
                    'only target': 'X' if file.only_target else '',
                    'size (source)': file.source.get_st_size(as_str=True) if file.source else '',
                    'size (target)': file.target.get_st_size(as_str=True) if file.target else '',
                    'modified (source)': file.source.get_st_mtime(as_date_str=True) if file.source else '',
                    'modified (target)': file.target.get_st_mtime(as_date_str=True) if file.target else '',
                    'compare error': file.compare_error,
                }
                for file in self.linked_files
            ]
        )

        logger.info('Starting to write comparison report')
        os.makedirs(os.path.dirname(self.save_report_path), exist_ok=True)
        df.to_excel(self.save_report_path, index=False)
        logger.info(f'Comparison report was saved to <{self.save_report_path}>')

    def print_results(self):
        logger.info('-------------------------')
        logger.info('Analyzing directory tree:')
        logger.info(f'Files in source: {len([f for f in self.linked_files if f.source]):,}')
        logger.info(f'Files only in source: {len([f for f in self.linked_files if f.only_source]):,}')
        logger.info(f'Files in target: {len([f for f in self.linked_files if f.target]):,}')
        logger.info(f'Files only in target: {len([f for f in self.linked_files if f.only_target]):,}')
        logger.info(
            f'Files in both and are the same: {len([f for f in self.linked_files if f.in_both and not f.moved and f.same]):,}'
        )
        logger.info(
            f'Files in both and are the same but moved: {len([f for f in self.linked_files if f.in_both and f.moved]):,}'
        )
        logger.info(
            f'Files in both and are modified: {len([f for f in self.linked_files if f.in_both and not f.same]):,}'
        )
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
        root_gui,
        dirs: list[DirectoryPair],
        default_actions: list[Action] | None = None,
        increment_mirror=True,
    ):
        logger.info('---------------------------')
        logger.info('Initializing synchronization')

        # Input variables
        self.root_gui = root_gui
        self.mirror = mirror
        self.increment_mirror = increment_mirror
        self.dirs = dirs
        self.default_actions = default_actions if default_actions is not None else [Action.COPY]

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

        # Confirm actions
        if self.open_confirmation_popup():
            self.copy_files()
            self.move_files()
            self.delete_files()
            logger.info('Finished synchronizing directories')
            self.print_errors()
        else:
            logger.warning('Popup did not end well')

    def open_confirmation_popup(self):
        popup = ActionSelection(
            self.root_gui,
            self.files_available_to_copy,
            self.files_available_to_move,
            self.files_available_to_delete,
            self.default_actions,
        )

        time_init = time.time()
        while (time.time() - time_init) < 7200:
            if popup.finished:
                self.files_requested_to_copy, self.files_requested_to_move, self.files_requested_to_delete = (
                    popup.get_outputs()
                )
                return popup.proceed
            else:
                time.sleep(0.1)

        self.files_requested_to_copy = list()
        self.files_requested_to_move = list()
        self.files_requested_to_delete = list()
        return False

    def copy_files(self):
        n_files = len(self.files_requested_to_copy)
        counter_size = 0
        start_time = time.time()

        for i, (source, target) in enumerate(self.files_requested_to_copy, 1):
            success = False
            try:
                size = get_size(source)
                logger.info(f'Copying file {i:,} of {n_files:,}: <{source}> -> <{target}> ({format_size(size)})')
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
                dir_pair = get_dirs_from_path(target, self.dirs)
                self.mirror.add_path(root_dir=dir_pair.target, path=target)
                counter_size += size
                log_progress(i, n_files, start_time, interval=10, speed_type='copy')
                if i % 10 == 0:
                    logger.debug(f'Avg. copy speed: {format_size(counter_size / (time.time() - start_time))}/s')
                success = True
            except Exception as e:
                error_msg = str(check_length(source) + '  ' + check_length(target)).strip()
                error_msg = e if error_msg == '' else error_msg
                logger.error(f'There was an error while copying file <{source}>. Exception: {error_msg}')

            self.files_copied.append(((source, target), success))

    def move_files(self):
        n_files = len(self.files_requested_to_move)
        t1 = time.time()

        for i, (source, target) in enumerate(self.files_requested_to_move, 1):
            success = False
            try:
                logger.info(f'Moving file {i:,} of {n_files:,}: <{source}> -> <{target}> ({get_size_as_str(source)})')
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(source, target)
                dir_pair = get_dirs_from_path(target, self.dirs)
                self.mirror.replace_path(root_dir=dir_pair.target, path=source, new_path=target)
                if i % 10 == 0:
                    logger.debug(f'Avg. move speed: {int(60 * i / (time.time() - t1)):,} files/min')
                success = True
            except Exception as e:
                error_msg = str(check_length(source) + '  ' + check_length(target)).strip()
                error_msg = e if error_msg == '' else error_msg
                logger.error(f'There was an error while moving file <{source}>. Exception: {error_msg}')

            self.files_moved.append(((source, target), success))

    def delete_files(self):
        n_files = len(self.files_requested_to_delete)
        start_time = time.time()

        for i, path in enumerate(self.files_requested_to_delete, 1):
            success = False
            try:
                logger.info(f'Deleting file {i:,} of {n_files:,}: <{path}> ({get_size_as_str(path)})')
                os.chmod(path, stat.S_IWRITE)
                os.remove(path)
                dir_pair = get_dirs_from_path(path, self.dirs)
                self.mirror.remove_path(root_dir=dir_pair.target, path=path)
                log_progress(i, n_files, start_time, interval=10, speed_type='delete')
                success = True
            except Exception as e:
                error_msg = check_length(path)
                error_msg = e if error_msg == '' else error_msg
                logger.error(f'There was an error while deleting file <{path}>. Exception: {error_msg}')

            # If the folder of the deleted file is left empty, delete it
            dir_name = os.path.dirname(path)
            if success and len(os.listdir(dir_name)) == 0:
                try:
                    os.removedirs(dir_name)
                    logger.info(f'Also removed empty directory <{dir_name}>')
                except Exception as e:
                    logger.info(f'Could not remove empty directory <{dir_name}>. Exception: {e}')

            self.files_deleted.append((path, success))

    def print_errors(self):
        failed_copy = [p for p, success in self.files_copied if not success]
        if failed_copy:
            logger.warning(
                'Summary of files that failed to be copied:\n    '
                + '\n    '.join([f'<{s}> -> <{d}>' for s, d in failed_copy])
            )
        failed_move = [p for p, success in self.files_moved if not success]
        if failed_move:
            logger.warning(
                'Summary of files that failed to be moved:\n    '
                + '\n    '.join([f'<{s}> -> <{d}>' for s, d in failed_move])
            )
        failed_delete = [p for p, success in self.files_deleted if not success]
        if failed_delete:
            logger.warning('Summary of files that failed to be deleted:\n    ' + '\n    '.join(failed_delete))


class ActionSelection:
    def __init__(
        self,
        root_gui: tk.Tk,
        files_available_to_copy: list[tuple[CstmPath, CstmPath]],
        files_available_to_move: list[tuple[CstmPath, CstmPath]],
        files_available_to_delete: list[CstmPath],
        default_actions: list[Action],
    ):
        # Load input variables
        self.default_actions = default_actions
        self.files_available_to_copy = files_available_to_copy
        self.files_available_to_move = files_available_to_move
        self.files_available_to_delete = files_available_to_delete
        self.files_requested_to_copy: list[tuple[str, str]] = list()
        self.files_requested_to_move: list[tuple[str, str]] = list()
        self.files_requested_to_delete: list[str] = list()

        # Configure variables
        self.root_gui = root_gui
        self.finished = False
        self.proceed = False

        # Configure timer
        self.is_timer_active = True
        self.init_time = 0  # Filled in create_widgets
        self.countdown_size = 1200

        # Configure gui
        self.popup = tk.Toplevel(self.root_gui)
        self.popup.protocol('WM_DELETE_WINDOW', self.button_cancel_click)
        self.create_widgets()

        # Init watchdog functions
        self.check_countdown()

    def create_widgets(self):
        logger.info('Collecting data for selection window. This may take a while')
        frame_buttons = tk.Frame(self.popup)

        self.button_save = tk.Button(
            frame_buttons, text='Save and continue', anchor='w', command=self.button_save_click
        )
        self.button_save.grid(row=0, column=0, sticky='w')

        def turn_timer_off():
            self.is_timer_active = False

        self.button_wait = tk.Button(frame_buttons, text='Wait', anchor='w', command=turn_timer_off)
        self.button_wait.grid(row=0, column=1, sticky='w')

        self.button_cancel = tk.Button(frame_buttons, text='Cancel', anchor='w', command=self.button_cancel_click)
        self.button_cancel.grid(row=0, column=2, sticky='w')

        self.create_table()

        frame_buttons.grid(row=0, column=0, sticky='w')
        self.init_time = time.time()
        winsound.PlaySound('SystemQuestion', winsound.SND_ALIAS)

    def button_save_click(self):
        logger.info('Saving selection of actions')
        self.is_timer_active = False
        self.files_requested_to_copy = list()
        self.files_requested_to_move = list()
        self.files_requested_to_delete = list()

        # Fill output
        for id_ in self.tree.get_checked():
            if '::' in id_:
                group, source_path, target_path = id_.split('::')
                if group == 'copy':
                    self.files_requested_to_copy.append((source_path, target_path))
                elif group == 'move':
                    self.files_requested_to_move.append((source_path, target_path))
                elif group == 'delete':
                    self.files_requested_to_delete.append(target_path)

        self.finished = True
        self.proceed = True
        self.popup.destroy()

    def button_cancel_click(self):
        logger.info('Canceling selection of actions. No action will be taken')
        self.is_timer_active = False
        self.files_requested_to_copy = list()
        self.files_requested_to_move = list()
        self.files_requested_to_delete = list()
        self.finished = True
        self.popup.destroy()

    def get_countdown(self) -> tuple[bool, str]:
        countdown = max(0, int(self.countdown_size + self.init_time - time.time()))
        countdown_str = f' ({countdown}s)' if self.is_timer_active else ''
        return self.is_timer_active and countdown <= 0, countdown_str

    def check_countdown(self):
        if not self.finished:
            status, value = self.get_countdown()
            self.button_save.configure(text='Save and continue' + value)
            if status:
                winsound.PlaySound('SystemAsterisk', winsound.SND_ALIAS)
                self.button_save_click()
            self.popup.after(1000, self.check_countdown)

    def create_table(self):
        # Create blank widget
        self.tree = CustomCheckboxTreeView(self.popup, height=30)
        self.tree.add_file_lists(
            {
                Action.COPY: self.files_available_to_copy,
                Action.MOVE: self.files_available_to_move,
                Action.DELETE: self.files_available_to_delete,
            },
            default_active=self.default_actions,
        )

        # Display widget
        self.tree.refresh_group_stats()
        self.tree.grid(row=1, column=0, sticky='wens')

    def get_outputs(self):
        return self.files_requested_to_copy, self.files_requested_to_move, self.files_requested_to_delete


def get_dirs_from_path(path: CstmPathType, dirs: list[DirectoryPair]) -> DirectoryPair:
    """Find the corresponding source and target directories for a given path."""

    def uniform(p_: CstmPathType) -> str:
        return str(p_).replace('/', '\\')

    for source, target in dirs:
        if uniform(source) in uniform(path) or uniform(target) in uniform(path):
            return DirectoryPair(source, target)
    raise FileNotFoundError(f'Could not identify root folders of path <{path}>. Dirs: {dirs}')


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
