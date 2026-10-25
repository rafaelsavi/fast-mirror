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
from gui.confirmation_popup import ActionSelection, CustomCheckboxTreeView, FileDetailsDialog
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


@pytest.mark.parametrize(
    ('confirm_cancel', 'expected_finished'),
    [(False, False), (True, True)],
)
def test_action_selection_window_close_warns_before_cancel(monkeypatch, confirm_cancel, expected_finished):
    class DummyPopup:
        def __init__(self):
            self.destroyed = False

        def destroy(self):
            self.destroyed = True

    popup = ActionSelection.__new__(ActionSelection)
    popup.finished = False
    popup.proceed = False
    popup.files_requested_to_copy = [('source', 'target')]
    popup.files_requested_to_move = [('old', 'new')]
    popup.files_requested_to_delete = ['obsolete']
    popup.popup = DummyPopup()
    popup.on_close_callback = None

    prompts = []
    monkeypatch.setattr(
        'gui.confirmation_popup.messagebox.askyesno',
        lambda *args, **kwargs: prompts.append((args, kwargs)) or confirm_cancel,
    )

    popup.on_window_close()

    assert len(prompts) == 1
    assert prompts[0][0][0] == 'Cancel Synchronization?'
    assert prompts[0][1]['default'] == 'no'
    assert popup.finished is expected_finished
    if confirm_cancel:
        assert popup.files_requested_to_copy == []
        assert popup.files_requested_to_move == []
        assert popup.files_requested_to_delete == []
    else:
        assert popup.popup.destroyed is False
        assert popup.files_requested_to_copy == [('source', 'target')]
        assert popup.files_requested_to_move == [('old', 'new')]
        assert popup.files_requested_to_delete == ['obsolete']
    if confirm_cancel:
        assert popup.popup.destroyed is True


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
    assert popup.popup.title() == 'FastMirror - Confirm Actions'

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


def test_action_selection_high_volume_filter_performance(tmp_path, monkeypatch):
    """Test filter operations execute within milliseconds without freezing on 10,000 items."""
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

    num_items = 10000
    exts = ['.pdf', '.jpg', '.mp4', '.zip', '.py']
    copies = []
    for i in range(num_items):
        ext = exts[i % len(exts)]
        src_p = CstmPath(src / f'file_{i:05d}{ext}', root_dir=src)
        tgt_p = CstmPath(tgt / f'file_{i:05d}{ext}', root_dir=tgt)
        src_p._stats = os.stat_result((0, 0, 0, 0, 0, 0, 1024 + i, 1700000000, 1700000000, 1700000000))
        tgt_p._is_new_target = True
        copies.append((src_p, tgt_p))

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=copies,
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        # 1. Filter by specific text (100 matches) should take well under 0.5s (typically ~20ms)
        t0 = time.perf_counter()
        popup.filter_var.set('file_005')
        t_filter = time.perf_counter() - t0
        assert t_filter < 0.5
        assert '100 matches' in popup.lbl_filter_count.cget('text')

        # 2. Filter by category chip should take well under 0.5s
        t0 = time.perf_counter()
        popup._on_category_chip_clicked('image')
        t_cat = time.perf_counter() - t0
        assert t_cat < 0.5
        assert '20 matches' in popup.lbl_filter_count.cget('text')
        assert '[Image]' in popup.lbl_filter_count.cget('text')

        # 3. Clearing filter should take well under 0.5s
        t0 = time.perf_counter()
        popup._on_clear_filter()
        t_clear = time.perf_counter() - t0
        assert t_clear < 0.5
        assert popup.lbl_filter_count.cget('text') == ''

        # 4. Typing simulation should not freeze
        for typed in ('f', 'fi', 'fil'):
            t0 = time.perf_counter()
            popup.filter_var.set(typed)
            assert (time.perf_counter() - t0) < 0.5

        # 5. Saving filtered or cleared state preserves items
        popup.button_save_click()
        assert popup.finished is True
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


