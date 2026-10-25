import contextlib
import os
import subprocess
import tkinter as tk
import winsound
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

import ttkwidgets

from core.file import CstmPath
from gui.icons import apply_icon, apply_window_icon
from gui.widgets import Action, BadgeLabel, add_tooltip
from utils.logger import logger
from utils.utils import format_size


class CustomCheckboxTreeView(ttkwidgets.CheckboxTreeview):
    custom_headers = [
        'enable',
        'source',
        'target',
        'size (source)',
        'size (target)',
        'modification date (source)',
        'modification date (target)',
    ]

    def __init__(self, *args, on_stats_changed: Callable[[], None] | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        self._data: dict[Action, dict[str, dict[str, float | str]]] = {}
        self._item_actions: dict[str, tuple[Action, str, str]] = {}
        self._cached_checked_by_action: dict[str, list[str]] = {}
        self._all_group_children: dict[str, list[str]] = {}
        self._attached_items: dict[str, set[str]] = {}
        self._highlighted_items: set[str] = set()
        self._search_cache: dict[str, tuple[str, str]] = {}
        self.on_stats_changed = on_stats_changed
        self._sort_col: str | None = None
        self._sort_descending: bool = False
        self._is_filtered: bool = False

        # Configure Treeview columns and headers
        self['columns'] = self.custom_headers[1:]
        self.column('#0', width=240, minwidth=180)
        self.heading('#0', text=self.custom_headers[0], command=lambda: self.sort_by_column('#0'))

        for column in self.custom_headers[1:]:
            self.heading(column, text=column.title(), command=lambda c=column: self.sort_by_column(c))
            if 'date' in column:
                self.column(column, width=155, minwidth=120)
            elif 'size' in column:
                self.column(column, width=100, minwidth=80)
            else:
                self.column(column, width=330, minwidth=180)

        # Configure Treeview selection highlight colors
        style = ttk.Style(self)
        style.map(
            'Checkbox.Treeview',
            background=[('selected', '#0078d7')],
            foreground=[('selected', '#ffffff')],
        )

        self.apply_theme_tags()

    def apply_theme_tags(self):
        """Configure row tinting and match highlighting for day mode."""
        self.tag_configure('copy_tag', background='#f6fff8')
        self.tag_configure('move_tag', background='#f0f7ff')
        self.tag_configure('delete_tag', background='#fff5f5')
        self.tag_configure('highlight_match', background='#fff59d')
        self.tag_configure('selected_row', background='#0078d7', foreground='#ffffff')

    def _box_click(self, event):
        super()._box_click(event)
        self.refresh_group_stats()

    def refresh_group_stats(self):
        """Single-pass O(N) grouping of checked items across actions to eliminate redundant tree queries."""
        checked_items = self.get_checked()
        checked_by_action: dict[str, list[str]] = {a: [] for a in self.get_children('')}
        for item_id in checked_items:
            prefix = item_id.partition('::')[0]
            if prefix in checked_by_action:
                checked_by_action[prefix].append(item_id)

        self._cached_checked_by_action = checked_by_action

        for action_str, selected_lines in checked_by_action.items():
            n_children = len(self._all_group_children.get(action_str, self.get_children(action_str)))
            selected_number = len(selected_lines)
            action_enum = Action.from_str(action_str)
            action_data = self._data.get(action_enum, {})
            size_list = [action_data[x]['size in bytes'] for x in selected_lines if x in action_data]

            if not all(isinstance(size, int | float) for size in size_list):
                raise TypeError('All elements in size_list must be numbers')

            selected_size = format_size(sum(size_list))  # type: ignore[arg-type]
            # Maintain exact substring format expected by existing tests: '<action> <size> (<X> of <Y>)'
            if self.exists(action_str):
                self.item(action_str, text=f'{action_str} {selected_size} ({selected_number} of {n_children})')

        if self.on_stats_changed:
            self.on_stats_changed()

    def get_action_stats(self, action: Action) -> tuple[int, int | float]:
        """Return (checked_file_count, total_checked_bytes) for the given action."""
        action_data = self._data.get(action, {})
        cached = getattr(self, '_cached_checked_by_action', None)
        if cached is not None:
            lines = cached.get(action.value, [])
        else:
            checked = self.get_checked()
            prefix = f'{action.value}::'
            lines = [x for x in checked if prefix in x]

        total_bytes: float = 0.0
        for x in lines:
            if x in action_data:
                val = action_data[x].get('size in bytes')
                if isinstance(val, int | float):
                    total_bytes += float(val)
        return len(lines), total_bytes

    def add_file_lists(
        self,
        file_lists: dict[Action, list[tuple[CstmPath, CstmPath]] | list[CstmPath]],
        default_active: list[Action] | None = None,
    ):
        if default_active is None:
            default_active = []

        self._item_actions.clear()
        self._all_group_children.clear()
        self._attached_items.clear()
        self._highlighted_items.clear()
        self._search_cache.clear()
        self._is_filtered = False
        self._sort_col = None
        self._sort_descending = False
        self.heading('#0', text=self.custom_headers[0])
        for column in self.custom_headers[1:]:
            self.heading(column, text=column.title())

        for action, file_list in file_lists.items():
            self._data[action] = {}
            for file_entry in file_list:
                args = (None, file_entry) if isinstance(file_entry, CstmPath) else file_entry
                values = self.get_row(*args, action=action)
                src_val = str(values['source'])
                tgt_val = str(values['target'])
                base_key = f'{action.value}::{src_val}::{tgt_val}'
                item_key = base_key
                counter = 1
                while item_key in self._item_actions:
                    item_key = f'{base_key}#{counter}'
                    counter += 1

                self._data[action][item_key] = values
                self._item_actions[item_key] = (action, src_val, tgt_val)

        for action, rows in self._data.items():
            state_tag = 'checked' if action in default_active else 'unchecked'
            group_item = self.insert(
                parent='',
                index='end',
                iid=action.value,
                text=action.value,
                tags=(state_tag,),
                open=True,
            )
            self._all_group_children[action.value] = []
            self._attached_items[action.value] = set()
            action_style_tag = f'{action.value}_tag'
            for key, row in rows.items():
                self._all_group_children[action.value].append(key)
                self._attached_items[action.value].add(key)
                src_val = str(row['source'])
                tgt_val = str(row['target'])
                path_for_cat = src_val if (src_val and src_val != '(none)') else tgt_val
                cat = get_file_category_group(path_for_cat)
                search_str = f'{key.lower()} {src_val.lower()} {tgt_val.lower()}'
                self._search_cache[key] = (search_str, cat)

                self.insert(
                    parent=group_item,
                    index='end',
                    iid=key,
                    values=(
                        row['source'],
                        row['target'],
                        row['size (source)'],
                        row['size (target)'],
                        row['modification date (source)'],
                        row['modification date (target)'],
                    ),
                    tags=(action_style_tag,),
                )

        self._attached_items[''] = set(self._all_group_children.keys())

    def get_checked(self) -> list[str]:
        """High-performance retrieval of checked leaf items."""
        checked: list[str] = []
        if self._all_group_children:
            for group, children in self._all_group_children.items():
                if self.exists(group) and self.tag_has('unchecked', group):
                    continue
                for child in children:
                    if self.exists(child) and self.tag_has('checked', child):
                        checked.append(child)
            return checked

        for group in self.get_children(''):
            # If the group is marked unchecked, all its descendants are unchecked
            if self.tag_has('unchecked', group):
                continue

            children = self.get_children(group)
            if not children:
                if self.tag_has('checked', group):
                    checked.append(group)
                continue

            for child in children:
                if self.tag_has('checked', child):
                    checked.append(child)
        return checked

    @staticmethod
    def get_row(
        source: CstmPath | None, target: CstmPath | None, action: Action | None = None
    ) -> dict[str, float | str]:
        def _extract_meta(p: CstmPath | None) -> tuple[str, str, int | float, str]:
            if p is None:
                return ('', '-', 0, '-')
            p_str = str(p)

            # Fast-path 1: Known new target that does not exist yet on disk/network
            is_new = getattr(p, 'is_new_target', getattr(p, '_is_new_target', False))
            failed = getattr(p, 'stat_failed', getattr(p, '_stat_failed', False))
            if is_new or failed:
                return (p_str, '-', 0, '-')

            # Fast-path 2: Pre-cached stats in memory (0 syscalls, 0 network calls)
            cached_st = getattr(p, 'cached_stats', getattr(p, '_stats', None))
            if cached_st is not None:
                bytes_val = cached_st.st_size
                size_str = format_size(bytes_val)
                mtime_str = p.to_date_str(cached_st.st_mtime) if hasattr(p, 'to_date_str') else str(cached_st.st_mtime)
                return (p_str, size_str, bytes_val, mtime_str)

            # Never query remote network UNC paths synchronously on the GUI thread
            if p_str.startswith(r'\\') or p_str.startswith('//'):
                return (p_str, '-', 0, '-')

            # Safe local-only query
            try:
                st = p.stats
                bytes_val = st.st_size
                size_str = format_size(bytes_val)
                mtime_str = p.to_date_str(st.st_mtime) if hasattr(p, 'to_date_str') else str(st.st_mtime)
                return (p_str, size_str, bytes_val, mtime_str)
            except Exception:
                return (p_str, '-', 0, '-')

        src_str, src_size_str, src_bytes, src_mtime_str = _extract_meta(source)
        tgt_str, tgt_size_str, tgt_bytes, tgt_mtime_str = _extract_meta(target)

        # Context-aware adjustments based on action type
        if action == Action.DELETE:
            src_str = '-'
            src_size_str = '-'
            src_mtime_str = '-'
            size_bytes = tgt_bytes
        elif action == Action.MOVE:
            tgt_size_str = '-'
            tgt_mtime_str = '-'
            size_bytes = src_bytes if source is not None else tgt_bytes
        else:
            # Action.COPY or default
            size_bytes = src_bytes if source is not None else tgt_bytes
            target_is_new = getattr(target, 'is_new_target', getattr(target, '_is_new_target', False))
            if target is not None and target_is_new:
                tgt_size_str = '-'
                tgt_mtime_str = '-'

        return {
            'source': src_str,
            'target': tgt_str,
            'size (source)': src_size_str,
            'size (target)': tgt_size_str,
            'modification date (source)': src_mtime_str,
            'modification date (target)': tgt_mtime_str,
            'size in bytes': size_bytes,
            'bytes (source)': src_bytes,
            'bytes (target)': tgt_bytes,
        }

    def select_all(self):
        """Check all group and child items that contain files."""
        groups = self._all_group_children if self._all_group_children else self.get_children('')
        for group in groups:
            if self.exists(group):
                self.change_state(group, 'checked')
        self.refresh_group_stats()

    def deselect_all(self):
        """Uncheck all group and child items."""
        groups = self._all_group_children if self._all_group_children else self.get_children('')
        for group in groups:
            if self.exists(group):
                self.change_state(group, 'unchecked')
        self.refresh_group_stats()

    def uncheck_action(self, action: Action):
        """Uncheck all items under a specific action (e.g. Action.DELETE)."""
        if self.exists(action.value):
            self.change_state(action.value, 'unchecked')
        self.refresh_group_stats()

    def set_copies_only(self):
        """Check all copy items and uncheck all move and delete items."""
        if self.exists(Action.COPY.value):
            self.change_state(Action.COPY.value, 'checked')
        if self.exists(Action.MOVE.value):
            self.change_state(Action.MOVE.value, 'unchecked')
        if self.exists(Action.DELETE.value):
            self.change_state(Action.DELETE.value, 'unchecked')
        self.refresh_group_stats()

    def sort_by_column(self, col: str):
        """Sort items within each action group by column ascending or descending."""
        if getattr(self, '_sort_col', None) == col:
            self._sort_descending = not getattr(self, '_sort_descending', False)
        else:
            self._sort_col = col
            self._sort_descending = False

        reverse = self._sort_descending
        arrow = ' ▼' if reverse else ' ▲'

        # Update headings
        col0_text = self.custom_headers[0]
        self.heading('#0', text=f'{col0_text}{arrow}' if col == '#0' else col0_text)
        for c in self.custom_headers[1:]:
            title = c.title()
            self.heading(c, text=f'{title}{arrow}' if c == col else title)

        # Sort children within each action group
        for group in self.get_children(''):
            children = self._all_group_children.get(group, list(self.get_children(group)))
            if not children:
                continue

            try:
                action_enum = Action.from_str(group)
            except Exception:
                action_enum = None

            action_data = self._data.get(action_enum, {}) if action_enum else {}

            def _sort_key(item_id: str, data=action_data):
                row = data.get(item_id, {})
                if col == 'size (source)':
                    val = row.get('bytes (source)', 0)
                    return float(val if isinstance(val, int | float) else 0)
                elif col == 'size (target)':
                    val = row.get('bytes (target)', 0)
                    return float(val if isinstance(val, int | float) else 0)
                elif col == 'modification date (source)':
                    return str(row.get('modification date (source)', ''))
                elif col == 'modification date (target)':
                    return str(row.get('modification date (target)', ''))
                elif col == 'source':
                    return str(row.get('source', '')).lower()
                elif col == 'target':
                    return str(row.get('target', '')).lower()
                elif col == '#0':
                    is_checked = self.tag_has('checked', item_id)
                    return (0 if is_checked else 1, item_id.lower())
                else:
                    return item_id.lower()

            sorted_children = sorted(children, key=_sort_key, reverse=reverse)
            self._all_group_children[group] = sorted_children

            attached = self._attached_items.get(group, set())
            idx = 0
            for item_id in sorted_children:
                if self.exists(item_id) and (not self._is_filtered or item_id in attached):
                    self.move(item_id, group, idx)
                    idx += 1

    def expand_all(self):
        """Expand all action groups."""
        for group in self.get_children(''):
            self.item(group, open=True)

    def collapse_all(self):
        """Collapse all action groups."""
        for group in self.get_children(''):
            self.item(group, open=False)

    def filter_items(self, query: str = '', category: str | None = None) -> tuple[int, str | None]:
        """
        Filter the displayed tree items by search query and optional file type category.

        Detaches non-matching leaf items and empty groups, and reattaches matching items.
        Returns (match_count, first_match_id).
        """
        query = query.strip().lower()
        cat_filter = category.lower() if category and category.lower() not in ('all', '') else None
        first_match: str | None = None
        match_count = 0

        # If both query and category filter are empty, restore all items and groups in their original order
        if not query and cat_filter is None:
            if not getattr(self, '_is_filtered', False):
                return 0, None
            self._is_filtered = False

            # Clear highlight tag only on previously highlighted items
            for child in list(self._highlighted_items):
                if self.exists(child):
                    tags = tuple(t for t in self.item(child, 'tags') if t != 'highlight_match')
                    self.item(child, tags=tags)
            self._highlighted_items.clear()

            # Restore any detached items and groups in order
            root_attached = self._attached_items.setdefault('', set(self.get_children('')))
            for group, all_children in self._all_group_children.items():
                if not self.exists(group):
                    continue
                attached = self._attached_items.setdefault(group, set())
                if len(attached) < len(all_children):
                    for child in all_children:
                        if child not in attached and self.exists(child):
                            self.reattach(child, group, 'end')
                    attached.update(all_children)
                if group not in root_attached:
                    self.reattach(group, '', 'end')
                    root_attached.add(group)

            return 0, None

        self._is_filtered = True

        root_attached = self._attached_items.setdefault('', set(self.get_children('')))

        for group, all_children in self._all_group_children.items():
            if not self.exists(group):
                continue

            attached = self._attached_items.setdefault(group, set())
            group_has_matches = False

            for child in all_children:
                search_str, cat = self._search_cache.get(child, ('', ''))
                text_match = not query or (query in search_str)
                cat_match = (cat_filter is None) or (cat == cat_filter)

                if text_match and cat_match:
                    match_count += 1
                    group_has_matches = True
                    if first_match is None:
                        first_match = child

                    if child not in attached:
                        self.reattach(child, group, 'end')
                        attached.add(child)

                    if query:
                        if child not in self._highlighted_items:
                            tags = tuple(t for t in self.item(child, 'tags') if t != 'highlight_match') + (
                                'highlight_match',
                            )
                            self.item(child, tags=tags)
                            self._highlighted_items.add(child)
                    elif child in self._highlighted_items:
                        tags = tuple(t for t in self.item(child, 'tags') if t != 'highlight_match')
                        self.item(child, tags=tags)
                        self._highlighted_items.discard(child)
                else:
                    if child in attached:
                        self.detach(child)
                        attached.discard(child)

                    if child in self._highlighted_items:
                        tags = tuple(t for t in self.item(child, 'tags') if t != 'highlight_match')
                        self.item(child, tags=tags)
                        self._highlighted_items.discard(child)

            if group_has_matches:
                if group not in root_attached:
                    self.reattach(group, '', 'end')
                    root_attached.add(group)
                self.item(group, open=True)
            else:
                if group in root_attached:
                    self.detach(group)
                    root_attached.discard(group)

        return match_count, first_match


def get_file_category_group(path: str) -> str:
    """Return category group: 'image', 'document', 'media', 'code', 'archive', or 'other'."""
    if not path or path in ('-', '(none)'):
        return 'other'
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico'):
        return 'image'
    if ext in ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.mp3', '.wav', '.flac', '.m4a'):
        return 'media'
    if ext in ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.csv', '.rtf'):
        return 'document'
    if ext in ('.zip', '.tar', '.gz', '.7z', '.rar', '.bz2', '.xz'):
        return 'archive'
    if ext in (
        '.py',
        '.js',
        '.ts',
        '.html',
        '.css',
        '.json',
        '.xml',
        '.yaml',
        '.yml',
        '.md',
        '.sh',
        '.bat',
        '.ps1',
        '.sql',
    ):
        return 'code'
    return 'other'


def get_file_type_badge(path: str) -> tuple[str, str]:
    """Return an icon and readable file type category for a given path."""
    if not path or path in ('-', '(none)'):
        return ('📄', 'File')
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico'):
        return ('🖼️', f'Image ({ext})')
    if ext in ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.mp3', '.wav', '.flac', '.m4a'):
        return ('🎬', f'Media ({ext})')
    if ext in ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.csv', '.rtf'):
        return ('📄', f'Document ({ext})')
    if ext in ('.zip', '.tar', '.gz', '.7z', '.rar', '.bz2', '.xz'):
        return ('📦', f'Archive ({ext})')
    if ext in (
        '.py',
        '.js',
        '.ts',
        '.html',
        '.css',
        '.json',
        '.xml',
        '.yaml',
        '.yml',
        '.md',
        '.sh',
        '.bat',
        '.ps1',
        '.sql',
    ):
        return ('💻', f'Code/Config ({ext})')
    if ext in ('.exe', '.msi', '.dll'):
        return ('⚙️', f'Binary ({ext})')
    if ext:
        return ('📄', f'{ext.upper()[1:]} File')
    return ('📄', 'File')


class FileDetailsDialog:
    """Detailed file properties and diff comparison dialog for a selected sync action."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        action: Action | str,
        source_path: str,
        target_path: str,
        row_data: dict[str, Any] | None = None,
        is_checked: bool = True,
    ):
        self.parent = parent
        self.action_enum = Action(action) if isinstance(action, str) else action
        self.source_path = source_path if source_path and source_path not in ('-', '(none)') else ''
        self.target_path = target_path if target_path and target_path not in ('-', '(none)') else ''
        self.row_data = row_data or {}
        self.is_checked = is_checked

        primary_path = self.source_path or self.target_path
        self.filename = os.path.basename(primary_path) or primary_path

        self.dialog = tk.Toplevel(parent)
        with contextlib.suppress(Exception):
            self.dialog.attributes('-alpha', 0.0)
        self.dialog.title(f'FastMirror - File Information - {self.filename}')
        with contextlib.suppress(Exception):
            self.dialog.configure(bg='SystemButtonFace')
        apply_window_icon(self.dialog)
        self.dialog.minsize(680, 520)
        self.dialog.transient(parent)

        self._center_dialog(width=720, height=580)
        self._create_widgets()

        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())
        self.dialog.bind('<Return>', lambda e: self.dialog.destroy())

        with contextlib.suppress(Exception):
            self.dialog.update_idletasks()
            self.dialog.attributes('-alpha', 1.0)
            self.dialog.deiconify()
            self.dialog.grab_set()
        self.dialog.focus_set()

    def _center_dialog(self, width: int, height: int):
        try:
            self.dialog.update_idletasks()
            px = self.parent.winfo_rootx()
            py = self.parent.winfo_rooty()
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            if pw > 100 and ph > 100:
                x = px + max(0, (pw - width) // 2)
                y = py + max(0, (ph - height) // 2)
            else:
                x = max(0, (self.dialog.winfo_screenwidth() - width) // 2)
                y = max(0, (self.dialog.winfo_screenheight() - height) // 2)
            self.dialog.geometry(f'{width}x{height}+{x}+{y}')
        except Exception:
            self.dialog.geometry(f'{width}x{height}')

    def _create_widgets(self):
        container = ttk.Frame(self.dialog, padding=(14, 12))
        container.pack(fill='both', expand=True)

        # 1. Header Card
        header_frame = tk.Frame(container, bg='SystemButtonFace')
        header_frame.pack(fill='x', pady=(0, 10))

        icon, cat_label = get_file_type_badge(self.source_path or self.target_path)

        lbl_fname = tk.Label(
            header_frame,
            text=f'{icon}  {self.filename}',
            font=('Segoe UI', 12, 'bold'),
            bg='SystemButtonFace',
            fg='#111827',
            anchor='w',
        )
        lbl_fname.pack(fill='x', pady=(0, 4))

        # Badges row
        badges_row = tk.Frame(header_frame, bg='SystemButtonFace')
        badges_row.pack(fill='x')

        act_variant = (
            'success'
            if self.action_enum == Action.COPY
            else ('primary' if self.action_enum == Action.MOVE else 'error')
        )
        act_text = f'{self.action_enum.value.upper()}'
        badge_act = BadgeLabel(
            badges_row,
            text=act_text,
            variant=act_variant,
            font=('Segoe UI', 9, 'bold'),
            padx=8,
            pady=2,
        )
        badge_act.pack(side='left', padx=(0, 6))

        badge_cat = BadgeLabel(
            badges_row,
            text=cat_label,
            variant='neutral',
            font=('Segoe UI', 9),
            padx=8,
            pady=2,
        )
        badge_cat.pack(side='left', padx=(0, 6))

        chk_text = '✓ Selected for synchronization' if self.is_checked else '○ Excluded from synchronization'
        chk_variant = 'success' if self.is_checked else 'neutral'
        badge_chk = BadgeLabel(
            badges_row,
            text=chk_text,
            variant=chk_variant,
            font=('Segoe UI', 9),
            padx=8,
            pady=2,
        )
        badge_chk.pack(side='left')

        # 2. Diff / Operation Summary Box
        diff_text = self._compute_diff_summary()
        diff_box = tk.LabelFrame(
            container,
            text=' Operation & Difference ',
            font=('Segoe UI', 9, 'bold'),
            padx=10,
            pady=8,
        )
        diff_box.pack(fill='x', pady=(0, 10))

        lbl_diff_info = ttk.Label(diff_box, text=diff_text, font=('Segoe UI', 9))
        lbl_diff_info.pack(fill='x')

        # 3. Source File Details Frame
        src_frame = ttk.LabelFrame(container, text=' Source File (Origin) ', padding=(10, 8))
        src_frame.pack(fill='x', pady=(0, 10))
        self._populate_location_frame(src_frame, self.source_path, 'source')

        # 4. Target File Details Frame
        tgt_frame = ttk.LabelFrame(container, text=' Target File (Destination) ', padding=(10, 8))
        tgt_frame.pack(fill='x', pady=(0, 12))
        self._populate_location_frame(tgt_frame, self.target_path, 'target')

        # 5. Bottom Action Buttons
        btn_bar = ttk.Frame(container)
        btn_bar.pack(fill='x', side='bottom')

        self.btn_copy_all = ttk.Button(
            btn_bar,
            text='Copy All Information',
            command=self._copy_all_info,
            width=22,
        )
        apply_icon(self.btn_copy_all, 'copy')
        self.btn_copy_all.pack(side='left')

        btn_close = ttk.Button(
            btn_bar,
            text='Close',
            command=self.dialog.destroy,
            style='Accent.TButton',
            width=12,
        )
        btn_close.pack(side='right')

        if self.target_path:
            btn_open_tgt = ttk.Button(
                btn_bar,
                text='Open Target Folder',
                command=lambda: self._open_in_explorer(self.target_path),
                width=18,
            )
            apply_icon(btn_open_tgt, 'folder')
            btn_open_tgt.pack(side='right', padx=(0, 6))

        if self.source_path:
            btn_open_src = ttk.Button(
                btn_bar,
                text='Open Source Folder',
                command=lambda: self._open_in_explorer(self.source_path),
                width=18,
            )
            apply_icon(btn_open_src, 'folder')
            btn_open_src.pack(side='right', padx=(0, 6))

    def _populate_location_frame(self, parent: ttk.LabelFrame, path: str, side: str):
        parent.grid_columnconfigure(1, weight=1)

        # Path row
        lbl_path = ttk.Label(parent, text='Full Path:', font=('Segoe UI', 9, 'bold'))
        lbl_path.grid(row=0, column=0, sticky='w', pady=2)

        path_display = path if (path and path not in ('-', '(none)')) else '-'
        entry_path = ttk.Entry(parent, font=('Segoe UI', 9))
        entry_path.insert(0, path_display)
        entry_path.configure(state='readonly')
        entry_path.grid(row=0, column=1, sticky='ew', padx=(6, 6), pady=2)

        btn_box = ttk.Frame(parent)
        btn_box.grid(row=0, column=2, sticky='e', pady=2)

        btn_copy = ttk.Button(
            btn_box,
            text='Copy',
            command=lambda: self._copy_text(path_display, f'{side} path'),
            width=7,
        )
        apply_icon(btn_copy, 'copy')
        btn_copy.pack(side='left', padx=(0, 4))

        btn_open = ttk.Button(
            btn_box,
            text='Explore',
            command=lambda: self._open_in_explorer(path),
            width=9,
            state='normal' if path else 'disabled',
        )
        apply_icon(btn_open, 'folder')
        btn_open.pack(side='left')

        # Folder row
        parent_dir = os.path.dirname(path) if path else ''
        lbl_dir = ttk.Label(parent, text='Directory:', font=('Segoe UI', 9))
        lbl_dir.grid(row=1, column=0, sticky='w', pady=2)

        entry_dir = ttk.Entry(parent, font=('Segoe UI', 9))
        entry_dir.insert(0, parent_dir if (parent_dir and parent_dir not in ('-', '(none)')) else '-')
        entry_dir.configure(state='readonly')
        entry_dir.grid(row=1, column=1, sticky='ew', padx=(6, 6), pady=2)

        btn_copy_dir = ttk.Button(
            parent,
            text='Copy',
            command=lambda: self._copy_text(parent_dir, f'{side} directory'),
            width=7,
            state='normal' if parent_dir else 'disabled',
        )
        apply_icon(btn_copy_dir, 'copy')
        btn_copy_dir.grid(row=1, column=2, sticky='e', pady=2)

        # Metadata row: Size & Modified Date
        sz_key = f'size ({side})'
        dt_key = f'modification date ({side})'
        bytes_key = f'bytes ({side})'

        sz_str = str(self.row_data.get(sz_key, '')) or '-'
        dt_str = str(self.row_data.get(dt_key, '')) or '-'
        bytes_val = self.row_data.get(bytes_key)

        bytes_desc = f' ({bytes_val:,} bytes)' if isinstance(bytes_val, int | float) and bytes_val > 0 else ''
        full_sz = f'{sz_str}{bytes_desc}' if sz_str != '-' else '-'

        meta_frame = ttk.Frame(parent)
        meta_frame.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(4, 0))

        ttk.Label(meta_frame, text='Size:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 4))
        ttk.Label(meta_frame, text=full_sz, font=('Segoe UI', 9)).pack(side='left', padx=(0, 16))

        ttk.Label(meta_frame, text='Modified:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 4))
        ttk.Label(meta_frame, text=dt_str, font=('Segoe UI', 9)).pack(side='left', padx=(0, 16))

        # Status indicator
        status_text = self._get_status_text(path, side)
        ttk.Label(meta_frame, text='Status:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 4))
        ttk.Label(meta_frame, text=status_text, font=('Segoe UI', 9)).pack(side='left')

    def _get_status_text(self, path: str, side: str) -> str:
        if not path:
            return 'Not applicable'
        if side == 'source':
            try:
                if os.path.exists(path):
                    return 'Exists locally'
            except Exception:
                pass
            return 'File not found'
        else:
            tgt_dt = self.row_data.get('modification date (target)')
            tgt_sz = self.row_data.get('size (target)')
            if self.action_enum == Action.DELETE:
                return 'Marked for deletion'
            if tgt_sz == '-' or tgt_dt in ('-', '', None):
                return 'New file (will be created)'
            return 'Target file exists (will be overwritten)'

    def _compute_diff_summary(self) -> str:
        src_sz = self.row_data.get('size (source)', '')
        tgt_sz = self.row_data.get('size (target)', '')
        if self.action_enum == Action.DELETE:
            return f'⚠️ Action: DELETE\nFile will be permanently deleted from target ({tgt_sz or "unknown size"}).'
        if self.action_enum == Action.MOVE:
            return (
                f'🔄 Action: MOVE / RENAME\nFile will be relocated or renamed at target destination '
                f'({src_sz or "unknown size"}).'
            )
        src_dt = self.row_data.get('modification date (source)', '')
        tgt_dt = self.row_data.get('modification date (target)', '')
        src_bytes = float(self.row_data.get('bytes (source)', 0) or 0)
        tgt_bytes = float(self.row_data.get('bytes (target)', 0) or 0)

        lines = [f'🟢 Action: COPY ({"Synchronizing" if self.is_checked else "Excluded"})']
        if tgt_sz == '-' or tgt_dt in ('-', '', None):
            lines.append(f'✨ New file on target • Source size: {src_sz}')
        else:
            if src_bytes != tgt_bytes:
                diff_bytes = src_bytes - tgt_bytes
                sign = '+' if diff_bytes > 0 else ''
                lines.append(
                    f'📊 Size difference: {sign}{format_size(diff_bytes)} (Source: {src_sz} vs Target: {tgt_sz})'
                )
            else:
                lines.append(f'📊 Size: Identical ({src_sz})')

            if src_dt and tgt_dt:
                if src_dt == tgt_dt:
                    lines.append('🕒 Timestamps: Identical')
                else:
                    lines.append(f'🕒 Timestamps: Source ({src_dt}) vs Target ({tgt_dt})')

        return '\n'.join(lines)

    def _copy_text(self, text: str, desc: str):
        if not text or text == '(none)':
            return
        with contextlib.suppress(Exception):
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(text)
            self.dialog.update_idletasks()
            logger.info(f"Copied {desc} to clipboard: '{text}'")

    def _open_in_explorer(self, path: str):
        if not path or path in ('-', '(none)'):
            return
        norm_path = os.path.normpath(path)
        try:
            if os.path.isfile(norm_path):
                subprocess.Popen(['explorer.exe', f'/select,{norm_path}'])
            elif os.path.isdir(norm_path):
                os.startfile(norm_path)
            else:
                pdir = os.path.dirname(norm_path)
                if os.path.isdir(pdir):
                    os.startfile(pdir)
        except Exception as e:
            logger.warning(f"Could not open explorer for '{norm_path}': {e}")

    def _copy_all_info(self):
        diff_summary = self._compute_diff_summary()
        summary = (
            f'Action: {self.action_enum.value.upper()}\n'
            f'File: {self.filename}\n'
            f'Status: {"Selected" if self.is_checked else "Excluded"}\n'
            f'----------------------------------------\n'
            f'Source Path: {self.source_path or "-"}\n'
            f'Source Directory: {os.path.dirname(self.source_path) if self.source_path else "-"}\n'
            f'Source Size: {self.row_data.get("size (source)", "-")}\n'
            f'Source Modified: {self.row_data.get("modification date (source)", "-")}\n'
            f'----------------------------------------\n'
            f'Target Path: {self.target_path or "-"}\n'
            f'Target Directory: {os.path.dirname(self.target_path) if self.target_path else "-"}\n'
            f'Target Size: {self.row_data.get("size (target)", "-")}\n'
            f'Target Modified: {self.row_data.get("modification date (target)", "-")}\n'
            f'----------------------------------------\n'
            f'{diff_summary}\n'
        )
        self._copy_text(summary, 'all details')
        self.btn_copy_all.config(text='✓ Copied!')
        self.dialog.after(1500, lambda: self.btn_copy_all.config(text='Copy All Information'))


class ActionSelection:
    """Modern interactive confirmation popup for reviewing and selectively executing file sync operations."""

    def __init__(
        self,
        root_gui: tk.Tk,
        files_available_to_copy: list[tuple[CstmPath, CstmPath]],
        files_available_to_move: list[tuple[CstmPath, CstmPath]],
        files_available_to_delete: list[CstmPath],
        default_actions: list[Action],
        on_close_callback: Callable[[], None] | None = None,
    ):
        # Load input variables
        self.default_actions = default_actions
        self.files_available_to_copy = files_available_to_copy
        self.files_available_to_move = files_available_to_move
        self.files_available_to_delete = files_available_to_delete
        self.on_close_callback = on_close_callback
        self.files_requested_to_copy: list[tuple[str, str]] = list()
        self.files_requested_to_move: list[tuple[str, str]] = list()
        self.files_requested_to_delete: list[str] = list()

        # State tracking
        self.root_gui = root_gui
        self.finished = False
        self.proceed = False

        # Create window
        self.popup = tk.Toplevel(self.root_gui)
        with contextlib.suppress(Exception):
            self.popup.attributes('-alpha', 0.0)
        self.popup.withdraw()
        self.popup.title('FastMirror - Confirm Actions')
        with contextlib.suppress(Exception):
            self.popup.configure(bg='SystemButtonFace')
        apply_window_icon(self.popup)
        self.popup.minsize(940, 600)
        self.popup.protocol('WM_DELETE_WINDOW', self.on_window_close)

        # Center window over root or screen
        self._center_window(width=1000, height=660)

        # Keyboard shortcuts
        self.popup.bind('<Return>', lambda e: self.button_save_click())
        self.popup.bind('<Escape>', self._on_escape_pressed)
        self.popup.bind('<Control-f>', lambda e: self._focus_filter_entry())
        self.popup.bind('<Control-F>', lambda e: self._focus_filter_entry())

        # Pause taskbar progress while awaiting user action review
        taskbar = getattr(getattr(self, 'root_gui', None), 'taskbar', None)
        if taskbar is not None:
            with contextlib.suppress(Exception):
                self.root_gui.after(0, taskbar.set_paused)

        self.create_widgets()

        # Smooth reveal after widgets and treeview are completely loaded
        self.popup.update_idletasks()
        with contextlib.suppress(Exception):
            self.popup.attributes('-alpha', 1.0)
        self.popup.deiconify()

        # Modal grab (safe fallback for headless / tests)
        with contextlib.suppress(Exception):
            self.popup.grab_set()
        self.popup.focus_set()

    def _center_window(self, width: int, height: int):
        try:
            self.popup.update_idletasks()
            parent_x = self.root_gui.winfo_rootx()
            parent_y = self.root_gui.winfo_rooty()
            parent_w = self.root_gui.winfo_width()
            parent_h = self.root_gui.winfo_height()

            if parent_w > 100 and parent_h > 100:
                pos_x = parent_x + max(0, (parent_w - width) // 2)
                pos_y = parent_y + max(0, (parent_h - height) // 2)
            else:
                screen_w = self.popup.winfo_screenwidth()
                screen_h = self.popup.winfo_screenheight()
                pos_x = max(0, (screen_w - width) // 2)
                pos_y = max(0, (screen_h - height) // 2)

            self.popup.geometry(f'{width}x{height}+{pos_x}+{pos_y}')
        except Exception:
            self.popup.geometry(f'{width}x{height}')

    def create_widgets(self):
        logger.info('Collecting data for selection window. This may take a while')

        # Configure main grid
        self.popup.grid_rowconfigure(2, weight=1)  # Table row expands
        self.popup.grid_columnconfigure(0, weight=1)

        # 1. Top Summary Banner
        self._create_summary_banner()

        # 2. Toolbar (Search, Select All, Deselect All, Expand/Collapse, Uncheck Deletions)
        self._create_toolbar()

        # 3. Table with modern scrollbars
        self.create_table()

        # 4. Bottom Path Inspector & Dialog Action Buttons
        self._create_bottom_bar()

        with contextlib.suppress(Exception):
            winsound.PlaySound('SystemQuestion', winsound.SND_ALIAS)

    def _create_summary_banner(self):
        banner_frame = tk.Frame(
            self.popup,
            bg='SystemButtonFace',
            highlightthickness=1,
            highlightbackground='#e2e8f0',
            padx=12,
            pady=8,
        )
        banner_frame.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 4))
        banner_frame.grid_columnconfigure(3, weight=1)

        # Title & Subtitle
        title_box = tk.Frame(banner_frame, bg='SystemButtonFace')
        title_box.grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 6))

        lbl_title = tk.Label(
            title_box,
            text='Review Synchronization Actions',
            font=('Segoe UI', 11, 'bold'),
            bg='SystemButtonFace',
            fg='#111827',
        )
        lbl_title.pack(anchor='w')

        lbl_desc = tk.Label(
            title_box,
            text='Inspect planned filesystem changes. Check or uncheck items to customize what will be executed.',
            font=('Segoe UI', 9),
            bg='SystemButtonFace',
            fg='#4b5563',
        )
        lbl_desc.pack(anchor='w')

        # Category Stat Badges
        badge_frame = tk.Frame(banner_frame, bg='SystemButtonFace')
        badge_frame.grid(row=1, column=0, columnspan=4, sticky='w')

        self.lbl_stat_copy = BadgeLabel(
            badge_frame,
            text='🟢 Copy: 0 files (0 B)',
            variant='success',
            font=('Segoe UI', 9),
            padx=8,
            pady=2,
        )
        self.lbl_stat_copy.pack(side='left', padx=(0, 6))

        self.lbl_stat_move = BadgeLabel(
            badge_frame,
            text='🔵 Move: 0 files (0 B)',
            variant='primary',
            font=('Segoe UI', 9),
            padx=8,
            pady=2,
        )
        self.lbl_stat_move.pack(side='left', padx=(0, 6))

        self.lbl_stat_delete = BadgeLabel(
            badge_frame,
            text='🔴 Delete: 0 files (0 B)',
            variant='error',
            font=('Segoe UI', 9),
            padx=8,
            pady=2,
        )
        self.lbl_stat_delete.pack(side='left', padx=(0, 6))

    def _create_toolbar(self):
        toolbar_frame = ttk.Frame(self.popup, padding=(8, 4))
        toolbar_frame.grid(row=1, column=0, sticky='ew')
        toolbar_frame.grid_columnconfigure(0, weight=1)

        # Row 1: Action buttons & Quick safety buttons
        row_actions = ttk.Frame(toolbar_frame)
        row_actions.pack(fill='x', pady=(0, 4))

        # Selection shortcuts
        btn_select_all = ttk.Button(
            row_actions,
            text='Select All',
            command=lambda: self.tree.select_all(),
            width=11,
        )
        add_tooltip(btn_select_all, 'Select and check all synchronization actions.')
        btn_select_all.pack(side='left', padx=(0, 4))

        btn_deselect_all = ttk.Button(
            row_actions,
            text='Deselect All',
            command=lambda: self.tree.deselect_all(),
            width=11,
        )
        add_tooltip(btn_deselect_all, 'Deselect and uncheck all synchronization actions.')
        btn_deselect_all.pack(side='left', padx=(0, 6))

        # Expand / Collapse
        btn_expand = ttk.Button(
            row_actions,
            text='Expand All',
            command=lambda: self.tree.expand_all(),
            width=11,
        )
        add_tooltip(btn_expand, 'Expand all action categories to display every file.')
        btn_expand.pack(side='left', padx=(0, 4))

        btn_collapse = ttk.Button(
            row_actions,
            text='Collapse All',
            command=lambda: self.tree.collapse_all(),
            width=11,
        )
        add_tooltip(btn_collapse, 'Collapse all action categories.')
        btn_collapse.pack(side='left', padx=(0, 8))

        ttk.Separator(row_actions, orient='vertical').pack(side='left', fill='y', padx=4)

        # Quick Safety Action Buttons
        self.btn_uncheck_deletions = ttk.Button(
            row_actions,
            text='Uncheck Deletions',
            command=lambda: self.tree.uncheck_action(Action.DELETE),
        )
        apply_icon(self.btn_uncheck_deletions, 'shield')
        add_tooltip(self.btn_uncheck_deletions, 'Safely uncheck all deletion operations with one click.')
        self.btn_uncheck_deletions.pack(side='left', padx=(6, 4))

        self.btn_copies_only = ttk.Button(
            row_actions,
            text='Copies Only',
            command=lambda: self.tree.set_copies_only(),
        )
        apply_icon(self.btn_copies_only, 'check_circle')
        add_tooltip(self.btn_copies_only, 'Check only copy operations; uncheck moves and deletions.')
        self.btn_copies_only.pack(side='left', padx=(0, 4))

        # Row 2: Search Entry & File Type Filter Chips
        row_filter = ttk.Frame(toolbar_frame)
        row_filter.pack(fill='x', pady=(2, 0))

        lbl_filter = ttk.Label(row_filter, text='Filter:', font=('Segoe UI', 9))
        lbl_filter.pack(side='left', padx=(0, 4))

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self._on_filter_changed)
        self.entry_filter = ttk.Entry(row_filter, textvariable=self.filter_var, width=24)
        add_tooltip(self.entry_filter, 'Filter by file name, path, or extension (Ctrl+F). Press Esc to clear.')
        self.entry_filter.pack(side='left', padx=(0, 4))

        btn_clear_filter = ttk.Button(
            row_filter,
            text='✕',
            command=self._on_clear_filter,
            width=3,
        )
        add_tooltip(btn_clear_filter, 'Clear filter and restore all items (Esc).')
        btn_clear_filter.pack(side='left', padx=(0, 8))

        ttk.Separator(row_filter, orient='vertical').pack(side='left', fill='y', padx=4)

        lbl_type = ttk.Label(row_filter, text='Type:', font=('Segoe UI', 9))
        lbl_type.pack(side='left', padx=(6, 4))

        self.active_category: str = 'all'
        self.category_buttons: dict[str, ttk.Button] = {}
        chip_defs = [
            ('all', 'All', None),
            ('image', 'Images', 'image'),
            ('document', 'Docs', 'document'),
            ('media', 'Media', 'media'),
            ('code', 'Code', 'code'),
            ('archive', 'Archives', 'archive'),
        ]

        for cat_id, cat_label, icon_name in chip_defs:
            btn = ttk.Button(
                row_filter,
                text=cat_label,
                command=lambda c=cat_id: self._on_category_chip_clicked(c),
                style='Accent.TButton' if cat_id == 'all' else 'TButton',
            )
            if icon_name:
                apply_icon(btn, icon_name)
            add_tooltip(btn, f'Filter by {cat_label.lower()} files.')
            btn.pack(side='left', padx=2)
            self.category_buttons[cat_id] = btn

        self.lbl_filter_count = ttk.Label(row_filter, text='', font=('Segoe UI', 9))
        self.lbl_filter_count.pack(side='left', padx=(8, 0))

    def create_table(self):
        frame_table = ttk.Frame(self.popup)
        frame_table.grid(row=2, column=0, sticky='nsew', padx=8, pady=4)
        frame_table.grid_rowconfigure(0, weight=1)
        frame_table.grid_columnconfigure(0, weight=1)

        self.tree = CustomCheckboxTreeView(frame_table, height=9, on_stats_changed=self._update_banner_stats)
        self.tree.grid(row=0, column=0, sticky='nsew')

        # Add vertical scrollbar
        vscroll = ttk.Scrollbar(frame_table, orient='vertical', command=self.tree.yview)
        vscroll.grid(row=0, column=1, sticky='ns')

        # Add horizontal scrollbar
        hscroll = ttk.Scrollbar(frame_table, orient='horizontal', command=self.tree.xview)
        hscroll.grid(row=1, column=0, sticky='ew')

        self.tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)

        self.tree.add_file_lists(
            {
                Action.COPY: self.files_available_to_copy,
                Action.MOVE: self.files_available_to_move,
                Action.DELETE: self.files_available_to_delete,
            },
            default_active=self.default_actions,
        )

        self.tree.bind('<<TreeviewSelect>>', self._on_item_selected)
        self.tree.bind('<Double-1>', self._on_item_double_click)
        self.tree.bind('<Button-3>', self._on_tree_right_click)
        self.tree.bind('<App>', self._on_context_key)
        self.tree.bind('<Shift-F10>', self._on_context_key)
        self.tree.refresh_group_stats()

    def _create_bottom_bar(self):
        bottom_frame = ttk.Frame(self.popup, padding=(8, 6))
        bottom_frame.grid(row=3, column=0, sticky='ew')
        bottom_frame.grid_columnconfigure(0, weight=1)

        # Side-by-Side Comparison & Diff Card
        inspector_frame = ttk.LabelFrame(bottom_frame, text=' Selected Item Comparison & Diff ')
        inspector_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        inspector_frame.grid_columnconfigure(0, weight=1)

        # Header: File Category Badge + Diff Summary + Copy Path button
        hdr = ttk.Frame(inspector_frame)
        hdr.grid(row=0, column=0, sticky='ew', padx=6, pady=(3, 4))
        hdr.grid_columnconfigure(1, weight=1)

        self.lbl_inspector_badge = ttk.Label(hdr, text='📄 File', font=('Segoe UI', 9, 'bold'))
        self.lbl_inspector_badge.grid(row=0, column=0, sticky='w')

        self.lbl_inspector_diff = ttk.Label(
            hdr, text='(select an item to view comparison)', font=('Segoe UI', 9), foreground='#005a9e'
        )
        self.lbl_inspector_diff.grid(row=0, column=1, sticky='w', padx=(10, 0))

        btn_action_box = ttk.Frame(hdr)
        btn_action_box.grid(row=0, column=2, sticky='e')

        self.btn_see_in_folder = ttk.Button(
            btn_action_box,
            text='See in Folder',
            command=self._open_selected_in_folder,
            width=14,
        )
        apply_icon(self.btn_see_in_folder, 'folder')
        self.btn_see_in_folder.pack(side='left', padx=(0, 4))

        self.btn_copy_path = ttk.Button(
            btn_action_box,
            text='Copy Path',
            command=self._copy_selected_path_to_clipboard,
            width=12,
        )
        apply_icon(self.btn_copy_path, 'copy')
        add_tooltip(self.btn_copy_path, 'Copy path to clipboard. Right-click for more copy options.')
        self.btn_copy_path.pack(side='left')

        self.btn_details = ttk.Button(
            btn_action_box,
            text='Details...',
            command=self._show_selected_details_dialog,
            width=11,
        )
        apply_icon(self.btn_details, 'document')
        add_tooltip(self.btn_details, 'View full metadata, diff, and properties for selected file.')
        self.btn_details.pack(side='left', padx=(4, 0))

        # Details: Source row and Target row
        details_frame = ttk.Frame(inspector_frame)
        details_frame.grid(row=1, column=0, sticky='ew', padx=6, pady=(0, 4))
        details_frame.grid_columnconfigure(1, weight=1)

        lbl_s = ttk.Label(details_frame, text='Source:', font=('Segoe UI', 9, 'bold'), width=7)
        lbl_s.grid(row=0, column=0, sticky='w', pady=1)
        self.lbl_inspector_source = ttk.Label(details_frame, text='(select an item to view path)', font=('Segoe UI', 9))
        self.lbl_inspector_source.grid(row=0, column=1, sticky='w', pady=1)

        self.lbl_inspector_src_meta = ttk.Label(details_frame, text='', font=('Segoe UI', 8), foreground='#555555')
        self.lbl_inspector_src_meta.grid(row=1, column=1, sticky='w', pady=(0, 2))

        lbl_t = ttk.Label(details_frame, text='Target:', font=('Segoe UI', 9, 'bold'), width=7)
        lbl_t.grid(row=2, column=0, sticky='w', pady=1)
        self.lbl_inspector_target = ttk.Label(details_frame, text='-', font=('Segoe UI', 9))
        self.lbl_inspector_target.grid(row=2, column=1, sticky='w', pady=1)

        self.lbl_inspector_tgt_meta = ttk.Label(details_frame, text='', font=('Segoe UI', 8), foreground='#555555')
        self.lbl_inspector_tgt_meta.grid(row=3, column=1, sticky='w', pady=(0, 2))

        # Context menu bindings for inspector components
        self.lbl_inspector_source.bind('<Button-3>', self._on_source_label_right_click)
        self.lbl_inspector_target.bind('<Button-3>', self._on_target_label_right_click)
        self.btn_copy_path.bind('<Button-3>', self._on_copy_btn_right_click)
        self.lbl_inspector_diff.bind('<Button-3>', self._on_tree_right_click)
        self.lbl_inspector_badge.bind('<Button-3>', self._on_tree_right_click)

        # Bottom Buttons
        btn_box = ttk.Frame(bottom_frame)
        btn_box.grid(row=1, column=1, sticky='e')

        self.button_save = ttk.Button(
            btn_box,
            text='Save and continue',
            command=self.button_save_click,
            style='Accent.TButton',
            width=18,
        )
        self.button_save.pack(side='right', padx=(6, 0))

        self.button_cancel = ttk.Button(
            btn_box,
            text='Cancel',
            command=self.button_cancel_click,
            width=12,
        )
        self.button_cancel.pack(side='right')

    def _copy_to_clipboard(self, text: str, description: str = 'text'):
        if not text:
            return
        try:
            self.popup.clipboard_clear()
            self.popup.clipboard_append(text)
            self.popup.update_idletasks()
            logger.info(f"Copied {description} to clipboard: '{text[:80]}{'...' if len(text) > 80 else ''}'")
            if hasattr(self, 'lbl_inspector_diff'):
                prev_text = self.lbl_inspector_diff.cget('text')
                self.lbl_inspector_diff.config(text=f'📋 Copied {description} to clipboard!')
                self.popup.after(2000, lambda: self._restore_diff_text(prev_text))
        except Exception as e:
            logger.warning(f'Could not copy {description} to clipboard: {e}')

    def _restore_diff_text(self, prev_text: str):
        if hasattr(self, 'lbl_inspector_diff'):
            curr = self.lbl_inspector_diff.cget('text')
            if curr.startswith('📋 Copied'):
                self.lbl_inspector_diff.config(text=prev_text)

    def _copy_source_path(self, path: str | None = None):
        if path is None:
            path = self.lbl_inspector_source.cget('text')
        if path and path not in ('-', '(none)', '(select an item to view path)'):
            self._copy_to_clipboard(path, 'source path')

    def _copy_target_path(self, path: str | None = None):
        if path is None:
            path = self.lbl_inspector_target.cget('text')
        if path and path not in ('-', '(none)', '(select an item to view path)'):
            self._copy_to_clipboard(path, 'target path')

    def _copy_both_paths(self, src: str | None = None, tgt: str | None = None):
        if src is None:
            src = self.lbl_inspector_source.cget('text')
        if tgt is None:
            tgt = self.lbl_inspector_target.cget('text')
        lines = []
        if src and src not in ('-', '(none)', '(select an item to view path)'):
            lines.append(f'Source: {src}')
        if tgt and tgt not in ('-', '(none)', '(select an item to view path)'):
            lines.append(f'Target: {tgt}')
        if lines:
            self._copy_to_clipboard('\n'.join(lines), 'source and target paths')

    def _copy_filename(self, path: str | None = None):
        if path is None:
            src = self.lbl_inspector_source.cget('text')
            tgt = self.lbl_inspector_target.cget('text')
            path = src if src not in ('-', '(none)', '(select an item to view path)') else tgt
        if path and path not in ('-', '(none)', '(select an item to view path)'):
            fname = os.path.basename(path) or path
            self._copy_to_clipboard(fname, 'filename')

    def _copy_row_details(self, item_id: str | None = None):
        if item_id is None:
            selected = self.tree.selection()
            if not selected:
                return
            item_id = selected[0]
        summary = self._format_item_summary(item_id)
        if summary:
            self._copy_to_clipboard(summary, 'item details')

    def _copy_multi_paths(self, item_ids: list[str], side: str):
        paths = []
        item_actions = getattr(self.tree, '_item_actions', {})
        for iid in item_ids:
            item_info = item_actions.get(iid)
            if item_info:
                p = item_info[1] if side == 'source' else item_info[2]
                if p and p not in ('-', '(none)'):
                    paths.append(p)
        if paths:
            self._copy_to_clipboard('\n'.join(paths), f'{side} paths ({len(paths)})')

    def _copy_multi_pairs(self, item_ids: list[str]):
        pairs = []
        item_actions = getattr(self.tree, '_item_actions', {})
        for iid in item_ids:
            item_info = item_actions.get(iid)
            if item_info:
                src = item_info[1] if item_info[1] not in ('-', '(none)') else ''
                tgt = item_info[2] if item_info[2] not in ('-', '(none)') else ''
                if src or tgt:
                    pairs.append(f'{src} -> {tgt}')
        if pairs:
            self._copy_to_clipboard('\n'.join(pairs), f'path pairs ({len(pairs)})')

    def _copy_multi_summary(self, item_ids: list[str]):
        lines = [f'FastMirror Selection Summary ({len(item_ids)} files):']
        item_actions = getattr(self.tree, '_item_actions', {})
        for iid in item_ids:
            item_info = item_actions.get(iid)
            if item_info:
                action, src, tgt = item_info
                lines.append(f'[{action.value.upper()}] {src} -> {tgt}')
        self._copy_to_clipboard('\n'.join(lines), 'selection summary')

    def _copy_group_summary(self, group_id: str):
        try:
            action_enum = Action.from_str(group_id)
            count, total_bytes = self.tree.get_action_stats(action_enum)
            all_children = self.tree._all_group_children.get(group_id, [])
            total_files = len(all_children)
            summary = (
                f'Action Group: {group_id.upper()}\n'
                f'Checked: {count} of {total_files} files\n'
                f'Total Size: {format_size(total_bytes)}\n'
            )
            self._copy_to_clipboard(summary, f'{group_id} group summary')
        except Exception as e:
            logger.warning(f'Could not copy group summary: {e}')

    def _format_item_summary(self, item_id: str) -> str:
        item_info = getattr(self.tree, '_item_actions', {}).get(item_id)
        if not item_info:
            return ''
        action, source_path, target_path = item_info
        row_data = self.tree._data.get(action, {}).get(item_id, {})
        primary_path = source_path if source_path and source_path != '(none)' else target_path
        fname = os.path.basename(primary_path) or primary_path
        is_chk = self.tree.tag_has('checked', item_id)

        lines = [
            f'Action: {action.value.upper()}',
            f'File: {fname}',
            f'Status: {"Selected for sync" if is_chk else "Excluded (unchecked)"}',
            f'Source Path: {source_path or "-"}',
            f'Source Size: {row_data.get("size (source)", "-")}',
            f'Source Modified: {row_data.get("modification date (source)", "-")}',
            f'Target Path: {target_path or "-"}',
            f'Target Size: {row_data.get("size (target)", "-")}',
            f'Target Modified: {row_data.get("modification date (target)", "-")}',
        ]
        return '\n'.join(lines)

    def _copy_selected_path_to_clipboard(self):
        target_path = self.lbl_inspector_target.cget('text')
        source_path = self.lbl_inspector_source.cget('text')
        path_to_copy = target_path if target_path not in ('-', '(none)') else source_path
        if path_to_copy and path_to_copy not in ('(none)', '(select an item to view path)'):
            self._copy_to_clipboard(path_to_copy, 'path')

    def _open_path_in_explorer(self, path: str):
        if not path or path in ('-', '(none)', '(select an item to view path)'):
            return
        norm_path = os.path.normpath(path)
        try:
            if os.path.isfile(norm_path):
                subprocess.Popen(['explorer.exe', f'/select,{norm_path}'])
            elif os.path.isdir(norm_path):
                os.startfile(norm_path)
            else:
                parent_dir = os.path.dirname(norm_path)
                if os.path.isdir(parent_dir):
                    os.startfile(parent_dir)
                else:
                    logger.warning(f"Neither '{norm_path}' nor its directory exist on disk.")
        except Exception as e:
            logger.warning(f"Could not open folder for '{norm_path}': {e}")

    def _show_selected_details_dialog(self, item_id: str | None = None):
        if item_id is None:
            selected = self.tree.selection()
            if not selected:
                return
            item_id = selected[0]

        if item_id in self.tree.get_children(''):
            return

        item_info = getattr(self.tree, '_item_actions', {}).get(item_id)
        if item_info is not None:
            action, source_path, target_path = item_info
            row_data = self.tree._data.get(action, {}).get(item_id)
        elif '::' in item_id:
            parts = item_id.split('::', 2)
            with contextlib.suppress(Exception):
                action = Action(parts[0])
            source_path = parts[1] if len(parts) >= 2 else ''
            target_path = parts[2] if len(parts) >= 3 else ''
            row_data = self.tree._data.get(action, {}).get(item_id)
        else:
            return

        is_checked = self.tree.tag_has('checked', item_id)
        FileDetailsDialog(
            parent=self.popup,
            action=action,
            source_path=source_path,
            target_path=target_path,
            row_data=row_data,
            is_checked=is_checked,
        )

    def _on_tree_right_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            self._show_empty_area_context_menu(event)
            return

        curr_selection = list(self.tree.selection())
        if row_id not in curr_selection:
            self.tree.selection_set(row_id)
            self._on_item_selected(None)
            curr_selection = [row_id]

        if row_id in self.tree.get_children(''):
            self._show_group_context_menu(event, row_id)
        elif len(curr_selection) > 1:
            self._show_multi_item_context_menu(event, curr_selection)
        else:
            self._show_single_item_context_menu(event, row_id)

    def _on_context_key(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        x = self.tree.winfo_rootx() + 50
        y = self.tree.winfo_rooty() + 50
        with contextlib.suppress(Exception):
            bbox = self.tree.bbox(selected[0])
            if bbox:
                x = self.tree.winfo_rootx() + bbox[0] + 20
                y = self.tree.winfo_rooty() + bbox[1] + 20
        dummy_event = type('DummyEvent', (), {'x_root': x, 'y_root': y})()
        if len(selected) > 1:
            self._show_multi_item_context_menu(dummy_event, list(selected))
        elif selected[0] in self.tree.get_children(''):
            self._show_group_context_menu(dummy_event, selected[0])
        else:
            self._show_single_item_context_menu(dummy_event, selected[0])

    def _show_single_item_context_menu(self, event, item_id: str):
        item_info = getattr(self.tree, '_item_actions', {}).get(item_id)
        if item_info is not None:
            action, source_path, target_path = item_info
        elif '::' in item_id:
            parts = item_id.split('::', 2)
            source_path = parts[1] if len(parts) >= 2 else ''
            target_path = parts[2] if len(parts) >= 3 else ''
        else:
            return

        menu = tk.Menu(self.popup, tearoff=0)

        has_src = bool(source_path and source_path not in ('-', '(none)'))
        has_tgt = bool(target_path and target_path not in ('-', '(none)'))

        menu.add_command(
            label='📋 Copy Source Path',
            command=lambda: self._copy_source_path(source_path),
            state='normal' if has_src else 'disabled',
        )
        menu.add_command(
            label='📋 Copy Target Path',
            command=lambda: self._copy_target_path(target_path),
            state='normal' if has_tgt else 'disabled',
        )
        menu.add_command(
            label='📋 Copy Both Paths',
            command=lambda: self._copy_both_paths(source_path, target_path),
            state='normal' if (has_src or has_tgt) else 'disabled',
        )
        menu.add_command(
            label='📋 Copy File Name',
            command=lambda: self._copy_filename(source_path or target_path),
        )
        menu.add_command(
            label='📋 Copy Row Details',
            command=lambda: self._copy_row_details(item_id),
        )

        menu.add_separator()

        menu.add_command(
            label='📂 Open Source in Explorer',
            command=lambda: self._open_path_in_explorer(source_path),
            state='normal' if has_src else 'disabled',
        )
        menu.add_command(
            label='📂 Open Target in Explorer',
            command=lambda: self._open_path_in_explorer(target_path),
            state='normal' if has_tgt else 'disabled',
        )

        menu.add_separator()

        menu.add_command(
            label='ℹ️ View File Details...',
            command=lambda: self._show_selected_details_dialog(item_id),
        )

        menu.add_separator()

        is_checked = self.tree.tag_has('checked', item_id)
        if is_checked:
            menu.add_command(
                label='☐ Uncheck Item',
                command=lambda: self._toggle_item_check(item_id, 'unchecked'),
            )
        else:
            menu.add_command(
                label='☑️ Check Item',
                command=lambda: self._toggle_item_check(item_id, 'checked'),
            )

        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _show_multi_item_context_menu(self, event, item_ids: list[str]):
        count = len(item_ids)
        menu = tk.Menu(self.popup, tearoff=0)

        menu.add_command(
            label=f'📋 Copy Selected Source Paths ({count})',
            command=lambda: self._copy_multi_paths(item_ids, 'source'),
        )
        menu.add_command(
            label=f'📋 Copy Selected Target Paths ({count})',
            command=lambda: self._copy_multi_paths(item_ids, 'target'),
        )
        menu.add_command(
            label=f'📋 Copy Selected Path Pairs ({count})',
            command=lambda: self._copy_multi_pairs(item_ids),
        )
        menu.add_command(
            label=f'📋 Copy Summary ({count} items)',
            command=lambda: self._copy_multi_summary(item_ids),
        )

        menu.add_separator()

        menu.add_command(
            label=f'☑️ Check Selected ({count})',
            command=lambda: self._set_multi_check(item_ids, 'checked'),
        )
        menu.add_command(
            label=f'☐ Uncheck Selected ({count})',
            command=lambda: self._set_multi_check(item_ids, 'unchecked'),
        )

        menu.add_separator()

        primary_id = item_ids[0]
        menu.add_command(
            label='ℹ️ View Details of Primary Item...',
            command=lambda: self._show_selected_details_dialog(primary_id),
        )

        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _show_group_context_menu(self, event, group_id: str):
        menu = tk.Menu(self.popup, tearoff=0)
        group_name = group_id.upper()
        children = self.tree._all_group_children.get(group_id, list(self.tree.get_children(group_id)))
        count = len(children)

        menu.add_command(
            label=f'📋 Copy All Source Paths in {group_name} ({count})',
            command=lambda: self._copy_multi_paths(children, 'source'),
            state='normal' if count > 0 else 'disabled',
        )
        menu.add_command(
            label=f'📋 Copy All Target Paths in {group_name} ({count})',
            command=lambda: self._copy_multi_paths(children, 'target'),
            state='normal' if count > 0 else 'disabled',
        )
        menu.add_command(
            label=f'📋 Copy Group Summary ({group_name})',
            command=lambda: self._copy_group_summary(group_id),
        )

        menu.add_separator()

        menu.add_command(
            label=f'☑️ Check All in {group_name}',
            command=lambda: self._set_group_check(group_id, 'checked'),
        )
        menu.add_command(
            label=f'☐ Uncheck All in {group_name}',
            command=lambda: self._set_group_check(group_id, 'unchecked'),
        )

        menu.add_separator()

        is_open = self.tree.item(group_id, 'open')
        if is_open:
            menu.add_command(
                label=f'➖ Collapse {group_name}',
                command=lambda: self.tree.item(group_id, open=False),
            )
        else:
            menu.add_command(
                label=f'➕ Expand {group_name}',
                command=lambda: self.tree.item(group_id, open=True),
            )

        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _show_empty_area_context_menu(self, event):
        menu = tk.Menu(self.popup, tearoff=0)
        menu.add_command(label='Select All', command=self.tree.select_all)
        menu.add_command(label='Deselect All', command=self.tree.deselect_all)
        menu.add_separator()
        menu.add_command(label='Expand All', command=self.tree.expand_all)
        menu.add_command(label='Collapse All', command=self.tree.collapse_all)
        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _on_source_label_right_click(self, event):
        src_path = self.lbl_inspector_source.cget('text')
        if not src_path or src_path in ('-', '(none)', '(select an item to view path)'):
            return
        menu = tk.Menu(self.popup, tearoff=0)
        menu.add_command(
            label='📋 Copy Source Path',
            command=lambda: self._copy_source_path(src_path),
        )
        menu.add_command(
            label='📂 Open Source in Explorer',
            command=lambda: self._open_path_in_explorer(src_path),
        )
        menu.add_separator()
        menu.add_command(
            label='ℹ️ View File Details...',
            command=self._show_selected_details_dialog,
        )
        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _on_target_label_right_click(self, event):
        tgt_path = self.lbl_inspector_target.cget('text')
        if not tgt_path or tgt_path in ('-', '(none)', '(select an item to view path)'):
            return
        menu = tk.Menu(self.popup, tearoff=0)
        menu.add_command(
            label='📋 Copy Target Path',
            command=lambda: self._copy_target_path(tgt_path),
        )
        menu.add_command(
            label='📂 Open Target in Explorer',
            command=lambda: self._open_path_in_explorer(tgt_path),
        )
        menu.add_separator()
        menu.add_command(
            label='ℹ️ View File Details...',
            command=self._show_selected_details_dialog,
        )
        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _on_copy_btn_right_click(self, event):
        menu = tk.Menu(self.popup, tearoff=0)
        menu.add_command(label='📋 Copy Target Path', command=self._copy_target_path)
        menu.add_command(label='📋 Copy Source Path', command=self._copy_source_path)
        menu.add_command(label='📋 Copy Both Paths', command=self._copy_both_paths)
        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _toggle_item_check(self, item_id: str, state: str):
        self.tree.change_state(item_id, state)
        self.tree.refresh_group_stats()

    def _set_multi_check(self, item_ids: list[str], state: str):
        for item_id in item_ids:
            if self.tree.exists(item_id):
                self.tree.change_state(item_id, state)
        self.tree.refresh_group_stats()

    def _set_group_check(self, group_id: str, state: str):
        if self.tree.exists(group_id):
            self.tree.change_state(group_id, state)
        self.tree.refresh_group_stats()

    def _open_selected_in_folder(self):
        """Reveal selected file in Windows Explorer, highlighting the file if it exists."""
        source_path = ''
        target_path = ''

        selected = self.tree.selection()
        if selected:
            item_id = selected[0]
            item_info = getattr(self.tree, '_item_actions', {}).get(item_id)
            if item_info is not None:
                _, source_path, target_path = item_info

        if not source_path and not target_path:
            source_path = self.lbl_inspector_source.cget('text')
            target_path = self.lbl_inspector_target.cget('text')

        # Prioritize path that actually exists on disk (source is usually local and exists)
        path_to_open = None
        for p in (source_path, target_path):
            if p and p not in ('-', '(none)', '(select an item to view path)'):
                if os.path.exists(p):
                    path_to_open = p
                    break
                elif path_to_open is None:
                    path_to_open = p

        if not path_to_open or path_to_open in ('-', '(none)', '(select an item to view path)'):
            return

        norm_path = os.path.normpath(path_to_open)
        try:
            if os.path.isfile(norm_path):
                # /select,<path> highlights the specific file in Windows Explorer
                subprocess.Popen(['explorer.exe', f'/select,{norm_path}'])
            elif os.path.isdir(norm_path):
                os.startfile(norm_path)
            else:
                parent_dir = os.path.dirname(norm_path)
                if os.path.isdir(parent_dir):
                    os.startfile(parent_dir)
        except Exception as e:
            logger.warning(f"Could not open folder for '{norm_path}': {e}")

    def _on_item_double_click(self, event):
        """Open folder of selected file in Windows Explorer upon double-click."""
        self._open_selected_in_folder()

    def _on_item_selected(self, event):
        selected = self.tree.selection()
        if not selected:
            return

        # Prominently highlight currently selected row and restore previous selection
        prev_selected = getattr(self, '_prev_selected_items', set())
        curr_selected = set(selected)
        for unsel_id in prev_selected - curr_selected:
            if self.tree.exists(unsel_id):
                tags = [t for t in self.tree.item(unsel_id, 'tags') if t != 'selected_row']
                action_info = getattr(self.tree, '_item_actions', {}).get(unsel_id)
                if action_info:
                    action_tag = f'{action_info[0].value}_tag'
                    if action_tag not in tags:
                        tags.append(action_tag)
                self.tree.item(unsel_id, tags=tuple(tags))
        for sel_id in curr_selected:
            if self.tree.exists(sel_id):
                tags = [t for t in self.tree.item(sel_id, 'tags') if not t.endswith('_tag')]
                if 'selected_row' not in tags:
                    tags.insert(0, 'selected_row')
                self.tree.item(sel_id, tags=tuple(tags))
        self._prev_selected_items = curr_selected

        item_id = selected[0]
        item_info = getattr(self.tree, '_item_actions', {}).get(item_id)
        action: Action | None = None
        source_path = ''
        target_path = ''
        row_data = None

        if item_info is not None:
            action, source_path, target_path = item_info
            if action in self.tree._data and item_id in self.tree._data[action]:
                row_data = self.tree._data[action][item_id]
        elif '::' in item_id:
            parts = item_id.split('::', 2)
            if len(parts) >= 3:
                source_path = parts[1] if (parts[1] and parts[1] not in ('-', '(none)')) else ''
                target_path = parts[2] if (parts[2] and parts[2] not in ('-', '(none)')) else ''
                with contextlib.suppress(Exception):
                    action = Action(parts[0])
        else:
            self.lbl_inspector_badge.config(text='📁 Group')
            self.lbl_inspector_diff.config(text=f'Category: {item_id.upper()}')
            self.lbl_inspector_source.config(text=f'Group: {item_id.upper()}')
            self.lbl_inspector_target.config(text='-')
            self.lbl_inspector_src_meta.config(text='')
            self.lbl_inspector_tgt_meta.config(text='')
            return

        display_src = source_path if (source_path and source_path not in ('-', '(none)')) else '-'
        display_tgt = target_path if (target_path and target_path not in ('-', '(none)')) else '-'
        self.lbl_inspector_source.config(text=display_src)
        self.lbl_inspector_target.config(text=display_tgt)

        # Determine file type badge
        inspect_path = source_path if (source_path and source_path not in ('-', '(none)')) else target_path
        icon, cat = get_file_type_badge(inspect_path)
        self.lbl_inspector_badge.config(text=f'{icon} {cat}')

        # Determine metadata and comparison diff
        src_meta = ''
        tgt_meta = ''
        diff_text = ''

        if row_data:
            src_sz = str(row_data.get('size (source)', ''))
            src_dt = str(row_data.get('modification date (source)', ''))
            tgt_sz = str(row_data.get('size (target)', ''))
            tgt_dt = str(row_data.get('modification date (target)', ''))

            if source_path in ('-', '(none)', '', None):
                src_meta = 'Size: -  •  Modified: -'
            elif src_sz or src_dt:
                src_meta = f'Size: {src_sz or "-"}  •  Modified: {src_dt or "-"}'

            if target_path in ('-', '(none)', '', None):
                tgt_meta = 'Size: -  •  Modified: -'
            elif tgt_sz or tgt_dt:
                tgt_meta = f'Size: {tgt_sz or "-"}  •  Modified: {tgt_dt or "-"}'

            src_bytes = float(row_data.get('bytes (source)', 0) or 0)
            tgt_bytes = float(row_data.get('bytes (target)', 0) or 0)

            if action == Action.DELETE:
                diff_text = (
                    f'⚠️ File will be removed from target ({tgt_sz})'
                    if tgt_sz != '-'
                    else '⚠️ File will be removed from target'
                )
            elif action == Action.MOVE:
                diff_text = f'🔄 File will be moved/renamed at destination ({src_sz})'
            elif tgt_sz == '-' or tgt_dt in ('-', '', None):
                diff_text = f'✨ New file on target • {src_sz}'
            else:
                parts = []
                if src_bytes != tgt_bytes:
                    diff_bytes = src_bytes - tgt_bytes
                    sign = '+' if diff_bytes > 0 else ''
                    parts.append(f'Size diff: {sign}{format_size(diff_bytes)}')
                else:
                    parts.append('Identical size')
                if src_dt and tgt_dt and src_dt != '-' and tgt_dt != '-':
                    parts.append('Same timestamp' if src_dt == tgt_dt else f'Source: {src_dt}')
                diff_text = ' • '.join(parts)
        elif action:
            diff_text = f'Action: {action.value.upper()}'

        self.lbl_inspector_src_meta.config(text=src_meta)
        self.lbl_inspector_tgt_meta.config(text=tgt_meta)
        self.lbl_inspector_diff.config(text=diff_text)

    def _update_banner_stats(self):
        copy_count, copy_bytes = self.tree.get_action_stats(Action.COPY)
        move_count, move_bytes = self.tree.get_action_stats(Action.MOVE)
        del_count, del_bytes = self.tree.get_action_stats(Action.DELETE)

        def _format_badge(action: Action, count: int, bytes_val: int | float, icon: str) -> str:
            name = action.value.capitalize()
            if count == 0:
                return f'{icon} {name}: 0 files (0 B)'
            action_data = self.tree._data.get(action, {})
            checked = getattr(self.tree, '_cached_checked_by_action', {}).get(action.value, [])
            size_key = 'size (target)' if action == Action.DELETE else 'size (source)'
            has_known = any(action_data[x].get(size_key) != '-' for x in checked if x in action_data)
            size_str = format_size(bytes_val) if has_known else '-'
            return f'{icon} {name}: {count} files ({size_str})'

        self.lbl_stat_copy.config(text=_format_badge(Action.COPY, copy_count, copy_bytes, '🟢'))
        self.lbl_stat_move.config(text=_format_badge(Action.MOVE, move_count, move_bytes, '🔵'))
        self.lbl_stat_delete.config(text=_format_badge(Action.DELETE, del_count, del_bytes, '🔴'))

    def _on_category_chip_clicked(self, cat: str):
        self.active_category = cat
        for c_key, btn in getattr(self, 'category_buttons', {}).items():
            btn.configure(style='Accent.TButton' if c_key == cat else 'TButton')
        self._on_filter_changed()

    def _on_clear_filter(self):
        self.active_category = 'all'
        for c_key, btn in getattr(self, 'category_buttons', {}).items():
            btn.configure(style='Accent.TButton' if c_key == 'all' else 'TButton')
        self.filter_var.set('')

    def _on_filter_changed(self, *args):
        query = self.filter_var.get()
        active_cat = getattr(self, 'active_category', 'all')
        match_count, first_match = self.tree.filter_items(query, category=active_cat)

        is_filtering = bool(query.strip()) or (active_cat != 'all')
        if is_filtering:
            cat_desc = f' [{active_cat.title()}]' if active_cat != 'all' else ''
            self.lbl_filter_count.config(text=f'({match_count} match{"es" if match_count != 1 else ""}{cat_desc})')
            if first_match is not None:
                self.tree.see(first_match)
                self.tree.selection_set(first_match)
                self._on_item_selected(None)
        else:
            self.lbl_filter_count.config(text='')

    def _focus_filter_entry(self):
        """Focus the search filter entry and select all text (Ctrl+F)."""
        if hasattr(self, 'entry_filter'):
            self.entry_filter.focus_set()
            self.entry_filter.select_range(0, 'end')
        return 'break'

    def _on_escape_pressed(self, event=None):
        """Smart Escape: clears filter if active; otherwise prompts/cancels."""
        if getattr(self, 'filter_var', None) and self.filter_var.get():
            self._on_clear_filter()
            return 'break'
        if getattr(self, 'active_category', 'all') != 'all':
            self._on_clear_filter()
            return 'break'
        self.button_cancel_click()
        return 'break'

    def button_save_click(self):
        if self.finished:
            return
        logger.info('Saving selection of actions')
        self.finished = True
        self.proceed = True

        # Restore treeview filter before collecting output selections
        self.tree.filter_items('', category=None)

        self.files_requested_to_copy = list()
        self.files_requested_to_move = list()
        self.files_requested_to_delete = list()

        item_actions = getattr(self.tree, '_item_actions', {})
        for id_ in self.tree.get_checked():
            item_info = item_actions.get(id_)
            if item_info is not None:
                action, source_path, target_path = item_info
                if action == Action.COPY:
                    self.files_requested_to_copy.append((source_path, target_path))
                elif action == Action.MOVE:
                    self.files_requested_to_move.append((source_path, target_path))
                elif action == Action.DELETE:
                    self.files_requested_to_delete.append(target_path)
            elif '::' in id_:
                parts = id_.split('::', 2)
                group = parts[0]
                raw_tgt = parts[2] if len(parts) > 2 else ''
                tgt_clean = raw_tgt.split('#')[0]
                if group == 'copy':
                    self.files_requested_to_copy.append((parts[1], tgt_clean))
                elif group == 'move':
                    self.files_requested_to_move.append((parts[1], tgt_clean))
                elif group == 'delete':
                    self.files_requested_to_delete.append(tgt_clean)

        with contextlib.suppress(Exception):
            self.popup.destroy()
        taskbar = getattr(getattr(self, 'root_gui', None), 'taskbar', None)
        if taskbar is not None:
            with contextlib.suppress(Exception):
                self.root_gui.after(0, taskbar.clear)
        if self.on_close_callback:
            self.on_close_callback()

    def button_cancel_click(self):
        if self.finished:
            return
        logger.info('Canceling selection of actions. No action will be taken')
        self.finished = True
        self.proceed = False
        self.files_requested_to_copy = list()
        self.files_requested_to_move = list()
        self.files_requested_to_delete = list()
        with contextlib.suppress(Exception):
            self.popup.destroy()
        taskbar = getattr(getattr(self, 'root_gui', None), 'taskbar', None)
        if taskbar is not None:
            with contextlib.suppress(Exception):
                self.root_gui.after(0, taskbar.clear)
        if self.on_close_callback:
            self.on_close_callback()

    def on_window_close(self):
        if self.finished:
            return
        if messagebox.askyesno(
            'Cancel Synchronization?',
            'Closing this window will cancel the synchronization. No listed actions will be performed.\n\n'
            'Cancel synchronization?',
            parent=self.popup,
            default='no',
        ):
            self.button_cancel_click()

    def get_outputs(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
        return self.files_requested_to_copy, self.files_requested_to_move, self.files_requested_to_delete
