"""Tests for the NewProfileModal component and prompt_new_profile function."""

import tkinter as tk

from gui.components.new_profile_modal import NewProfileModal, prompt_new_profile


def test_new_profile_modal_initial_state():
    """Verify default widget state and variables on modal creation."""
    root = tk.Tk()
    root.withdraw()
    try:
        modal = NewProfileModal(
            parent=root,
            active_profile_name='PhotoBackup',
            existing_profiles=['Default', 'PhotoBackup'],
            wait=False,
        )

        assert modal.var_name.get() == ''
        assert modal.var_template.get() == 'current'
        assert modal.active_profile_name == 'PhotoBackup'
        assert 'default' in modal.existing_profiles
        assert 'photobackup' in modal.existing_profiles
        assert modal.result is None
    finally:
        modal.window.destroy()
        root.destroy()


def test_new_profile_modal_create_success():
    """Verify creating a profile sets sanitized name and template in result."""
    root = tk.Tk()
    root.withdraw()
    try:
        # 1. Based on current profile
        modal = NewProfileModal(root, active_profile_name='Default', wait=False)
        modal.var_name.set('  My Work Profile  ')
        modal.var_template.set('current')
        modal._on_create()
        assert modal.result == ('My Work Profile', 'current')

        # 2. Blank profile
        modal2 = NewProfileModal(root, active_profile_name='Default', wait=False)
        modal2.var_name.set('Fresh-Clean')
        modal2.var_template.set('blank')
        modal2._on_create()
        assert modal2.result == ('Fresh-Clean', 'blank')
    finally:
        root.destroy()


def test_new_profile_modal_cancel():
    """Verify cancelling resets result to None."""
    root = tk.Tk()
    root.withdraw()
    try:
        modal = NewProfileModal(root, wait=False)
        modal.var_name.set('ShouldCancel')
        modal._on_cancel()
        assert modal.result is None
    finally:
        root.destroy()


def test_new_profile_modal_empty_name_validation(monkeypatch):
    """Verify empty name triggers a warning and does not complete."""
    root = tk.Tk()
    root.withdraw()
    warning_called = False

    def mock_showwarning(title, message, parent=None):
        nonlocal warning_called
        warning_called = True

    monkeypatch.setattr('tkinter.messagebox.showwarning', mock_showwarning)

    try:
        modal = NewProfileModal(root, wait=False)
        modal.var_name.set('   ')
        modal._on_create()
        assert warning_called is True
        assert modal.result is None
    finally:
        modal.window.destroy()
        root.destroy()


def test_new_profile_modal_invalid_name_validation(monkeypatch):
    """Verify invalid name characters trigger a warning."""
    root = tk.Tk()
    root.withdraw()
    warning_called = False

    def mock_showwarning(title, message, parent=None):
        nonlocal warning_called
        warning_called = True

    monkeypatch.setattr('tkinter.messagebox.showwarning', mock_showwarning)

    try:
        modal = NewProfileModal(root, wait=False)
        modal.var_name.set(':::***???')
        modal._on_create()
        assert warning_called is True
        assert modal.result is None
    finally:
        modal.window.destroy()
        root.destroy()


def test_new_profile_modal_duplicate_overwrite(monkeypatch):
    """Verify existing profile prompts for overwrite confirmation."""
    root = tk.Tk()
    root.withdraw()

    askyesno_response = False

    def mock_askyesno(title, message, parent=None):
        return askyesno_response

    monkeypatch.setattr('tkinter.messagebox.askyesno', mock_askyesno)

    try:
        modal = NewProfileModal(root, existing_profiles=['work', 'default'], wait=False)
        modal.var_name.set('Work')

        # User refuses overwrite
        askyesno_response = False
        modal._on_create()
        assert modal.result is None

        # User confirms overwrite
        askyesno_response = True
        modal._on_create()
        assert modal.result == ('Work', 'current')
    finally:
        root.destroy()


def test_prompt_new_profile_mocked(monkeypatch):
    """Verify prompt_new_profile function delegates and returns result."""
    monkeypatch.setattr(
        'gui.components.new_profile_modal.NewProfileModal',
        lambda parent, active, existing, wait=True: type('DummyModal', (), {'result': ('MockedProfile', 'blank')})(),
    )

    res = prompt_new_profile(None, active_profile_name='Default')
    assert res == ('MockedProfile', 'blank')
