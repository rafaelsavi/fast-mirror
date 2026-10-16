import os
import sys
import threading
import tkinter as tk

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.backend import ActionSelection, SyncDirs
from core.file import CstmPath
from core.mirror import MirrorDatabase
from gui.custom_gui import CustomCheckboxTreeView
from gui.widgets import Action
from utils.utils import DirectoryPair


def test_open_confirmation_popup_approved(monkeypatch):
    class DummyPopup:
        def __init__(self, *args, **kwargs):
            self.finished = True
            self.proceed = True
            if 'on_close_callback' in kwargs and kwargs['on_close_callback']:
                kwargs['on_close_callback']()

        def get_outputs(self):
            return [('s1', 't1')], [('s2', 't2')], ['t3']

    class DummyRoot:
        def after(self, delay, func):
            func()

    monkeypatch.setattr('core.backend.ActionSelection', DummyPopup)

    sync = SyncDirs.__new__(SyncDirs)
    sync.root_gui = DummyRoot()
    sync.files_available_to_copy = []
    sync.files_available_to_move = []
    sync.files_available_to_delete = []
    sync.default_actions = []

    res = sync.open_confirmation_popup()
    assert res is True
    assert sync.files_requested_to_copy == [('s1', 't1')]
    assert sync.files_requested_to_move == [('s2', 't2')]
    assert sync.files_requested_to_delete == ['t3']


def test_open_confirmation_popup_cancelled(monkeypatch):
    class DummyPopup:
        def __init__(self, *args, **kwargs):
            self.finished = True
            self.proceed = False
            if 'on_close_callback' in kwargs and kwargs['on_close_callback']:
                kwargs['on_close_callback']()

        def get_outputs(self):
            return [], [], []

    class DummyRoot:
        def after(self, delay, func):
            func()

    monkeypatch.setattr('core.backend.ActionSelection', DummyPopup)

    sync = SyncDirs.__new__(SyncDirs)
    sync.root_gui = DummyRoot()
    sync.files_available_to_copy = []
    sync.files_available_to_move = []
    sync.files_available_to_delete = []
    sync.default_actions = []

    res = sync.open_confirmation_popup()
    assert res is False
    assert sync.files_requested_to_copy == []


def test_action_selection_no_timer_and_cancel(monkeypatch):
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    callback_called = False

    def on_close():
        nonlocal callback_called
        callback_called = True

    action_sel = ActionSelection(
        root_gui=root,
        files_available_to_copy=[],
        files_available_to_move=[],
        files_available_to_delete=[],
        default_actions=[],
        on_close_callback=on_close,
    )

    assert action_sel.button_save.cget('text') == 'Save and continue'

    action_sel.button_cancel_click()
    assert action_sel.finished is True
    assert action_sel.proceed is False
    assert callback_called is True
    root.destroy()


def test_custom_checkbox_treeview_headers():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    tree = CustomCheckboxTreeView(root)
    assert 'creation date (source)' not in tree.custom_headers
    assert 'creation date (target)' not in tree.custom_headers
    assert tree['columns'] == (
        'source',
        'target',
        'size (source)',
        'size (target)',
        'modification date (source)',
        'modification date (target)',
    )
    root.destroy()


def test_action_selection_popup_title_and_scrollbars():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    popup = ActionSelection(root, [], [], [], [])
    assert popup.popup.title() == 'Automatic Backup - Confirm Actions'

    xscroll = popup.tree.cget('xscrollcommand')
    yscroll = popup.tree.cget('yscrollcommand')
    assert xscroll != ''
    assert yscroll != ''

    popup.button_cancel_click()
    assert popup.finished is True
    assert popup.proceed is False
    root.destroy()


def test_sync_dirs_cancels_cleanly_when_popup_canceled(tmp_path, monkeypatch):
    source = tmp_path / 'src'
    target = tmp_path / 'dst'
    source.mkdir()
    target.mkdir()
    f1 = source / 'file1.txt'
    f1.write_text('content')

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    monkeypatch.setattr(SyncDirs, 'open_confirmation_popup', lambda self: False)

    sync = SyncDirs(
        files_to_copy=[(CstmPath(f1), CstmPath(target / 'file1.txt'))],
        files_to_move=[],
        files_to_delete=[],
        mirror=MirrorDatabase(path=str(tmp_path / 'mirror.db')),
        root_gui=root,
        dirs=[DirectoryPair(source=str(source), target=str(target))],
        confirm_sync=True,
    )

    assert len(sync.files_copied) == 0
    assert not (target / 'file1.txt').exists()
    root.destroy()


