import contextlib
import tkinter as tk
import winsound
from collections.abc import Callable

import ttkwidgets

from core.file import CstmPath
from gui.widgets import Action
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
        self.on_stats_changed = on_stats_changed

        # Configure headers to preserve exact backward compatibility
        self['columns'] = self.custom_headers[1:]
        self.column('#0', width=220, minwidth=160)
        self.heading('#0', text=self.custom_headers[0])

        for column in self.custom_headers[1:]:
            self.heading(column, text=column.title())
            if 'date' in column:
                self.column(column, width=150, minwidth=120)
            elif 'size' in column:
                self.column(column, width=95, minwidth=75)
            else:
                self.column(column, width=320, minwidth=180)

        # Style tags for actions to provide clear visual cues
        self.tag_configure('copy_tag', background='#f6fff8')
        self.tag_configure('move_tag', background='#f0f7ff')
        self.tag_configure('delete_tag', background='#fff5f5')
        self.tag_configure('highlight_match', background='#fff59d')

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
            n_children = len(self.get_children(action_str))
            selected_number = len(selected_lines)
            action_enum = Action.from_str(action_str)
            action_data = self._data.get(action_enum, {})
            size_list = [action_data[x]['size in bytes'] for x in selected_lines if x in action_data]

            if not all(isinstance(size, int | float) for size in size_list):
                raise TypeError('All elements in size_list must be numbers')

            selected_size = format_size(sum(size_list))  # type: ignore[arg-type]
            # Maintain exact substring format expected by existing tests: '<action> <size> (<X> of <Y>)'
            self.item(action_str, text=f'{action_str} {selected_size} ({selected_number} of {n_children})')

        if self.on_stats_changed:
            self.on_stats_changed()

    def add_file_lists(
        self,
        file_lists: dict[Action, list[tuple[CstmPath, CstmPath]] | list[CstmPath]],
        default_active: list[Action] | None = None,
    ):
        if default_active is None:
            default_active = []

        self._item_actions.clear()

        for action, file_list in file_lists.items():
            self._data[action] = {}
            for file_entry in file_list:
                args = (None, file_entry) if isinstance(file_entry, CstmPath) else file_entry
                values = self.get_row(*args)
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
            action_style_tag = f'{action.value}_tag'
            for key, row in rows.items():
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

    @staticmethod
    def get_row(source: CstmPath | None, target: CstmPath | None) -> dict[str, float | str]:
        def _extract_meta(p: CstmPath | None) -> tuple[str, str, int | float, str]:
            if p is None:
                return ('', '0', 0, '')
            p_str = str(p)
            with contextlib.suppress(Exception):
                st = getattr(p, 'stats', None)
                if st is not None:
                    bytes_val = st.st_size
                    size_str = format_size(bytes_val)
                    mtime_str = p.to_date_str(st.st_mtime) if hasattr(p, 'to_date_str') else str(st.st_mtime)
                    return (p_str, size_str, bytes_val, mtime_str)

            size_str = '0'
            bytes_val = 0
            mtime_str = ''
            if hasattr(p, 'get_st_size'):
                with contextlib.suppress(Exception):
                    size_str = str(p.get_st_size(as_str=True))
                    bytes_val = p.get_st_size(as_str=False)
            if hasattr(p, 'get_st_mtime'):
                with contextlib.suppress(Exception):
                    mtime_str = str(p.get_st_mtime(as_date_str=True))
            return (p_str, size_str, bytes_val, mtime_str)

        src_str, src_size_str, src_bytes, src_mtime_str = _extract_meta(source)
        tgt_str, tgt_size_str, tgt_bytes, tgt_mtime_str = _extract_meta(target)
        size_bytes = src_bytes if source is not None else tgt_bytes

        return {
            'source': src_str,
            'target': tgt_str,
            'size (source)': src_size_str,
            'size (target)': tgt_size_str,
            'modification date (source)': src_mtime_str,
            'modification date (target)': tgt_mtime_str,
            'size in bytes': size_bytes,
        }

    def select_all(self):
        """Check all group and child items that contain files."""
        for group in self.get_children(''):
            if self.get_children(group):
                self.change_state(group, 'checked')
        self.refresh_group_stats()

    def deselect_all(self):
        """Uncheck all group and child items."""
        for group in self.get_children(''):
            self.change_state(group, 'unchecked')
        self.refresh_group_stats()

    def uncheck_action(self, action: Action):
        """Uncheck all items under a specific action (e.g. Action.DELETE)."""
        if action.value in self.get_children(''):
            self.change_state(action.value, 'unchecked')
        self.refresh_group_stats()


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

        # Create window (withdrawn during creation to avoid multiple repaint events)
        self.popup = tk.Toplevel(self.root_gui)
        self.popup.withdraw()
        self.popup.title('Automatic Backup - Confirm Actions')
        self.popup.minsize(920, 580)
        self.popup.transient(self.root_gui)
        self.popup.protocol('WM_DELETE_WINDOW', self.button_cancel_click)

        # Center window over root or screen
        self._center_window(width=980, height=640)

        # Keyboard shortcuts
        self.popup.bind('<Return>', lambda e: self.button_save_click())
        self.popup.bind('<Escape>', lambda e: self.button_cancel_click())

        # Modal grab (safe fallback for headless / tests)
        with contextlib.suppress(Exception):
            self.popup.grab_set()

        self.create_widgets()
        self.popup.deiconify()

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

        # 2. Toolbar (Search, Select All, Deselect All, Uncheck Deletions)
        self._create_toolbar()

        # 3. Table with scrollbars
        self.create_table()

        # 4. Bottom Path Inspector & Dialog Action Buttons
        self._create_bottom_bar()

        with contextlib.suppress(Exception):
            winsound.PlaySound('SystemQuestion', winsound.SND_ALIAS)

    def _create_summary_banner(self):
        banner_frame = tk.Frame(self.popup, bg='#f8f9fa', bd=1, relief='solid', padx=12, pady=8)
        banner_frame.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 4))
        banner_frame.grid_columnconfigure(3, weight=1)

        # Title & Subtitle
        title_box = tk.Frame(banner_frame, bg='#f8f9fa')
        title_box.grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 6))

        lbl_title = tk.Label(
            title_box,
            text='Review Synchronization Actions',
            font=('Segoe UI', 11, 'bold'),
            bg='#f8f9fa',
            fg='#212529',
        )
        lbl_title.pack(anchor='w')

        lbl_desc = tk.Label(
            title_box,
            text='Select or unselect specific files to customize which actions are executed.',
            font=('Segoe UI', 8),
            bg='#f8f9fa',
            fg='#6c757d',
        )
        lbl_desc.pack(anchor='w')

        # Category Stat Badges
        badge_frame = tk.Frame(banner_frame, bg='#f8f9fa')
        badge_frame.grid(row=1, column=0, columnspan=4, sticky='w')

        self.lbl_stat_copy = tk.Label(
            badge_frame,
            text='🟢 Copy: 0 files',
            font=('Segoe UI', 9),
            bg='#e8f5e9',
            fg='#2e7d32',
            padx=8,
            pady=3,
            relief='groove',
        )
        self.lbl_stat_copy.pack(side='left', padx=(0, 6))

        self.lbl_stat_move = tk.Label(
            badge_frame,
            text='🔵 Move: 0 files',
            font=('Segoe UI', 9),
            bg='#e3f2fd',
            fg='#1565c0',
            padx=8,
            pady=3,
            relief='groove',
        )
        self.lbl_stat_move.pack(side='left', padx=(0, 6))

        self.lbl_stat_delete = tk.Label(
            badge_frame,
            text='🔴 Delete: 0 files',
            font=('Segoe UI', 9),
            bg='#ffebee',
            fg='#c62828',
            padx=8,
            pady=3,
            relief='groove',
        )
        self.lbl_stat_delete.pack(side='left', padx=(0, 6))

        self.lbl_delete_alert = tk.Label(
            badge_frame,
            text='⚠️ Deletions are pending!',
            font=('Segoe UI', 9, 'bold'),
            bg='#fff3e0',
            fg='#e65100',
            padx=8,
            pady=3,
            relief='groove',
        )

    def _create_toolbar(self):
        toolbar_frame = tk.Frame(self.popup, padx=8, pady=4)
        toolbar_frame.grid(row=1, column=0, sticky='ew')

        # Select All / Deselect All
        btn_select_all = tk.Button(
            toolbar_frame,
            text='Select All',
            command=lambda: self.tree.select_all(),
            padx=6,
            pady=2,
            font=('Segoe UI', 8),
        )
        btn_select_all.pack(side='left', padx=(0, 4))

        btn_deselect_all = tk.Button(
            toolbar_frame,
            text='Deselect All',
            command=lambda: self.tree.deselect_all(),
            padx=6,
            pady=2,
            font=('Segoe UI', 8),
        )
        btn_deselect_all.pack(side='left', padx=(0, 6))

        # Safety button: Uncheck all deletions
        btn_safe_delete = tk.Button(
            toolbar_frame,
            text='🛡️ Uncheck All Deletions',
            command=lambda: self.tree.uncheck_action(Action.DELETE),
            padx=8,
            pady=2,
            font=('Segoe UI', 8, 'bold'),
            fg='#b71c1c',
        )
        btn_safe_delete.pack(side='left', padx=(0, 12))

        # Filter Entry
        lbl_filter = tk.Label(toolbar_frame, text='Filter:', font=('Segoe UI', 8))
        lbl_filter.pack(side='left', padx=(0, 4))

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self._on_filter_changed)
        self.entry_filter = tk.Entry(toolbar_frame, textvariable=self.filter_var, width=28, font=('Segoe UI', 8))
        self.entry_filter.pack(side='left', padx=(0, 4))

        btn_clear_filter = tk.Button(
            toolbar_frame,
            text='✕',
            command=lambda: self.filter_var.set(''),
            padx=4,
            pady=1,
            font=('Segoe UI', 7),
        )
        btn_clear_filter.pack(side='left', padx=(0, 6))

        self.lbl_filter_count = tk.Label(toolbar_frame, text='', font=('Segoe UI', 8), fg='#666666')
        self.lbl_filter_count.pack(side='left')

    def create_table(self):
        frame_table = tk.Frame(self.popup)
        frame_table.grid(row=2, column=0, sticky='nsew', padx=8, pady=4)
        frame_table.grid_rowconfigure(0, weight=1)
        frame_table.grid_columnconfigure(0, weight=1)

        self.tree = CustomCheckboxTreeView(frame_table, height=22, on_stats_changed=self._update_banner_stats)
        self.tree.grid(row=0, column=0, sticky='nsew')

        # Add vertical scrollbar
        vscroll = tk.Scrollbar(frame_table, orient='vertical', command=self.tree.yview)
        vscroll.grid(row=0, column=1, sticky='ns')

        # Add horizontal scrollbar
        hscroll = tk.Scrollbar(frame_table, orient='horizontal', command=self.tree.xview)
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
        self.tree.refresh_group_stats()

    def _create_bottom_bar(self):
        bottom_frame = tk.Frame(self.popup, padx=8, pady=6)
        bottom_frame.grid(row=3, column=0, sticky='ew')
        bottom_frame.grid_columnconfigure(0, weight=1)

        # Path Inspector panel
        inspector_frame = tk.LabelFrame(
            bottom_frame, text='Selected Item Details', font=('Segoe UI', 8), padx=8, pady=4
        )
        inspector_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        inspector_frame.grid_columnconfigure(1, weight=1)

        lbl_s = tk.Label(inspector_frame, text='Source:', font=('Segoe UI', 8, 'bold'), anchor='w')
        lbl_s.grid(row=0, column=0, sticky='w')
        self.lbl_inspector_source = tk.Label(
            inspector_frame, text='(select an item to view path)', font=('Segoe UI', 8), fg='#333333', anchor='w'
        )
        self.lbl_inspector_source.grid(row=0, column=1, sticky='ew', padx=(4, 0))

        lbl_t = tk.Label(inspector_frame, text='Target:', font=('Segoe UI', 8, 'bold'), anchor='w')
        lbl_t.grid(row=1, column=0, sticky='w')
        self.lbl_inspector_target = tk.Label(inspector_frame, text='-', font=('Segoe UI', 8), fg='#333333', anchor='w')
        self.lbl_inspector_target.grid(row=1, column=1, sticky='ew', padx=(4, 0))

        # Bottom Buttons
        btn_box = tk.Frame(bottom_frame)
        btn_box.grid(row=1, column=1, sticky='e')

        self.button_save = tk.Button(
            btn_box,
            text='Save and continue',
            command=self.button_save_click,
            font=('Segoe UI', 9, 'bold'),
            bg='#2e7d32',
            fg='white',
            padx=14,
            pady=4,
        )
        self.button_save.pack(side='right', padx=(6, 0))

        self.button_cancel = tk.Button(
            btn_box,
            text='Cancel',
            command=self.button_cancel_click,
            font=('Segoe UI', 9),
            padx=12,
            pady=4,
        )
        self.button_cancel.pack(side='right')

    def _on_item_selected(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        item_info = getattr(self.tree, '_item_actions', {}).get(item_id)
        if item_info is not None:
            _, source_path, target_path = item_info
            self.lbl_inspector_source.config(text=source_path if source_path else '(none)')
            self.lbl_inspector_target.config(text=target_path if target_path else '(none)')
        elif '::' in item_id:
            parts = item_id.split('::', 2)
            if len(parts) >= 3:
                source_path = parts[1] if parts[1] else '(none)'
                target_path = parts[2] if parts[2] else '(none)'
                self.lbl_inspector_source.config(text=source_path)
                self.lbl_inspector_target.config(text=target_path)
        else:
            self.lbl_inspector_source.config(text=f'Group: {item_id.upper()}')
            self.lbl_inspector_target.config(text='-')

    def _update_banner_stats(self):
        cached = getattr(self.tree, '_cached_checked_by_action', None)
        if cached is not None:
            copy_lines = cached.get('copy', [])
            move_lines = cached.get('move', [])
            del_lines = cached.get('delete', [])
        else:
            checked = self.tree.get_checked()
            copy_lines = [x for x in checked if 'copy::' in x]
            move_lines = [x for x in checked if 'move::' in x]
            del_lines = [x for x in checked if 'delete::' in x]

        self.lbl_stat_copy.config(text=f'🟢 Copy: {len(copy_lines)} files')
        self.lbl_stat_move.config(text=f'🔵 Move: {len(move_lines)} files')
        self.lbl_stat_delete.config(text=f'🔴 Delete: {len(del_lines)} files')

        if len(del_lines) > 0:
            self.lbl_delete_alert.pack(side='left', padx=(6, 0))
        else:
            self.lbl_delete_alert.pack_forget()

    def _on_filter_changed(self, *args):
        query = self.filter_var.get().strip().lower()
        first_match = None
        match_count = 0

        for group in self.tree.get_children(''):
            children = self.tree.get_children(group)
            group_matched = False
            for child in children:
                matches = bool(query and query in child.lower())
                curr_tags = list(self.tree.item(child, 'tags'))
                if matches:
                    match_count += 1
                    group_matched = True
                    if first_match is None:
                        first_match = child
                    if 'highlight_match' not in curr_tags:
                        curr_tags.append('highlight_match')
                        self.tree.item(child, tags=tuple(curr_tags))
                else:
                    if 'highlight_match' in curr_tags:
                        curr_tags.remove('highlight_match')
                        self.tree.item(child, tags=tuple(curr_tags))

            if query and group_matched:
                self.tree.item(group, open=True)

        if query:
            self.lbl_filter_count.config(text=f'({match_count} match{"es" if match_count != 1 else ""})')
            if first_match is not None:
                self.tree.see(first_match)
                self.tree.selection_set(first_match)
                self._on_item_selected(None)
        else:
            self.lbl_filter_count.config(text='')

    def button_save_click(self):
        if self.finished:
            return
        logger.info('Saving selection of actions')
        self.finished = True
        self.proceed = True

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
                if group == 'copy':
                    self.files_requested_to_copy.append((parts[1], parts[2]))
                elif group == 'move':
                    self.files_requested_to_move.append((parts[1], parts[2]))
                elif group == 'delete':
                    self.files_requested_to_delete.append(parts[2])

        with contextlib.suppress(Exception):
            self.popup.destroy()
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
        if self.on_close_callback:
            self.on_close_callback()

    def get_outputs(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
        return self.files_requested_to_copy, self.files_requested_to_move, self.files_requested_to_delete
