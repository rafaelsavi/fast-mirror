import filecmp
import os
import shutil
import stat
import time
import tkinter as tk
import winsound
from copy import deepcopy

import pandas as pd

from custom_gui import CustomCheckboxTreeView
from logger import logger
from mirror import MirrorDatabase
from utils import (
    CstmPath,
    check_length,
    compare_files,
    encode_stats,
    format_size,
    get_size,
    log_progress,
)


class CompareDirs:
    def __init__(
        self,
        mirror: MirrorDatabase,
        dirs: list[tuple[str, str]],
        exclusions: list[str],
        save_report_path='',
        compare_with_local_mirror=False,
        use_light_comparison=False,
        care_about_moved_files=True,
    ):
        logger.info('-----------------------------')
        logger.info('Initializing comparison')
        logger.info('Directories:\n  ' + '\n  '.join([f'{d1}  -->  {d2}' for d1, d2 in dirs]))
        t1_compare_dirs = time.time()

        self.mirror = mirror
        self.dirs = dirs
        self.exclusions = exclusions
        self.save_report_path = save_report_path
        self.use_light_comparison = use_light_comparison

        # Initialize comparison variables
        filecmp.clear_cache()
        self.files_only_in_source: set[CstmPath] = set()
        self.files_only_in_target: set[CstmPath] = set()
        self.files_in_both: set[tuple[CstmPath, CstmPath]] = set()
        self.not_modified_files: set[tuple[CstmPath, CstmPath]] = set()
        self.modified_files_in_source: set[tuple[CstmPath, CstmPath]] = set()
        self.modified_files_in_target: set[tuple[CstmPath, CstmPath]] = set()
        self.moved_files: set[tuple[CstmPath, CstmPath]] = set()
        self.new_files: set[CstmPath] = set()
        self.residual_files: set[CstmPath] = set()
        self.error_files: set[CstmPath] = set()

        # Initialize sync variables
        self.files_to_copy: set[tuple[CstmPath, CstmPath]] = set()
        self.files_to_move: set[tuple[CstmPath, CstmPath]] = set()
        self.files_to_delete: set[CstmPath] = set()
        self.files_to_keep: set[CstmPath] = set()

        # Run comparison
        if compare_with_local_mirror:
            self.get_files_from_source_and_local_mirror()
        else:
            self.get_files_from_source_and_destination()

        logger.info(
            f'Finished collecting file paths: '
            f'{len(self.files_in_both)} exist in source and destination, '
            f'{len(self.files_only_in_source)} exist only in source, '
            f'{len(self.files_only_in_target)} exist only in destination'
        )
        logger.info('Starting to compare files')
        self.get_modified_files()
        if care_about_moved_files:
            self.get_moved_files()
        self.get_new_files()
        self.get_residual_files()
        logger.info('Finished to compare files')
        self.save_report()
        self.print_results()

        # Estimate synchronization actions
        self.estimate_actions()
        logger.info(f'Finished comparing directories in {int((time.time() - t1_compare_dirs) / 60)} minutes')

    def get_files_from_source_and_local_mirror(self):
        logger.info('Starting to compare files based on local mirror')
        logger.debug(f'Local mirror has {self.mirror.size()} entries')

        self.files_only_in_source = set()
        self.files_only_in_target = set()
        self.files_in_both = set()
        files_in_mirror = self.mirror.get_keys(exclude=self.exclusions)
        files_in_source = {
            f
            for source_dir, target_dir in self.dirs
            for f in CstmPath.get_from_dir(source_dir, exclude=self.exclusions)
        }

        logger.info(
            f'Finished scanning all files. Found {len(files_in_source)} files in the source and '
            f'{len(files_in_mirror)} files in the mirror'
        )
        logger.info('Starting to compare source with mirror')

        # Compare local paths with local mirror
        files_only_in_mirror = files_in_mirror - files_in_source  # Paths that might be deleted
        files_only_in_source = files_in_source - files_in_mirror  # Paths that might be new

        files_in_both = files_in_source & files_in_mirror  # Paths that might have changed
        mirror_stats = self.mirror.get(files_in_both)
        actual_stats = {encode_stats(os.stat(p)) for p in files_in_both}
        files_in_both = {
            p
            for p, mirror_stat, actual_stat in zip(files_in_both, mirror_stats, actual_stats, strict=False)
            if mirror_stat != actual_stat
        }

        total_number = len(files_only_in_mirror) + len(files_only_in_source) + len(files_in_both)
        logger.info(f'Found {total_number} files with possible changes')
        logger.info('Confirming changes with destination now')

        # Check file existence in source and target
        all_paths = files_only_in_mirror | files_only_in_source | files_in_both
        for p in all_paths:
            source_dir, target_dir = get_dirs_from_path(p, self.dirs)
            if source_dir is not None:
                source_file = CstmPath(abs_path=p, root_dir=source_dir)
                target_file = source_file.change_root_dir(target_dir)
                if source_file.exists() and not target_file.exists():
                    self.files_only_in_source.add(source_file)
                elif not source_file.exists() and target_file.exists():
                    self.files_only_in_target.add(target_file)
                elif source_file.exists() and target_file.exists():
                    self.files_in_both.add((source_file, target_file))

    def get_files_from_source_and_destination(self):
        logger.info('Starting to compare files')
        self.files_only_in_source = set()
        self.files_only_in_target = set()
        self.files_in_both = set()

        for source_dir, target_dir in self.dirs:
            files_in_source = CstmPath.get_from_dir(source_dir, exclude=self.exclusions)
            files_in_target = CstmPath.get_from_dir(target_dir, exclude=self.exclusions)

            rel_paths_in_source = {f.get_rel() for f in files_in_source}
            rel_paths_in_target = {f.get_rel() for f in files_in_target}

            self.files_only_in_source.update({f for f in files_in_source if f.get_rel() not in rel_paths_in_target})
            self.files_only_in_target.update({f for f in files_in_target if f.get_rel() not in rel_paths_in_source})
            self.files_in_both.update(
                {
                    (source_dir / rel_path, target_dir / rel_path)
                    for rel_path in rel_paths_in_source
                    if rel_path in rel_paths_in_target
                }
            )

    def get_modified_files(self):
        """Compare files that exist in both places and check for newer versions in the source"""
        logger.debug('Searching for modified files')
        number_files = len(self.files_in_both)
        start_time = time.time()
        for i, (file_source, file_target) in enumerate(self.files_in_both):
            log_progress(i, number_files, start_time)

            success, match = compare_files(file_source, file_target, light=self.use_light_comparison)

            if success:
                if match:
                    self.not_modified_files.add((file_source, file_target))
                else:
                    is_target_newer = False
                    try:
                        source_mod_date = file_source.getmtime()
                        target_mod_date = file_target.getmtime()
                        if source_mod_date < target_mod_date:
                            is_target_newer = True
                    except Exception as e:
                        logger.warning(
                            f'Could not compare modification times of {file_source} or {file_target}. Exception: {e}'
                        )
                        is_target_newer = False

                    if is_target_newer:
                        self.modified_files_in_target.add((file_source, file_target))
                    else:
                        self.modified_files_in_source.add((file_source, file_target))
            else:
                self.error_files.update({file_source, file_target})

    def get_moved_files(self):
        logger.debug('Searching for moved files')
        used_files = deepcopy(self.error_files)
        number_files = len(self.files_only_in_source)
        start_time = time.time()
        for i, file_in_source in enumerate(self.files_only_in_source):
            log_progress(i, number_files, start_time)

            file_basename_in_source = file_in_source.get_basename()

            for file_in_target in self.files_only_in_target:
                file_basename_in_target = file_in_target.get_basename()

                if file_in_source in used_files:
                    break
                if file_in_target in used_files:
                    continue

                if file_basename_in_source == file_basename_in_target:
                    success, match = compare_files(file_in_source, file_in_target, self.use_light_comparison)
                    if success:
                        if match:
                            # logger.debug(f'Found two single files with same basename, '
                            #              f'and they seem to be the same: {file_in_source} and {file_in_target}')
                            pair = (file_in_target, file_in_source.change_root_dir(file_in_target._root_dir))
                            self.moved_files.add(pair)
                        else:
                            pass
                            # logger.debug(f'Found two single files with same basename, '
                            #              f'but they are not the same: {file_in_source} and {file_in_target}')
                    else:
                        self.error_files.update({file_in_source, file_in_target})
                    used_files.update({file_in_source, file_in_target})

    def get_new_files(self):
        logger.debug('Searching for new files')
        for file_in_source in self.files_only_in_source:
            if (
                file_in_source in self.error_files | self.modified_files_in_source | self.modified_files_in_target
                or file_in_source.get_rel() in [t.get_rel() for s, t in self.moved_files]
            ):
                continue
            self.new_files.add(file_in_source)

    def get_residual_files(self):
        logger.debug('Searching for residual files')
        for file_in_target in self.files_only_in_target:
            if (
                file_in_target in self.error_files | self.modified_files_in_source | self.modified_files_in_target
                or file_in_target.get_rel() in [s.get_rel() for s, t in self.moved_files]
            ):
                continue
            self.residual_files.add(file_in_target)

    def save_report(self):
        if self.save_report_path.endswith('.xlsx'):
            logger.info('Loading data to create comparison report')
            both_files = {f for sub_l in self.files_in_both for f in sub_l}
            all_files = sorted(
                self.files_only_in_target | self.files_only_in_source | both_files, key=lambda x: x.get_rel()
            )
            df = pd.DataFrame(data=all_files, columns=['file'])
            source_files = self.files_only_in_source | both_files
            df['exist in source'] = list(sorted([file in source_files for file in all_files]))
            target_files = self.files_only_in_target | both_files
            df['exist in target'] = list(sorted([file in target_files for file in all_files]))
            not_modified = [f for sub_l in self.not_modified_files for f in sub_l]
            df['same files'] = list(sorted([file in not_modified for file in all_files]))
            modified_in_source = [f for sub_l in self.modified_files_in_source for f in sub_l]
            df['modified in source'] = list(sorted([file in modified_in_source for file in all_files]))
            modified_in_target = [f for sub_l in self.modified_files_in_target for f in sub_l]
            df['modified in target'] = list(sorted([file in modified_in_target for file in all_files]))
            moved = [f.get_rel() for sub_l in self.moved_files for f in sub_l]
            df['moved'] = list(sorted([file.get_rel() in moved for file in all_files]))
            df['new'] = list(sorted([file in self.new_files for file in all_files]))
            df['residual in target'] = list(sorted([file in self.residual_files for file in all_files]))
            df['error'] = list(sorted([file in self.error_files for file in all_files]))

            # Convert boolean True/False to string 'X' and empty
            df = df.applymap(lambda x: {True: 'X', False: ''}.get(x, x))

            logger.info('Starting to write comparison report')
            os.makedirs(os.path.dirname(self.save_report_path), exist_ok=True)
            df.to_excel(self.save_report_path, index=False)
            logger.info(f'Comparison report was saved to {self.save_report_path}')

    def print_results(self):
        logger.info('-------------------------')
        logger.info('Analyzing directory tree:')
        logger.info(f'Files that exist only in source: {len(self.files_only_in_source)}')
        logger.info(f'Files that exist only in target: {len(self.files_only_in_target)}')
        logger.info(f'Files that exist in both directories: {len(self.files_in_both)}')
        logger.info('---------------------------')
        logger.info('Analyzing content of files:')
        logger.info(f'Files that are the not modified: {len(self.not_modified_files)}')
        logger.info(f'Files that were modified in source: {len(self.modified_files_in_source)}')
        logger.info(f'Files that were modified in target: {len(self.modified_files_in_target)}')
        logger.info(f'Files that were moved : {len(self.moved_files)}')
        logger.info(f'Files that are new in source: {len(self.new_files)}')
        logger.info(f'Files that are residual in target: {len(self.residual_files)}')
        logger.info(
            f'Files that could not be analyzed ({len(self.error_files)})'
            + str({True: ': \n' + '\n  '.join(self.error_files), False: ''}.get(len(self.error_files) > 0))
        )

    def estimate_actions(self):
        self.files_to_copy = (
            self.modified_files_in_source
            | self.modified_files_in_target
            | {(file, file.as_target(self.dirs)) for file in self.new_files}
        )
        self.files_to_move = self.moved_files
        self.files_to_delete = self.residual_files
        self.files_to_keep = {s for s, t in self.not_modified_files}

    def get_results(
        self,
    ) -> tuple[list[tuple[CstmPath, CstmPath]], list[tuple[CstmPath, CstmPath]], list[CstmPath], list[CstmPath]]:
        sorted_files_to_copy = list(sorted(self.files_to_copy, key=lambda x: x[0]))
        sorted_files_to_move = list(sorted(self.files_to_move, key=lambda x: x[0]))
        sorted_files_to_delete = list(sorted(self.files_to_delete))
        sorted_files_to_keep = list(sorted(self.files_to_keep))

        return sorted_files_to_copy, sorted_files_to_move, sorted_files_to_delete, sorted_files_to_keep


