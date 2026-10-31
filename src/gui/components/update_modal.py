"""Update notification modal dialog for FastMirror."""

from __future__ import annotations

import contextlib
import tkinter as tk
import webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from gui.components.base_modal import BaseModalDialog
from gui.icons import apply_icon, apply_window_icon
from gui.widgets import BadgeLabel, add_tooltip
from utils.constants import APP_VERSION
from utils.updater import ReleaseInfo


class UpdateModal(BaseModalDialog):
    """Modern modal dialog displaying release notes and one-click download buttons for app updates."""

    def __init__(self, parent: tk.Tk | tk.Toplevel | None, release_info: ReleaseInfo):
        self.release_info = release_info
        super().__init__(
            parent=parent,
            title=f'FastMirror — Update Available (v{release_info.version})',
            width=680,
            height=520,
            min_width=600,
            min_height=420,
            modal=False,
        )
        apply_window_icon(self.window)
        self._create_widgets()
        self._center_and_reveal(modal=False)

    def _create_widgets(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        # 1. Header Banner
        banner = ttk.Frame(self.window, padding=(16, 12, 16, 8))
        banner.grid(row=0, column=0, sticky='ew')
        banner.columnconfigure(0, weight=1)

        header_top = ttk.Frame(banner)
        header_top.pack(fill='x')

        lbl_title = ttk.Label(
            header_top,
            text='🚀 A New FastMirror Update is Available!',
            font=('Segoe UI', 12, 'bold'),
        )
        lbl_title.pack(side='left')

        badge_version = BadgeLabel(
            header_top,
            text=f'v{self.release_info.version}',
            variant='success',
            font=('Segoe UI', 9, 'bold'),
        )
        badge_version.pack(side='right')

        date_str = f'Released: {self.release_info.published_at}' if self.release_info.published_at else ''
        sub_text = f'Installed: v{APP_VERSION}  ➔  Latest: v{self.release_info.version}    {date_str}'
        lbl_sub = ttk.Label(
            banner,
            text=sub_text,
            font=('Segoe UI', 9),
            foreground='#555555',
        )
        lbl_sub.pack(anchor='w', pady=(4, 0))

        # 2. Release Notes Area
        body_frame = ttk.LabelFrame(self.window, text=' What’s New in This Release ', padding=10)
        body_frame.grid(row=1, column=0, sticky='nsew', padx=14, pady=(4, 8))
        body_frame.columnconfigure(0, weight=1)
        body_frame.rowconfigure(0, weight=1)

        txt_notes = ScrolledText(
            body_frame,
            wrap=tk.WORD,
            font=('Segoe UI', 9),
            relief='flat',
            padx=10,
            pady=8,
            background='#fafafa',
            foreground='#1e293b',
        )
        txt_notes.grid(row=0, column=0, sticky='nsew')

        raw_notes = self.release_info.body.strip() or 'No detailed release notes provided for this release.'
        txt_notes.insert(tk.END, raw_notes)
        txt_notes.configure(state='disabled')

        lbl_safe = ttk.Label(
            body_frame,
            text='ℹ️ Upgrading preserves 100% of your configurations, directory pairs, and mirror database.',
            font=('Segoe UI', 8, 'italic'),
            foreground='#666666',
        )
        lbl_safe.grid(row=1, column=0, sticky='w', pady=(6, 0))

        # 3. Bottom Action Bar
        bottom = ttk.Frame(self.window, padding=(14, 8, 14, 12))
        bottom.grid(row=2, column=0, sticky='ew')
        bottom.columnconfigure(0, weight=1)

        btn_github = ttk.Button(
            bottom,
            text='View on GitHub',
            command=self._open_github_release,
            width=16,
        )
        apply_icon(btn_github, 'document')
        add_tooltip(btn_github, 'Open the full GitHub release page in your default browser.')
        btn_github.pack(side='left')

        btn_box = ttk.Frame(bottom)
        btn_box.pack(side='right')

        if self.release_info.setup_download_url:
            self.btn_download_setup = ttk.Button(
                btn_box,
                text='Download Setup (.exe)',
                command=self._download_setup,
                style='Accent.TButton',
                width=22,
            )
            apply_icon(self.btn_download_setup, 'sync')
            add_tooltip(
                self.btn_download_setup,
                'Download the latest Windows Setup wizard (.exe) to perform an in-place upgrade.',
            )
            self.btn_download_setup.pack(side='left', padx=(0, 6))

        if self.release_info.portable_download_url:
            self.btn_download_portable = ttk.Button(
                btn_box,
                text='Portable (.zip)',
                command=self._download_portable,
                width=16,
            )
            apply_icon(self.btn_download_portable, 'archive')
            add_tooltip(self.btn_download_portable, 'Download the standalone portable edition (.zip).')
            self.btn_download_portable.pack(side='left', padx=(0, 6))

        self.btn_close = ttk.Button(
            btn_box,
            text='Close',
            command=self.on_close,
            width=10,
        )
        apply_icon(self.btn_close, 'check_circle')
        add_tooltip(self.btn_close, 'Close this update dialog.')
        self.btn_close.pack(side='left')

    def _download_setup(self):
        """Open the direct setup installer download URL in the user's default browser."""
        url = self.release_info.setup_download_url or self.release_info.html_url
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    def _download_portable(self):
        """Open the direct portable ZIP download URL in the user's default browser."""
        url = self.release_info.portable_download_url or self.release_info.html_url
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    def _open_github_release(self):
        """Open GitHub release page in the user's default browser."""
        with contextlib.suppress(Exception):
            webbrowser.open(self.release_info.html_url)