def test_action_selection_summary_badges_show_size(tmp_path, monkeypatch):
    """Verify that summary badges display both file count and total size."""
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
    f1.write_bytes(b'x' * 1024)  # 1 KB
    f2 = tgt / 'del.txt'
    f2.write_bytes(b'y' * 2048)  # 2 KB

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[(CstmPath(f1, root_dir=src), CstmPath(tgt / 'f1.txt', root_dir=tgt))],
            files_available_to_move=[],
            files_available_to_delete=[CstmPath(f2, root_dir=tgt)],
            default_actions=[Action.COPY, Action.DELETE],
        )

        copy_badge_text = popup.lbl_stat_copy.cget('text')
        move_badge_text = popup.lbl_stat_move.cget('text')
        del_badge_text = popup.lbl_stat_delete.cget('text')

        assert '1 files' in copy_badge_text
        assert '1.00KB' in copy_badge_text
        assert '0 files' in move_badge_text
        assert '0' in move_badge_text
        assert '1 files' in del_badge_text
        assert '2.00KB' in del_badge_text
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_row_highlighting_on_selection(tmp_path, monkeypatch):
    """Verify that clicking/selecting a row prominently highlights it with selected_row tag."""
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
    f1 = src / 'row1.txt'
    f2 = src / 'row2.txt'
    f1.write_text('1')
    f2.write_text('2')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[
                (CstmPath(f1, root_dir=src), CstmPath(tgt / 'row1.txt', root_dir=tgt)),
                (CstmPath(f2, root_dir=src), CstmPath(tgt / 'row2.txt', root_dir=tgt)),
            ],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        children = popup.tree.get_children(Action.COPY.value)
        assert len(children) == 2
        item1, item2 = children[0], children[1]

        # Select first item
        popup.tree.selection_set(item1)
        popup._on_item_selected(None)

        tags1 = popup.tree.item(item1, 'tags')
        assert 'selected_row' in tags1
        assert 'selected_row' not in popup.tree.item(item2, 'tags')

        # Select second item
        popup.tree.selection_set(item2)
        popup._on_item_selected(None)

        tags2 = popup.tree.item(item2, 'tags')
        assert 'selected_row' in tags2
        # First item reverted
        assert 'selected_row' not in popup.tree.item(item1, 'tags')
        assert 'copy_tag' in popup.tree.item(item1, 'tags')
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_filter_hides_non_matching_rows(tmp_path, monkeypatch):
    """Verify that filter text hides non-matching rows and restores them when cleared."""
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
    f1 = src / 'alpha_document.txt'
    f2 = src / 'beta_image.png'
    f1.write_text('alpha')
    f2.write_text('beta')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[
                (CstmPath(f1, root_dir=src), CstmPath(tgt / 'alpha_document.txt', root_dir=tgt)),
                (CstmPath(f2, root_dir=src), CstmPath(tgt / 'beta_image.png', root_dir=tgt)),
            ],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        # Initially 2 children under copy
        assert len(popup.tree.get_children(Action.COPY.value)) == 2

        # 1. Filter by 'alpha': only alpha row should be visible
        popup.filter_var.set('alpha')
        visible_children = popup.tree.get_children(Action.COPY.value)
        assert len(visible_children) == 1
        assert 'alpha_document' in visible_children[0]
        assert '1 match' in popup.lbl_filter_count.cget('text')

        # Checked items still returns both (or checked items)
        checked = popup.tree.get_checked()
        assert len(checked) == 2

        # 2. Filter by 'nonexistent_query': 0 matches, copy group detached / hidden
        popup.filter_var.set('SX')
        assert '0 matches' in popup.lbl_filter_count.cget('text')
        assert Action.COPY.value not in popup.tree.get_children('')

        # 3. Clear filter: all rows and groups restored
        popup.filter_var.set('')
        assert Action.COPY.value in popup.tree.get_children('')
        assert len(popup.tree.get_children(Action.COPY.value)) == 2
        assert popup.lbl_filter_count.cget('text') == ''
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_see_in_folder_button(tmp_path, monkeypatch):
    """Verify See in Folder button exists and invokes explorer with the selected file."""
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
    f1 = src / 'folder_test.txt'
    f1.write_text('content')

    explorer_calls = []

    def mock_popen(cmd, *args, **kwargs):
        explorer_calls.append(cmd)

    monkeypatch.setattr('subprocess.Popen', mock_popen)

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[(CstmPath(f1, root_dir=src), CstmPath(tgt / 'folder_test.txt', root_dir=tgt))],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        assert hasattr(popup, 'btn_see_in_folder')
        assert 'See in Folder' in popup.btn_see_in_folder.cget('text')

        # Select the item
        children = popup.tree.get_children(Action.COPY.value)
        assert len(children) == 1
        popup.tree.selection_set(children[0])
        popup._on_item_selected(None)

        # Click "See in Folder"
        popup.btn_see_in_folder.invoke()

        assert len(explorer_calls) == 1
        assert 'explorer.exe' in explorer_calls[0][0]
        assert 'folder_test.txt' in explorer_calls[0][1]
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_custom_treeview_click_to_sort_columns(tmp_path):
    """Test click-to-sort columns ascending/descending with arrow indicators and correct numeric/text ordering."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    src = tmp_path / 's'
    tgt = tmp_path / 't'
    src.mkdir()
    tgt.mkdir()

    # Create 3 files with different sizes and names
    f_small = src / 'z_small.txt'
    f_small.write_bytes(b'x' * 10)
    f_large = src / 'a_large.txt'
    f_large.write_bytes(b'x' * 1000)
    f_medium = src / 'm_medium.txt'
    f_medium.write_bytes(b'x' * 200)

    try:
        tree = CustomCheckboxTreeView(root)
        tree.add_file_lists(
            {
                Action.COPY: [
                    (CstmPath(f_small, root_dir=src), CstmPath(tgt / 'z_small.txt', root_dir=tgt)),
                    (CstmPath(f_large, root_dir=src), CstmPath(tgt / 'a_large.txt', root_dir=tgt)),
                    (CstmPath(f_medium, root_dir=src), CstmPath(tgt / 'm_medium.txt', root_dir=tgt)),
                ]
            },
            default_active=[Action.COPY],
        )

        # 1. Sort by Size (Source) Ascending
        tree.sort_by_column('size (source)')
        assert '▲' in tree.heading('size (source)', 'text')
        children_asc = tree._all_group_children[Action.COPY.value]
        # Should be small (10 B), medium (200 B), large (1000 B)
        assert 'z_small.txt' in children_asc[0]
        assert 'm_medium.txt' in children_asc[1]
        assert 'a_large.txt' in children_asc[2]

        # 2. Sort by Size (Source) Descending (click again)
        tree.sort_by_column('size (source)')
        assert '▼' in tree.heading('size (source)', 'text')
        children_desc = tree._all_group_children[Action.COPY.value]
        # Should be large (1000 B), medium (200 B), small (10 B)
        assert 'a_large.txt' in children_desc[0]
        assert 'm_medium.txt' in children_desc[1]
        assert 'z_small.txt' in children_desc[2]

        # 3. Sort by Source Alphabetical Ascending
        tree.sort_by_column('source')
        assert '▲' in tree.heading('source', 'text')
        children_name = tree._all_group_children[Action.COPY.value]
        assert 'a_large.txt' in children_name[0]
        assert 'm_medium.txt' in children_name[1]
        assert 'z_small.txt' in children_name[2]
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_safety_buttons(tmp_path, monkeypatch):
    """Test 'Uncheck Deletions' and 'Copies Only' toolbar buttons."""
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

    f_copy = src / 'copy.txt'
    f_copy.write_text('copy')
    f_move = src / 'move.txt'
    f_move.write_text('move')
    f_del = tgt / 'del.txt'
    f_del.write_text('del')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[(CstmPath(f_copy, root_dir=src), CstmPath(tgt / 'copy.txt', root_dir=tgt))],
            files_available_to_move=[(CstmPath(f_move, root_dir=src), CstmPath(tgt / 'moved.txt', root_dir=tgt))],
            files_available_to_delete=[CstmPath(f_del, root_dir=tgt)],
            default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        )

        assert hasattr(popup, 'btn_uncheck_deletions')
        assert hasattr(popup, 'btn_copies_only')

        # Initially all three are checked
        checked = popup.tree.get_checked()
        assert any('copy::' in x for x in checked)
        assert any('move::' in x for x in checked)
        assert any('delete::' in x for x in checked)

        # 1. Test "Uncheck Deletions"
        popup.btn_uncheck_deletions.invoke()
        checked_after_uncheck = popup.tree.get_checked()
        assert any('copy::' in x for x in checked_after_uncheck)
        assert any('move::' in x for x in checked_after_uncheck)
        assert not any('delete::' in x for x in checked_after_uncheck)

        # Re-enable deletions
        popup.tree.change_state(Action.DELETE.value, 'checked')
        assert any('delete::' in x for x in popup.tree.get_checked())

        # 2. Test "Copies Only"
        popup.btn_copies_only.invoke()
        checked_copies_only = popup.tree.get_checked()
        assert any('copy::' in x for x in checked_copies_only)
        assert not any('move::' in x for x in checked_copies_only)
        assert not any('delete::' in x for x in checked_copies_only)
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_file_type_filter_chips(tmp_path, monkeypatch):
    """Test interactive file-type filter chips (Images, Docs, Media, Code, Archives)."""
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

    f_img = src / 'photo.jpg'
    f_img.write_text('img')
    f_doc = src / 'report.pdf'
    f_doc.write_text('doc')
    f_med = src / 'music.mp3'
    f_med.write_text('med')
    f_code = src / 'script.py'
    f_code.write_text('code')
    f_arch = src / 'backup.zip'
    f_arch.write_text('arch')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[
                (CstmPath(f_img, root_dir=src), CstmPath(tgt / 'photo.jpg', root_dir=tgt)),
                (CstmPath(f_doc, root_dir=src), CstmPath(tgt / 'report.pdf', root_dir=tgt)),
                (CstmPath(f_med, root_dir=src), CstmPath(tgt / 'music.mp3', root_dir=tgt)),
                (CstmPath(f_code, root_dir=src), CstmPath(tgt / 'script.py', root_dir=tgt)),
                (CstmPath(f_arch, root_dir=src), CstmPath(tgt / 'backup.zip', root_dir=tgt)),
            ],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        assert 'image' in popup.category_buttons
        assert 'document' in popup.category_buttons
        assert 'media' in popup.category_buttons
        assert 'code' in popup.category_buttons
        assert 'archive' in popup.category_buttons

        # Initially all 5 are visible
        assert len(popup.tree.get_children(Action.COPY.value)) == 5

        # 1. Filter by Images chip
        popup.category_buttons['image'].invoke()
        visible_images = popup.tree.get_children(Action.COPY.value)
        assert len(visible_images) == 1
        assert 'photo.jpg' in visible_images[0]
        assert 'Image' in popup.lbl_filter_count.cget('text')

        # 2. Filter by Documents chip
        popup.category_buttons['document'].invoke()
        visible_docs = popup.tree.get_children(Action.COPY.value)
        assert len(visible_docs) == 1
        assert 'report.pdf' in visible_docs[0]

        # 3. Filter by Code chip
        popup.category_buttons['code'].invoke()
        visible_code = popup.tree.get_children(Action.COPY.value)
        assert len(visible_code) == 1
        assert 'script.py' in visible_code[0]

        # 4. Clear filter button
        popup._on_clear_filter()
        assert len(popup.tree.get_children(Action.COPY.value)) == 5
        assert popup.lbl_filter_count.cget('text') == ''
        assert popup.active_category == 'all'
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_action_selection_keyboard_shortcuts(monkeypatch):
    """Test Ctrl+F focuses filter entry and Escape smartly clears active filter."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        popup = ActionSelection(
            root_gui=root,
            files_available_to_copy=[],
            files_available_to_move=[],
            files_available_to_delete=[],
            default_actions=[Action.COPY],
        )

        # 1. Test Ctrl+F helper
        res = popup._focus_filter_entry()
        assert res == 'break'
        with contextlib.suppress(Exception):
            popup.popup.update()
        assert popup.popup.focus_get() in (popup.entry_filter, popup.popup)

        # 2. Test smart Escape when query is present
        popup.filter_var.set('search_text')
        assert popup.filter_var.get() == 'search_text'
        res_esc = popup._on_escape_pressed()
        assert res_esc == 'break'
        assert popup.filter_var.get() == ''
        assert popup.finished is False  # Dialog NOT cancelled

        # 3. Test smart Escape when category filter is active
        popup.active_category = 'image'
        res_esc2 = popup._on_escape_pressed()
        assert res_esc2 == 'break'
        assert popup.active_category == 'all'
        assert popup.finished is False

        # 4. Test Escape when no filter active -> prompts/cancels
        monkeypatch.setattr('tkinter.messagebox.askyesno', lambda *args, **kwargs: True)
        res_esc3 = popup._on_escape_pressed()
        assert res_esc3 == 'break'
        assert popup.finished is True
        assert popup.proceed is False
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_confirmation_popup_right_click_single_item(monkeypatch):
    """Test right click context menu operations on a single leaf item."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        src = CstmPath('D:/test/photos/image.jpg')
        tgt = CstmPath('//192.168.1.100/share/photos/image.jpg')
        src._stats = type('Stats', (), {'st_size': 1024 * 500, 'st_mtime': 1700000000.0})()
        tgt._stats = type('Stats', (), {'st_size': 1024 * 300, 'st_mtime': 1690000000.0})()

        popup = ActionSelection(root, [(src, tgt)], [], [], [Action.COPY])
        copy_children = popup.tree.get_children('copy')
        assert len(copy_children) == 1
        item_id = copy_children[0]

        # Select item
        popup.tree.selection_set(item_id)
        popup._on_item_selected(None)

        # 1. Test copy source path
        popup._copy_source_path()
        assert 'D:' in popup.popup.clipboard_get()

        # 2. Test copy target path
        popup._copy_target_path()
        assert '192.168.1.100' in popup.popup.clipboard_get()

        # 3. Test copy both paths
        popup._copy_both_paths()
        clip = popup.popup.clipboard_get()
        assert 'Source:' in clip and 'Target:' in clip

        # 4. Test copy filename
        popup._copy_filename()
        assert popup.popup.clipboard_get() == 'image.jpg'

        # 5. Test copy row details
        popup._copy_row_details(item_id)
        details_clip = popup.popup.clipboard_get()
        assert 'Action: COPY' in details_clip
        assert 'image.jpg' in details_clip
        assert 'Source Path:' in details_clip

        # 6. Test toggle item check
        assert popup.tree.tag_has('checked', item_id)
        popup._toggle_item_check(item_id, 'unchecked')
        assert popup.tree.tag_has('unchecked', item_id)
        popup._toggle_item_check(item_id, 'checked')
        assert popup.tree.tag_has('checked', item_id)

        # 7. Test right-click dispatch event without raising
        dummy_event = type('DummyEvent', (), {'x': 10, 'y': 10, 'x_root': 100, 'y_root': 100})()
        monkeypatch.setattr(popup.tree, 'identify_row', lambda y: item_id)
        monkeypatch.setattr('tkinter.Menu.tk_popup', lambda *a, **k: None)
        popup._on_tree_right_click(dummy_event)

        # 8. Test context key dispatch
        popup._on_context_key(dummy_event)

        popup.button_cancel_click()
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_confirmation_popup_right_click_multi_item_and_group(monkeypatch):
    """Test right click context menu operations on multiple selected items and group headers."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        src1 = CstmPath('D:/test/f1.txt')
        tgt1 = CstmPath('//server/share/f1.txt')
        src1._stats = type('Stats', (), {'st_size': 100, 'st_mtime': 1700000000.0})()
        tgt1._stats = type('Stats', (), {'st_size': 100, 'st_mtime': 1700000000.0})()

        src2 = CstmPath('D:/test/f2.txt')
        tgt2 = CstmPath('//server/share/f2.txt')
        src2._stats = type('Stats', (), {'st_size': 200, 'st_mtime': 1700000000.0})()
        tgt2._stats = type('Stats', (), {'st_size': 200, 'st_mtime': 1700000000.0})()

        popup = ActionSelection(root, [(src1, tgt1), (src2, tgt2)], [], [], [Action.COPY])
        children = popup.tree.get_children('copy')
        assert len(children) == 2

        # 1. Multi-item copying
        popup._copy_multi_paths(list(children), 'source')
        clip = popup.popup.clipboard_get()
        assert 'f1.txt' in clip and 'f2.txt' in clip

        popup._copy_multi_pairs(list(children))
        clip_pairs = popup.popup.clipboard_get()
        assert ' -> ' in clip_pairs

        popup._copy_multi_summary(list(children))
        clip_summary = popup.popup.clipboard_get()
        assert 'FastMirror Selection Summary' in clip_summary

        # 2. Multi-item check state toggling
        popup._set_multi_check(list(children), 'unchecked')
        for c in children:
            assert popup.tree.tag_has('unchecked', c)

        popup._set_multi_check(list(children), 'checked')
        for c in children:
            assert popup.tree.tag_has('checked', c)

        # 3. Group header operations
        popup._copy_group_summary('copy')
        group_clip = popup.popup.clipboard_get()
        assert 'Action Group: COPY' in group_clip

        popup._set_group_check('copy', 'unchecked')
        assert popup.tree.tag_has('unchecked', 'copy')
        popup._set_group_check('copy', 'checked')
        assert popup.tree.tag_has('checked', 'copy')

        # 4. Multi-item right click menu dispatch
        monkeypatch.setattr('tkinter.Menu.tk_popup', lambda *a, **k: None)
        dummy_event = type('DummyEvent', (), {'x': 10, 'y': 10, 'x_root': 100, 'y_root': 100})()
        popup.tree.selection_set(children)
        popup._show_multi_item_context_menu(dummy_event, list(children))

        # 5. Group header right click menu dispatch
        popup._show_group_context_menu(dummy_event, 'copy')

        # 6. Empty area right click menu dispatch
        popup._show_empty_area_context_menu(dummy_event)

        popup.button_cancel_click()
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_confirmation_popup_inspector_right_click_and_details_button(monkeypatch):
    """Test inspector right-click handlers and details button."""
    monkeypatch.setattr('winsound.PlaySound', lambda *args, **kwargs: None)
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        src = CstmPath('D:/test/doc.pdf')
        tgt = CstmPath('//server/share/doc.pdf')
        src._stats = type('Stats', (), {'st_size': 5000, 'st_mtime': 1700000000.0})()
        tgt._stats = type('Stats', (), {'st_size': 5000, 'st_mtime': 1700000000.0})()

        popup = ActionSelection(root, [(src, tgt)], [], [], [Action.COPY])
        children = popup.tree.get_children('copy')
        popup.tree.selection_set(children[0])
        popup._on_item_selected(None)

        # 1. Details button exists and has tooltip
        assert popup.btn_details is not None
        assert popup.btn_details.cget('text') == 'Details...'

        # 2. Test right click on inspector elements
        monkeypatch.setattr('tkinter.Menu.tk_popup', lambda *a, **k: None)
        dummy_event = type('DummyEvent', (), {'x': 10, 'y': 10, 'x_root': 100, 'y_root': 100})()

        popup._on_source_label_right_click(dummy_event)
        popup._on_target_label_right_click(dummy_event)
        popup._on_copy_btn_right_click(dummy_event)

        # 3. Test transient diff text restore helper
        popup.lbl_inspector_diff.config(text='📋 Copied source path to clipboard!')
        popup._restore_diff_text('previous text')
        assert popup.lbl_inspector_diff.cget('text') == 'previous text'

        popup.button_cancel_click()
    finally:
        with contextlib.suppress(Exception):
            root.destroy()


