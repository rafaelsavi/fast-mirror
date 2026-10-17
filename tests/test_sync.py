import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from core.backend import CompareDirs, SyncDirs
from core.file import CstmPath, File
from core.mirror import MirrorDatabase
from gui.widgets import Action
from utils.utils import DirectoryPair, sanitize_path


def test_cstmpath_get_from_dir_exclusions_on_windows(tmp_path):
    root = tmp_path / 'ScanRoot'
    sub1 = root / 'SubFolder'
    sub2 = root / 'IgnoredFolder'
    sub1.mkdir(parents=True)
    sub2.mkdir(parents=True)

    keep_file = sub1 / 'keep.txt'
    keep_file.write_text('keep')
    ignored_file = sub2 / 'skip.txt'
    ignored_file.write_text('skip')
    ext_ignored = sub1 / 'skip.tmp'
    ext_ignored.write_text('skip')

    exclude = ['IgnoredFolder/*', '*.tmp']
    scanned = CstmPath.get_from_dir(str(root), exclude=exclude)
    scanned_names = {p.name for p in scanned}

    assert 'keep.txt' in scanned_names
    assert 'skip.txt' not in scanned_names
    assert 'skip.tmp' not in scanned_names


def test_cstm_path_get_from_dir_ignores_tmp_files(tmp_path):
    source_dir = tmp_path / 'scan_dir'
    source_dir.mkdir()
    valid_file = source_dir / 'real_photo.jpg'
    tmp_file1 = source_dir / 'video.mp4.tmp'
    tmp_file2 = source_dir / 'backup.zip.tmp.1234_1'

    valid_file.write_text('valid')
    tmp_file1.write_text('tmp1')
    tmp_file2.write_text('tmp2')

    scanned = CstmPath.get_from_dir(source_dir, exclude=[])
    scanned_names = {Path(p).name for p in scanned}

    assert 'real_photo.jpg' in scanned_names
    assert 'video.mp4.tmp' not in scanned_names
    assert 'backup.zip.tmp.1234_1' not in scanned_names


def test_file_class_properties(tmp_path):
    root_s = tmp_path / 's'
    root_t = tmp_path / 't'
    root_s.mkdir()
    root_t.mkdir()

    f_s = root_s / 'file.txt'
    f_t = root_t / 'file.txt'
    f_s.write_text('content')
    shutil.copy2(f_s, f_t)

    cp_s = CstmPath(f_s, root_dir=root_s)
    cp_t = CstmPath(f_t, root_dir=root_t)

    # only source
    f_only_s = File(source=cp_s, target=None)
    assert f_only_s.only_source is True
    assert f_only_s.only_target is False
    assert f_only_s.in_both is False

    # only target
    f_only_t = File(source=None, target=cp_t)
    assert f_only_t.only_source is False
    assert f_only_t.only_target is True
    assert f_only_t.in_both is False

    # in both, same relative path
    f_both = File(source=cp_s, target=cp_t)
    assert f_both.in_both is True
    assert f_both.moved is False
    f_both.compare()
    assert f_both.same is True
    assert f_both.modified is False
    assert f_both.compare_error is False

    # moved (different rel_to_root)
    f_sub = root_t / 'sub' / 'file.txt'
    f_sub.parent.mkdir()
    f_sub.write_text('content')
    cp_sub = CstmPath(f_sub, root_dir=root_t)
    f_moved = File(source=cp_s, target=cp_sub)
    assert f_moved.in_both is True
    assert f_moved.moved is True


def test_syncdirs_execution_order(monkeypatch, tmp_path):
    call_order: list[str] = []

    monkeypatch.setattr(SyncDirs, 'move_files', lambda self: call_order.append('move'))
    monkeypatch.setattr(SyncDirs, 'delete_files', lambda self: call_order.append('delete'))
    monkeypatch.setattr(SyncDirs, 'copy_files', lambda self: call_order.append('copy'))
    monkeypatch.setattr(SyncDirs, 'delete_empty_dirs', lambda self: call_order.append('prune'))
    monkeypatch.setattr(SyncDirs, 'print_errors', lambda self: None)

    source = tmp_path / 's'
    target = tmp_path / 't'
    source.mkdir()
    target.mkdir()
    f_src = CstmPath(source / 'a.txt', root_dir=source)
    f_tgt = CstmPath(target / 'a.txt', root_dir=target)

    SyncDirs(
        files_to_copy=[(f_src, f_tgt)],
        files_to_move=[],
        files_to_delete=[],
        mirror=None,  # type: ignore
        root_gui=None,
        dirs=[DirectoryPair(str(source), str(target))],
        confirm_sync=False,
    )

    assert call_order == ['move', 'delete', 'copy', 'prune']