def test_action_selection_real_items_population(tmp_path, monkeypatch):
    """Test ActionSelection populates group statistics and items with real files."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 'src'
    tgt = tmp_path / 'tgt'
    src.mkdir()
    tgt.mkdir()

    f1_src = src / 'copy1.txt'
    f1_tgt = tgt / 'copy1.txt'
    f1_src.write_text('hello copy 1')

    f2_src = src / 'copy2.txt'
    f2_tgt = tgt / 'copy2.txt'
    f2_src.write_text('hello copy 2 - longer data')

    del_file = tgt / 'delete_me.txt'
    del_file.write_text('obsolete')

    cp1_src = CstmPath(f1_src, root_dir=src)
    cp1_tgt = CstmPath(f1_tgt, root_dir=tgt)
    cp2_src = CstmPath(f2_src, root_dir=src)
    cp2_tgt = CstmPath(f2_tgt, root_dir=tgt)
    cp_del = CstmPath(del_file, root_dir=tgt)

    popup = ActionSelection(
        root_gui=root,
        files_available_to_copy=[(cp1_src, cp1_tgt), (cp2_src, cp2_tgt)],
        files_available_to_move=[],
        files_available_to_delete=[cp_del],
        default_actions=[Action.COPY, Action.DELETE],
    )

    # Verify root nodes exist
    children = popup.tree.get_children('')
    assert 'copy' in children
    assert 'move' in children
    assert 'delete' in children

    # Verify group text includes count
    copy_text = popup.tree.item('copy', 'text')
    assert 'copy' in copy_text
    assert '2 of 2' in copy_text

    delete_text = popup.tree.item('delete', 'text')
    assert 'delete' in delete_text
    assert '1 of 1' in delete_text

    # Verify child items exist under copy
    copy_children = popup.tree.get_children('copy')
    assert len(copy_children) == 2

    popup.button_cancel_click()
    root.destroy()


def test_action_selection_selective_check_and_save(tmp_path, monkeypatch):
    """Test selectively unchecking an item in the treeview produces only the remaining checked items."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 'src'
    tgt = tmp_path / 'tgt'
    src.mkdir()
    tgt.mkdir()

    f1_src = src / 'f1.txt'
    f1_tgt = tgt / 'f1.txt'
    f1_src.write_text('1')

    f2_src = src / 'f2.txt'
    f2_tgt = tgt / 'f2.txt'
    f2_src.write_text('2')

    cp1_src = CstmPath(f1_src, root_dir=src)
    cp1_tgt = CstmPath(f1_tgt, root_dir=tgt)
    cp2_src = CstmPath(f2_src, root_dir=src)
    cp2_tgt = CstmPath(f2_tgt, root_dir=tgt)

    popup = ActionSelection(
        root_gui=root,
        files_available_to_copy=[(cp1_src, cp1_tgt), (cp2_src, cp2_tgt)],
        files_available_to_move=[],
        files_available_to_delete=[],
        default_actions=[Action.COPY],
    )

    # Both are checked initially
    copy_children = popup.tree.get_children('copy')
    assert len(copy_children) == 2

    # Programmatically uncheck the second file
    item_to_uncheck = copy_children[1]
    popup.tree.change_state(item_to_uncheck, 'unchecked')
    popup.tree.refresh_group_stats()

    # Click save
    popup.button_save_click()

    assert popup.finished is True
    assert popup.proceed is True
    copy_out, move_out, del_out = popup.get_outputs()

    # Only 1 item was confirmed
    assert len(copy_out) == 1
    assert copy_out[0] == (str(f1_src), str(f1_tgt))
    assert len(move_out) == 0
    assert len(del_out) == 0

    root.destroy()


def test_e2e_syncdirs_selective_execution_with_popup(tmp_path, monkeypatch):
    """End-to-end integration test: SyncDirs with confirm_sync=True executing only user-confirmed actions."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 'source'
    tgt = tmp_path / 'target'
    src.mkdir()
    tgt.mkdir()

    # File 1: will be confirmed and copied
    keep_src = src / 'keep.txt'
    keep_tgt = tgt / 'keep.txt'
    keep_src.write_text('keep content')

    # File 2: will be unchecked in popup and skipped
    skip_src = src / 'skip.txt'
    skip_tgt = tgt / 'skip.txt'
    skip_src.write_text('skip content')

    # File 3: delete target file
    del_file = tgt / 'obsolete.txt'
    del_file.write_text('obsolete')

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    # Hook ActionSelection to simulate user interaction (unchecking skip.txt then clicking Save)
    orig_action_selection = ActionSelection

    def interactive_action_selection(*args, **kwargs):
        popup = orig_action_selection(*args, **kwargs)

        def user_interact():
            # Find the item for skip_src and uncheck it
            for child in popup.tree.get_children('copy'):
                if str(skip_src) in child:
                    popup.tree.change_state(child, 'unchecked')
            popup.tree.refresh_group_stats()
            # User clicks save
            popup.button_save_click()

        root.after(50, user_interact)
        return popup

    monkeypatch.setattr('core.backend.ActionSelection', interactive_action_selection)

    def run_sync():
        try:
            SyncDirs(
                files_to_copy=[
                    (CstmPath(keep_src, root_dir=src), CstmPath(keep_tgt, root_dir=tgt)),
                    (CstmPath(skip_src, root_dir=src), CstmPath(skip_tgt, root_dir=tgt)),
                ],
                files_to_move=[],
                files_to_delete=[CstmPath(del_file, root_dir=tgt)],
                mirror=mirror,
                root_gui=root,
                dirs=dirs,
                default_actions=[Action.COPY, Action.DELETE],
                confirm_sync=True,
            )
        finally:
            root.after(0, root.quit)

    sync_thread = threading.Thread(target=run_sync)
    root.after(20, sync_thread.start)
    root.mainloop()
    sync_thread.join(timeout=3.0)

    # Assert outcomes:
    # 1. keep.txt was copied
    assert keep_tgt.is_file()
    assert keep_tgt.read_text() == 'keep content'

    # 2. skip.txt was NOT copied (user unchecked it in popup!)
    assert not skip_tgt.exists()

    # 3. obsolete.txt was deleted
    assert not del_file.exists()

    # 4. Mirror database reflects the changes
    assert mirror.exists(str(tgt), str(keep_tgt))
    assert not mirror.exists(str(tgt), str(skip_tgt))
    assert not mirror.exists(str(tgt), str(del_file))

    root.destroy()
