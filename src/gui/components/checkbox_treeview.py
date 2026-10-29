"""Multi-level destination-centric CheckboxTreeview for FastMirror synchronization review."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any

import ttkwidgets

from core.file import CstmPath
from gui.components.sync_tree_model import (
    FolderNode,
    _compact_trie,
    _extract_relative_folder_parts,
    _format_move_origin,
    get_file_type_badge,
)
from gui.widgets import Action
from utils.utils import format_size


class CustomCheckboxTreeView(ttkwidgets.CheckboxTreeview):
    custom_headers = [
        'enable',
        'action',
        'origin',
        'size',
        'modified',
    ]

    def __init__(self, *args, on_stats_changed: Callable[[], None] | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        self._data: dict[Action, dict[str, dict[str, float | str]]] = {}
        self._item_actions: dict[str, tuple[Action, str, str]] = {}
        self._all_group_children: dict[str, list[str]] = {}
        self._folder_nodes: set[str] = set()
        self._folder_display_names: dict[str, str] = {}
        self._folder_leaf_map: dict[str, list[str]] = {}
        self._item_parents: dict[str, str] = {}
        self._original_tree_structure: dict[str, list[str]] = {}
        self._attached_items: dict[str, set[str]] = {}
        self._highlighted_items: set[str] = set()
        self._search_cache: dict[str, tuple[str, str]] = {}
        self.on_stats_changed = on_stats_changed
        self._sort_col: str | None = None
        self._sort_descending: bool = False
        self._is_filtered: bool = False

        # Configure Treeview columns and headers
        self['columns'] = self.custom_headers[1:]
        self.column('#0', width=380, minwidth=260)
        self.heading('#0', text='Item / File Name', command=lambda: self.sort_by_column('#0'))

        col_configs = {
            'action': (105, 85, 'Action'),
            'origin': (290, 180, 'Origin / Details'),
            'size': (95, 75, 'Size'),
            'modified': (145, 110, 'Modified'),
        }
        for column in self.custom_headers[1:]:
            width, minwidth, title = col_configs.get(column, (150, 100, column.title()))
            self.heading(column, text=title, command=lambda c=column: self.sort_by_column(c))
            self.column(column, width=width, minwidth=minwidth)

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
        self.tag_configure('folder_tag', background='#ffffff')
        self.tag_configure('highlight_match', background='#fff59d')
        self.tag_configure('selected_row', background='#0078d7', foreground='#ffffff')

    def _box_click(self, event):
        super()._box_click(event)
        self.refresh_group_stats()

    def refresh_group_stats(self):
        """Update folder summary rows and notify stats listeners."""
        for folder_iid in getattr(self, '_folder_nodes', set()):
            if not self.exists(folder_iid):
                continue
            leaf_children = self._folder_leaf_map.get(folder_iid, [])
            checked_leaves = [ch for ch in leaf_children if self.exists(ch) and self.tag_has('checked', ch)]
            n_checked = len(checked_leaves)
            n_total = len(leaf_children)

            folder_bytes = 0.0
            has_known = False
            for ch in checked_leaves:
                action_info = self._item_actions.get(ch)
                if not action_info:
                    continue
                action = action_info[0]
                row = self._data.get(action, {}).get(ch, {})
                b = row.get('size in bytes', 0)
                if isinstance(b, int | float):
                    folder_bytes += b
                sz_key = 'size (target)' if action == Action.DELETE else 'size (source)'
                if row.get(sz_key) != '-':
                    has_known = True

            sz_str = format_size(folder_bytes) if has_known else '-'
            folder_display = self._folder_display_names.get(folder_iid, '')
            self.item(
                folder_iid,
                text=f'📁  {folder_display}',
                values=(
                    f'({n_checked}/{n_total} files)' if n_total > 1 else '(1 file)',
                    '',
                    sz_str,
                    '',
                ),
            )

        if self.on_stats_changed:
            self.on_stats_changed()

    def has_known_size(self, action: Action) -> bool:
        """Return True if at least one checked leaf of this action has a known (non '-') size."""
        action_data = self._data.get(action, {})
        size_key = 'size (target)' if action == Action.DELETE else 'size (source)'
        for item_id in self._all_group_children.get(action.value, []):
            row = action_data.get(item_id)
            if (
                row is not None
                and row.get(size_key) != '-'
                and self.exists(item_id)
                and self.tag_has('checked', item_id)
            ):
                return True
        return False

    def get_action_stats(self, action: Action) -> tuple[int, int | float]:
        """Return (checked_file_count, total_checked_bytes) for the given action."""
        action_data = self._data.get(action, {})
        all_leaves = self._all_group_children.get(action.value, [])
        checked_count = 0
        total_bytes: float = 0.0
        for item_id in all_leaves:
            if self.exists(item_id) and self.tag_has('checked', item_id):
                checked_count += 1
                if item_id in action_data:
                    val = action_data[item_id].get('size in bytes')
                    if isinstance(val, int | float):
                        total_bytes += float(val)
        return checked_count, total_bytes

    def add_file_lists(
        self,
        file_lists: dict[Action, list[tuple[CstmPath, CstmPath]] | list[CstmPath]],
        default_active: list[Action] | None = None,
    ):
        if default_active is None:
            default_active = []

        self._item_actions.clear()
        self._all_group_children.clear()
        self._folder_nodes.clear()
        self._folder_display_names.clear()
        self._folder_leaf_map.clear()
        self._item_parents.clear()
        self._original_tree_structure.clear()
        self._attached_items.clear()
        self._highlighted_items.clear()
        self._search_cache.clear()
        self._is_filtered = False
        self._sort_col = None
        self._sort_descending = False

        self.heading('#0', text='Item / File Name')
        col_configs = {
            'action': 'Action',
            'origin': 'Origin / Details',
            'size': 'Size',
            'modified': 'Modified',
        }
        for column in self.custom_headers[1:]:
            self.heading(column, text=col_configs.get(column, column.title()))

        # 1. Parse row data
        all_entries: list[tuple[str, Action, str, str, dict[str, Any]]] = []
        all_parent_parts: list[list[str]] = []

        for action, file_list in file_lists.items():
            self._data[action] = {}
            for file_entry in file_list:
                src_arg, tgt_arg = (None, file_entry) if isinstance(file_entry, CstmPath) else file_entry
                values = self.get_row(src_arg, tgt_arg, action=action)
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
                all_entries.append((item_key, action, src_val, tgt_val, values))

                primary_tgt = tgt_val if (tgt_val and tgt_val != '-') else src_val
                if primary_tgt and primary_tgt not in ('-', '(none)'):
                    parent_parts = list(Path(primary_tgt).parent.parts)
                    if parent_parts:
                        all_parent_parts.append(parent_parts)

        # 2. Construct folder Trie using full paths from root so no folders are loose
        root_trie = FolderNode(name='', path_key='')
        for item_key, action, src_val, tgt_val, row in all_entries:
            primary_tgt = tgt_val if (tgt_val and tgt_val != '-') else src_val
            folder_parts, _ = _extract_relative_folder_parts(primary_tgt)

            curr = root_trie
            accum_parts: list[str] = []
            for part in folder_parts:
                part_key = part.lower()
                accum_parts.append(part_key)
                path_key = '/'.join(accum_parts)
                if part_key not in curr.children:
                    curr.children[part_key] = FolderNode(name=part, path_key=path_key)
                curr = curr.children[part_key]
            curr.files.append((item_key, action, src_val, tgt_val, row))

        # 4. Compact single-child folder chains
        root_trie = _compact_trie(root_trie, is_root=True)

        # 5. Insert compacted Trie into Treeview
        self._populate_tree_from_trie('', root_trie, default_active)

        # 6. Bottom-up leaf aggregation and folder state initialization
        for folder_iid in sorted(self._folder_nodes, key=lambda x: x.count('/'), reverse=True):
            children = self._original_tree_structure.get(folder_iid, [])
            all_leaves: list[str] = []
            for ch in children:
                if ch in self._folder_nodes:
                    all_leaves.extend(self._folder_leaf_map.get(ch, []))
                else:
                    all_leaves.append(ch)
            self._folder_leaf_map[folder_iid] = all_leaves

            checked_count = sum(1 for lf in all_leaves if self.tag_has('checked', lf))
            if checked_count == len(all_leaves) and len(all_leaves) > 0:
                self.change_state(folder_iid, 'checked')
            elif checked_count == 0:
                self.change_state(folder_iid, 'unchecked')
            else:
                self.change_state(folder_iid, 'tristate')

        self.refresh_group_stats()

    def _populate_tree_from_trie(self, parent_iid: str, node: FolderNode, default_active: list[Action]):
        """Recursively insert folders and files into the treeview."""
        # Insert subfolders
        for child in node.children.values():
            folder_iid = f'folder::{child.path_key}'
            self._folder_nodes.add(folder_iid)
            self._folder_display_names[folder_iid] = child.name
            self._item_parents[folder_iid] = parent_iid
            self._attached_items.setdefault(parent_iid, set()).add(folder_iid)
            self._original_tree_structure.setdefault(parent_iid, []).append(folder_iid)

            self.insert(
                parent=parent_iid,
                index='end',
                iid=folder_iid,
                text=f'📁  {child.name}',
                values=('', '', '', ''),
                tags=('folder_tag',),
                open=True,
            )

            self._populate_tree_from_trie(folder_iid, child, default_active)

        # Insert files in this folder
        for file_key, action, src_val, tgt_val, row in node.files:
            self._folder_leaf_map.setdefault(parent_iid, []).append(file_key)
            self._item_parents[file_key] = parent_iid
            self._attached_items.setdefault(parent_iid, set()).add(file_key)
            self._original_tree_structure.setdefault(parent_iid, []).append(file_key)
            self._item_actions[file_key] = (action, src_val, tgt_val)
            self._all_group_children.setdefault(action.value, []).append(file_key)

            primary_path = tgt_val if (tgt_val and tgt_val != '-') else src_val
            icon, _ = get_file_type_badge(primary_path)
            fname = os.path.basename(primary_path) or primary_path

            # Determine Origin / Transition details
            if action == Action.MOVE:
                origin_str = _format_move_origin(src_val, tgt_val)
                action_badge = '🔵 Move'
                sz_str = str(row.get('size (source)', '')) or '-'
                dt_str = str(row.get('modification date (source)', '')) or '-'
            elif action == Action.DELETE:
                origin_str = '⚠️ Will be removed'
                action_badge = '🔴 Delete'
                sz_str = str(row.get('size (target)', '')) or '-'
                dt_str = str(row.get('modification date (target)', '')) or '-'
            else:  # Action.COPY
                tgt_sz = row.get('size (target)')
                origin_str = '✨ New file' if (tgt_sz == '-' or not tgt_sz) else '⚠️ Overwrite'
                action_badge = '🟢 Copy'
                sz_str = str(row.get('size (source)', '')) or '-'
                dt_str = str(row.get('modification date (source)', '')) or '-'

            state_tag = 'checked' if action in default_active else 'unchecked'
            action_style_tag = f'{action.value}_tag'

            folder_display = self._folder_display_names.get(parent_iid, '')
            search_str = (
                f'{fname.lower()} {src_val.lower()} {tgt_val.lower()} {origin_str.lower()} {folder_display.lower()}'
            )
            self._search_cache[file_key] = (search_str, action.value)

            self.insert(
                parent=parent_iid,
                index='end',
                iid=file_key,
                text=f'{icon}  {fname}',
                values=(
                    action_badge,
                    origin_str,
                    sz_str,
                    dt_str,
                ),
                tags=(action_style_tag, state_tag),
            )

    def get_checked(self) -> list[str]:
        """High-performance retrieval of checked leaf items."""
        checked: list[str] = []
        for item_key in self._item_actions:
            if self.exists(item_key) and self.tag_has('checked', item_key):
                checked.append(item_key)
        return checked

    def get_children(self, item=None):
        """Return child items, supporting action group names ('copy', 'move', 'delete') as aliases."""
        if item in ('copy', 'move', 'delete'):
            leaves = self._all_group_children.get(item, [])
            visible = getattr(self, '_visible_leaves', None)
            if visible is not None:
                leaves = [lf for lf in leaves if lf in visible]
            return tuple(leaves)
        return super().get_children(item or '')

    def item(self, item, option=None, **kw):
        """Query or modify item options, supporting action group names ('copy', 'move', 'delete')."""
        if item in ('copy', 'move', 'delete'):
            if kw:
                if 'open' in kw:
                    for f_id in getattr(self, '_folder_nodes', set()):
                        if self.exists(f_id):
                            super().item(f_id, open=kw['open'])
                return
            act_enum = Action(item)
            count, total_bytes = self.get_action_stats(act_enum)
            total_files = len(self._all_group_children.get(item, []))
            size_str = format_size(total_bytes) if self.has_known_size(act_enum) else '-'
            text_val = f'{item} {size_str} ({count} of {total_files})'
            if option == 'text':
                return text_val
            return {'text': text_val, 'open': True}
        return super().item(item, option=option, **kw)

    def change_state(self, item, state):
        """Set checkbox state, cascading across all leaf items for action group names."""
        if item in ('copy', 'move', 'delete'):
            leaves = self._all_group_children.get(item, [])
            for leaf in leaves:
                if self.exists(leaf):
                    super().change_state(leaf, state)
                    if state == 'checked':
                        self._check_ancestor(leaf)
                    else:
                        self._uncheck_ancestor(leaf)
            self.refresh_group_stats()
            return
        super().change_state(item, state)

    def tag_has(self, tag, item=None):
        """Check if an item has a tag, supporting action group names ('copy', 'move', 'delete')."""
        if item in ('copy', 'move', 'delete'):
            leaves = self._all_group_children.get(item, [])
            if not leaves:
                return False
            base_tag_has = super().tag_has
            checked_count = sum(1 for lf in leaves if self.exists(lf) and base_tag_has('checked', lf))
            if tag == 'checked':
                return checked_count == len(leaves)
            elif tag == 'unchecked':
                return checked_count == 0
            elif tag == 'tristate':
                return 0 < checked_count < len(leaves)
            return False
        return super().tag_has(tag, item)

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
        """Check all tree items."""
        for root in self.get_children(''):
            self.change_state(root, 'checked')
            self._check_descendant(root)
        self.refresh_group_stats()

    def deselect_all(self):
        """Uncheck all tree items."""
        for root in self.get_children(''):
            self.change_state(root, 'unchecked')
            self._uncheck_descendant(root)
        self.refresh_group_stats()

    def uncheck_action(self, action: Action):
        """Uncheck all leaf items belonging to a specific action."""
        leaves = self._all_group_children.get(action.value, [])
        for leaf in leaves:
            if self.exists(leaf):
                self.change_state(leaf, 'unchecked')
                self._uncheck_ancestor(leaf)
        self.refresh_group_stats()

    def set_copies_only(self):
        """Check all copy items and uncheck all move and delete items."""
        copy_leaves = self._all_group_children.get(Action.COPY.value, [])
        for leaf in copy_leaves:
            if self.exists(leaf):
                self.change_state(leaf, 'checked')
                self._check_ancestor(leaf)
        for act in (Action.MOVE, Action.DELETE):
            for leaf in self._all_group_children.get(act.value, []):
                if self.exists(leaf):
                    self.change_state(leaf, 'unchecked')
                    self._uncheck_ancestor(leaf)
        self.refresh_group_stats()

    def sort_by_column(self, col: str):
        """Sort items within each folder and top level by column ascending or descending."""
        orig_col = col
        if col in ('size (source)', 'size (target)', 'size in bytes'):
            col = 'size'
        elif col in ('source', 'target', 'origin / details'):
            col = 'origin'
        elif col in ('modification date (source)', 'modification date (target)'):
            col = 'modified'

        if getattr(self, '_sort_col', None) == col:
            self._sort_descending = not getattr(self, '_sort_descending', False)
        else:
            self._sort_col = col
            self._sort_descending = False

        reverse = self._sort_descending
        arrow = ' ▼' if reverse else ' ▲'

        # Update headings
        col0_text = 'Item / File Name'
        self.heading('#0', text=f'{col0_text}{arrow}' if col == '#0' else col0_text)
        for c in self.custom_headers[1:]:
            title = 'Origin / Details' if c == 'origin' else ('Modified' if c == 'modified' else c.title())
            self.heading(c, text=f'{title}{arrow}' if c == col else title)
        if orig_col != col:
            with contextlib.suppress(Exception):
                self.heading(orig_col, text=f'{orig_col}{arrow}')

        def _sort_key(item_id: str):
            if item_id in self._folder_nodes:
                return (0, self._folder_display_names.get(item_id, item_id).lower())
            action_info = self._item_actions.get(item_id)
            if not action_info:
                return (1, item_id.lower())
            action, src_val, tgt_val = action_info
            row = self._data.get(action, {}).get(item_id, {})
            if col == 'size':
                val = row.get('size in bytes', 0)
                return (1, float(val if isinstance(val, int | float) else 0))
            elif col == 'action':
                return (1, action.value)
            elif col == 'origin':
                primary_path = tgt_val if (tgt_val and tgt_val != '-') else src_val
                return (1, str(primary_path).lower())
            elif col == 'modified':
                dt_key = 'modification date (target)' if action == Action.DELETE else 'modification date (source)'
                return (1, str(row.get(dt_key, '')))
            elif col == '#0':
                primary_path = tgt_val if (tgt_val and tgt_val != '-') else src_val
                return (1, os.path.basename(primary_path).lower())
            else:
                return (1, item_id.lower())

        for parent_iid, children in list(self._original_tree_structure.items()):
            sorted_children = sorted(children, key=_sort_key, reverse=reverse)
            self._original_tree_structure[parent_iid] = sorted_children
            attached = self._attached_items.get(parent_iid, set())
            idx = 0
            for child_id in sorted_children:
                if self.exists(child_id) and (not self._is_filtered or child_id in attached):
                    self.move(child_id, parent_iid, idx)
                    idx += 1

        for act_str, leaves in self._all_group_children.items():
            self._all_group_children[act_str] = sorted(leaves, key=_sort_key, reverse=reverse)

    def expand_all(self):
        """Expand all folder nodes."""
        for folder_iid in self._folder_nodes:
            if self.exists(folder_iid):
                self.item(folder_iid, open=True)

    def collapse_all(self):
        """Collapse all folder nodes."""
        for folder_iid in self._folder_nodes:
            if self.exists(folder_iid):
                self.item(folder_iid, open=False)

    def filter_items(
        self,
        query: str = '',
        action_filter: str | None = None,
        category: str | None = None,
    ) -> tuple[int, str | None]:
        """
        Filter the displayed tree items by free text and action type ('all', 'copy', 'move', 'delete').
        Detaches non-matching items and empty folders, and reattaches matching items.
        Returns (match_count, first_match_id).
        """
        query = query.strip().lower()
        effective_act = action_filter or category
        act = effective_act.lower() if effective_act and effective_act.lower() not in ('all', '') else None
        first_match = None
        match_count = 0

        # If neither filter is active, restore full original hierarchy
        if not query and act is None:
            self._visible_leaves = None
            if not getattr(self, '_is_filtered', False):
                return 0, None
            self._is_filtered = False

            # Clear highlight match tag
            for child in list(self._highlighted_items):
                if self.exists(child):
                    tags = tuple(t for t in self.item(child, 'tags') if t != 'highlight_match')
                    self.item(child, tags=tags)
            self._highlighted_items.clear()

            # Reattach in original order (one Tk call per parent)
            for parent_iid, children in self._original_tree_structure.items():
                if parent_iid and not self.exists(parent_iid):
                    continue
                self.set_children(parent_iid, *children)
                self._attached_items[parent_iid] = set(children)
            return 0, None

        self._is_filtered = True
        matching_leaves: set[str] = set()
        self._visible_leaves = matching_leaves

        for item_key, (search_str, file_action) in self._search_cache.items():
            text_match = not query or (query in search_str)
            act_match = (act is None) or (file_action == act)
            if text_match and act_match:
                matching_leaves.add(item_key)
                match_count += 1
                if first_match is None:
                    first_match = item_key

        # Folders that contain at least one matching leaf
        active_folders: set[str] = set()
        for folder_iid, leaves in self._folder_leaf_map.items():
            if any(lf in matching_leaves for lf in leaves):
                active_folders.add(folder_iid)

        # Clear stale highlights
        for child in list(self._highlighted_items):
            if child not in matching_leaves or not query:
                if self.exists(child):
                    tags = tuple(t for t in self.item(child, 'tags') if t != 'highlight_match')
                    self.item(child, tags=tags)
                self._highlighted_items.discard(child)

        # Update visibility in treeview (one Tk call per parent)
        for parent_iid, children in self._original_tree_structure.items():
            if parent_iid and not self.exists(parent_iid):
                continue
            parent_is_active = parent_iid == '' or parent_iid in active_folders
            visible: list[str] = []
            if parent_is_active:
                for child_iid in children:
                    if child_iid in self._folder_nodes:
                        if child_iid in active_folders:
                            visible.append(child_iid)
                    elif child_iid in matching_leaves:
                        visible.append(child_iid)
            self.set_children(parent_iid, *visible)
            self._attached_items[parent_iid] = set(visible)

            for child_iid in visible:
                if child_iid in self._folder_nodes:
                    self.item(child_iid, open=True)
                elif query and child_iid not in self._highlighted_items:
                    tags = tuple(self.item(child_iid, 'tags')) + ('highlight_match',)
                    self.item(child_iid, tags=tags)
                    self._highlighted_items.add(child_iid)

        return match_count, first_match
