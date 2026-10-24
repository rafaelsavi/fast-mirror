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

    def get_configured_pairs(self) -> list[tuple[str, str]]:
        """
        Return all syntactic directory pairs (source, target) configured in the text widget.

        Unlike get(), this does not perform disk/network existence checks, preserving
        configured offline UNC network shares and unmounted external drives across saves.
        """
        raw: str = super().get('1.0', tk.END)
        pairs: list[tuple[str, str]] = []
        for line in raw.splitlines():
            line_str = line.strip()
            if not line_str or ' -> ' not in line_str:
                continue
            source, target = [p.strip().strip('"\'') for p in line_str.split(' -> ', 1)]
            if source and target:
                pairs.append((source, target))
        seen: set[tuple[str, str]] = set()
        unique: list[tuple[str, str]] = []
        for p in pairs:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

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

    def insert(self, index, chars, *args):
        was_disabled = str(self.cget('state')) == TkinterCfgState.DISABLED.value
        if was_disabled:
            self.configure(state=TkinterCfgState.NORMAL.value)
        super().insert(index, chars, *args)
        self.highlight_syntax()
        if was_disabled:
            self.configure(state=TkinterCfgState.DISABLED.value)

    def delete(self, index1, index2=None):
        was_disabled = str(self.cget('state')) == TkinterCfgState.DISABLED.value
        if was_disabled:
            self.configure(state=TkinterCfgState.NORMAL.value)
        if index2 is None:
            super().delete(index1)
        else:
            super().delete(index1, index2)
        self.highlight_syntax()
        if was_disabled:
            self.configure(state=TkinterCfgState.DISABLED.value)

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
        self.delete('1.0', tk.END)  # delete current text
        self.insert('1.0', raw)  # add at line 1, col 0

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
        self.tag_config('TAG_JUMP_HIGHLIGHT', background='#fed7aa')

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

    def jump_to_next_tag(self, tags: str | list[str] | tuple[str, ...]) -> bool:
        """Scroll and highlight the next occurrence of the specified tag(s)."""
        target_tags = (tags,) if isinstance(tags, str) else tuple(tags)

        # Collect all start positions for the target tags
        match_positions: list[str] = []
        for tag in target_tags:
            ranges = self.tag_ranges(tag)
            for i in range(0, len(ranges), 2):
                match_positions.append(str(ranges[i]))

        if not match_positions:
            return False

        def _idx_key(idx: str) -> tuple[int, int]:
            parts = idx.split('.')
            return (int(parts[0]), int(parts[1]))

        match_positions.sort(key=_idx_key)

        # Determine current view/insert position to find the next entry
        current_insert = self.index('insert')
        next_pos = None
        for pos in match_positions:
            if self.compare(pos, '>', current_insert):
                next_pos = pos
                break
        if next_pos is None:
            # Wrap around to the first match
            next_pos = match_positions[0]

        # Focus, move insertion cursor, and scroll into view
        self.mark_set('insert', next_pos)
        self.see(next_pos)

        # Apply a temporary highlight tag to the matched line
        self.tag_remove('TAG_JUMP_HIGHLIGHT', '1.0', tk.END)
        line_start = f'{next_pos.split(".")[0]}.0'
        line_end = f'{next_pos.split(".")[0]}.end'
        self.tag_add('TAG_JUMP_HIGHLIGHT', line_start, line_end)

        # Schedule automatic removal of the jump highlight
        with contextlib.suppress(Exception):
            self.after(1800, lambda: self.tag_remove('TAG_JUMP_HIGHLIGHT', '1.0', tk.END))

        return True


class ToolTip:
    """Lightweight, non-blocking tooltip for Tkinter and ttk widgets."""

    def __init__(self, widget: tk.Misc, text: str, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._tip_window: tk.Toplevel | None = None
        self._after_id: str | None = None

        self.widget.bind('<Enter>', self._schedule, add='+')
        self.widget.bind('<Leave>', self._hide, add='+')
        self.widget.bind('<ButtonPress>', self._hide, add='+')
        self.widget.bind('<Destroy>', self._on_destroy, add='+')

    def set_text(self, text: str):
        """Update tooltip explanation text dynamically."""
        self.text = text
        if self._tip_window is not None:
            self._hide()

    def _schedule(self, event=None):
        self._cancel()
        if self.text:
            self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id is not None:
            with contextlib.suppress(Exception):
                self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if not self.text:
            return
        with contextlib.suppress(Exception):
            if not self.widget.winfo_exists():
                return

        self._hide()

        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4

            # Screen boundary collision check
            screen_h = self.widget.winfo_screenheight()
            if y + 30 > screen_h:
                y = max(0, self.widget.winfo_rooty() - 26)

            self._tip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f'+{x}+{y}')
            with contextlib.suppress(Exception):
                tw.attributes('-topmost', True)

            lbl = tk.Label(
                tw,
                text=self.text,
                justify='left',
                background='#2b2b2b',
                foreground='#ffffff',
                relief='solid',
                borderwidth=1,
                padx=6,
                pady=3,
                font=('Segoe UI', 8),
            )
            lbl.pack()
        except Exception:
            self._hide()

    def _hide(self, event=None):
        self._cancel()
        if self._tip_window is not None:
            with contextlib.suppress(Exception):
                self._tip_window.destroy()
            self._tip_window = None

    def _on_destroy(self, event=None):
        self._cancel()
        self._hide()


