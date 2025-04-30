import pandas as pd
import os
import stat
from copy import deepcopy
from typing import List, Set, Tuple, Iterable, Union
import filecmp
import shutil
import winsound
import time
import tkinter as tk
from source.custom_gui import CustomCheckboxTreeView
from source.utils import get_size, format_size, Path, check_length, compare_files, is_list_of_substr_in_str, \
    encode_stats, CustomException
from source.logger import logger
from sqlitedict import SqliteDict


class MirrorDataBase:

    def __init__(self, path=r'.\local_mirror.db', reset=False):
        self.path = path
        if reset:
            self.reset()

    def _get_db(self):
        try:
            return SqliteDict(self.path, autocommit=True)
        except Exception as e:
            raise Exception(f'Could not access database. Exception: {e}')

    def size(self):
        try:
            with self._get_db() as mirror_db:
                return len(mirror_db)
        except Exception as e:
            logger.warning(f'Could not get size of database. Exception: {e}')
            return 0

    def reset(self):
        try:
            os.remove(self.path)
            self._get_db()
            return True
        except Exception as e:
            logger.warning(f'Could not reset database. Exception: {e}')
            return False

    def process_and_add(self, file_path: Union[str, List[str], Set[str]]):
        def add_stats(self_, p):
            try:
                stats = os.stat(p)
                stats = encode_stats(stats)
                self_.add(os.path.normpath(p), stats)
            except Exception as e:
                logger.error(f'Could not add file {p} to local mirror. Exception: {e}')

        if isinstance(file_path, Iterable) and not isinstance(file_path, str):
            for _file_path in file_path:
                add_stats(self, _file_path)
        else:
            add_stats(self, file_path)

    def add(self, key=None, value=None, dictionary=None):
        try:
            with self._get_db() as mirror_db:
                if dictionary is not None:
                    mirror_db.update(dictionary)
                elif key is not None and value is not None:
                    mirror_db[key] = value
                else:
                    raise Exception('Missing arguments to set database')
            return True
        except Exception as e:
            logger.warning(f'Could not save to database ({key}: {value}). Exception: {e}')
            return False

    def get(self, key, fallback=None):
        def get_from_dict(d, k, f):
            try:
                if f:
                    return d.get(k, f)
                else:
                    return d[k]
            except KeyError:
                logger.warning(f'Could not read key from database because it does not exist: {k}')
                return None

        try:
            with self._get_db() as mirror_db:
                if isinstance(key, Iterable) and not isinstance(key, str):
                    return {get_from_dict(mirror_db, k, fallback) for k in key}
                else:
                    return get_from_dict(mirror_db, key, fallback)
        except Exception as e:
            logger.warning(f'Could not read from database (Key {key}). Exception: {e}')
            return None

    def get_keys(self, exclude: List[str] = None) -> set:
        try:
            with self._get_db() as mirror_db:
                keys = mirror_db.keys()
                if exclude is not None:
                    return {k for k in keys if not is_list_of_substr_in_str(exclude, k)}
                else:
                    return set(keys)
        except Exception as e:
            logger.warning(f'Could not read from database. Exception: {e}')
            return set()

    def remove(self, key):
        try:
            with self._get_db() as mirror_db:
                if key in mirror_db:
                    del mirror_db[key]
                return True
        except Exception as e:
            logger.warning(f'Could not remove key from database (Key {key}). Exception: {e}')
            return False


if 'local_mirror' not in locals():
    local_mirror = MirrorDataBase()


