import filecmp
import os
import shutil
import stat
import time
import tkinter as tk
import winsound

import pandas as pd

from custom_gui import CustomCheckboxTreeView
from file import CstmPath, CstmPathType, File
from logger import logger
from mirror import MirrorDatabase
from utils import CompareMethod, DirectoryPair, check_length, format_size, get_size, log_progress, time_diff_to_min


class CompareDirs:
    def __init__(
        self,
        mirror: MirrorDatabase,
        dirs: list[DirectoryPair],
        exclusions: list[str],
        save_report_path='',
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

        self.mirror = mirror
        self.dirs = dirs
        self.exclusions = exclusions
        self.save_report_path = save_report_path
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

        if care_about_moved_files:
            self.get_moved_files()

        self.get_files_to_copy()
        self.get_files_to_delete()

        self.print_results()
        self.save_report()

        # Estimate synchronization actions
        logger.info(f'Finished comparing directories in {time_diff_to_min(start_time)}')

    def scan_source_files(self):
        logger.info('Starting to scan source files')
        start_time = time.time()
        self.files_in_source = {
            dir_pair.source: CstmPath.get_from_dir(dir_pair.source, exclude=self.exclusions) for dir_pair in self.dirs
        }
        num_files = sum(len(files) for files in self.files_in_source.values())
        logger.info(f'Finished scanning all source files. Found {num_files} files in {time_diff_to_min(start_time)}')

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
                    f'Using mirror for <{dir_pair.target}>. Table has {self.mirror.size(dir_pair.target)} entries'
                )
                self.files_in_target[dir_pair.target] = {
                    CstmPath(p, root_dir=dir_pair.target) for p in self.mirror.get_keys(root_dir=dir_pair.target)
                }
                continue

            if use_mirror and not mirror_exists:
                logger.warning('Mirror does not exist for target directory. Using file system instead')

            logger.info(f'Using file system to scan target directory <{dir_pair.target}>')
            self.files_in_target[dir_pair.target] = CstmPath.get_from_dir(dir_pair.target, exclude=self.exclusions)

            if increment_mirror or rebuild_mirror:
                logger.info(f'Adding {len(self.files_in_target[dir_pair.target])} files to mirror')
                self.mirror.add(dir_pair.target, self.files_in_target[dir_pair.target])

        num_files = sum(len(files) for files in self.files_in_target.values())
        logger.info(f'Finished scanning all target files. Found {num_files} files in {time_diff_to_min(start_time)}')

    def link_files(self):
        logger.info('Starting to link source and target files')

        for dir_pair in self.dirs:
            logger.info(
                f'Linking <{dir_pair.source}> ({len(self.files_in_source[dir_pair.source])} files) and '
                f'<{dir_pair.target}> ({len(self.files_in_target[dir_pair.target])} files)'
            )
            source_paths = {f.rel_to_root: f for f in self.files_in_source[dir_pair.source]}
            target_paths = {f.rel_to_root: f for f in self.files_in_target[dir_pair.target]}

            logger.info('')
            start_time = time.time()
            number_files = len(source_paths)
            for i, (source_file_rel_path, source_file) in enumerate(source_paths.items()):
                log_progress(i, number_files, start_time, interval=10000)
                if source_file_rel_path in target_paths:
                    self.linked_files.append(File(source=source_file, target=target_paths[source_file_rel_path]))
                    del target_paths[source_file_rel_path]
                else:
                    self.linked_files.append(
                        File(source=source_file, target=None, missing_target_root_dir=dir_pair.target)
                    )

            # Remaining target paths did not match to any source path
            self.linked_files += [File(source=None, target=target_file) for target_file in target_paths.values()]

        self.linked_files = list(sorted(self.linked_files, key=lambda x: x.any_path))

    def compare_files(self):
        """Compare files that exist in both places and check for newer versions in the source"""
        files_in_both = [f for f in self.linked_files if f.in_both]
        number_files = len(files_in_both)
        if not number_files:
            logger.info('Not comparing any file since there are no files existing in both directories')
            return

        start_time = time.time()
        logger.info(f'Comparing {number_files} files that exist in both directories')
        for i, file in enumerate(files_in_both):
            log_progress(i, number_files, start_time, interval=1000)
            if file.in_both:
                file.compare(self.comparison_method)

    def get_moved_files(self):
        logger.info('Move files recognition not implemented yet')
        # logger.debug('Searching for moved files')
        # used_files = deepcopy(self.error_files)
        # number_files = len(self.files_only_in_source)
        # start_time = time.time()
        # for i, file_in_source in enumerate(self.files_only_in_source):
        #     log_progress(i, number_files, start_time)

        #     file_basename_in_source = file_in_source.name

        #     for file_in_target in self.files_only_in_target:
        #         file_basename_in_target = file_in_target.name

        #         if file_in_source in used_files:
        #             break
        #         if file_in_target in used_files:
        #             continue

        #         if file_basename_in_source == file_basename_in_target:
        #             success, match = compare_files(file_in_source, file_in_target, self.comparison_method)
        #             if success:
        #                 if match:
        #                     # logger.debug(f'Found two single files with same basename, '
        #                     #              f'and they seem to be the same: {file_in_source} and {file_in_target}')
        #                     pair = (file_in_target, file_in_source.change_root_dir(file_in_target._root_dir))
        #                     self.moved_files.add(pair)
        #                 else:
        #                     pass
        #                     # logger.debug(f'Found two single files with same basename, '
        #                     #              f'but they are not the same: {file_in_source} and {file_in_target}')
        #             else:
        #                 self.error_files.update({file_in_source, file_in_target})
        #             used_files.update({file_in_source, file_in_target})

    def get_files_to_copy(self):
        """
        Get files that need to be copied from source to target.
        These are files that only exist in source or that were modified
        """
        self.files_to_copy = [
            (f.source, f.missing_target) for f in self.linked_files if f.only_source or (f.in_both and f.modified)
        ]
        self.files_to_copy = list(sorted(self.files_to_copy, key=lambda x: x[0]))

    def get_files_to_move(self):
        logger.warning('Not implemented yet')

    def get_files_to_delete(self):
        """
        Get files that need to be deleted from target.
        These are files that only exist in target
        """
        self.files_to_delete = list(sorted([f.target for f in self.linked_files if f.only_target]))

    def save_report(self):
        if self.save_report_path.endswith('.xlsx'):
            logger.info('Loading data to create comparison report')

            # Load all linked files and store as a dataframe where columns are file attributes
            df = pd.DataFrame(
                [
                    {
                        'source': str(file.source) if file.source else '-',
                        'target': str(file.target) if file.target else '-',
                        'in both': 'X' if file.in_both else '',
                        'modified': 'X' if file.modified else '',
                        'only source': 'X' if file.only_source else '',
                        'only target': 'X' if file.only_target else '',
                        'size (source)': file.source.get_st_size(as_str=True) if file.source else '',
                        'size (target)': file.target.get_st_size(as_str=True) if file.target else '',
                        'modified (source)': file.source.get_st_mtime(as_date_str=True) if file.source else '',
                        'modified (target)': file.target.get_st_mtime(as_date_str=True) if file.target else '',
                        'created (source)': file.source.get_st_birthtime(as_date_str=True) if file.source else '',
                        'created (target)': file.target.get_st_birthtime(as_date_str=True) if file.target else '',
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
        logger.info(f'Files that exist in source: {len([f for f in self.linked_files if f.source])}')
        logger.info(f'Files that exist only in source: {len([f for f in self.linked_files if f.only_source])}')
        logger.info(f'Files that exist in target: {len([f for f in self.linked_files if f.target])}')
        logger.info(f'Files that exist only in target: {len([f for f in self.linked_files if f.only_target])}')
        logger.info(f'Files that exist in both: {len([f for f in self.linked_files if f.in_both])}')
        logger.info(
            f'Files that exist in both and are the same: {len([f for f in self.linked_files if f.in_both and f.same])}'
        )
        logger.info(
            f'Files that exist in both and are modified: {len([f for f in self.linked_files if f.in_both and not f.same])}'
        )
        files_compare_error = [f for f in self.linked_files if f.compare_error]
        logger.info(
            f'Files that could not be analyzed: {len(files_compare_error)}'
            + str({True: ': \n' + '\n  '.join(files_compare_error), False: ''}.get(len(files_compare_error) > 0))
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
        default_actions=None,
        increment_mirror=True,
    ):
        logger.info('---------------------------')
        logger.info('Initializing synchronization')

        # Input variables
        self.root_gui = root_gui
        self.mirror = mirror
        self.increment_mirror = increment_mirror
        self.dirs = dirs
        self.default_actions = default_actions if default_actions is not None else ['copy']

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
        self.files_requested_to_copy, self.files_requested_to_move, self.files_requested_to_delete = set(), set(), set()
        return False

    def copy_files(self):
        total_files = len(self.files_requested_to_copy)
        counter_size = 0
        start_time = time.time()

        for i, (source, target) in enumerate(self.files_requested_to_copy, 1):
            success = False
            try:
                size = get_size(source, as_str=False)
                logger.info(f'Copying file {i} of {total_files}: <{source}> - <{target}> ({format_size(size)})')
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
                dir_pair = get_dirs_from_path(target, self.dirs)
                self.mirror.add(root_dir=dir_pair.target, path=target)
                counter_size += size
                log_progress(i, total_files, start_time, interval=10, speed_type='copy')
                if i % 10 == 0:
                    logger.debug(f'Avg. copy speed: {format_size(counter_size / (time.time() - start_time))}/s')
                success = True
            except Exception as e:
                error_msg = str(check_length(source) + '  ' + check_length(target)).strip()
                error_msg = e if error_msg == '' else error_msg
                logger.error(f'There was an error while copying file <{source}>. Exception: {error_msg}')

            self.files_copied.append(((source, target), success))

    def move_files(self):
        number = len(self.files_requested_to_move)
        t1 = time.time()
        for i, (source, target) in enumerate(self.files_requested_to_move, 1):
            success = False
            try:
                logger.info(f'Moving file {i} of {number}: <{source}> ({get_size(source)})')
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(source, target)
                dir_pair = get_dirs_from_path(target, self.dirs)
                self.mirror.replace(root_dir=dir_pair.target, path=source, new_path=target)
                logger.debug(f'Move finished. Average speed {int(60 * i / (time.time() - t1))} files/min')
                success = True
            except Exception as e:
                error_msg = str(check_length(source) + '  ' + check_length(target)).strip()
                error_msg = e if error_msg == '' else error_msg
                logger.error(f'There was an error while moving file <{source}>. Exception: {error_msg}')

            self.files_moved.append(((source, target), success))

    def delete_files(self):
        total_files = len(self.files_requested_to_delete)
        start_time = time.time()
        for i, path in enumerate(self.files_requested_to_delete, 1):
            success = False
            try:
                logger.info(f'Deleting file {i} of {total_files}: <{path}> ({get_size(path)})')
                os.chmod(path, stat.S_IWRITE)
                os.remove(path)
                dir_pair = get_dirs_from_path(path, self.dirs)
                self.mirror.remove(root_dir=dir_pair.target, path=path)
                log_progress(i, total_files, start_time, interval=10, speed_type='delete')
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
        files_to_copy: list[tuple[str, str]],
        files_to_move: list[tuple[str, str]],
        files_to_delete: list[str],
        default_actions: list[str],
    ):
        # Load input variables
        self.files_to_copy = files_to_copy
        self.files_to_move = files_to_move
        self.files_to_delete = files_to_delete
        self.default_actions = default_actions

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

    def get_countdown(self) -> tuple[bool, str]:
        countdown = max(0, int(self.countdown_size + self.init_time - time.time()))
        countdown_str = f' ({countdown}s)' if self.is_timer_active else ''
        return self.is_timer_active and countdown <= 0, countdown_str

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
            {'copy': self.files_to_copy, 'move': self.files_to_move, 'delete': self.files_to_delete},
            default_active=self.default_actions,
        )

        # Display widget
        self.tree.refresh_group_stats()
        self.tree.grid(row=1, column=0, sticky='wens')

    def button_save_click(self):
        logger.info('Saving selection of actions')
        self.is_timer_active = False
        self.files_to_copy = set()
        self.files_to_move = set()
        self.files_to_delete = set()

        # Fill output
        for id_ in self.tree.get_checked():
            if '::' in id_:
                group, source_path, target_path = id_.split('::')
                if group == 'copy':
                    self.files_to_copy.add((source_path, target_path))
                elif group == 'move':
                    self.files_to_move.add((source_path, target_path))
                elif group == 'delete':
                    self.files_to_delete.add(target_path)

        self.finished = True
        self.proceed = True
        self.popup.destroy()

    def button_cancel_click(self):
        logger.info('Canceling selection of actions. No action will be taken')
        self.is_timer_active = False
        self.files_to_copy = set()
        self.files_to_move = set()
        self.files_to_delete = set()
        self.finished = True
        self.popup.destroy()

    def get_outputs(self):
        return self.files_to_copy, self.files_to_move, self.files_to_delete


def get_dirs_from_path(path: CstmPathType, dirs: list[DirectoryPair]) -> DirectoryPair:
    """Find the corresponding source and target directories for a given path."""

    def uniform(p_: CstmPathType) -> str:
        return str(p_).replace('\\', '/')

    for source, target in dirs:
        if uniform(source) in uniform(path) or uniform(target) in uniform(path):
            return DirectoryPair(source, target)
    raise FileNotFoundError(f'Could not identify root folders of path <{path}>. Dirs: {dirs}')


if __name__ == '__main__':
    # Example usage CompareDirs
    compare_dirs = CompareDirs(
        dirs=[
            DirectoryPair(
                source=os.path.normpath(os.path.join(os.path.dirname(__file__), '../tests/TestData/Source')),
                target=os.path.normpath(os.path.join(os.path.dirname(__file__), '../tests/TestData/Target')),
            )
        ],
        mirror=MirrorDatabase(path=os.path.join(__file__, '../tests/TestData/mirror.db')),
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
        default_actions=['copy', 'move', 'delete'],
    )
