import contextlib
import os
import time
import tkinter as tk
from collections.abc import Callable
from enum import Enum
from tkinter.scrolledtext import ScrolledText

from gui.enums import TkinterCfgState
from utils.logger import logger
from utils.utils import DirectoryPair, sanitize_path


class EntryPaths(ScrolledText):
    def __init__(self, *args, **kwargs):
        if 'font' not in kwargs:
            kwargs['font'] = ('Consolas', 9)
        self.on_changed: Callable[[], None] | None = None
        super().__init__(*args, **kwargs)
        self.bind('<KeyRelease>', lambda e: self.highlight_syntax())
        self._setup_context_menu()

    def _setup_context_menu(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label='📂 Open in Explorer', command=self._context_open_explorer)
        menu.add_separator()
        menu.add_command(label='✂️ Cut', command=lambda: self.event_generate('<<Cut>>'))
        menu.add_command(label='📋 Copy', command=lambda: self.event_generate('<<Copy>>'))
        menu.add_command(label='📥 Paste', command=lambda: self.event_generate('<<Paste>>'))
        menu.add_separator()
        menu.add_command(label='Select All', command=lambda: self.tag_add(tk.SEL, '1.0', tk.END))

        def _show_menu(event):
            with contextlib.suppress(Exception):
                menu.tk_popup(event.x_root, event.y_root)

        self.bind('<Button-3>', _show_menu)

    def _context_open_explorer(self):
        line = self.get('insert linestart', 'insert lineend').strip()
        target = ''
        if ' -> ' in line:
            src, tgt = [p.strip().strip('"\'') for p in line.split(' -> ', 1)]
            target = src if os.path.exists(src) else tgt
        elif os.path.exists(line.strip('"\'')):
            target = line.strip('"\'')
        if target and os.path.exists(target):
            with contextlib.suppress(Exception):
                if hasattr(os, 'startfile'):
                    os.startfile(target)
                else:
                    import subprocess

                    subprocess.Popen(['explorer', target])

    def highlight_syntax(self):
        """Apply clean syntax highlighting to source paths, arrows, and target paths."""
        try:
            self.tag_configure('pair_arrow', foreground='#0d9488', font=('Segoe UI', 9, 'bold'))
            self.tag_configure('pair_source', foreground='#0f172a', font=('Consolas', 9, 'bold'))
            self.tag_configure('pair_target', foreground='#0284c7', font=('Consolas', 9))
            self.tag_configure('pair_error', foreground='#dc2626', underline=True)

            self.tag_remove('pair_arrow', '1.0', tk.END)
            self.tag_remove('pair_source', '1.0', tk.END)
            self.tag_remove('pair_target', '1.0', tk.END)
            self.tag_remove('pair_error', '1.0', tk.END)

            raw = super().get('1.0', tk.END)
            for line_idx, line in enumerate(raw.splitlines(), start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                if ' -> ' in line:
                    arrow_idx = line.find(' -> ')
                    self.tag_add('pair_source', f'{line_idx}.0', f'{line_idx}.{arrow_idx}')
                    self.tag_add('pair_arrow', f'{line_idx}.{arrow_idx}', f'{line_idx}.{arrow_idx + 4}')
                    self.tag_add('pair_target', f'{line_idx}.{arrow_idx + 4}', f'{line_idx}.end')
                else:
                    self.tag_add('pair_error', f'{line_idx}.0', f'{line_idx}.end')
        except Exception:
            pass
        if getattr(self, 'on_changed', None) is not None:
            with contextlib.suppress(Exception):
                self.on_changed()

    def get_text(self, start: str = '1.0', end: str = tk.END) -> str:
        return super().get(start, end)

    def get(self, *args, **kwargs) -> list[tuple[str, str]]:  # type: ignore[override]
        raw: str = super().get('1.0', tk.END)
        lines = raw.splitlines()
        valid_paths: list[tuple[str, str]] = [pair for line in lines if (pair := self.parse_line(line)) is not None]
        unique_paths = list(set(valid_paths))
        unique_paths.sort(key=lambda x: x[0])  # sort by source path
        return unique_paths

    def get_as_dir_pairs(self) -> list[DirectoryPair]:
        return [DirectoryPair(source=pair[0], target=pair[1]) for pair in self.get()]

    def get_raw_pairs(self) -> list[tuple[str, str, str]]:
        """
        Scan all non-empty lines and validate syntax and source existence.
        Returns tuples: (source, target, status_error).
        """
        raw: str = super().get('1.0', tk.END)
        results = []
        for line in raw.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            if ' -> ' not in line_str:
                results.append((line_str, '', 'Invalid format: missing " -> "'))
                continue
            source, target = [p.strip().strip('"\'') for p in line_str.split(' -> ', 1)]
            if not os.path.exists(source):
                results.append((source, target, f'Source does not exist or disconnected: {source}'))
            elif not os.path.isdir(source):
                results.append((source, target, f'Source is not a directory: {source}'))
            else:
                results.append((source, target, ''))
        return results

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
        self.highlight_syntax()
        if was_disabled:
            self.configure(state=TkinterCfgState.DISABLED.value)

    @staticmethod
    def parse_line(raw: str) -> None | tuple[str, str]:
        try:
            if ' -> ' not in raw:
                return None
            source, target = raw.split(' -> ', 1)
            source, target = source.strip().strip('"\''), target.strip().strip('"\'')
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
        if 'font' not in kwargs:
            kwargs['font'] = ('Consolas', 9)
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
        if 'font' not in kwargs:
            kwargs['font'] = ('Consolas', 9)
        super().__init__(*args, **kwargs)

    def get(self, *args, **kwargs) -> list[str]:  # type: ignore[override]
        raw: str = super().get('1.0', tk.END)
        times = raw.splitlines()
        normalized = []
        for t in times:
            try:
                parsed = time.strptime(t.strip(), '%H:%M')
                normalized.append(f'{parsed.tm_hour:02d}:{parsed.tm_min:02d}')
            except Exception:
                pass
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
    def __init__(self, *args, on_log_updated: Callable[[], None] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lines: list[tuple[str, str]] = []
        self.log_levels: list[str] = []
        self.limit_lines = 50000
        self.on_log_updated = on_log_updated
        self._level_counts: dict[str, int] = {'DEBUG': 0, 'INFO': 0, 'WARNING': 0, 'ERROR': 0, 'CRITICAL': 0}
        self.configure(font=('Consolas', 10))
        self.tag_config('DEBUG', foreground='gray')
        self.tag_config('INFO', foreground='black')
        self.tag_config('WARNING', foreground='orange')
        self.tag_config('ERROR', foreground='red')
        self.tag_config('CRITICAL', foreground='red', underline=True)

    @property
    def level_counts(self) -> dict[str, int]:
        return dict(self._level_counts)

    def reset_counts(self):
        self._level_counts = {'DEBUG': 0, 'INFO': 0, 'WARNING': 0, 'ERROR': 0, 'CRITICAL': 0}
        if self.on_log_updated:
            with contextlib.suppress(Exception):
                self.on_log_updated()

    def set_log_levels(self, levels: list[str]):
        self.log_levels = levels
        self._rewrite()

    def insert(self, *args, **kwargs):
        message, tag = args
        self.insert_batch([(message, tag)])

    def insert_batch(self, records: list[tuple[str, str]]):
        """Batch-insert multiple log entries into the widget in a single GUI state toggle."""
        if not records:
            return

        visible: list[tuple[str, str]] = []
        for message, tag in records:
            self.lines.append((message, tag))
            self._level_counts[tag] = self._level_counts.get(tag, 0) + 1
            if tag in self.log_levels:
                visible.append((message, tag))

        if visible:
            self.configure(state=TkinterCfgState.NORMAL.value)
            for message, tag in visible:
                super().insert(tk.END, message + '\n', tag)
            self.configure(state=TkinterCfgState.DISABLED.value)
            self._check_num_lines()

        if self.on_log_updated:
            with contextlib.suppress(Exception):
                self.on_log_updated()

    def _check_num_lines(self):
        # O(1) in-memory check without expensive get('1.0', tk.END).splitlines() serialization
        if len(self.lines) > self.limit_lines * 1.1:
            self._rewrite()

    def _rewrite(self):
        yview_pos = self.yview()[0]
        if len(self.lines) > self.limit_lines * 1.5:
            self.lines = self.lines[-self.limit_lines :]
            self._level_counts = {'DEBUG': 0, 'INFO': 0, 'WARNING': 0, 'ERROR': 0, 'CRITICAL': 0}
            for _, tag in self.lines:
                self._level_counts[tag] = self._level_counts.get(tag, 0) + 1
        self.configure(state=TkinterCfgState.NORMAL.value)
        self.delete('1.0', tk.END)
        for message, tag in self.lines[-self.limit_lines :]:
            if tag in self.log_levels:
                super().insert(tk.END, message + '\n', tag)
        self.configure(state=TkinterCfgState.DISABLED.value)
        self.yview_moveto(yview_pos)
        if self.on_log_updated:
            with contextlib.suppress(Exception):
                self.on_log_updated()