class CompareDirs:

    def __init__(self, dirs: List[Tuple[str, str]], exclusions: List[str], save_report_path='',
                 compare_with_local_mirror=False, use_light_comparison=False, care_about_moved_files=True):

        logger.info('-----------------------------')
        logger.info('Initializing comparison')
        logger.info('Directories:\n  ' + '\n  '.join([f'{d1}  -->  {d2}' for d1, d2 in dirs]))
        t1_compare_dirs = time.time()

        self.dirs = dirs
        self.exclusions = exclusions
        self.save_report_path = save_report_path
        self.use_light_comparison = use_light_comparison

        # Initialize comparison variables
        filecmp.clear_cache()
        self.files_only_in_source: Set[Path] = set()
        self.files_only_in_target: Set[Path] = set()
        self.files_in_both: Set[Tuple[Path, Path]] = set()
        self.not_modified_files: Set[Tuple[Path, Path]] = set()
        self.modified_files_in_source: Set[Tuple[Path, Path]] = set()
        self.modified_files_in_target: Set[Tuple[Path, Path]] = set()
        self.moved_files: Set[Tuple[Path, Path]] = set()
        self.new_files: Set[Path] = set()
        self.residual_files: Set[Path] = set()
        self.error_files: Set[Path] = set()

        # Initialize sync variables
        self.files_to_copy: Set[Tuple[Path, Path]] = set()
        self.files_to_move: Set[Tuple[Path, Path]] = set()
        self.files_to_delete: Set[Path] = set()
        self.files_to_keep: Set[Path] = set()

        # Run comparison
        if compare_with_local_mirror:
            self.get_files_from_source_and_local_mirror()
        else:
            self.get_files_from_source_and_destination()

        logger.info(f'Finished collecting file paths: '
                    f'{len(self.files_in_both)} exist in source and destination, '
                    f'{len(self.files_only_in_source)} exist only in source, '
                    f'{len(self.files_only_in_target)} exist only in destination')
        logger.info('Starting to compare files')
        self.get_modified_files()
        if care_about_moved_files:
            self.get_moved_files()
        self.get_new_files()
        self.get_residual_files()
        logger.info('Finished to compare files')
        self.save_report()
        self.print_results()

        # Estimate syncronization actions
        self.estimate_actions()
        logger.info(f'Finished comparing directories in {int((time.time() - t1_compare_dirs)/60)} minutes')

    def get_files_from_source_and_local_mirror(self):
        logger.info('Starting to compare files based on local mirror')
        logger.debug(f'Local mirror has {local_mirror.size()} entries')

        self.files_only_in_source = set()
        self.files_only_in_target = set()
        self.files_in_both = set()
        paths_in_mirror = local_mirror.get_keys(exclude=self.exclusions)
        paths_in_source = {f.get() for source_dir, target_dir in self.dirs
                           for f in Path.get_from_dir(source_dir, exclude=self.exclusions)}

        logger.info(f'Finished scanning all files. Found {len(paths_in_source)} files in the source and '
                    f'{len(paths_in_mirror)} files in the mirror')
        logger.info(f'Starting to compare source with mirror')

        # Compare local paths with local mirror
        paths_only_in_mirror = paths_in_mirror - paths_in_source  # Paths that might be deleted
        paths_only_in_source = paths_in_source - paths_in_mirror  # Paths that might be new

        paths_in_both = paths_in_source & paths_in_mirror  # Paths that might have changed
        mirror_stats = local_mirror.get(paths_in_both)
        actual_stats = {encode_stats(os.stat(p)) for p in paths_in_both}
        paths_in_both = {p for p, mirror_stat, actual_stat in zip(paths_in_both, mirror_stats, actual_stats)
                         if mirror_stat != actual_stat}

        logger.info('Found {} files with possible changes'.format(
            len(paths_only_in_mirror) + len(paths_only_in_source) + len(paths_in_both)))
        logger.info('Confirming changes with destination now')

        # Check file existence in source and target
        all_paths = paths_only_in_mirror | paths_only_in_source | paths_in_both
        for p in all_paths:
            source_dir, target_dir = get_dirs_from_path(p, self.dirs)
            if source_dir is not None:
                source_file = Path(abs_path=p, root_dir=source_dir)
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
            files_in_source = Path.get_from_dir(source_dir, exclude=self.exclusions)
            files_in_target = Path.get_from_dir(target_dir, exclude=self.exclusions)

            rel_paths_in_source = {f.get_rel() for f in files_in_source}
            rel_paths_in_target = {f.get_rel() for f in files_in_target}

            self.files_only_in_source.update({f for f in files_in_source if f.get_rel() not in rel_paths_in_target})
            self.files_only_in_target.update({f for f in files_in_target if f.get_rel() not in rel_paths_in_source})
            self.files_in_both.update({(Path(f, source_dir), Path(root_dir=target_dir, rel_path=f.get_rel()))
                                       for f in files_in_source if f.get_rel() in rel_paths_in_target})

    def get_modified_files(self):
        """Compare files that exist in both places and check for newer versions in the source"""
        logger.debug('Searching for modified files')
        number_files = len(self.files_in_both)
        t1 = time.time()
        for i, (file_source, file_target) in enumerate(self.files_in_both):
            if i > 0 and i % 1000 == 0:
                logger.debug(f'{i} of {number_files} files scanned so far. '
                             f'Average read speed: {int(60*i/(time.time() - t1))} files/min')

            success, match = compare_files(file_source.get(), file_target.get(), light=self.use_light_comparison)

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
                        logger.warning(f'Could not compare modification times of {file_source} or {file_target}. '
                                       f'Exception: {e}')
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
        t1 = time.time()
        for i, file_in_source in enumerate(self.files_only_in_source):
            if i > 0 and i % 500 == 0:
                logger.debug(f'{i} of {number_files} files scanned so far'
                             f'Average read speed: {int(60*i/(time.time() - t1))} files/min')

            file_basename_in_source = file_in_source.get_basename()

            for file_in_target in self.files_only_in_target:
                file_basename_in_target = file_in_target.get_basename()

                if file_in_source in used_files:
                    break
                if file_in_target in used_files:
                    continue

                if file_basename_in_source == file_basename_in_target:
                    success, match = compare_files(file_in_source.get(), file_in_target.get(), self.use_light_comparison)
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
            if file_in_source in self.error_files | self.modified_files_in_source | self.modified_files_in_target \
            or file_in_source.get_rel() in [t.get_rel() for s, t in self.moved_files]:
                continue
            self.new_files.add(file_in_source)

    def get_residual_files(self):
        logger.debug('Searching for residual files')
        for file_in_target in self.files_only_in_target:
            if file_in_target in self.error_files | self.modified_files_in_source | self.modified_files_in_target \
            or file_in_target.get_rel() in [s.get_rel() for s, t in self.moved_files]:
                continue
            self.residual_files.add(file_in_target)

    def save_report(self):
        if self.save_report_path.endswith('.xlsx'):
            logger.info('Loading data to create comparison report')
            both_files = {f for sub_l in self.files_in_both for f in sub_l}
            all_files = sorted(self.files_only_in_target | self.files_only_in_source | both_files,
                               key=lambda x: x.get_rel())
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
        logger.info('Analysing directory tree:')
        logger.info(f'Files that exist only in source: {len(self.files_only_in_source)}')
        logger.info(f'Files that exist only in target: {len(self.files_only_in_target)}')
        logger.info(f'Files that exist in both directories: {len(self.files_in_both)}')
        logger.info('---------------------------')
        logger.info('Analysing content of files:')
        logger.info(f'Files that are the not modified: {len(self.not_modified_files)}')
        logger.info(f'Files that were modified in source: {len(self.modified_files_in_source)}')
        logger.info(f'Files that were modified in target: {len(self.modified_files_in_target)}')
        logger.info(f'Files that were moved : {len(self.moved_files)}')
        logger.info(f'Files that are new in source: {len(self.new_files)}')
        logger.info(f'Files that are residual in target: {len(self.residual_files)}')
        logger.info(f'Files that could not be analysed ({len(self.error_files)})'
                    + str({True: ': \n' + '\n  '.join([x.get() for x in self.error_files]), False: ''}.get(len(self.error_files) > 0)))

    def estimate_actions(self):
        self.files_to_copy = self.modified_files_in_source | self.modified_files_in_target | \
                             {(file, file.as_target(self.dirs)) for file in self.new_files}
        self.files_to_move = self.moved_files
        self.files_to_delete = self.residual_files
        self.files_to_keep = {s for s, t in self.not_modified_files}

    def get_results(self):
        sorted_files_to_copy = list(sorted(self.files_to_copy, key=lambda x: x[0].get()))
        sorted_files_to_move = list(sorted(self.files_to_move, key=lambda x: x[0].get()))
        sorted_files_to_delete = list(sorted(self.files_to_delete, key=lambda x: x.get()))
        sorted_files_to_keep = list(sorted(self.files_to_keep, key=lambda x: x.get()))

        return sorted_files_to_copy, sorted_files_to_move, sorted_files_to_delete, sorted_files_to_keep