def add_tooltip(widget: tk.Misc, text: str, delay_ms: int = 450) -> ToolTip:
    """Attach a lightweight tooltip to any widget and retain a persistent reference."""
    tooltip = ToolTip(widget, text, delay_ms=delay_ms)
    widget._tooltip = tooltip  # type: ignore[attr-defined]
    return tooltip


BADGE_PALETTES: dict[str, dict[str, str]] = {
    'neutral': {
        'bg': '#f1f5f9',
        'fg': '#64748b',
        'border': '#e2e8f0',
        'hover_bg': '#e2e8f0',
    },
    'neutral_bold': {
        'bg': '#f1f5f9',
        'fg': '#334155',
        'border': '#cbd5e1',
        'hover_bg': '#e2e8f0',
    },
    'info': {
        'bg': '#e0f2fe',
        'fg': '#0369a1',
        'border': '#bae6fd',
        'hover_bg': '#bae6fd',
    },
    'warning': {
        'bg': '#fef3c7',
        'fg': '#b45309',
        'border': '#fde68a',
        'hover_bg': '#fde68a',
    },
    'error': {
        'bg': '#fee2e2',
        'fg': '#b91c1c',
        'border': '#fecaca',
        'hover_bg': '#fecaca',
    },
    'success': {
        'bg': '#dcfce7',
        'fg': '#15803d',
        'border': '#bbf7d0',
        'hover_bg': '#bbf7d0',
    },
    'primary': {
        'bg': '#dbeafe',
        'fg': '#1d4ed8',
        'border': '#bfdbfe',
        'hover_bg': '#bfdbfe',
    },
}


class BadgeLabel(tk.Label):
    """
    Modern flat status indicator / pill badge with subtle uniform tint border.

    Eliminates 3D bevels (groove/sunken) and harsh solid borders that make
    indicator labels look like pressed buttons or vintage form fields.
    """

    def __init__(
        self,
        master: tk.Misc,
        text: str = '',
        variant: str = 'neutral',
        interactive: bool = False,
        **kwargs,
    ):
        self._variant = variant
        self._interactive = interactive
        palette = BADGE_PALETTES.get(variant, BADGE_PALETTES['neutral'])

        kwargs.setdefault('font', ('Segoe UI', 8, 'bold') if variant != 'neutral' else ('Segoe UI', 8))
        kwargs.setdefault('padx', 8)
        kwargs.setdefault('pady', 2)
        kwargs['relief'] = 'flat'
        kwargs['bd'] = 0
        kwargs.setdefault('bg', palette['bg'])
        kwargs.setdefault('fg', palette['fg'])
        kwargs.setdefault('highlightthickness', 1)
        kwargs.setdefault('highlightbackground', palette['border'])
        kwargs.setdefault('highlightcolor', palette['border'])

        if interactive:
            kwargs.setdefault('cursor', 'hand2')

        super().__init__(master, text=text, **kwargs)

        if interactive:
            self.bind('<Enter>', self._on_enter)
            self.bind('<Leave>', self._on_leave)

    def _on_enter(self, _event=None):
        palette = BADGE_PALETTES.get(self._variant, BADGE_PALETTES['neutral'])
        super().config(bg=palette['hover_bg'])

    def _on_leave(self, _event=None):
        palette = BADGE_PALETTES.get(self._variant, BADGE_PALETTES['neutral'])
        super().config(bg=palette['bg'])

    def set_variant(self, variant: str, text: str | None = None, is_bold: bool | None = None):
        """Update badge palette variant and optionally text/font weight."""
        self._variant = variant
        palette = BADGE_PALETTES.get(variant, BADGE_PALETTES['neutral'])
        cfg: dict = {
            'bg': palette['bg'],
            'fg': palette['fg'],
            'highlightbackground': palette['border'],
            'highlightcolor': palette['border'],
            'relief': 'flat',
            'bd': 0,
        }
        if text is not None:
            cfg['text'] = text
        if is_bold is not None:
            cfg['font'] = ('Segoe UI', 8, 'bold') if is_bold else ('Segoe UI', 8)
        super().config(**cfg)

    def config(self, cnf=None, **kwargs):
        """Ensure relief stays flat to avoid pressed-button regressions."""
        if 'relief' in kwargs and kwargs['relief'] in ('groove', 'sunken', 'raised', 'solid'):
            kwargs['relief'] = 'flat'
        if 'bd' in kwargs and kwargs['bd'] > 0:
            kwargs['bd'] = 0
        return super().config(cnf, **kwargs)

    def configure(self, cnf=None, **kwargs):
        """Alias for config."""
        return self.config(cnf, **kwargs)
