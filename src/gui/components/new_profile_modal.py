"""Modal dialog for creating a new profile with template selection (Blank vs Based on current)."""

import tkinter as tk
from tkinter import messagebox, ttk

from gui.components.base_modal import BaseModalDialog
from utils.profile_manager import sanitize_profile_name


class NewProfileModal(BaseModalDialog):
    """Modal dialog allowing the user to enter a profile name and choose an initial configuration template."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | None,
        active_profile_name: str = 'Default',
        existing_profiles: list[str] | None = None,
        wait: bool = True,
    ):
        self.active_profile_name = active_profile_name
        self.existing_profiles = [p.lower() for p in (existing_profiles or [])]
        self.result: tuple[str, str] | None = None

        super().__init__(
            parent=parent,
            title='New Configuration Profile',
            width=480,
            height=330,
            resizable=False,
            modal=wait,
        )

        self._create_widgets()
        self._center_and_reveal(modal=wait)

        self.bind('<Return>', lambda _e: self._on_create())
        self.entry_name.focus_set()

        if wait:
            try:
                if parent is not None:
                    parent.wait_window(self)
                else:
                    self.wait_window()
            except Exception:
                pass

    def on_close(self):
        self._on_cancel()

    def _create_widgets(self):
        container = ttk.Frame(self.window, padding=(18, 16, 18, 16))
        container.pack(fill='both', expand=True)

        # 1. Header Banner
        header = ttk.Frame(container)
        header.pack(fill='x', pady=(0, 10))

        lbl_title = ttk.Label(
            header,
            text='Create New Profile',
            font=('Segoe UI', 11, 'bold'),
        )
        lbl_title.pack(anchor='w')

        lbl_desc = ttk.Label(
            header,
            text='Enter a profile name and choose a starting configuration.',
            font=('Segoe UI', 8),
            foreground='#64748b',
        )
        lbl_desc.pack(anchor='w', pady=(2, 0))

        sep1 = ttk.Separator(container, orient='horizontal')
        sep1.pack(fill='x', pady=(0, 10))

        # 2. Profile Name field
        lbl_name = ttk.Label(container, text='Profile Name:', font=('Segoe UI', 9, 'bold'))
        lbl_name.pack(anchor='w')

        self.var_name = tk.StringVar()
        self.entry_name = ttk.Entry(container, textvariable=self.var_name, font=('Segoe UI', 9))
        self.entry_name.pack(fill='x', pady=(4, 12))

        # 3. Starting Template Selection
        lbl_template = ttk.Label(container, text='Starting Configuration:', font=('Segoe UI', 9, 'bold'))
        lbl_template.pack(anchor='w', pady=(0, 6))

        self.var_template = tk.StringVar(value='current')

        # Option: Current Profile
        f_current = ttk.Frame(container)
        f_current.pack(fill='x', pady=(0, 6))

        rb_current = ttk.Radiobutton(
            f_current,
            text=f"Based on current profile ('{self.active_profile_name}')",
            value='current',
            variable=self.var_template,
        )
        rb_current.pack(anchor='w')

        lbl_current_desc = ttk.Label(
            f_current,
            text='    Copy directory pairs, exclusions, schedules, and mirror settings.',
            font=('Segoe UI', 8),
            foreground='#64748b',
        )
        lbl_current_desc.pack(anchor='w')

        # Option: Blank Profile
        f_blank = ttk.Frame(container)
        f_blank.pack(fill='x', pady=(0, 8))

        rb_blank = ttk.Radiobutton(
            f_blank,
            text='Blank profile',
            value='blank',
            variable=self.var_template,
        )
        rb_blank.pack(anchor='w')

        lbl_blank_desc = ttk.Label(
            f_blank,
            text='    Start clean with default options and no configured directory pairs.',
            font=('Segoe UI', 8),
            foreground='#64748b',
        )
        lbl_blank_desc.pack(anchor='w')

        sep2 = ttk.Separator(container, orient='horizontal')
        sep2.pack(fill='x', pady=(4, 12))

        # 4. Action Buttons
        btn_box = ttk.Frame(container)
        btn_box.pack(fill='x', side='bottom')

        btn_cancel = ttk.Button(btn_box, text='Cancel', command=self._on_cancel, width=10)
        btn_cancel.pack(side='right', padx=(6, 0))

        btn_create = ttk.Button(
            btn_box,
            text='Create Profile',
            style='Accent.TButton',
            command=self._on_create,
            width=14,
        )
        btn_create.pack(side='right')

    def _on_create(self):
        raw_name = self.var_name.get().strip()
        if not raw_name:
            messagebox.showwarning(
                'Profile Name Required',
                'Please enter a name for the new profile.',
                parent=self.window,
            )
            self.entry_name.focus_set()
            return

        try:
            clean_name = sanitize_profile_name(raw_name)
        except ValueError as e:
            messagebox.showwarning(
                'Invalid Profile Name',
                str(e),
                parent=self.window,
            )
            self.entry_name.focus_set()
            return

        if clean_name.lower() in self.existing_profiles:
            overwrite = messagebox.askyesno(
                'Profile Exists',
                f"A profile named '{clean_name}' already exists.\n\nDo you want to overwrite it?",
                parent=self.window,
            )
            if not overwrite:
                self.entry_name.focus_set()
                return

        self.result = (clean_name, self.var_template.get())
        self.window.destroy()

    def _on_cancel(self):
        self.result = None
        self.window.destroy()


def prompt_new_profile(
    parent: tk.Tk | tk.Toplevel | None,
    active_profile_name: str = 'Default',
    existing_profiles: list[str] | None = None,
) -> tuple[str, str] | None:
    """
    Display the New Profile modal and return (profile_name, template) or None if cancelled.

    Template is either 'current' (based on current profile) or 'blank' (clean empty profile).
    """
    modal = NewProfileModal(parent, active_profile_name, existing_profiles, wait=True)
    return modal.result