class SyncDirs:

    def __init__(self, files_to_copy: List[Tuple[Path, Path]], files_to_move: List[Tuple[Path, Path]],
                 files_to_delete: List[Path], files_to_keep: List[Path], root_gui, dirs, default_actions=None, rebuild_mirror=False):
        logger.info('---------------------------')
        logger.info('Initializing syncronization')

        # Input variables
        self.root_gui = root_gui
        self.dirs = dirs
        self.default_actions = default_actions if default_actions is not None else ['copy']

        # Initialize variables
        self.files_available_to_copy: List[Tuple[Path, Path]] = files_to_copy
        self.files_available_to_move: List[Tuple[Path, Path]] = files_to_move
        self.files_available_to_delete: List[Path] = files_to_delete
        self.files_requested_to_copy: List[Tuple[str, str]] = list()
        self.files_requested_to_move: List[Tuple[str, str]] = list()
        self.files_requested_to_delete: List[str] = list()
        self.files_copied = list()
        self.files_moved = list()
        self.files_deleted = list()

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

    @staticmethod
    def rebuild_local_mirror(add_files: List[Path]):
        logger.info('Rebuilding local mirror')
        time_init = time.time()
        local_mirror.reset()
        local_mirror.process_and_add({f.get() for f in add_files})
        logger.info(f'Local mirror was rebuilt in {int(time.time()-time_init)} seconds. '
                    f'New length is {local_mirror.size()} entries')

    def open_confirmation_popup(self):
        popup = ActionSelection(self.root_gui, self.files_available_to_copy, self.files_available_to_move,
                                self.files_available_to_delete, self.default_actions)
        time_init = time.time()
        while (time.time() - time_init) < 7200:
            if popup.finished:
                self.files_requested_to_copy, self.files_requested_to_move, self.files_requested_to_delete = popup.get_outputs()
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
                local_mirror.process_and_add(origin)
                counter_size += size
                logger.debug(f'Copy finished. Average speed {format_size(counter_size/(time.time()-counter_timer))}/s')
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
                    local_mirror.remove(origin.replace(target_dir, source_dir))
                    local_mirror.process_and_add(destination.replace(target_dir, source_dir))
                logger.debug(f'Move finished. Average speed {int(60*i/(time.time() - t1))} files/min')
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
                    local_mirror.remove(path.replace(target_dir, source_dir))
                logger.info(f'Delete finished. Average speed {int(60*i/(time.time() - t1))} files/min')
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
            logger.warning('Summary of files that failed to be copied:\n    ' + '\n    '.join([f'{s} -> {d}' for s, d in failed_copy]))
        failed_move = [p for p, success in self.files_moved if not success]
        if failed_move:
            logger.warning('Summary of files that failed to be moved:\n    ' + '\n    '.join([f'{s} -> {d}' for s, d in failed_move]))
        failed_delete = [p for p, success in self.files_deleted if not success]
        if failed_delete:
            logger.warning('Summary of files that failed to be deleted:\n    ' + '\n    '.join(failed_delete))


