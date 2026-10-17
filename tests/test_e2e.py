import os
import shutil
import stat
import time

from core.backend import CompareDirs, SyncDirs
from core.file import CstmPath
from core.mirror import MirrorDatabase
from gui.widgets import Action
from utils.utils import CompareMethod, DirectoryPair


def test_e2e_full_backup_cycle(tmp_path):
    """End-to-end integration test: Full initial backup of complex directory hierarchy."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    # Create realistic directory structure
    (src / 'notes.txt').write_text('Meeting notes and ideas')
    (src / 'readme.md').write_text('# Project Documentation')

    docs = src / 'documents'
    docs.mkdir()
    (docs / 'report.pdf').write_bytes(b'%PDF-1.4 sample pdf content 12345')
    (docs / 'data.csv').write_text('id,name,value\n1,alpha,100\n2,beta,200\n')

    photos = src / 'photos' / '2026'
    photos.mkdir(parents=True)
    (photos / 'vacation.jpg').write_bytes(b'\xff\xd8\xff\xe0\x00\x10JFIF sample image data')

    mirror_db = str(tmp_path / 'mirror.db')
    mirror = MirrorDatabase(path=mirror_db)
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    # 1. Compare phase
    compare = CompareDirs(
        mirror=mirror,
        dirs=dirs,
        exclusions=[],
        comparison_method=CompareMethod.METADATA,
        use_mirror=True,
        increment_mirror=True,
    )

    assert len(compare.files_to_copy) == 5
    assert len(compare.files_to_move) == 0
    assert len(compare.files_to_delete) == 0

    # 2. Sync phase
    sync = SyncDirs(
        files_to_copy=compare.files_to_copy,
        files_to_move=compare.files_to_move,
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        confirm_sync=False,
    )

    assert len(sync.files_copied) == 5
    assert all(ok for _, ok in sync.files_copied)
    assert len(sync.files_moved) == 0
    assert len(sync.files_deleted) == 0

    # Verify target directory contents
    assert (tgt / 'notes.txt').read_text() == 'Meeting notes and ideas'
    assert (tgt / 'readme.md').read_text() == '# Project Documentation'
    assert (tgt / 'documents' / 'report.pdf').read_bytes() == b'%PDF-1.4 sample pdf content 12345'
    assert (tgt / 'documents' / 'data.csv').read_text() == 'id,name,value\n1,alpha,100\n2,beta,200\n'
    assert (tgt / 'photos' / '2026' / 'vacation.jpg').read_bytes() == b'\xff\xd8\xff\xe0\x00\x10JFIF sample image data'

    # Verify mirror database tracks all 5 target files
    for rel_path in [
        'notes.txt',
        'readme.md',
        'documents/report.pdf',
        'documents/data.csv',
        'photos/2026/vacation.jpg',
    ]:
        target_file_path = str(tgt / rel_path)
        assert mirror.exists(str(tgt), target_file_path)


def test_e2e_incremental_backup_and_idempotency(tmp_path):
    """End-to-end integration test: Verifies idempotency then tests copy, move, and delete in cycle."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    # Initial files
    (src / 'file1.txt').write_text('content 1')
    (src / 'file2.txt').write_text('content 2')
    (src / 'will_move.txt').write_text('content to be moved')
    (src / 'will_delete.txt').write_text('content to be deleted')

    mirror = MirrorDatabase(path=str(tmp_path / 'mirror.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    # Initial sync
    comp1 = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])
    SyncDirs(
        files_to_copy=comp1.files_to_copy,
        files_to_move=comp1.files_to_move,
        files_to_delete=comp1.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        confirm_sync=False,
    )

    # 1. Idempotency check: Immediately running another comparison should find 0 operations
    comp_idempotent = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])
    assert len(comp_idempotent.files_to_copy) == 0
    assert len(comp_idempotent.files_to_move) == 0
    assert len(comp_idempotent.files_to_delete) == 0

    # 2. Modify files in source:
    # - file1.txt modified
    time.sleep(0.05)
    (src / 'file1.txt').write_text('content 1 updated!')

    # - will_move.txt moved to subfolder
    sub = src / 'archive'
    sub.mkdir()
    shutil.move(str(src / 'will_move.txt'), str(sub / 'will_move.txt'))

    # - will_delete.txt removed from source
    (src / 'will_delete.txt').unlink()

    # - new_file.txt created in source
    (src / 'new_file.txt').write_text('brand new file')

    # Run incremental comparison
    comp2 = CompareDirs(
        mirror=mirror,
        dirs=dirs,
        exclusions=[],
        comparison_method=CompareMethod.METADATA,
        use_mirror=True,
    )

    copy_srcs = [str(s) for s, _ in comp2.files_to_copy]
    assert str(src / 'file1.txt') in copy_srcs
    assert str(src / 'new_file.txt') in copy_srcs
    assert str(src / 'file2.txt') not in copy_srcs

    # Verify move detected
    assert len(comp2.files_to_move) == 1
    m_src, m_tgt = comp2.files_to_move[0]
    assert str(m_src) == str(tgt / 'will_move.txt')
    assert str(m_tgt) == str(tgt / 'archive' / 'will_move.txt')

    # Verify delete detected
    del_targets = [str(d) for d in comp2.files_to_delete]
    assert str(tgt / 'will_delete.txt') in del_targets

    # Execute sync
    sync2 = SyncDirs(
        files_to_copy=comp2.files_to_copy,
        files_to_move=comp2.files_to_move,
        files_to_delete=comp2.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        confirm_sync=False,
    )

    assert len(sync2.files_copied) == 2
    assert all(ok for _, ok in sync2.files_copied)
    assert len(sync2.files_moved) == 1
    assert all(ok for _, ok in sync2.files_moved)
    assert len(sync2.files_deleted) == 1
    assert all(ok for _, ok in sync2.files_deleted)

    # Final target assertions
    assert (tgt / 'file1.txt').read_text() == 'content 1 updated!'
    assert (tgt / 'new_file.txt').read_text() == 'brand new file'
    assert (tgt / 'archive' / 'will_move.txt').read_text() == 'content to be moved'
    assert not (tgt / 'will_move.txt').exists()
    assert not (tgt / 'will_delete.txt').exists()

    # Final mirror check
    assert mirror.exists(str(tgt), str(tgt / 'archive' / 'will_move.txt'))
    assert not mirror.exists(str(tgt), str(tgt / 'will_move.txt'))
    assert not mirror.exists(str(tgt), str(tgt / 'will_delete.txt'))


