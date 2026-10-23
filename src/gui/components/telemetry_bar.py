import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


class TelemetryBar(ttk.Frame):
    """Modern real-time telemetry bar showing animated progress, transfer speed, and current file."""

    def __init__(
        self,
        master: tk.Misc,
        **kwargs,
    ):
        super().__init__(master, **kwargs)

        self._active_mode: str | None = None
        self._current_file = ''
        self._create_widgets()

    def _create_widgets(self):
        self.columnconfigure(1, weight=1)

        # Row 0: Top Framing Separator
        sep = ttk.Separator(self, orient='horizontal')
        sep.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 4))

        # Row 1: Status label on left, Details on right
        self.lbl_status = ttk.Label(
            self,
            text='Ready',
            font=('Segoe UI', 9, 'bold'),
        )
        self.lbl_status.grid(row=1, column=0, sticky='w', padx=(4, 8), pady=(2, 2))

        self.lbl_details = ttk.Label(
            self,
            text='',
            font=('Segoe UI', 9),
            foreground='#555555',
        )
        self.lbl_details.grid(row=1, column=1, sticky='ew', padx=(0, 4), pady=(2, 2))
        self._details_font = tkfont.Font(root=self, font=self.lbl_details.cget('font'))
        self.lbl_details.bind('<Configure>', self._on_details_resize)

        # Row 2: Modern Progress Bar
        self.progress = ttk.Progressbar(
            self,
            orient='horizontal',
            mode='indeterminate',
        )
        self.progress.grid(row=2, column=0, columnspan=2, sticky='ew', padx=(4, 4), pady=(2, 4))

    def set_indeterminate(self, message: str = 'Scanning files...'):
        """Switch to smooth indeterminate animated progress during directory scanning."""
        self._active_mode = 'indeterminate'
        self.lbl_status.config(text=message)
        self._current_file = ''
        self.lbl_details.config(text='')
        self.progress.config(mode='indeterminate')
        self.progress.start(15)

    def set_determinate(
        self,
        action: str,
        current: int,
        total: int,
        bytes_transferred: int = 0,
        current_file: str = '',
        speed: str = '',
    ):
        """Update determinate progress with live file counter, speed, and current path."""
        if self._active_mode != 'determinate':
            self.progress.stop()
            self.progress.config(mode='determinate')
            self._active_mode = 'determinate'

        pct = (current / total * 100.0) if total > 0 else 0.0
        self.progress['value'] = pct

        action_title = action.title()
        status_text = f'{action_title}: {current:,} of {total:,} ({pct:.1f}%)'
        if speed:
            status_text += f' • {speed}'
        self.lbl_status.config(text=status_text)

        self._current_file = current_file
        self._refresh_current_file_label()

    def _on_details_resize(self, _event: tk.Event) -> None:
        self._refresh_current_file_label()

    def _refresh_current_file_label(self) -> None:
        if not self._current_file:
            self.lbl_details.config(text='')
            return

        full_text = f'Current: {self._current_file}'
        available_width = self.lbl_details.winfo_width()
        if available_width <= 1 or self._details_font.measure(full_text) <= available_width:
            self.lbl_details.config(text=full_text)
            return

        prefix = 'Current: ...'
        if self._details_font.measure(prefix) > available_width:
            if self._details_font.measure('...') > available_width:
                display_text = ''
            else:
                low, high = 0, len(full_text)
                while low < high:
                    middle = (low + high + 1) // 2
                    candidate = f'...{full_text[-middle:]}'
                    if self._details_font.measure(candidate) <= available_width:
                        low = middle
                    else:
                        high = middle - 1
                display_text = f'...{full_text[-low:]}' if low else '...'
        else:
            low, high = 0, len(self._current_file)
            while low < high:
                middle = (low + high + 1) // 2
                candidate = f'{prefix}{self._current_file[-middle:]}'
                if self._details_font.measure(candidate) <= available_width:
                    low = middle
                else:
                    high = middle - 1
            display_text = f'{prefix}{self._current_file[-low:]}' if low else prefix

        self.lbl_details.config(text=display_text)

    def reset(self, message: str = 'Ready'):
        """Stop animation and return to standby state."""
        self._active_mode = None
        self._current_file = ''
        self.progress.stop()
        self.progress['value'] = 0
        self.progress.config(mode='indeterminate')
        self.lbl_status.config(text=message)
        self.lbl_details.config(text='')