def test_compare_dirs_classifies_copy_move_delete(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    # 1. Unchanged file (identical content and mtime)
    unchanged_src = source / 'unchanged.txt'
    unchanged_tgt = target / 'unchanged.txt'
    unchanged_src.write_text('same')
    shutil.copy2(unchanged_src, unchanged_tgt)

    # 2. New file (source only)
    new_src = source / 'new.txt'
    new_src.write_text('new')

    # 3. Obsolete file (target only)
    obsolete_tgt = target / 'obsolete.txt'
    obsolete_tgt.write_text('obsolete')

    # 4. Modified file (exists in both, but content differs)
    mod_src = source / 'modified.txt'
    mod_tgt = target / 'modified.txt'
    mod_src.write_text('source version v2')
    mod_tgt.write_text('target version v1')
    os.utime(mod_src, (time.time() - 10, time.time() - 10))
    os.utime(mod_tgt, (time.time() - 500, time.time() - 500))

    # 5. Moved file (source is in subfolder, target has same name/content in root)
    moved_src = source / 'subfolder' / 'moved.txt'
    moved_src.parent.mkdir()
    moved_src.write_text('unique moved content')
    moved_tgt = target / 'moved.txt'
    shutil.copy2(moved_src, moved_tgt)

    mirror_db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=mirror_db_path)

    dirs = [DirectoryPair(str(source), str(target))]
    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])

    copy_sources = [str(s) for s, _ in compare.files_to_copy]
    assert str(new_src) in copy_sources
    assert str(mod_src) in copy_sources
    assert str(unchanged_src) not in copy_sources

    assert len(compare.files_to_move) == 1
    move_src, move_dst = compare.files_to_move[0]
    assert str(move_src) == str(moved_tgt)
    assert str(move_dst) == str(target / 'subfolder' / 'moved.txt')

    delete_targets = [str(t) for t in compare.files_to_delete]
    assert str(obsolete_tgt) in delete_targets
    assert str(unchanged_tgt) not in delete_targets


def test_compare_dirs_respects_exclusions(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    keep = source / 'keep.txt'
    keep.write_text('keep')
    ignored = source / 'temp.log'
    ignored.write_text('log')
    git_file = source / '.git' / 'config'
    git_file.parent.mkdir()
    git_file.write_text('git')

    mirror = MirrorDatabase(path=str(tmp_path / 'mirror.db'))
    dirs = [DirectoryPair(str(source), str(target))]
    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=['*.log', '.git/*'])

    copy_paths = [str(s) for s, _ in compare.files_to_copy]
    assert str(keep) in copy_paths
    assert str(ignored) not in copy_paths
    assert str(git_file) not in copy_paths


def test_syncdirs_end_to_end_execution(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    new_src = source / 'new.txt'
    new_src.write_text('new content')

    mod_src = source / 'mod.txt'
    mod_tgt = target / 'mod.txt'
    mod_src.write_text('updated mod')
    mod_tgt.write_text('old mod')
    os.utime(mod_src, (time.time() - 10, time.time() - 10))
    os.utime(mod_tgt, (time.time() - 500, time.time() - 500))

    obs_tgt = target / 'obsolete.txt'
    obs_tgt.write_text('old obsolete')

    moved_src = source / 'sub' / 'moved.txt'
    moved_src.parent.mkdir()
    moved_src.write_text('moved file')
    moved_tgt = target / 'old_sub' / 'moved.txt'
    moved_tgt.parent.mkdir()
    shutil.copy2(moved_src, moved_tgt)

    mirror_db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=mirror_db_path)
    dirs = [DirectoryPair(str(source), str(target))]

    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])

    SyncDirs(
        files_to_copy=compare.files_to_copy,
        files_to_move=compare.files_to_move,
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        confirm_sync=False,
    )

    assert (target / 'new.txt').is_file()
    assert (target / 'new.txt').read_text() == 'new content'
    assert (target / 'mod.txt').read_text() == 'updated mod'
    assert not obs_tgt.exists()
    assert (target / 'sub' / 'moved.txt').is_file()
    assert not moved_tgt.exists()

    assert not (target / 'old_sub').exists()
    assert target.is_dir()
    assert source.is_dir()