class ActionSelection:

    def __init__(self, root_gui, files_to_copy, files_to_move, files_to_delete, default_actions):
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
        self.init_time = None
        self.countdown_size = 1200

        # Configure gui
        self.popup = tk.Toplevel(self.root_gui)
        self.popup.protocol("WM_DELETE_WINDOW", self.button_cancel_click)
        self.create_widgets()

        # Init watchdog functions
        self.check_countdown()

    def get_countdown(self) -> Tuple[bool, str]:
        countdown = max(0, int(self.countdown_size + self.init_time - time.time()))
        countdown_str = f' ({countdown}s)' if self.is_timer_active else ''
        return self.is_timer_active and countdown <= 0, countdown_str

    def create_widgets(self):
        logger.info('Collecting data for selection window. This may take a while')
        frame_buttons = tk.Frame(self.popup)

        self.button_save = tk.Button(frame_buttons, text='Save and continue', anchor='w', command=self.button_save_click)
        self.button_save.grid(row=0, column=0, sticky='w')

        def turn_timer_off(): self.is_timer_active = False
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
        self.tree.add_file_lists({'copy': self.files_to_copy,
                                  'move': self.files_to_move,
                                  'delete': self.files_to_delete}, default_active=self.default_actions)

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
    def uniform(p_: str):
        return p_.replace('\\', '/')
    for s, t in dirs:
        if uniform(s) in uniform(path) or uniform(t) in uniform(path):
            return s, t
    logger.error(f'Could not identify root folders of path {path}')
    return None, None


if __name__ == '__main__':

    source_root_dir = r'D:\Projects\Python\AutomaticBackup\TestBackupSource'
    # source_root_dir = r'E:'
    #target_root_dir = r'N:\BackupPC\D'
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
    #root_.mainloop()