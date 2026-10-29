"""Interactive confirmation popup for reviewing and selectively executing file sync operations."""

from __future__ import annotations

import contextlib
import os
import subprocess
import tkinter as tk
import winsound
from collections.abc import Callable
from tkinter import messagebox, ttk

from core.file import CstmPath
from gui.components.checkbox_treeview import CustomCheckboxTreeView
from gui.components.file_details_dialog import FileDetailsDialog
from gui.components.sync_tree_model import (
    FolderNode,
    _compact_trie,
    _extract_relative_folder_parts,
    _format_move_origin,
    get_file_category_group,
    get_file_type_badge,
)
from gui.icons import apply_icon, apply_window_icon, conceal_window, reveal_window
from gui.theme import FILTER_BTN_PALETTES
from gui.widgets import Action, FilterToggleButton, add_tooltip
from utils.logger import logger
from utils.utils import format_size

__all__ = [
    'FILTER_BTN_PALETTES',
    'ActionSelection',
    'CustomCheckboxTreeView',
    'FileDetailsDialog',
    'FilterToggleButton',
    'FolderNode',
    '_compact_trie',
    '_extract_relative_folder_parts',
    '_format_move_origin',
    'get_file_category_group',
    'get_file_type_badge',
]


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
        conceal_window(self.popup)
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

        # Smooth reveal after widgets and treeview are completely mapped and painted
        reveal_window(self.popup)

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
            pady=6,
        )
        banner_frame.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 4))
        banner_frame.grid_columnconfigure(0, weight=1)

        # Title & Subtitle
        title_box = tk.Frame(banner_frame, bg='SystemButtonFace')
        title_box.grid(row=0, column=0, sticky='w')

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
        self.lbl_stat_copy = self.action_buttons['copy']
        self.lbl_stat_move = self.action_buttons['move']
        self.lbl_stat_delete = self.action_buttons['delete']

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