def test_delete_empty_dirs_preserves_root_directory(tmp_path):
    source = tmp_path / 'source_root'
    target = tmp_path / 'target_root'
    source.mkdir()
    target.mkdir()

    nested = target / 'level1' / 'level2'
    nested.mkdir(parents=True)

    mirror = MirrorDatabase(path=str(tmp_path / 'mirror.db'))
    dirs = [DirectoryPair(str(source), str(target))]

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )

    sync.files_deleted = [(str(nested / 'fake_file.txt'), True)]
    sync.delete_empty_dirs()

    assert not nested.exists()
    assert not (target / 'level1').exists()
    assert target.is_dir()
    assert source.is_dir()


def test_copy_files_jit_self_healing(tmp_path):
    source_dir = tmp_path / 'Source'
    target_dir = tmp_path / 'Target'
    source_dir.mkdir()
    target_dir.mkdir()

    source_file = source_dir / 'photo.jpg'
    target_file = target_dir / 'photo.jpg'
    payload = b'image payload content'
    source_file.write_bytes(payload)
    target_file.write_bytes(payload)

    s_stat = os.stat(source_file)
    os.utime(target_file, (s_stat.st_atime, s_stat.st_mtime))

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    assert not mirror.exists(str(target_dir), str(target_file))

    dirs = [DirectoryPair(source=str(source_dir), target=str(target_dir))]
    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_copy = [(str(source_file), str(target_file))]

    old_target_mtime = os.stat(target_file).st_mtime
    sync.copy_files()

    assert len(sync.files_copied) == 1
    assert sync.files_copied[0][1] is True
    assert mirror.exists(str(target_dir), str(target_file))
    assert os.stat(target_file).st_mtime == old_target_mtime


def test_delete_files_jit_phantom_cleanup(tmp_path):
    target_dir = tmp_path / 'Target'
    target_dir.mkdir()
    phantom_file = target_dir / 'deleted_externally.txt'

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)

    with mirror._get_db(str(target_dir)) as db:
        db[sanitize_path(phantom_file)] = 'stats_hash_123'
    assert mirror.exists(str(target_dir), str(phantom_file))

    dirs = [DirectoryPair(source=str(tmp_path / 'Source'), target=str(target_dir))]
    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_delete = [str(phantom_file)]
    sync.delete_files()

    assert len(sync.files_deleted) == 1
    assert sync.files_deleted[0][1] is True
    assert not mirror.exists(str(target_dir), str(phantom_file))


def test_move_files_jit_self_healing(tmp_path):
    target_dir = tmp_path / 'Target'
    target_dir.mkdir()
    old_target = target_dir / 'old_sub' / 'file.txt'
    new_target = target_dir / 'new_sub' / 'file.txt'
    new_target.parent.mkdir(parents=True)
    new_target.write_text('moved file data')

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)

    mirror.add_path(str(target_dir), str(new_target))
    with mirror._get_db(str(target_dir)) as db:
        del db[sanitize_path(new_target)]
        db[sanitize_path(old_target)] = 'old_hash'

    assert mirror.exists(str(target_dir), str(old_target))
    assert not mirror.exists(str(target_dir), str(new_target))

    dirs = [DirectoryPair(source=str(tmp_path / 'Source'), target=str(target_dir))]
    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_move = [(str(old_target), str(new_target))]
    sync.move_files()

    assert len(sync.files_moved) == 1
    assert sync.files_moved[0][1] is True
    assert not mirror.exists(str(target_dir), str(old_target))
    assert mirror.exists(str(target_dir), str(new_target))


