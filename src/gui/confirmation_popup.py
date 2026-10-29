import contextlib
import os
import subprocess
import tkinter as tk
import winsound
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import ttkwidgets

from core.file import CstmPath
from gui.icons import apply_icon, apply_window_icon
from gui.widgets import Action, BadgeLabel, add_tooltip
from utils.logger import logger
from utils.utils import format_size


class FolderNode:
    """Node in directory tree used for multi-level folder hierarchy with compaction."""

    def __init__(self, name: str, path_key: str):
        self.name = name
        self.path_key = path_key
        self.children: dict[str, FolderNode] = {}
        self.files: list[tuple[str, Action, str, str, dict[str, Any]]] = []


def _extract_relative_folder_parts(
    target_path: str,
    root_dir: str | None = None,
    common_prefix_parts: list[str] | None = None,
) -> tuple[list[str], str]:
    """Extract full directory parts from root and filename without blocking network I/O."""
    if not target_path or target_path in ('-', '(none)'):
        return [], ''

    p = Path(target_path)
    filename = p.name or target_path

    raw_parts = list(p.parent.parts)
    parts: list[str] = []
    for part in raw_parts:
        cleaned = part.rstrip('\\/')
        if cleaned:
            parts.append(cleaned)
    return parts, filename


def _format_move_origin(src_val: str, tgt_val: str) -> str:
    """Format a smart diff-based relative origin string for Move operations."""
    src_parts, src_name = _extract_relative_folder_parts(src_val)
    tgt_parts, tgt_name = _extract_relative_folder_parts(tgt_val)

    name_changed = src_name != tgt_name
    name_case_only = name_changed and (src_name.lower() == tgt_name.lower())

    # 1. Exact same folder path (including case): file-only rename
    if src_parts == tgt_parts:
        if name_case_only:
            return f'Case rename: {src_name} → {tgt_name}'
        if name_changed:
            return f'Renamed from: {src_name}'
        return f'from: {src_val}'

    # 2. Same folder hierarchy, only folder casing changed
    if len(src_parts) == len(tgt_parts) and [pt.lower() for pt in src_parts] == [pt.lower() for pt in tgt_parts]:
        diff_pairs = [(s, t) for s, t in zip(src_parts, tgt_parts, strict=False) if s != t]
        old_seg = '\\'.join(s for s, _ in diff_pairs)
        new_seg = '\\'.join(t for _, t in diff_pairs)
        if name_changed:
            return f'Case rename: {old_seg}\\{src_name} → {new_seg}\\{tgt_name}'
        return f'Case rename: {old_seg} → {new_seg}'

    # Find longest common case-insensitive prefix between src_parts and tgt_parts
    common_len = 0
    for s_part, t_part in zip(src_parts, tgt_parts, strict=False):
        if s_part.lower() == t_part.lower():
            common_len += 1
        else:
            break

    # 3. Moved UP from a subfolder inside the target directory
    if common_len == len(tgt_parts) and len(src_parts) > len(tgt_parts):
        sub_rel = '\\'.join(src_parts[common_len:])
        if name_changed:
            return f'Moved up from: .\\{sub_rel}\\{src_name}'
        return f'Moved up from: .\\{sub_rel}\\'

    # 4. Moved DOWN into a subfolder from an ancestor directory
    if common_len == len(src_parts) and len(tgt_parts) > len(src_parts):
        parent_name = src_parts[-1] if src_parts else ''
        if name_changed:
            return (
                f'Moved down from: .\\{src_name} (in {parent_name}\\)'
                if parent_name
                else f'Moved down from: .\\{src_name}'
            )
        return f'Moved down from: .\\ (in {parent_name}\\)' if parent_name else 'Moved down from: .\\ (parent folder)'

    # 5. Divergent folder branches: show path from 1 folder above the divergence point (or share-relative)
    if common_len >= 1:
        start_idx = max(1, common_len - 1)
        rel_branch = '\\'.join(src_parts[start_idx:])
        prefix = '...\\' if start_idx > 1 else ''
        if name_changed:
            return f'from: {prefix}{rel_branch}\\{src_name}'
        return f'from: {prefix}{rel_branch}\\'

    # Fallback: completely different roots
    full_src_dir = '\\'.join(src_parts)
    if name_changed:
        return f'from: {full_src_dir}\\{src_name}' if full_src_dir else f'Renamed from: {src_name}'
    return f'from: {full_src_dir}\\' if full_src_dir else f'from: {src_val}'


