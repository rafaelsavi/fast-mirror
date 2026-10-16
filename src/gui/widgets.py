import os
import time
import tkinter as tk
from enum import Enum
from tkinter.scrolledtext import ScrolledText

from gui.enums import TkinterCfgState
from utils.logger import logger
from utils.utils import DirectoryPair, sanitize_path


class EntryPaths(ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get(self, *args, **kwargs) -> list[tuple[str, str]]:  # type: ignore[override]
        raw: str = super().get('1.0', tk.END)
        lines = raw.splitlines()
        valid_paths: list[tuple[str, str]] = [pair for line in lines if (pair := self.parse_line(line)) is not None]
        unique_paths = list(set(valid_paths))
        unique_paths.sort(key=lambda x: x[0])  # sort by source path
        return unique_paths

    def get_as_dir_pairs(self) -> list[DirectoryPair]:
        return [DirectoryPair(source=pair[0], target=pair[1]) for pair in self.get()]

    def add(self, pair: tuple[str, str] | DirectoryPair):
        pair_tuple = (pair.source, pair.target) if isinstance(pair, DirectoryPair) else pair
        self.set(self.get() + [pair_tuple])

    def set(self, paths: list[tuple[str, str]] | list[DirectoryPair] | list[list[str]]):
        normalized_paths: list[tuple[str, str]] = []
        for p in paths:
            if isinstance(p, DirectoryPair):
                normalized_paths.append((p.source, p.target))
            else:
                normalized_paths.append((str(p[0]), str(p[1])))
        normalized_paths = list(set(normalized_paths))
        normalized_paths.sort(key=lambda x: x[0])  # sort by source path
        raw = '\n'.join([f'{pair[0]} -> {pair[1]}' for pair in normalized_paths])
        was_disabled = self.cget('state') == TkinterCfgState.DISABLED.value
        if was_disabled:
            self.configure(state=TkinterCfgState.NORMAL.value)
        super().delete('1.0', tk.END)  # delete current text
        super().insert('1.0', raw)  # add at line 1, col 0
        if was_disabled:
            self.configure(state=TkinterCfgState.DISABLED.value)

    @staticmethod
    def parse_line(raw: str) -> None | tuple[str, str]:
        try:
            if ' -> ' not in raw:
                return None
            source, target = raw.split(' -> ', 1)
            source, target = source.strip(), target.strip()
            # Source must exist as a directory.
            # Target can exist as a directory, or its parent directory must exist
            # (e.g. creating a new backup target folder).
            if os.path.isdir(source) and (
                os.path.isdir(target) or os.path.isdir(os.path.dirname(os.path.realpath(target)))
            ):
                return (os.path.realpath(source), os.path.realpath(target))
            return None
        except Exception:
            return None


class EntryExclusions(tk.Entry):
    def __init__(self, *args, **kwargs):
        self.var = tk.StringVar()
        super().__init__(*args, textvariable=self.var, **kwargs)
        self.reset()

    def get(self, *args, **kwargs) -> list[str]:  # type: ignore[override]
        raw = self.var.get()
        exclusions = list(sorted({sanitize_path(x.strip()) for x in raw.split(',') if x.strip() != ''}))
        return exclusions

    def set(self, exclusions: list[str]):
        raw = ','.join(list(sorted(exclusions)))
        self.var.set(raw)

    def reset(self):
        self.set(['$RECYCLE.BIN', r'\~$'])


class EntryTimes(ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get(self, *args, **kwargs) -> list[str]:  # type: ignore[override]
        raw: str = super().get('1.0', tk.END)
        times = raw.splitlines()
        normalized = []
        for t in times:
            try:
                parsed = time.strptime(t.strip(), '%H:%M')
                normalized.append(f'{parsed.tm_hour:02d}:{parsed.tm_min:02d}')
            except Exception as e:
                if t.strip() != '':
                    logger.warning(
                        f'Time entry "{t}" was ignored because it does not match the format hh:mm. Exception: {e}'
                    )
        return list(sorted(set(normalized)))

    def set(self, times):
        normalized = []
        for t in times:
            try:
                parsed = time.strptime(t.strip(), '%H:%M')
                normalized.append(f'{parsed.tm_hour:02d}:{parsed.tm_min:02d}')
            except Exception:
                continue
        normalized = list(sorted(set(normalized)))
        raw = '\n'.join(normalized)
        was_disabled = self.cget('state') == TkinterCfgState.DISABLED.value
        if was_disabled:
            self.configure(state=TkinterCfgState.NORMAL.value)
        super().delete('1.0', tk.END)  # delete current text
        super().insert('1.0', raw)  # add at line 1, col 0
        if was_disabled:
            self.configure(state=TkinterCfgState.DISABLED.value)

    @staticmethod
    def is_hh_mm(t):
        try:
            time.strptime(t.strip(), '%H:%M')
        except Exception as e:
            if t.strip() != '':
                logger.warning(
                    f'Time entry "{t}" was ignored because it does not match the format hh:mm. Exception: {e}'
                )
            return False
        else:
            return True


class Action(Enum):
    COPY = 'copy'
    MOVE = 'move'
    DELETE = 'delete'

    @classmethod
    def get_options(cls) -> list['Action']:
        return list(cls.__members__.values())

    @classmethod
    def get_options_str(cls) -> list[str]:
        return [action.value for action in cls.get_options()]

    @classmethod
    def from_str(cls, value: str) -> 'Action':
        if value.upper() in cls.__members__:
            return cls.__members__[value.upper()]
        else:
            raise ValueError(f'Invalid {cls.__name__} value: {value}. Must be one of {list(cls.__members__.keys())}.')


class DefaultActions:
    def __init__(self):
        self._data: dict[Action, bool] = {k: False for k in Action.get_options()}
        self._tkinter_vars: dict[Action, tk.BooleanVar] = {k: tk.BooleanVar() for k in Action.get_options()}
        self.reset()

    def get(self) -> list[str]:
        return [k.value for k, v in self._data.items() if self.get_var_value(k)]

    def get_as_actions(self) -> list[Action]:
        return [k for k, v in self._data.items() if self.get_var_value(k)]

    def get_var(self, k: Action | str) -> tk.BooleanVar:
        if isinstance(k, str):
            k = Action.from_str(k)
        return self._tkinter_vars[k]

    def get_var_value(self, k: Action | str) -> bool:
        if isinstance(k, str):
            k = Action.from_str(k)
        return self._tkinter_vars[k].get()

    def set(self, values: list[Action | str]):
        if not isinstance(values, list):
            raise TypeError(f'Expected list of Action, got {type(values)}.')
        parsed_actions = [Action.from_str(k) if isinstance(k, str) else k for k in values]
        for action in Action.get_options():
            self[action] = action in parsed_actions

    def __setitem__(self, k: Action | str, v: bool):
        if isinstance(k, str):
            k = Action.from_str(k)

        if k not in Action.get_options():
            raise ValueError(f'Invalid Action: {k}. Must be one of {Action.get_options_str()}.')

        self._data[k] = v
        self._tkinter_vars[k].set(v)

    def reset(self):
        self[Action.COPY] = True
        self[Action.MOVE] = False
        self[Action.DELETE] = False


class WeekDays:
    options = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

    def __init__(self):
        self.checkboxes = {day: tk.BooleanVar() for day in self.options}

    def set(self, values: list[str]):
        for value, _status in self.checkboxes.items():
            self.checkboxes[value].set(True) if value in values else self.checkboxes[value].set(False)

    def get(self) -> list[str]:
        return [value for value, status in self.checkboxes.items() if status.get()]

    def get_as_numbers(self) -> list[int]:
        return [self.options.index(day) for day in self.get()]


class LogLevels:
    options = 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'

    def __init__(self):
        self.checkboxes = {option: tk.BooleanVar() for option in self.options}
        self.reset()

    def reset(self):
        for k, _v in self.checkboxes.items():
            if k in ['DEBUG']:
                self.checkboxes[k].set(False)
            else:
                self.checkboxes[k].set(True)

    def set(self, values: list[str]):
        for value, _status in self.checkboxes.items():
            self.checkboxes[value].set(True) if value in values else self.checkboxes[value].set(False)

    def get(self) -> list[str]:
        return [value for value, status in self.checkboxes.items() if status.get()]


class TextLogger(ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lines = []
        self.log_levels = []
        self.limit_lines = 50000
        self.configure(font='TkFixedFont')
        self.tag_config('DEBUG', foreground='gray')
        self.tag_config('INFO', foreground='black')
        self.tag_config('WARNING', foreground='orange')
        self.tag_config('ERROR', foreground='red')
        self.tag_config('CRITICAL', foreground='red', underline=True)

    def set_log_levels(self, levels: list[str]):
        self.log_levels = levels
        self._rewrite()

    def insert(self, *args, **kwargs):
        message, tag = args
        self.lines.append((message, tag))
        if tag in self.log_levels:
            self.configure(state=TkinterCfgState.NORMAL.value)
            super().insert(tk.END, message + '\n', tag)
            self.configure(state=TkinterCfgState.DISABLED.value)
            self._check_num_lines()

    def _check_num_lines(self):
        # Remove excessive lines
        lines = self.get('1.0', tk.END).splitlines()
        if len(lines) > self.limit_lines * 1.1:
            self._rewrite()

    def _rewrite(self):
        yview_pos = self.yview()[0]
        if len(self.lines) > self.limit_lines * 1.5:
            self.lines = self.lines[-self.limit_lines :]
        self.configure(state=TkinterCfgState.NORMAL.value)
        self.delete('1.0', tk.END)
        for message, tag in self.lines[-self.limit_lines :]:
            if tag in self.log_levels:
                super().insert(tk.END, message + '\n', tag)
        self.configure(state=TkinterCfgState.DISABLED.value)
        self.yview_moveto(yview_pos)