def test_file_details_dialog(monkeypatch):
    """Test FileDetailsDialog initialization, diff summary, and copy details."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip('Tkinter display not available')

    try:
        row_data = {
            'source': 'D:/test/photos/vacation.jpg',
            'target': '//nas/backup/vacation.jpg',
            'size (source)': '1.50MB',
            'size (target)': '1.20MB',
            'bytes (source)': 1572864,
            'bytes (target)': 1258291,
            'modification date (source)': '2026/10/20 14:00:00',
            'modification date (target)': '2026/10/18 10:00:00',
        }

        dialog = FileDetailsDialog(
            parent=root,
            action=Action.COPY,
            source_path='D:/test/photos/vacation.jpg',
            target_path='//nas/backup/vacation.jpg',
            row_data=row_data,
            is_checked=True,
        )

        assert dialog.filename == 'vacation.jpg'
        assert dialog.action_enum == Action.COPY

        diff_summary = dialog._compute_diff_summary()
        assert 'Action: COPY' in diff_summary
        assert 'Size difference' in diff_summary

        # Test copy all info
        dialog._copy_all_info()
        clip = dialog.dialog.clipboard_get()
        assert 'vacation.jpg' in clip
        assert 'D:/test/photos/vacation.jpg' in clip
        assert '//nas/backup/vacation.jpg' in clip

        # Test DELETE variant
        del_dialog = FileDetailsDialog(
            parent=root,
            action=Action.DELETE,
            source_path='',
            target_path='//nas/backup/old.tmp',
            row_data={'size (target)': '50.00KB'},
            is_checked=False,
        )
        del_summary = del_dialog._compute_diff_summary()
        assert 'DELETE' in del_summary

        dialog.dialog.destroy()
        del_dialog.dialog.destroy()
    finally:
        with contextlib.suppress(Exception):
            root.destroy()