def _compact_trie(node: FolderNode, is_root: bool = False) -> FolderNode:
    """Recursively compact single-child folder chains into single path nodes (VS Code style)."""
    for k in list(node.children.keys()):
        node.children[k] = _compact_trie(node.children[k], is_root=False)

    if not is_root and len(node.files) == 0 and len(node.children) == 1:
        only_child = next(iter(node.children.values()))
        compacted = FolderNode(f'{node.name} \\ {only_child.name}', only_child.path_key)
        compacted.children = only_child.children
        compacted.files = only_child.files
        return compacted
    return node


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


FILTER_BTN_PALETTES: dict[str, dict[str, str]] = {
    'all': {
        'inactive_text': 'All',
        'active_text': '✓ All',
        'inactive_bg': '#ffffff',
        'inactive_fg': '#1e293b',
        'hover_bg': '#e2e8f0',
        'active_bg': '#0078d7',
        'active_fg': '#ffffff',
    },
    'copy': {
        'inactive_text': '🟢 Copies',
        'active_text': '✓ Copies',
        'inactive_bg': '#ffffff',
        'inactive_fg': '#15803d',
        'hover_bg': '#dcfce7',
        'active_bg': '#15803d',
        'active_fg': '#ffffff',
    },
    'move': {
        'inactive_text': '🔵 Moves',
        'active_text': '✓ Moves',
        'inactive_bg': '#ffffff',
        'inactive_fg': '#1d4ed8',
        'hover_bg': '#dbeafe',
        'active_bg': '#1d4ed8',
        'active_fg': '#ffffff',
    },
    'delete': {
        'inactive_text': '🔴 Deletions',
        'active_text': '✓ Deletions',
        'inactive_bg': '#ffffff',
        'inactive_fg': '#b91c1c',
        'hover_bg': '#fee2e2',
        'active_bg': '#b91c1c',
        'active_fg': '#ffffff',
    },
}