def test_move_files_purges_phantom_record(tmp_path):
    target_dir = tmp_path / 'Target'
    target_dir.mkdir()
    source_file = tmp_path / 'Source' / 'ghost.txt'
    target_file = target_dir / 'ghost.txt'

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    with mirror._get_db(str(target_dir)) as db:
        db[sanitize_path(source_file)] = 'phantom_hash'
    assert mirror.exists(str(target_dir), str(source_file))

    dirs = [DirectoryPair(source=str(tmp_path / 'Source'), target=str(target_dir))]
    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_move = [(str(source_file), str(target_file))]
    sync.move_files()

    assert len(sync.files_moved) == 1
    assert sync.files_moved[0][1] is False
    assert not mirror.exists(str(target_dir), str(source_file))


def test_preflight_directory_pair_validation(tmp_path):
    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    dirs = [DirectoryPair(source=str(tmp_path / 'Source'), target=str(tmp_path / 'Target'))]

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )

    invalid_target = 'Z:\\Unmapped\\outside.txt'
    sync.files_requested_to_delete = [invalid_target]
    sync.delete_files()

    assert len(sync.files_deleted) == 1
    assert sync.files_deleted[0] == (invalid_target, False)


def test_sync_dirs_cancel_cooperative(tmp_path):
    source_dir = tmp_path / 'Source'
    target_dir = tmp_path / 'Target'
    source_dir.mkdir()
    target_dir.mkdir()

    f1 = source_dir / '1.txt'
    f2 = source_dir / '2.txt'
    f1.write_text('1')
    f2.write_text('2')

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    dirs = [DirectoryPair(source=str(source_dir), target=str(target_dir))]

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_copy = [
        (str(f1), str(target_dir / '1.txt')),
        (str(f2), str(target_dir / '2.txt')),
    ]

    sync.cancel()
    sync.copy_files()

    assert len(sync.files_copied) == 0
    assert not (target_dir / '1.txt').exists()
    assert not (target_dir / '2.txt').exists()


def test_copy_files_skips_when_source_missing(tmp_path):
    source_dir = tmp_path / 'Source'
    target_dir = tmp_path / 'Target'
    source_dir.mkdir()
    target_dir.mkdir()
    missing_source = source_dir / 'missing.txt'
    target_file = target_dir / 'missing.txt'

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    dirs = [DirectoryPair(source=str(source_dir), target=str(target_dir))]

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
    )
    sync.files_requested_to_copy = [(str(missing_source), str(target_file))]
    sync.copy_files()

    assert sync.files_copied == [((str(missing_source), str(target_file)), False)]
    assert not target_file.exists()


def test_sync_dirs_progress_callback(tmp_path):
    source_dir = tmp_path / 'Source'
    target_dir = tmp_path / 'Target'
    source_dir.mkdir()
    target_dir.mkdir()

    f1 = source_dir / 'f1.txt'
    f2 = source_dir / 'f2.txt'
    f1.write_text('content1')
    f2.write_text('content2')

    db_path = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=db_path)
    dirs = [DirectoryPair(source=str(source_dir), target=str(target_dir))]

    progress_events: list[tuple[str, int, int]] = []

    def on_progress(action: str, current: int, total: int, bytes_transferred: int, current_file: str, speed: str):
        progress_events.append((action, current, total))
        if current == 1:
            # Deliberately raise exception to test callback robustness
            raise RuntimeError('Simulated transient UI callback error')

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        root_gui=None,
        dirs=dirs,
        confirm_sync=False,
        progress_callback=on_progress,
    )
    sync.files_requested_to_copy = [
        (str(f1), str(target_dir / 'f1.txt')),
        (str(f2), str(target_dir / 'f2.txt')),
    ]
    sync.copy_files()

    # Verify both files copied successfully despite callback exception
    assert (target_dir / 'f1.txt').exists()
    assert (target_dir / 'f2.txt').exists()
    assert len(sync.files_copied) == 2
    assert all(success for _, success in sync.files_copied)

    # Verify callback was called for both items
    assert len(progress_events) == 2
    assert progress_events[0] == ('copy', 1, 2)
    assert progress_events[1] == ('copy', 2, 2)
