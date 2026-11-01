"""Update notification modal dialog for FastMirror."""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from gui.components.base_modal import BaseModalDialog
from gui.icons import apply_icon, apply_window_icon
from gui.widgets import BadgeLabel, add_tooltip
from utils.constants import APP_VERSION
from utils.logger import logger
from utils.single_instance import release_single_instance
from utils.updater import ReleaseInfo, download_installer_async, get_default_installer_download_path


class UpdateModal(BaseModalDialog):
    """
    Modern modal dialog displaying release notes and seamless update installation.

    Supports:
    1. One-click background installer download with live progress tracking.
    2. Automated clean application shutdown and installer launch ("Restart & Install Now").
    3. Browser download fallback with clear guidance and an instant "Close FastMirror" action.
    """

    def __init__(self, parent: tk.Tk | tk.Toplevel | None, release_info: ReleaseInfo):
        self.release_info = release_info
        self.cancel_download_event = threading.Event()
        self.downloaded_installer_path: str | None = None
        self._is_downloading = False

        super().__init__(
            parent=parent,
            title=f'FastMirror — Update Available (v{release_info.version})',
            width=700,
            height=560,
            min_width=620,
            min_height=460,
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
        body_frame.grid(row=1, column=0, sticky='nsew', padx=14, pady=(4, 6))
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

        # 3. Progress and Upgrade Status Frame
        self.progress_frame = ttk.Frame(self.window, padding=(14, 2, 14, 4))
        self.progress_frame.grid(row=2, column=0, sticky='ew')
        self.progress_frame.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(self.progress_frame, orient='horizontal', mode='determinate')
        self.progress_bar.grid(row=0, column=0, sticky='ew', pady=(0, 4))

        self.lbl_progress_status = ttk.Label(
            self.progress_frame,
            text='',
            font=('Segoe UI', 9),
            foreground='#1e293b',
        )
        self.lbl_progress_status.grid(row=1, column=0, sticky='w')

        # Hide progress elements initially until download is triggered
        self.progress_bar.grid_remove()
        self.lbl_progress_status.grid_remove()

        # 4. Bottom Action Bar
        bottom = ttk.Frame(self.window, padding=(14, 8, 14, 12))
        bottom.grid(row=3, column=0, sticky='ew')
        bottom.columnconfigure(0, weight=1)

        btn_github = ttk.Button(
            bottom,
            text='View on GitHub',
            command=self._open_github_release,
            width=15,
        )
        apply_icon(btn_github, 'document')
        add_tooltip(btn_github, 'Open the full GitHub release page in your default browser.')
        btn_github.pack(side='left')

        btn_box = ttk.Frame(bottom)
        btn_box.pack(side='right')

        if self.release_info.setup_download_url:
            self.btn_action_setup = ttk.Button(
                btn_box,
                text='Update & Restart',
                command=self._start_in_app_update,
                style='Accent.TButton',
                width=18,
            )
            apply_icon(self.btn_action_setup, 'sync')
            add_tooltip(
                self.btn_action_setup,
                'Download the update in the background, close FastMirror cleanly, and launch the installer.',
            )
            self.btn_action_setup.pack(side='left', padx=(0, 6))
            self.btn_download_setup = self.btn_action_setup  # Backward compatibility alias

            self.btn_browser = ttk.Button(
                btn_box,
                text='In Browser',
                command=self._download_via_browser,
                width=12,
            )
            apply_icon(self.btn_browser, 'folder')
            add_tooltip(
                self.btn_browser,
                'Open the setup installer download URL in your web browser instead of updating in-app.',
            )
            self.btn_browser.pack(side='left', padx=(0, 6))

        if self.release_info.portable_download_url:
            self.btn_download_portable = ttk.Button(
                btn_box,
                text='Portable (.zip)',
                command=self._download_portable,
                width=14,
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

    def _start_in_app_update(self):
        """Initiate background download of the setup installer with real-time UI progress."""
        if not self.release_info.setup_download_url:
            return

        self._is_downloading = True
        self.cancel_download_event.clear()

        # Reveal progress UI
        self.progress_bar.grid()
        self.lbl_progress_status.grid()
        self.progress_bar['value'] = 0
        self.lbl_progress_status.config(
            text='Connecting to GitHub Releases...',
            foreground='#1e293b',
        )

        self.btn_action_setup.config(state='disabled', text='Downloading...')
        self.btn_close.config(text='Cancel')

        target_path = get_default_installer_download_path(self.release_info.version)
        download_installer_async(
            url=self.release_info.setup_download_url,
            target_path=target_path,
            on_progress=self._on_download_progress,
            on_complete=self._on_download_complete,
            cancel_event=self.cancel_download_event,
        )

    def _on_download_progress(self, downloaded: int, total: int | None):
        """Handle download progress update on the main Tkinter thread."""

        def _update():
            if not self.window.winfo_exists():
                return
            if total and total > 0:
                pct = min(100.0, (downloaded / total) * 100.0)
                self.progress_bar['value'] = pct
                mb_down = downloaded / (1024 * 1024)
                mb_tot = total / (1024 * 1024)
                self.lbl_progress_status.config(
                    text=f'Downloading update: {mb_down:.1f} MB / {mb_tot:.1f} MB ({pct:.0f}%)'
                )
            else:
                mb_down = downloaded / (1024 * 1024)
                self.lbl_progress_status.config(text=f'Downloading update: {mb_down:.1f} MB')

        self.window.after(0, _update)

    def _on_download_complete(self, target_path: str | None, err: str | None):
        """Handle download conclusion on the main Tkinter thread."""

        def _finish():
            if not self.window.winfo_exists():
                return

            self._is_downloading = False
            self.btn_close.config(text='Close')

            if target_path:
                self.downloaded_installer_path = target_path
                self.progress_bar['value'] = 100
                self.lbl_progress_status.config(
                    text='✅ Update downloaded! FastMirror will close cleanly and launch setup.',
                    foreground='#15803d',
                )
                self.btn_action_setup.config(
                    state='normal',
                    text='Restart & Install Now',
                    command=self._launch_installer_and_exit,
                )
                apply_icon(self.btn_action_setup, 'check_circle')
                add_tooltip(
                    self.btn_action_setup,
                    'Close FastMirror, release locks, and launch the installer wizard.',
                )
            else:
                self.lbl_progress_status.config(
                    text=f'Download failed: {err or "Unknown error"}. You can download via browser instead.',
                    foreground='#b91c1c',
                )
                self.btn_action_setup.config(
                    state='normal',
                    text='Retry Download',
                    command=self._start_in_app_update,
                )

        self.window.after(0, _finish)

    def _launch_installer_and_exit(self):
        """Launch the downloaded installer process and cleanly finalize/quit FastMirror."""
        if not self.downloaded_installer_path:
            return

        installer_path = self.downloaded_installer_path
        logger.info(f'Launching installer upgrade: {installer_path}')

        try:
            # Spawn independent installer wizard
            subprocess.Popen([installer_path])
        except Exception as e:
            logger.error(f'Failed to launch installer executable: {e}')
            self.lbl_progress_status.config(
                text=f'Could not launch installer: {e}',
                foreground='#b91c1c',
            )
            return

        # Explicitly release the Win32 single-instance mutex so the installer passes AppMutex check
        release_single_instance()

        # Cleanly finalize and exit the application
        if self.parent and hasattr(self.parent, 'finalize_quit'):
            with contextlib.suppress(Exception):
                self.parent.finalize_quit(force=True)
        self.on_close()
        sys.exit(0)

    def _download_via_browser(self):
        """Open installer URL in browser and show advisory guidance with a Close FastMirror button."""
        url = self.release_info.setup_download_url or self.release_info.html_url
        with contextlib.suppress(Exception):
            webbrowser.open(url)

        self.lbl_progress_status.grid()
        self.lbl_progress_status.config(
            text='⚠️ Downloading in browser. FastMirror must be closed before running the installer.',
            foreground='#b45309',
        )

        # Offer an instant 1-click button to cleanly close FastMirror for the user
        self.btn_action_setup.config(
            state='normal',
            text='Close FastMirror Now',
            command=self._close_app_for_installer,
            style='Accent.TButton',
        )
        apply_icon(self.btn_action_setup, 'check_circle')
        add_tooltip(
            self.btn_action_setup,
            'Cleanly close FastMirror to prevent file lock errors when running the installer.',
        )

    _download_setup = _download_via_browser  # Backward compatibility alias

    def _close_app_for_installer(self):
        """Shut down FastMirror cleanly to ensure no locked files when user runs setup."""
        release_single_instance()
        if self.parent and hasattr(self.parent, 'finalize_quit'):
            with contextlib.suppress(Exception):
                self.parent.finalize_quit(force=True)
        self.on_close()
        sys.exit(0)

    def _download_portable(self):
        """Open the direct portable ZIP download URL in the user's default browser."""
        url = self.release_info.portable_download_url or self.release_info.html_url
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    def _open_github_release(self):
        """Open GitHub release page in the user's default browser."""
        with contextlib.suppress(Exception):
            webbrowser.open(self.release_info.html_url)

    def on_close(self):
        """Handle modal dialog closure and cancel any active in-flight installer download."""
        if self._is_downloading:
            self.cancel_download_event.set()
        super().on_close()
