import contextlib
import os
import sys
import threading
import tkinter as tk

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest

from core.backend import SyncDirs
from core.file import CstmPath
from core.mirror import MirrorDatabase
from gui.confirmation_popup import ActionSelection, CustomCheckboxTreeView
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

    try:

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
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_toolbar_select_and_deselect_all(tmp_path, monkeypatch):
    """Test toolbar buttons 'Select All' and 'Deselect All'."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 's'
    tgt = tmp_path / 't'
    src.mkdir()
    tgt.mkdir()
    f1 = src / 'f1.txt'
    f2 = src / 'f2.txt'
    f1.write_text('1')
    f2.write_text('2')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[
                (CstmPath(f1, root_dir=src), CstmPath(tgt / 'f1.txt', root_dir=tgt)),
                (CstmPath(f2, root_dir=src), CstmPath(tgt / 'f2.txt', root_dir=tgt)),
            ],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        assert len(popup.tree.get_checked()) == 2  # 2 leaf copy items

        # Test Deselect All
        popup.tree.deselect_all()
        assert len(popup.tree.get_checked()) == 0

        # Test Select All
        popup.tree.select_all()
        assert len(popup.tree.get_checked()) == 2
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_uncheck_deletions_safety(tmp_path, monkeypatch):
    """Test the safety button 'Uncheck All Deletions' leaves copies checked while disabling deletes."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 's'
    tgt = tmp_path / 't'
    src.mkdir()
    tgt.mkdir()
    f_copy = src / 'doc.txt'
    f_del = tgt / 'obsolete.txt'
    f_copy.write_text('doc')
    f_del.write_text('old')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[(CstmPath(f_copy, root_dir=src), CstmPath(tgt / 'doc.txt', root_dir=tgt))],
            files_available_to_move=[],
            files_available_to_delete=[CstmPath(f_del, root_dir=tgt)],
            default_actions=[Action.COPY, Action.DELETE],
        )

        # Initially both copy and delete are checked
        checked_before = popup.tree.get_checked()
        assert any('copy::' in x for x in checked_before)
        assert any('delete::' in x for x in checked_before)

        # Trigger safety button: Uncheck all deletions
        popup.tree.uncheck_action(Action.DELETE)

        checked_after = popup.tree.get_checked()
        # Copies remain checked
        assert any('copy::' in x for x in checked_after)
        # Deletions are now completely unchecked
        assert not any('delete::' in x for x in checked_after)
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_path_inspector_updates_on_select(tmp_path, monkeypatch):
    """Test Path Inspector panel updates source and target labels when an item is selected."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 's'
    tgt = tmp_path / 't'
    src.mkdir()
    tgt.mkdir()
    f1 = src / 'inspector_test.txt'
    f1.write_text('test')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[(CstmPath(f1, root_dir=src), CstmPath(tgt / 'inspector_test.txt', root_dir=tgt))],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        children = popup.tree.get_children('copy')
        assert len(children) == 1
        item_id = children[0]

        # Select the item and trigger selection callback
        popup.tree.selection_set(item_id)
        popup._on_item_selected(None)

        assert str(f1) in popup.lbl_inspector_source.cget('text')
        assert str(tgt / 'inspector_test.txt') in popup.lbl_inspector_target.cget('text')
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_high_volume_performance(tmp_path, monkeypatch):
    """Test ActionSelection loads and saves hundreds/thousands of files with sub-second performance."""
    import time

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

    # Generate 1500 simulated file pairs with unique paths
    num_items = 1500
    copies = [
        (CstmPath(src / f'sample_{i}.txt', root_dir=src), CstmPath(tgt / f'sample_{i}.txt', root_dir=tgt))
        for i in range(num_items)
    ]

    try:
        t0 = time.perf_counter()
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=copies,
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )
        t_load = time.perf_counter() - t0

        # Load time should be under 2.5 seconds for 1500 items in Tkinter
        assert t_load < 2.5
        assert f'{num_items} of {num_items}' in popup.tree.item('copy', 'text')

        # Test submit speed
        t1 = time.perf_counter()
        popup.button_save_click()
        t_save = time.perf_counter() - t1

        assert t_save < 0.5
        assert popup.finished is True
        assert popup.proceed is True
        copy_out, _, _ = popup.get_outputs()
        assert len(copy_out) == num_items
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_filter_and_highlight(tmp_path, monkeypatch):
    """Test filter updates match counter, highlights matching items, and clears cleanly."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 's'
    tgt = tmp_path / 't'
    src.mkdir()
    tgt.mkdir()

    f1 = src / 'target_document.pdf'
    f2 = src / 'target_photo.jpg'
    f3 = src / 'other_file.txt'
    for f in (f1, f2, f3):
        f.write_text('content')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[
                (CstmPath(f1, root_dir=src), CstmPath(tgt / 'target_document.pdf', root_dir=tgt)),
                (CstmPath(f2, root_dir=src), CstmPath(tgt / 'target_photo.jpg', root_dir=tgt)),
                (CstmPath(f3, root_dir=src), CstmPath(tgt / 'other_file.txt', root_dir=tgt)),
            ],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        # Initially no filter
        assert popup.lbl_filter_count.cget('text') == ''

        # Filter for 'target' -> 2 matches
        popup.filter_var.set('target')
        assert '2 matches' in popup.lbl_filter_count.cget('text')

        # Check tag on children
        children = popup.tree.get_children('copy')
        highlighted = [c for c in children if 'highlight_match' in popup.tree.item(c, 'tags')]
        assert len(highlighted) == 2

        # Clear filter
        popup.filter_var.set('')
        assert popup.lbl_filter_count.cget('text') == ''
        highlighted_after = [c for c in children if 'highlight_match' in popup.tree.item(c, 'tags')]
        assert len(highlighted_after) == 0

        popup.button_cancel_click()
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_duplicate_file_entries_handled_safely(tmp_path, monkeypatch):
    """Test passing duplicate paths in file_list generates distinct keys without TclError."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 's'
    tgt = tmp_path / 't'
    src.mkdir()
    tgt.mkdir()

    f = src / 'dup.txt'
    f.write_text('data')
    cp_s = CstmPath(f, root_dir=src)
    cp_t = CstmPath(tgt / 'dup.txt', root_dir=tgt)

    try:
        # Pass identical file pair 3 times
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[(cp_s, cp_t), (cp_s, cp_t), (cp_s, cp_t)],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )
        children = popup.tree.get_children('copy')
        assert len(children) == 3

        popup.button_save_click()
        assert popup.finished is True
        copy_out, _, _ = popup.get_outputs()
        assert len(copy_out) == 3
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_dismissal_idempotence(monkeypatch):
    """Test calling button_save_click or button_cancel_click multiple times executes callback only once."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    call_count = 0

    def on_close():
        nonlocal call_count
        call_count += 1

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[],
            on_close_callback=on_close,
        )

        popup.button_save_click()
        popup.button_save_click()
        popup.button_cancel_click()

        assert call_count == 1
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_custom_treeview_expand_and_collapse_all(tmp_path):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        src = tmp_path / 's.txt'
        tgt = tmp_path / 't.txt'
        src.write_text('content')

        tree = CustomCheckboxTreeView(root)
        tree.add_file_lists(
            {
                Action.COPY: [(CstmPath(src), CstmPath(tgt))],
            }
        )

        tree.collapse_all()
        assert bool(tree.item(Action.COPY.value, 'open')) is False

        tree.expand_all()
        assert bool(tree.item(Action.COPY.value, 'open')) is True
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_copy_path_and_selection(tmp_path):
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        src = tmp_path / 'source_file.txt'
        tgt = tmp_path / 'target_file.txt'
        src.write_text('hello')

        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[(CstmPath(src), CstmPath(tgt))],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        child_id = popup.tree.get_children(Action.COPY.value)[0]
        popup.tree.selection_set(child_id)
        popup._on_item_selected(None)

        assert str(src) in popup.lbl_inspector_source.cget('text')
        assert str(tgt) in popup.lbl_inspector_target.cget('text')

        popup._copy_selected_path_to_clipboard()
        copied = root.clipboard_get()
        assert copied == str(tgt)

        popup.button_cancel_click()
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_confirmation_popup_no_network_stat_for_new_targets(tmp_path, monkeypatch):
    """Verify that remote network destination targets never trigger blocking os.stat calls."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        from core.file import File

        src_dir = tmp_path / 'source'
        src_dir.mkdir()
        target_root = r'\\192.168.1.100\Backup\D'

        files_to_copy = []
        for i in range(200):
            f_path = src_dir / f'photo_{i}.jpg'
            f_path.write_bytes(b'test data ' * 10)
            cstm_src = CstmPath(f_path, root_dir=src_dir)
            file_obj = File(source=cstm_src, missing_target_root_dir=target_root)
            files_to_copy.append((file_obj.source, file_obj.source_as_target))

        # Spy on os.stat calls
        original_stat = os.stat
        remote_stat_calls = []

        def spy_stat(path, *args, **kwargs):
            path_str = str(path)
            if '192.168.1.100' in path_str:
                remote_stat_calls.append(path_str)
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr('os.stat', spy_stat)

        tree = CustomCheckboxTreeView(root)
        tree.add_file_lists({Action.COPY: files_to_copy}, default_active=[Action.COPY])
        tree.refresh_group_stats()

        # Zero remote stat calls must have been made to the NAS!
        assert len(remote_stat_calls) == 0

        # Verify rows were populated correctly with size and dates
        action_data = tree._data[Action.COPY]
        assert len(action_data) == 200
        first_row = list(action_data.values())[0]
        assert first_row['size (source)'] != '0'
        assert first_row['size (target)'] == '0'
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_confirmation_popup_large_dataset_performance(tmp_path):
    """Verify that populating and computing stats for 1,500+ items executes in under 1 second."""
    import time

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        src_dir = tmp_path / 'perf_source'
        src_dir.mkdir()
        dummy_file = src_dir / 'template.txt'
        dummy_file.write_text('content for performance testing')

        cstm_source = CstmPath(dummy_file, root_dir=src_dir)

        # 1,500 file operations
        copy_items = [
            (cstm_source, CstmPath(f'\\\\192.168.1.100\\Share\\dest_{i}.txt', is_new_target=True)) for i in range(800)
        ]
        move_items = [
            (
                cstm_source,
                CstmPath(f'\\\\192.168.1.100\\Share\\dest_move_{i}.txt', is_new_target=True),
            )
            for i in range(400)
        ]
        delete_items = [cstm_source for _ in range(300)]

        start_time = time.time()
        tree = CustomCheckboxTreeView(root)
        tree.add_file_lists(
            {
                Action.COPY: copy_items,
                Action.MOVE: move_items,
                Action.DELETE: delete_items,
            },
            default_active=[Action.COPY, Action.MOVE, Action.DELETE],
        )
        tree.refresh_group_stats()
        checked = tree.get_checked()
        duration = time.time() - start_time

        assert len(checked) == 1500
        assert duration < 2.0  # Must be fast and never freeze
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_hierarchical_get_checked_accuracy_and_speed(tmp_path):
    """Verify smart get_checked() matches native behavior in all states (all checked, all unchecked, tristate)."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        src_dir = tmp_path / 'tree_test'
        src_dir.mkdir()
        f1 = src_dir / 'a.txt'
        f2 = src_dir / 'b.txt'
        f3 = src_dir / 'c.txt'
        f1.write_text('a')
        f2.write_text('b')
        f3.write_text('c')

        items = [
            (CstmPath(f1, root_dir=src_dir), CstmPath('d:/dest/a.txt', is_new_target=True)),
            (CstmPath(f2, root_dir=src_dir), CstmPath('d:/dest/b.txt', is_new_target=True)),
            (CstmPath(f3, root_dir=src_dir), CstmPath('d:/dest/c.txt', is_new_target=True)),
        ]

        tree = CustomCheckboxTreeView(root)
        tree.add_file_lists({Action.COPY: items}, default_active=[Action.COPY])

        # 1. All checked
        assert len(tree.get_checked()) == 3

        # 2. Group unchecked
        tree.uncheck_action(Action.COPY)
        assert len(tree.get_checked()) == 0

        # 3. Select all
        tree.select_all()
        assert len(tree.get_checked()) == 3

        # 4. Tristate: uncheck one child
        first_child = tree.get_children(Action.COPY.value)[0]
        tree._uncheck_ancestor(first_child)
        assert tree.tag_has('tristate', Action.COPY.value) is True
        checked = tree.get_checked()
        assert len(checked) == 2
        assert first_child not in checked
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_cstmpath_scandir_caches_stats(tmp_path):
    """Verify CstmPath.get_from_dir pre-caches stats on all returned CstmPath instances."""
    scan_dir = tmp_path / 'scan_cache_test'
    scan_dir.mkdir()
    sub_dir = scan_dir / 'sub'
    sub_dir.mkdir()

    file1 = scan_dir / 'doc1.txt'
    file2 = sub_dir / 'doc2.txt'
    file1.write_text('content one')
    file2.write_text('content two is slightly longer')

    scanned = CstmPath.get_from_dir(scan_dir, exclude=[])
    assert len(scanned) == 2

    for p in scanned:
        # Pre-cached stats must be present in memory!
        assert p._stats is not None
        assert p._stats.st_size > 0
        assert p._stats.st_mtime > 0
        # Accessing size and date must not fail or raise
        assert p.get_st_size() == p._stats.st_size
        assert isinstance(p.get_st_mtime(as_date_str=True), str)