class FilterToggleButton(tk.Button):
    """Toggleable filter button with high-contrast pressed/active visual feedback."""

    def __init__(
        self,
        master: tk.Misc,
        action_key: str,
        command: Callable[[], None],
        active: bool = False,
        **kwargs,
    ):
        self.action_key = action_key
        self.is_active = active
        self._style = 'Accent.TButton' if active else 'TButton'
        palette = FILTER_BTN_PALETTES.get(action_key, FILTER_BTN_PALETTES['all'])

        kwargs.pop('style', None)
        super().__init__(
            master,
            command=command,
            cursor='hand2',
            padx=12,
            pady=2,
            **kwargs,
        )
        self.set_active(active)
        self.bind('<Enter>', self._on_enter, add='+')
        self.bind('<Leave>', self._on_leave, add='+')

        # Keep reference to palette for hover
        self._palette = palette

    def set_active(self, active: bool):
        self.is_active = active
        self._style = 'Accent.TButton' if active else 'TButton'
        p = FILTER_BTN_PALETTES.get(self.action_key, FILTER_BTN_PALETTES['all'])
        if active:
            super().configure(
                text=p['active_text'],
                bg=p['active_bg'],
                fg=p['active_fg'],
                activebackground=p['active_bg'],
                activeforeground=p['active_fg'],
                relief='sunken',
                bd=2,
                font=('Segoe UI', 9, 'bold'),
            )
        else:
            super().configure(
                text=p['inactive_text'],
                bg=p['inactive_bg'],
                fg=p['inactive_fg'],
                activebackground=p['hover_bg'],
                activeforeground=p['inactive_fg'],
                relief='raised',
                bd=1,
                font=('Segoe UI', 9),
            )

    def _on_enter(self, _event=None):
        if not self.is_active:
            p = FILTER_BTN_PALETTES.get(self.action_key, FILTER_BTN_PALETTES['all'])
            super().configure(bg=p['hover_bg'])

    def _on_leave(self, _event=None):
        if not self.is_active:
            p = FILTER_BTN_PALETTES.get(self.action_key, FILTER_BTN_PALETTES['all'])
            super().configure(bg=p['inactive_bg'])

    def cget(self, key: str):
        if key == 'style':
            return self._style
        return super().cget(key)

    def configure(self, cnf=None, **kwargs):
        if 'style' in kwargs:
            st = kwargs.pop('style')
            self.set_active(st == 'Accent.TButton')
        if cnf or kwargs:
            return super().configure(cnf, **kwargs)
        return None

    def config(self, cnf=None, **kwargs):
        return self.configure(cnf, **kwargs)


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
            cursor='hand2',
        )
        self.lbl_stat_copy.pack(side='left', padx=(0, 6))
        self.lbl_stat_copy.bind('<Button-1>', lambda e: self._on_action_filter_clicked('copy'))
        add_tooltip(self.lbl_stat_copy, 'Click to filter tree by Copy operations.')

        self.lbl_stat_move = BadgeLabel(
            badge_frame,
            text='🔵 Move: 0 files (0 B)',
            variant='primary',
            font=('Segoe UI', 9),
            padx=8,
            pady=2,
            cursor='hand2',
        )
        self.lbl_stat_move.pack(side='left', padx=(0, 6))
        self.lbl_stat_move.bind('<Button-1>', lambda e: self._on_action_filter_clicked('move'))
        add_tooltip(self.lbl_stat_move, 'Click to filter tree by Move operations.')

        self.lbl_stat_delete = BadgeLabel(
            badge_frame,
            text='🔴 Delete: 0 files (0 B)',
            variant='error',
            font=('Segoe UI', 9),
            padx=8,
            pady=2,
            cursor='hand2',
        )
        self.lbl_stat_delete.pack(side='left', padx=(0, 6))
        self.lbl_stat_delete.bind('<Button-1>', lambda e: self._on_action_filter_clicked('delete'))
        add_tooltip(self.lbl_stat_delete, 'Click to filter tree by Delete operations.')

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
        add_tooltip(btn_expand, 'Expand all folder categories to display every file.')
        btn_expand.pack(side='left', padx=(0, 4))

        btn_collapse = ttk.Button(
            row_actions,
            text='Collapse All',
            command=lambda: self.tree.collapse_all(),
            width=11,
        )
        add_tooltip(btn_collapse, 'Collapse all folder categories.')
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

        # Row 2: Search Entry & Action Filter Buttons
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

        lbl_type = ttk.Label(row_filter, text='Action:', font=('Segoe UI', 9))
        lbl_type.pack(side='left', padx=(6, 4))

        self.active_category: str = 'all'
        self.active_action_filter: str = 'all'
        self.action_buttons: dict[str, FilterToggleButton] = {}
        action_defs = [
            ('all', 'All'),
            ('copy', 'Copies'),
            ('move', 'Moves'),
            ('delete', 'Deletions'),
        ]

        for act_id, act_label in action_defs:
            btn = FilterToggleButton(
                row_filter,
                action_key=act_id,
                command=lambda a=act_id: self._on_action_filter_clicked(a),
                active=(act_id == 'all'),
            )
            add_tooltip(btn, f'Toggle filter to show {act_label.lower()}.')
            btn.pack(side='left', padx=3)
            self.action_buttons[act_id] = btn

        self.category_buttons = self.action_buttons  # Backwards compatibility alias

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
            command=self.on_window_close,
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

        if item_id in self.tree.get_children('') or item_id in getattr(self.tree, '_folder_nodes', set()):
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

        if row_id in self.tree.get_children('') or row_id in self.tree._folder_nodes:
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
        elif selected[0] in self.tree.get_children('') or selected[0] in self.tree._folder_nodes:
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
        is_folder = group_id in self.tree._folder_nodes
        if is_folder:
            group_name = self.tree._folder_display_names.get(group_id, group_id)
            children = list(self.tree._folder_leaf_map.get(group_id, []))
        else:
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
        if not is_folder:
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
        if group_id in getattr(self.tree, '_folder_nodes', set()) and self.tree.exists(group_id):
            if state == 'checked':
                self.tree._check_descendant(group_id)
                self.tree._check_ancestor(group_id)
            else:
                self.tree._uncheck_descendant(group_id)
                self.tree._uncheck_ancestor(group_id)
        elif group_id in ('copy', 'move', 'delete') or self.tree.exists(group_id):
            self.tree.change_state(group_id, state)
        self.tree.refresh_group_stats()

    def _open_selected_in_folder(self):
        """Reveal selected file in Windows Explorer, highlighting the file if it exists."""
        source_path = ''
        target_path = ''

        selected = self.tree.selection()
        if selected:
            item_id = selected[0]
            if item_id in getattr(self.tree, '_folder_nodes', set()):
                leaves = self.tree._folder_leaf_map.get(item_id, [])
                for lf in leaves:
                    info = getattr(self.tree, '_item_actions', {}).get(lf)
                    if info:
                        tgt_p = info[2]
                        if tgt_p and tgt_p not in ('-', '(none)'):
                            dir_to_open = os.path.dirname(tgt_p)
                            if os.path.exists(dir_to_open):
                                self._open_path_in_explorer(dir_to_open)
                                return
                        src_p = info[1]
                        if src_p and src_p not in ('-', '(none)'):
                            dir_to_open = os.path.dirname(src_p)
                            if os.path.exists(dir_to_open):
                                self._open_path_in_explorer(dir_to_open)
                                return
                return
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
            if item_id in getattr(self.tree, '_folder_nodes', set()):
                disp_name = self.tree._folder_display_names.get(item_id, item_id)
                leaves = self.tree._folder_leaf_map.get(item_id, [])
                folder_bytes = 0.0
                for lf in leaves:
                    lf_info = self.tree._item_actions.get(lf)
                    if lf_info:
                        b = self.tree._data.get(lf_info[0], {}).get(lf, {}).get('size in bytes', 0)
                        if isinstance(b, int | float):
                            folder_bytes += b
                sz_text = format_size(folder_bytes) if folder_bytes > 0 else '-'
                self.lbl_inspector_badge.config(text='📁 Folder')
                self.lbl_inspector_diff.config(
                    text=f'Folder contains {len(leaves)} planned sync file{"s" if len(leaves) != 1 else ""} ({sz_text})'
                )
                self.lbl_inspector_source.config(text=f'Folder: {disp_name}')
                self.lbl_inspector_target.config(text='-')
                self.lbl_inspector_src_meta.config(text=f'Files: {len(leaves)}  •  Total Size: {sz_text}')
                self.lbl_inspector_tgt_meta.config(text='')
                return
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
            size_str = format_size(bytes_val) if self.tree.has_known_size(action) else '-'
            return f'{icon} {name}: {count} files ({size_str})'

        self.lbl_stat_copy.config(text=_format_badge(Action.COPY, copy_count, copy_bytes, '🟢'))
        self.lbl_stat_move.config(text=_format_badge(Action.MOVE, move_count, move_bytes, '🔵'))
        self.lbl_stat_delete.config(text=_format_badge(Action.DELETE, del_count, del_bytes, '🔴'))

    def _update_action_filter_visuals(self, act_id: str):
        for a_key, btn in getattr(self, 'action_buttons', {}).items():
            btn.configure(style='Accent.TButton' if a_key == act_id else 'TButton')

        badge_map = {
            'copy': (getattr(self, 'lbl_stat_copy', None), '#15803d', '#bbf7d0'),
            'move': (getattr(self, 'lbl_stat_move', None), '#1d4ed8', '#bfdbfe'),
            'delete': (getattr(self, 'lbl_stat_delete', None), '#b91c1c', '#fecaca'),
        }
        for b_key, (badge, active_border, normal_border) in badge_map.items():
            if badge is not None:
                with contextlib.suppress(Exception):
                    if act_id == b_key:
                        badge.configure(highlightthickness=2, highlightbackground=active_border)
                    else:
                        badge.configure(highlightthickness=1, highlightbackground=normal_border)

    def _on_action_filter_clicked(self, act_id: str):
        if getattr(self, 'active_action_filter', 'all') == act_id and act_id != 'all':
            act_id = 'all'
        self.active_action_filter = act_id
        self.active_category = act_id
        self._update_action_filter_visuals(act_id)
        self._on_filter_changed()

    def _on_category_chip_clicked(self, cat: str):
        self._on_action_filter_clicked(cat)

    def _on_clear_filter(self):
        self.active_action_filter = 'all'
        self.active_category = 'all'
        self._update_action_filter_visuals('all')
        self.filter_var.set('')

    def _on_filter_changed(self, *args):
        query = self.filter_var.get()
        active_act = getattr(self, 'active_action_filter', 'all')
        match_count, first_match = self.tree.filter_items(query, action_filter=active_act)

        is_filtering = bool(query.strip()) or (active_act != 'all')
        if is_filtering:
            act_desc = f' [{active_act.title()}]' if active_act != 'all' else ''
            self.lbl_filter_count.config(text=f'({match_count} match{"es" if match_count != 1 else ""}{act_desc})')
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
        if getattr(self, 'active_action_filter', 'all') != 'all':
            self._on_clear_filter()
            return 'break'
        self.on_window_close()
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
