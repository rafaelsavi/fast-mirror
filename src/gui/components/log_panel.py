import datetime
import os
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk

from gui.enums import TkinterCfgState
from gui.icons import apply_icon
from gui.widgets import BadgeLabel, LogLevels, TextLogger, add_tooltip
from utils.logger import logger


class LogPanel(ttk.LabelFrame):
    """Panel hosting the real-time activity log viewer, level filters, live search, and auto-scroll controls."""

    def __init__(
        self,
        master: tk.Misc,
        log_levels: LogLevels | None = None,
        toggle_auto_scroll: tk.BooleanVar | None = None,
        on_update_log_levels: Callable[[], None] | None = None,
        on_toggle_auto_scroll: Callable[[], None] | None = None,
        text_logger: TextLogger | None = None,
        **kwargs,
    ):
        super().__init__(master, text=' Activity & Operation Log ', **kwargs)

        self.log_levels = log_levels or LogLevels()
        self.toggle_auto_scroll = toggle_auto_scroll or tk.BooleanVar(value=True)
        self.on_update_log_levels = on_update_log_levels
        self.on_toggle_auto_scroll = on_toggle_auto_scroll

        self.search_var = tk.StringVar()
        self.search_count_var = tk.StringVar(value='')
        self._search_matches: list[str] = []
        self._current_match_idx: int = -1

        self._create_widgets(text_logger)
        self.search_var.trace_add('write', self._on_search_query_changed)

    def _create_widgets(self, text_logger: TextLogger | None):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Toolbar Row 0: Log Level Filters on left, Copy/Clear/Auto-scroll on right
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky='ew', padx=8, pady=(4, 4))

        lbl_filter = ttk.Label(toolbar, text='Levels:', font=('Segoe UI', 9, 'bold'))
        lbl_filter.pack(side='left', padx=(0, 6))

        self.frame_buttons_level = ttk.Frame(toolbar)
        self.frame_buttons_level.pack(side='left')

        self.check_box_log_level: dict[str, ttk.Checkbutton] = {}
        for level in self.log_levels.options:
            cb = ttk.Checkbutton(
                self.frame_buttons_level,
                text=level,
                variable=self.log_levels.checkboxes[level],
                command=self._handle_level_change,
            )
            cb.pack(side='left', padx=4)
            self.check_box_log_level[level] = cb

        # Right side: Auto-scroll, Clear, Copy, Export, and Open Folder
        self.checkbox_auto_scroll = ttk.Checkbutton(
            toolbar,
            text='Auto-scroll',
            variable=self.toggle_auto_scroll,
            command=self._handle_auto_scroll_toggle,
        )
        self.checkbox_auto_scroll.pack(side='right', padx=(6, 2))

        self.btn_clear = ttk.Button(
            toolbar,
            text='Clear',
            command=self.clear_log,
            width=8,
        )
        add_tooltip(self.btn_clear, 'Clear all activity log messages')
        self.btn_clear.pack(side='right', padx=2)

        self.btn_copy = ttk.Button(
            toolbar,
            text='Copy',
            command=self.copy_log,
            width=10,
        )
        apply_icon(self.btn_copy, 'copy')
        self.btn_copy.pack(side='right', padx=2)

        self.btn_export = ttk.Button(
            toolbar,
            text='Export...',
            command=self.export_log,
            width=11,
        )
        apply_icon(self.btn_export, 'save')
        self.btn_export.pack(side='right', padx=2)

        self.btn_open_folder = ttk.Button(
            toolbar,
            text='Log Folder',
            command=self.open_log_folder,
            width=12,
        )
        apply_icon(self.btn_open_folder, 'folder')
        self.btn_open_folder.pack(side='right', padx=2)

        # Toolbar Row 1: Search & Filter inside Log Console
        search_bar = ttk.Frame(self)
        search_bar.grid(row=1, column=0, sticky='ew', padx=8, pady=(0, 6))

        lbl_find = ttk.Label(search_bar, text='Find in log:', font=('Segoe UI', 9))
        lbl_find.pack(side='left', padx=(0, 4))

        self.entry_search = ttk.Entry(search_bar, textvariable=self.search_var, width=32)
        self.entry_search.pack(side='left', padx=(0, 2))

        btn_clear_search = ttk.Button(
            search_bar,
            text='✕',
            width=3,
            command=self._clear_search,
        )
        btn_clear_search.pack(side='left', padx=(0, 4))

        btn_prev = ttk.Button(
            search_bar,
            text='▲',
            width=3,
            command=self._prev_match,
        )
        btn_prev.pack(side='left', padx=1)

        btn_next = ttk.Button(
            search_bar,
            text='▼',
            width=3,
            command=self._next_match,
        )
        btn_next.pack(side='left', padx=1)

        lbl_count = ttk.Label(
            search_bar,
            textvariable=self.search_count_var,
            font=('Segoe UI', 9),
            foreground='#555555',
        )
        lbl_count.pack(side='left', padx=(6, 0))

        # Severity stats on the right side of search bar (styled pill badges)
        self.stats_frame = ttk.Frame(search_bar)
        self.stats_frame.pack(side='right', padx=(0, 2))

        self.lbl_stat_info = BadgeLabel(
            self.stats_frame,
            text='Info: 0',
            variant='neutral',
        )
        self.lbl_stat_info.pack(side='left', padx=3)
        add_tooltip(self.lbl_stat_info, 'Total number of informational log messages.')

        self.lbl_stat_warning = BadgeLabel(
            self.stats_frame,
            text='Warnings: 0',
            variant='neutral',
            interactive=True,
        )
        self.lbl_stat_warning.pack(side='left', padx=3)
        self.lbl_stat_warning.bind('<Button-1>', lambda _e: self.jump_to_next_warning())
        add_tooltip(self.lbl_stat_warning, 'Click to navigate to the next warning in the log.')

        self.lbl_stat_error = BadgeLabel(
            self.stats_frame,
            text='Errors: 0',
            variant='neutral',
            interactive=True,
        )
        self.lbl_stat_error.pack(side='left', padx=3)
        self.lbl_stat_error.bind('<Button-1>', lambda _e: self.jump_to_next_error())
        add_tooltip(self.lbl_stat_error, 'Click to navigate to the next error or critical issue in the log.')

        # Main Log Text View (Row 2)
        if text_logger is not None:
            self.text_logger = text_logger
            self.text_logger.on_log_updated = self.update_stats
        else:
            self.text_logger = TextLogger(
                self, state=TkinterCfgState.DISABLED.value, height=22, width=90, on_log_updated=self.update_stats
            )
        self.text_logger.set_log_levels(self.log_levels.get())
        self.text_logger.grid(row=2, column=0, sticky='nsew', padx=8, pady=(0, 8))
        self.update_stats()

    def _handle_level_change(self):
        self.text_logger.set_log_levels(self.log_levels.get())
        if self.on_update_log_levels:
            self.on_update_log_levels()
        if self.toggle_auto_scroll.get():
            self.text_logger.yview(tk.END)
        self._on_search_query_changed()

    def _handle_auto_scroll_toggle(self):
        if self.on_toggle_auto_scroll:
            self.on_toggle_auto_scroll()
        if self.toggle_auto_scroll.get():
            self.text_logger.yview(tk.END)

    def _clear_search(self):
        self.search_var.set('')

    def _on_search_query_changed(self, *args):
        query = self.search_var.get().strip()
        self.text_logger.tag_remove('SEARCH_MATCH', '1.0', tk.END)
        self.text_logger.tag_remove('SEARCH_CURRENT', '1.0', tk.END)
        self._search_matches.clear()
        self._current_match_idx = -1

        if not query:
            self.search_count_var.set('')
            return

        pos = '1.0'
        while True:
            pos = self.text_logger.search(query, pos, stopindex=tk.END, nocase=True)
            if not pos:
                break
            end_pos = f'{pos}+{len(query)}c'
            self.text_logger.tag_add('SEARCH_MATCH', pos, end_pos)
            self._search_matches.append(pos)
            pos = end_pos

        count = len(self._search_matches)
        if count > 0:
            self._current_match_idx = 0
            self._highlight_current_match()
            self.search_count_var.set(f'1 of {count} match{"es" if count != 1 else ""}')
        else:
            self.search_count_var.set('0 matches')

    def _highlight_current_match(self):
        if 0 <= self._current_match_idx < len(self._search_matches):
            self.text_logger.tag_remove('SEARCH_CURRENT', '1.0', tk.END)
            pos = self._search_matches[self._current_match_idx]
            query = self.search_var.get().strip()
            end_pos = f'{pos}+{len(query)}c'
            self.text_logger.tag_add('SEARCH_CURRENT', pos, end_pos)
            self.text_logger.see(pos)
            count = len(self._search_matches)
            self.search_count_var.set(f'{self._current_match_idx + 1} of {count} match{"es" if count != 1 else ""}')

    def _next_match(self):
        if self._search_matches:
            self._current_match_idx = (self._current_match_idx + 1) % len(self._search_matches)
            self._highlight_current_match()

    def _prev_match(self):
        if self._search_matches:
            self._current_match_idx = (self._current_match_idx - 1) % len(self._search_matches)
            self._highlight_current_match()

    def copy_log(self):
        content = self.text_logger.get('1.0', tk.END)
        if content.strip():
            self.clipboard_clear()
            self.clipboard_append(content)
            apply_icon(self.btn_copy, 'check_circle', text='Copied!')
            self.after(1500, lambda: apply_icon(self.btn_copy, 'copy', text='Copy'))

    def export_log(self):
        """Export current log content to a user-selected text file."""
        content = self.text_logger.get('1.0', tk.END)
        if not content.strip():
            messagebox.showinfo('Export Log', 'The log is currently empty.')
            return

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        default_filename = f'automatic_backup_log_{timestamp}.txt'
        dest = filedialog.asksaveasfilename(
            title='Export Log to File',
            initialfile=default_filename,
            defaultextension='.txt',
            filetypes=[('Text Files', '*.txt'), ('All Files', '*.*')],
        )
        if dest:
            try:
                with open(dest, 'w', encoding='utf-8') as f:
                    f.write(content)
                messagebox.showinfo('Export Log', f'Log successfully exported to:\n{dest}')
            except Exception as e:
                messagebox.showerror('Export Error', f'Failed to export log: {e}')

    def open_log_folder(self):
        """Open the application log directory in Windows File Explorer."""
        log_dir = logger.log_dir
        try:
            os.makedirs(log_dir, exist_ok=True)
            if hasattr(os, 'startfile'):
                os.startfile(log_dir)
            else:
                import subprocess

                subprocess.Popen(['explorer', log_dir])
        except Exception as e:
            messagebox.showerror('Log Folder Error', f'Could not open log folder: {e}')

    def clear_log(self, confirm: bool = True):
        """Clear all messages from the log console, prompting for user confirmation if logs exist."""
        if not self.text_logger.lines and not self.text_logger.get('1.0', tk.END).strip():
            return

        if confirm and not messagebox.askyesno(
            'Clear Log',
            'Are you sure you want to clear the activity log?',
            parent=self.winfo_toplevel(),
        ):
            return

        self.text_logger.configure(state=TkinterCfgState.NORMAL.value)
        self.text_logger.delete('1.0', tk.END)
        self.text_logger.lines.clear()
        self.text_logger.reset_counts()
        self.text_logger.configure(state=TkinterCfgState.DISABLED.value)
        self._on_search_query_changed()
        self.update_stats()

    def update_stats(self):
        """Update live log severity count pills on search toolbar."""
        if not hasattr(self, 'lbl_stat_info'):
            return
        counts = self.text_logger.level_counts
        info_count = counts.get('INFO', 0)
        warn_count = counts.get('WARNING', 0)
        error_count = counts.get('ERROR', 0) + counts.get('CRITICAL', 0)

        # Info badge
        if info_count > 0:
            self.lbl_stat_info.set_variant('info', text=f'Info: {info_count:,}', is_bold=True)
        else:
            self.lbl_stat_info.set_variant('neutral', text='Info: 0', is_bold=False)

        # Warning badge
        if warn_count > 0:
            self.lbl_stat_warning.set_variant('warning', text=f'⚠️ Warnings: {warn_count:,}', is_bold=True)
        else:
            self.lbl_stat_warning.set_variant('neutral', text='Warnings: 0', is_bold=False)

        # Error badge
        if error_count > 0:
            self.lbl_stat_error.set_variant('error', text=f'❌ Errors: {error_count:,}', is_bold=True)
        else:
            self.lbl_stat_error.set_variant('neutral', text='Errors: 0', is_bold=False)

    def jump_to_next_warning(self):
        """Navigate and scroll to the next warning entry in the log."""
        if 'WARNING' not in self.log_levels.get():
            self.log_levels.checkboxes['WARNING'].set(True)
            self._handle_level_change()
        self.text_logger.jump_to_next_tag('WARNING')

    def jump_to_next_error(self):
        """Navigate and scroll to the next error or critical entry in the log."""
        needed_levels = [lvl for lvl in ('ERROR', 'CRITICAL') if lvl not in self.log_levels.get()]
        if needed_levels:
            for lvl in needed_levels:
                self.log_levels.checkboxes[lvl].set(True)
            self._handle_level_change()
        self.text_logger.jump_to_next_tag(('ERROR', 'CRITICAL'))

    def apply_theme(self, theme_name: str = 'light'):
        """Apply clean light or dark theme styling to text logger."""
        if theme_name == 'dark':
            self.text_logger.configure(
                bg='#1e1e1e',
                fg='#d4d4d4',
                insertbackground='#ffffff',
                selectbackground='#264f78',
            )
            self.text_logger.tag_config('DEBUG', foreground='#808080')
            self.text_logger.tag_config('INFO', foreground='#d4d4d4')
            self.text_logger.tag_config('WARNING', foreground='#e5c07b')
            self.text_logger.tag_config('ERROR', foreground='#f44747')
            self.text_logger.tag_config('CRITICAL', foreground='#f44747', underline=True)
            self.text_logger.tag_config('TAG_JUMP_HIGHLIGHT', background='#7c2d12')
            self.text_logger.tag_config('SEARCH_MATCH', background='#613214', foreground='#ffffff')
            self.text_logger.tag_config('SEARCH_CURRENT', background='#e5a158', foreground='#000000')
        else:
            self.text_logger.configure(
                bg='#ffffff',
                fg='#1c1c1c',
                insertbackground='#000000',
                selectbackground='#b0c4de',
            )
            self.text_logger.tag_config('DEBUG', foreground='gray')
            self.text_logger.tag_config('INFO', foreground='black')
            self.text_logger.tag_config('WARNING', foreground='orange')
            self.text_logger.tag_config('ERROR', foreground='red')
            self.text_logger.tag_config('CRITICAL', foreground='red', underline=True)
            self.text_logger.tag_config('TAG_JUMP_HIGHLIGHT', background='#fed7aa')
            self.text_logger.tag_config('SEARCH_MATCH', background='#fff3bf', foreground='#000000')
            self.text_logger.tag_config('SEARCH_CURRENT', background='#ff922b', foreground='#ffffff')
