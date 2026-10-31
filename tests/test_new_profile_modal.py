"""Tests for the NewProfileModal component and prompt_new_profile function."""

import contextlib
import tkinter as tk

import pytest

from gui.components.new_profile_modal import NewProfileModal, prompt_new_profile


@pytest.fixture(scope='module')
def root():
    """Module-scoped root window to avoid repeated Tcl interpreter teardown/recreation churn."""
    r = tk.Tk()
    r.withdraw()
    yield r
    with contextlib.suppress(Exception):
        r.destroy()


def test_new_profile_modal_initial_state(root):
    """Verify default widget state and variables on modal creation."""
    modal = NewProfileModal(
        parent=root,
        active_profile_name='PhotoBackup',
        existing_profiles=['Default', 'PhotoBackup'],
        wait=False,
    )
    try:
        assert modal.var_name.get() == ''
        assert modal.var_template.get() == 'current'
        assert modal.active_profile_name == 'PhotoBackup'
        assert 'default' in modal.existing_profiles
        assert 'photobackup' in modal.existing_profiles
        assert modal.result is None
    finally:
        modal.window.destroy()


def test_new_profile_modal_create_success(root):
    """Verify creating a profile sets sanitized name and template in result."""
    # 1. Based on current profile
    modal = NewProfileModal(root, active_profile_name='Default', wait=False)
    try:
        modal.var_name.set('  My Work Profile  ')
        modal.var_template.set('current')
        modal._on_create()
        assert modal.result == ('My Work Profile', 'current')
    finally:
        modal.window.destroy()

    # 2. Blank profile
    modal2 = NewProfileModal(root, active_profile_name='Default', wait=False)
    try:
        modal2.var_name.set('Fresh-Clean')
        modal2.var_template.set('blank')
        modal2._on_create()
        assert modal2.result == ('Fresh-Clean', 'blank')
    finally:
        modal2.window.destroy()


def test_new_profile_modal_cancel(root):
    """Verify cancelling resets result to None."""
    modal = NewProfileModal(root, wait=False)
    try:
        modal.var_name.set('ShouldCancel')
        modal._on_cancel()
        assert modal.result is None
    finally:
        modal.window.destroy()


def test_new_profile_modal_empty_name_validation(root, monkeypatch):
    """Verify empty name triggers a warning and does not complete."""
    warning_called = False

    def mock_showwarning(title, message, parent=None):
        nonlocal warning_called
        warning_called = True

    monkeypatch.setattr('tkinter.messagebox.showwarning', mock_showwarning)

    modal = NewProfileModal(root, wait=False)
    try:
        modal.var_name.set('   ')
        modal._on_create()
        assert warning_called is True
        assert modal.result is None
    finally:
        modal.window.destroy()


def test_new_profile_modal_invalid_name_validation(root, monkeypatch):
    """Verify invalid name characters trigger a warning."""
    warning_called = False

    def mock_showwarning(title, message, parent=None):
        nonlocal warning_called
        warning_called = True

    monkeypatch.setattr('tkinter.messagebox.showwarning', mock_showwarning)

    modal = NewProfileModal(root, wait=False)
    try:
        modal.var_name.set(':::***???')
        modal._on_create()
        assert warning_called is True
        assert modal.result is None
    finally:
        modal.window.destroy()


def test_new_profile_modal_duplicate_overwrite(root, monkeypatch):
    """Verify existing profile prompts for overwrite confirmation."""
    askyesno_response = False

    def mock_askyesno(title, message, parent=None):
        return askyesno_response

    monkeypatch.setattr('tkinter.messagebox.askyesno', mock_askyesno)

    modal = NewProfileModal(root, existing_profiles=['work', 'default'], wait=False)
    try:
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
        modal.window.destroy()


def test_prompt_new_profile_mocked(monkeypatch):
    """Verify prompt_new_profile function delegates and returns result."""
    monkeypatch.setattr(
        'gui.components.new_profile_modal.NewProfileModal',
        lambda parent, active, existing, wait=True: type('DummyModal', (), {'result': ('MockedProfile', 'blank')})(),
    )

    res = prompt_new_profile(None, active_profile_name='Default')
    assert res == ('MockedProfile', 'blank')
