import time
import tkinter as tk
from copy import deepcopy
from tkinter.scrolledtext import ScrolledText
import os
from enum import Enum

from gui.enums import TkinterCfgStatus
from utils.logger import logger
from utils.utils import DirectoryPair


class EntryTimes(ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get(self, *args, **kwargs):
        raw: str
        raw = super().get('1.0', tk.END)
        times = raw.splitlines()
        times = [t for t in times if self.is_hh_mm(t)]
        return times

    def set(self, times):
        times = [t for t in times if self.is_hh_mm(t)]
        raw = '\n'.join(times)
        super().delete('1.0', tk.END)  # delete current text
        super().insert('1.0', raw)  # add at line 1, col 0

    @staticmethod
    def is_hh_mm(t):
        try:
            time.strptime(t, '%H:%M')
        except:
            if t.strip() != '':
                logger.warning(f'Time entry "{t}" was ignored because it does not match the format hh:mm')
            return False
        else:
            return True


class EntryExclusions(tk.Entry):
    def __init__(self, *args, **kwargs):
        self.var = tk.StringVar()
        super().__init__(*args, textvariable=self.var, **kwargs)
        self.reset()

    def get(self, *args, **kwargs) -> list[str]:
        raw = self.var.get()
        exclusions = list({x.strip().replace('/', '\\') for x in raw.split(',') if x.strip() != ''})
        return exclusions

    def set(self, exclusions: list[str]):
        raw = ','.join(exclusions)
        self.var.set(raw)

    def reset(self):
        self.set([r'D:\$RECYCLE.BIN', r'\~$'])


class EntryPaths(ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get(self, *args, **kwargs) -> list[tuple[str, str]]:
        raw: str
        raw = super().get('1.0', tk.END)
        lines = raw.splitlines()
        paths = list({self.parse_line(line) for line in lines})
        paths = [pair for pair in paths if pair is not None]
        return paths

    def get_as_dir_pairs(self) -> list[DirectoryPair]:
        return [DirectoryPair(source=pair[0], target=pair[1]) for pair in self.get()]

    def add(self, pair: tuple[str, str]):
        self.set(self.get() + [pair])

    def set(self, paths: list[tuple[str, str]] | list[DirectoryPair]):
        paths = [(pair.source, pair.target) if isinstance(pair, DirectoryPair) else pair for pair in paths]
        raw = '\n'.join([f'{pair[0]} -> {pair[1]}' for pair in paths])
        super().delete('1.0', tk.END)  # delete current text
        super().insert('1.0', raw)  # add at line 1, col 0

    @staticmethod
    def parse_line(raw: str) -> None | tuple[str, str]:
        try:
            source, target = raw.split(' -> ')
            if os.path.isdir(source) and os.path.isdir(target):
                return (os.path.realpath(source), os.path.realpath(target))
            else:
                return None
        except:
            return None


class DefaultAction(Enum):
    COPY = 'copy'
    MOVE = 'move'
    DELETE = 'delete'


class DefaultActions:
    options = [DefaultAction.COPY, DefaultAction.MOVE, DefaultAction.DELETE]

    def __init__(self):
        self.data: dict[DefaultAction, bool] = {a: False for a in DefaultAction}
        self.reset()
        self.data_as_tkinter = {k: tk.BooleanVar() for k in self.data.keys()}
        self._set_tkinter_data()

    def get(self):
        for k, _v in self.data_as_tkinter.items():
            self.data[k] = self.data_as_tkinter[k].get()
        return self.data

    def get_tk(self, k: DefaultAction | str) -> tk.BooleanVar:
        key = k if isinstance(k, DefaultAction) else DefaultAction(k)
        return self.data_as_tkinter[key]

    def __setitem__(self, k: DefaultAction | str, v: bool):
        key = k if isinstance(k, DefaultAction) else DefaultAction(k)
        self.data[key] = v
        self._set_tkinter_data()

    def set(self, obj: dict[DefaultAction, bool]):
        self.data = obj
        self._set_tkinter_data()

    def _set_tkinter_data(self):
        for k, v in self.data.items():
            self.data_as_tkinter[k].set(v)

    def get_actions(self) -> list[DefaultAction]:
        return [k for k, v in self.get().items() if v]

    def reset(self):
        self.data[DefaultAction.COPY] = True
        self.data[DefaultAction.MOVE] = False
        self.data[DefaultAction.DELETE] = False


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
            self.configure(state=TkinterCfgStatus.NORMAL.value)
            super().insert(tk.END, message + '\n', tag)
            self.configure(state=TkinterCfgStatus.DISABLED.value)
            self._check_num_lines()

    def _check_num_lines(self):
        # Remove excessive lines
        lines = self.get('1.0', tk.END).splitlines()
        if len(lines) > self.limit_lines * 1.1:
            self._rewrite()

    def _rewrite(self):
        self.configure(state=TkinterCfgStatus.NORMAL.value)
        self.delete('1.0', tk.END)
        for message, tag in self.lines[-self.limit_lines :]:
            if tag in self.log_levels:
                super().insert(tk.END, message + '\n', tag)
        self.configure(state=TkinterCfgStatus.DISABLED.value)