class SyncDirs:
    def __init__(
        self,
        files_to_copy: list[tuple[CstmPath, CstmPath]],
        files_to_move: list[tuple[CstmPath, CstmPath]],
        files_to_delete: list[CstmPath],
        files_to_keep: list[CstmPath],
        mirror: MirrorDatabase,
        root_gui,
        dirs,
        default_actions=None,
        rebuild_mirror=False,
    ):
        logger.info('---------------------------')
        logger.info('Initializing synchronization')

        # Input variables
        self.root_gui = root_gui
        self.mirror = mirror
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
            # Run functions
            if rebuild_mirror:
                self.rebuild_local_mirror(add_files=files_to_keep)
            self.copy_files()
            self.move_files()
            self.delete_files()
            logger.info('Finished synchronizing directories')
            self.print_errors()
        else:
            logger.warning('Popup did not end well')

    def rebuild_local_mirror(self, add_files: list[CstmPath]):
        logger.info('Rebuilding local mirror')
        time_init = time.time()
        self.mirror.reset()
        self.mirror.add(add_files)
        logger.info(
            f'Local mirror was rebuilt in {int(time.time() - time_init)} seconds. '
            f'New length is {self.mirror.size()} entries'
        )

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
        number = len(self.files_requested_to_copy)
        counter_size = 0
        counter_timer = time.time()

        for i, (origin, destination) in enumerate(self.files_requested_to_copy, 1):
            success = False
            try:
                size = get_size(origin, as_str=False)
                logger.info(f'Copying file {i} of {number}: {origin} ({format_size(size)})')
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(origin, destination)
                self.mirror.add(origin)
                counter_size += size
                logger.debug(
                    f'Copy finished. Average speed {format_size(counter_size / (time.time() - counter_timer))}/s'
                )
                success = True
            except Exception as e:
                error_msg = str(check_length(origin) + '  ' + check_length(destination)).strip()
                error_msg = e if error_msg == '' else error_msg
                logger.error(f'There was an error while copying file {origin}. Exception: {error_msg}')

            self.files_copied.append(((origin, destination), success))

    def move_files(self):
        number = len(self.files_requested_to_move)
        t1 = time.time()
        for i, (origin, destination) in enumerate(self.files_requested_to_move, 1):
            success = False
            try:
                logger.info(f'Moving file {i} of {number}: {origin} ({get_size(origin)})')
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.move(origin, destination)
                source_dir, target_dir = get_dirs_from_path(origin, self.dirs)
                if source_dir is not None:
                    self.mirror.replace(
                        origin.replace(target_dir, source_dir), destination.replace(target_dir, source_dir)
                    )
                logger.debug(f'Move finished. Average speed {int(60 * i / (time.time() - t1))} files/min')
                success = True
            except Exception as e:
                error_msg = str(check_length(origin) + '  ' + check_length(destination)).strip()
                error_msg = e if error_msg == '' else error_msg
                logger.error(f'There was an error while moving file {origin}. Exception: {error_msg}')

            self.files_moved.append(((origin, destination), success))

    def delete_files(self):
        number = len(self.files_requested_to_delete)
        t1 = time.time()
        for i, path in enumerate(self.files_requested_to_delete, 1):
            success = False
            try:
                logger.info(f'Deleting file {i} of {number}: {path} ({get_size(path)})')
                os.chmod(path, stat.S_IWRITE)
                os.remove(path)
                source_dir, target_dir = get_dirs_from_path(path, self.dirs)
                if source_dir is not None:
                    self.mirror.remove(path.replace(target_dir, source_dir))
                logger.info(f'Delete finished. Average speed {int(60 * i / (time.time() - t1))} files/min')
                success = True
            except Exception as e:
                error_msg = check_length(path)
                error_msg = e if error_msg == '' else error_msg
                logger.error(f'There was an error while deleting file {path}. Exception: {error_msg}')

            # If the folder of the deleted file is left empty, delete it
            dir_name = os.path.dirname(path)
            if success and len(os.listdir(dir_name)) == 0:
                try:
                    os.removedirs(dir_name)
                    logger.info(f'Also removed empty directory {dir_name}')
                except Exception as e:
                    logger.info(f'Could not remove empty directory {dir_name}. Exception: {e}')

            self.files_deleted.append((path, success))

    def print_errors(self):
        failed_copy = [p for p, success in self.files_copied if not success]
        if failed_copy:
            logger.warning(
                'Summary of files that failed to be copied:\n    '
                + '\n    '.join([f'{s} -> {d}' for s, d in failed_copy])
            )
        failed_move = [p for p, success in self.files_moved if not success]
        if failed_move:
            logger.warning(
                'Summary of files that failed to be moved:\n    '
                + '\n    '.join([f'{s} -> {d}' for s, d in failed_move])
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


def get_dirs_from_path(path, dirs):
    def uniform(p_: str) -> str:
        return p_.replace('\\', '/')

    for s, t in dirs:
        if uniform(s) in uniform(path) or uniform(t) in uniform(path):
            return s, t
    logger.error(f'Could not identify root folders of path {path}')
    return None, None


if __name__ == '__main__':
    source_root_dir = r'D:\Projects\Python\AutomaticBackup\TestBackupSource'
    # source_root_dir = r'E:'
    # target_root_dir = r'N:\BackupPC\D'
    target_root_dir = r'D:\Projects\Python\AutomaticBackup\TestBackupDestination'
    # target_root_dir = r'N:\NetBakData\Rafael Savi@RAFAEL-SAVI\Disk E'

    root_ = tk.Tk()

    files = get_all_files('D:/Musicas', [])
    files2 = files.copy()

    t1 = time.time()
    stats1 = [get_stat(p) for p in files]
    t2 = time.time()
    print(mode, t2 - t1)

    stats1[1]
    # root_.mainloop()