def test_e2e_special_characters_and_readonly_files(tmp_path):
    """End-to-end integration test: Handling special characters, unicode, spaces, and read-only attributes."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    # 1. Special characters & unicode in filename
    special_file = src / 'Report [2026] #1 - unicode & spaces!.txt'
    special_file.write_text('unicode content with symbols: [alpha, beta, gamma]', encoding='utf-8')

    # 2. Readonly file in source and target
    ro_file = src / 'readonly_doc.txt'
    ro_file.write_text('readonly text')
    os.chmod(ro_file, stat.S_IREAD)  # Make readonly

    mirror = MirrorDatabase(path=str(tmp_path / 'mirror.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    comp = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])
    SyncDirs(
        files_to_copy=comp.files_to_copy,
        files_to_move=comp.files_to_move,
        files_to_delete=comp.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        confirm_sync=False,
    )

    tgt_special = tgt / special_file.name
    assert tgt_special.exists()
    assert tgt_special.read_text(encoding='utf-8') == 'unicode content with symbols: [alpha, beta, gamma]'

    tgt_ro = tgt / 'readonly_doc.txt'
    assert tgt_ro.exists()
    assert tgt_ro.read_text() == 'readonly text'

    # Now test overwriting and deleting a readonly target file
    # Unlock source readonly for modification
    os.chmod(ro_file, stat.S_IWRITE | stat.S_IREAD)
    ro_file.write_text('readonly text updated')
    # Make target readonly
    os.chmod(tgt_ro, stat.S_IREAD)

    comp2 = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])
    SyncDirs(
        files_to_copy=comp2.files_to_copy,
        files_to_move=comp2.files_to_move,
        files_to_delete=comp2.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        confirm_sync=False,
    )

    # Must have overwritten the readonly target cleanly!
    assert tgt_ro.read_text() == 'readonly text updated'

    # Clean up permissions so pytest tmp_path cleanup succeeds
    os.chmod(ro_file, stat.S_IWRITE | stat.S_IREAD)
    os.chmod(tgt_ro, stat.S_IWRITE | stat.S_IREAD)


def test_e2e_cooperative_cancellation_during_sync(tmp_path):
    """End-to-end integration test: Cooperative cancellation halts synchronization safely."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    # Create 20 files
    files = []
    for i in range(20):
        f = src / f'item_{i:02d}.txt'
        f.write_text(f'data {i}')
        files.append((CstmPath(f, root_dir=src), CstmPath(tgt / f.name, root_dir=tgt)))

    mirror = MirrorDatabase(path=str(tmp_path / 'mirror.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY],
        confirm_sync=False,
    )

    sync.files_requested_to_copy = [(str(s), str(t)) for s, t in files]
    sync.cancel()
    sync.copy_files()

    # With cancel() called before execution, 0 files should have been copied
    assert len(sync.files_copied) == 0
    assert not (tgt / 'item_00.txt').exists()


def test_e2e_sync_without_mirror_db(tmp_path):
    """End-to-end integration test: Full compare and sync completely without mirror DB."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    # File to copy
    (src / 'standalone_copy.txt').write_text('copy without mirror')

    # File to move
    (src / 'sub' / 'standalone_move.txt').parent.mkdir()
    (src / 'sub' / 'standalone_move.txt').write_text('move without mirror')
    shutil.copy2(src / 'sub' / 'standalone_move.txt', tgt / 'standalone_move.txt')

    # File to delete
    (tgt / 'standalone_delete.txt').write_text('obsolete without mirror')

    mirror = MirrorDatabase(path=str(tmp_path / 'unused_mirror.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    # Compare strictly from filesystem (no mirror used, no increment)
    compare = CompareDirs(
        mirror=mirror,
        dirs=dirs,
        exclusions=[],
        comparison_method=CompareMethod.METADATA,
        use_mirror=False,
        increment_mirror=False,
        rebuild_mirror=False,
    )

    assert len(compare.files_to_copy) == 1
    assert len(compare.files_to_move) == 1
    assert len(compare.files_to_delete) == 1

    # Sync without updating mirror
    sync = SyncDirs(
        files_to_copy=compare.files_to_copy,
        files_to_move=compare.files_to_move,
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY, Action.MOVE, Action.DELETE],
        increment_mirror=False,
        confirm_sync=False,
    )

    assert len(sync.files_copied) == 1
    assert len(sync.files_moved) == 1
    assert len(sync.files_deleted) == 1

    # Verify target directory is updated
    assert (tgt / 'standalone_copy.txt').read_text() == 'copy without mirror'
    assert (tgt / 'sub' / 'standalone_move.txt').read_text() == 'move without mirror'
    assert not (tgt / 'standalone_move.txt').exists()
    assert not (tgt / 'standalone_delete.txt').exists()

    # Mirror table for target should NOT exist or be empty
    assert not mirror.exists_table(str(tgt)) or mirror.size(str(tgt)) == 0


def test_e2e_sync_with_rebuild_mirror(tmp_path):
    """End-to-end integration test: rebuild_mirror wipes stale mirror table and builds fresh index."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    (src / 'active.txt').write_text('active content')
    shutil.copy2(src / 'active.txt', tgt / 'active.txt')

    mirror = MirrorDatabase(path=str(tmp_path / 'rebuild_mirror.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    # Artificially inject stale/ghost record into mirror by creating, indexing, and unlinking
    ghost_file = tgt / 'ghost_record.txt'
    ghost_file.write_text('ghost content')
    ghost_path = str(ghost_file)
    mirror.add_path(str(tgt), [CstmPath(ghost_path, root_dir=tgt)])
    assert mirror.exists(str(tgt), ghost_path)
    ghost_file.unlink()  # Now it only exists in mirror DB, not on disk!

    # Rebuild mirror during comparison
    compare = CompareDirs(
        mirror=mirror,
        dirs=dirs,
        exclusions=[],
        comparison_method=CompareMethod.METADATA,
        use_mirror=False,
        increment_mirror=False,
        rebuild_mirror=True,
    )

    # Ghost record should have been wiped by rebuild!
    assert not mirror.exists(str(tgt), ghost_path)
    # Real file should now be in the rebuilt mirror
    assert mirror.exists(str(tgt), str(tgt / 'active.txt'))
    # Files are identical, so 0 copy/move/delete
    assert len(compare.files_to_copy) == 0
    assert len(compare.files_to_move) == 0
    assert len(compare.files_to_delete) == 0


def test_e2e_compare_content_vs_metadata(tmp_path):
    """End-to-end integration test: Differentiating between metadata and hash content comparison."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    # Case 1: Same content, but different timestamp
    f_same = src / 'same_content.txt'
    f_same_tgt = tgt / 'same_content.txt'
    f_same.write_text('exact same content')
    f_same_tgt.write_text('exact same content')
    # Make source newer by 50 seconds
    now = time.time()
    os.utime(f_same, (now, now))
    os.utime(f_same_tgt, (now - 50, now - 50))

    # Case 2: Same timestamp and size, but different content
    f_diff = src / 'diff_content.txt'
    f_diff_tgt = tgt / 'diff_content.txt'
    f_diff.write_bytes(b'AAAA1234')
    f_diff_tgt.write_bytes(b'BBBB1234')
    os.utime(f_diff, (now - 100, now - 100))
    os.utime(f_diff_tgt, (now - 100, now - 100))

    mirror = MirrorDatabase(path=str(tmp_path / 'method_test.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    # --- METADATA COMPARISON ---
    comp_meta = CompareDirs(
        mirror=mirror,
        dirs=dirs,
        exclusions=[],
        comparison_method=CompareMethod.METADATA,
        use_mirror=False,
    )
    meta_copy_srcs = [str(s) for s, _ in comp_meta.files_to_copy]

    # Under metadata comparison:
    # - Case 1 is flagged because timestamp differs
    assert str(f_same) in meta_copy_srcs
    # - Case 2 is NOT flagged because size and timestamp are identical
    assert str(f_diff) not in meta_copy_srcs

    # --- CONTENT COMPARISON ---
    comp_content = CompareDirs(
        mirror=mirror,
        dirs=dirs,
        exclusions=[],
        comparison_method=CompareMethod.CONTENT,
        use_mirror=False,
    )
    content_copy_srcs = [str(s) for s, _ in comp_content.files_to_copy]

    # Under content comparison:
    # - Case 1 is NOT flagged because hash/content is identical despite different timestamps!
    assert str(f_same) not in content_copy_srcs
    # - Case 2 IS flagged because contents differ!
    assert str(f_diff) in content_copy_srcs


def test_e2e_selective_default_actions(tmp_path):
    """End-to-end integration test: Verifies that only chosen DefaultActions are executed."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    # 1. New file (COPY)
    (src / 'new_doc.txt').write_text('new doc')

    # 2. Moved file (MOVE)
    (src / 'sub' / 'moved_doc.txt').parent.mkdir()
    (src / 'sub' / 'moved_doc.txt').write_text('moved doc')
    shutil.copy2(src / 'sub' / 'moved_doc.txt', tgt / 'moved_doc.txt')

    # 3. Obsolete file (DELETE)
    (tgt / 'old_doc.txt').write_text('old doc')

    mirror = MirrorDatabase(path=str(tmp_path / 'selective.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])
    assert len(compare.files_to_copy) == 1
    assert len(compare.files_to_move) == 1
    assert len(compare.files_to_delete) == 1

    # --- RUN 1: ONLY COPY ---
    sync_copy_only = SyncDirs(
        files_to_copy=compare.files_to_copy,
        files_to_move=compare.files_to_move,
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY],  # Only COPY selected!
        confirm_sync=False,
    )
    assert len(sync_copy_only.files_copied) == 1
    assert len(sync_copy_only.files_moved) == 0
    assert len(sync_copy_only.files_deleted) == 0

    assert (tgt / 'new_doc.txt').exists()
    assert (tgt / 'moved_doc.txt').exists()  # Not moved yet!
    assert (tgt / 'old_doc.txt').exists()  # Not deleted yet!

    # --- RUN 2: ONLY MOVE ---
    sync_move_only = SyncDirs(
        files_to_copy=compare.files_to_copy,
        files_to_move=compare.files_to_move,
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.MOVE],  # Only MOVE selected!
        confirm_sync=False,
    )
    assert len(sync_move_only.files_copied) == 0
    assert len(sync_move_only.files_moved) == 1
    assert len(sync_move_only.files_deleted) == 0

    assert (tgt / 'sub' / 'moved_doc.txt').exists()
    assert not (tgt / 'moved_doc.txt').exists()  # Successfully moved
    assert (tgt / 'old_doc.txt').exists()  # Still not deleted!

    # --- RUN 3: ONLY DELETE ---
    sync_delete_only = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.DELETE],  # Only DELETE selected!
        confirm_sync=False,
    )
    assert len(sync_delete_only.files_deleted) == 1
    assert not (tgt / 'old_doc.txt').exists()  # Finally deleted


def test_e2e_empty_directory_pruning_preserves_root(tmp_path):
    """End-to-end integration test: Deleting files prunes empty subdirectories up to root safely."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    # Setup nested directories in target with an obsolete file
    deep_tgt_dir = tgt / 'level1' / 'level2' / 'level3'
    deep_tgt_dir.mkdir(parents=True)
    obsolete_file = deep_tgt_dir / 'obsolete.txt'
    obsolete_file.write_text('delete me')

    mirror = MirrorDatabase(path=str(tmp_path / 'prune.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])
    assert len(compare.files_to_delete) == 1

    sync = SyncDirs(
        files_to_copy=[],
        files_to_move=[],
        files_to_delete=compare.files_to_delete,
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.DELETE],
        confirm_sync=False,
    )

    assert len(sync.files_deleted) == 1
    assert not obsolete_file.exists()
    # The empty nested directories must have been pruned!
    assert not (tgt / 'level1').exists()
    # But target root must ALWAYS remain!
    assert tgt.exists()
    assert tgt.is_dir()


def test_e2e_jit_resilience_missing_source_during_batch(tmp_path):
    """End-to-end integration test: If a source file is removed mid-batch, other files succeed cleanly."""
    src = tmp_path / 'Source'
    tgt = tmp_path / 'Target'
    src.mkdir()
    tgt.mkdir()

    f1 = src / 'good1.txt'
    f2 = src / 'vanished.txt'
    f3 = src / 'good2.txt'

    f1.write_text('content 1')
    f2.write_text('content 2')
    f3.write_text('content 3')

    mirror = MirrorDatabase(path=str(tmp_path / 'jit.db'))
    dirs = [DirectoryPair(source=str(src), target=str(tgt))]

    compare = CompareDirs(mirror=mirror, dirs=dirs, exclusions=[])
    assert len(compare.files_to_copy) == 3

    # Simulate external file deletion right before SyncDirs runs
    f2.unlink()

    sync = SyncDirs(
        files_to_copy=compare.files_to_copy,
        files_to_move=[],
        files_to_delete=[],
        mirror=mirror,
        dirs=dirs,
        default_actions=[Action.COPY],
        confirm_sync=False,
    )

    # 2 succeeded, 1 failed gracefully without crashing
    copied_map = dict(sync.files_copied)
    assert copied_map[(str(f1), str(tgt / 'good1.txt'))] is True
    assert copied_map[(str(f3), str(tgt / 'good2.txt'))] is True
    assert copied_map[(str(f2), str(tgt / 'vanished.txt'))] is False

    assert (tgt / 'good1.txt').read_text() == 'content 1'
    assert (tgt / 'good2.txt').read_text() == 'content 3'
    assert not (tgt / 'vanished.txt').exists()
