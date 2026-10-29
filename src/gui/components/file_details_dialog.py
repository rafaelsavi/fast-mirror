"""Detailed file properties and side-by-side comparison modal dialog."""

from __future__ import annotations

import contextlib
import os
import subprocess
import tkinter as tk
from tkinter import ttk
from typing import Any

from gui.components.sync_tree_model import get_file_type_badge
from gui.icons import apply_icon, apply_window_icon, conceal_window, reveal_window
from gui.widgets import Action, BadgeLabel
from utils.logger import logger
from utils.utils import format_size


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
        conceal_window(self.dialog)
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

        reveal_window(self.dialog)
        with contextlib.suppress(Exception):
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
