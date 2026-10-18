# Synchronization Robustness & JIT Self-Healing

This document explains how FastMirror handles real-world edge cases during the
synchronization pipeline. It covers what happens when files appear, vanish, or
change between the comparison phase and the sync phase — and how the engine
recovers gracefully without user intervention.

For the general architecture overview, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Table of Contents

1. [The Problem: Filesystem Drift](#the-problem-filesystem-drift)
2. [Two-Phase Pipeline Overview](#two-phase-pipeline-overview)
3. [Execution Ordering & Why It Matters](#execution-ordering--why-it-matters)
4. [JIT Self-Healing Mechanisms](#jit-self-healing-mechanisms)
   - [Copy: Target Already Exists & Matches](#copy-target-already-exists--matches)
   - [Copy: Source Vanished Before Transfer](#copy-source-vanished-before-transfer)
   - [Move: Source Already Gone, Target Exists](#move-source-already-gone-target-exists)
   - [Move: Both Source and Target Missing](#move-both-source-and-target-missing)
   - [Delete: File Already Missing](#delete-file-already-missing)
5. [Atomic Writes & Crash Safety](#atomic-writes--crash-safety)
6. [Permission Recovery on Windows](#permission-recovery-on-windows)
7. [Network Resilience & Retry Strategy](#network-resilience--retry-strategy)
8. [Mirror Cache Consistency](#mirror-cache-consistency)
9. [Empty Directory Pruning Safety](#empty-directory-pruning-safety)
10. [Cooperative Cancellation](#cooperative-cancellation)
11. [Corner-Case Reference Table](#corner-case-reference-table)
12. [Known Limitations](#known-limitations)

---

## The Problem: Filesystem Drift

FastMirror operates in two sequential phases: **compare** then **sync**. Between
these phases — or even *during* the sync batch — the filesystem may change:

- The user edits, moves, or deletes files while the sync is running.
- Another program (antivirus, cloud sync, indexer) modifies files.
- A previous partial sync already placed some files at the target.
- The NAS/network share goes to sleep and reconnects.
- A file listed by the mirror database no longer exists on disk.

Without defensive handling, any of these situations would cause crashes, data
corruption, or stale mirror entries. The engine addresses each with targeted
**just-in-time (JIT) checks** right before performing each operation.

---

## Two-Phase Pipeline Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 1 — CompareDirs                                      │
│                                                             │
│   Scan Source FS ──► Scan Target (FS or Mirror DB)          │
│         │                      │                            │
│         └──────► Link Files ◄──┘                            │
│                      │                                      │
│                Compare Linked Files                         │
│                      │                                      │
│            ┌─────────┼─────────┐                            │
│             ▼         ▼         ▼                            │
│          to_copy   to_move   to_delete                      │
└────────────┬─────────┬─────────┬────────────────────────────┘
             │         │         │
             ▼         ▼         ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 2 — SyncDirs                                         │
│                                                             │
│  User Confirmation ──► Move ──► Delete ──► Copy ──► Prune   │
│                                                             │
│  Each file operation has JIT pre-flight checks:             │
│  • Does the source still exist?                             │
│  • Is the target already up-to-date?                        │
│  • Has the filesystem already reached the desired state?    │
└─────────────────────────────────────────────────────────────┘
```

---

## Execution Ordering & Why It Matters

SyncDirs executes operations in this deliberate order:

| Order | Operation | Rationale |
|:-----:|-----------|-----------|
| 1 | **Move** | Relocates existing target files to new paths. On the same volume this is an instant metadata rename (`os.rename`), freeing the old path immediately. |
| 2 | **Delete** | Removes obsolete files, reclaiming disk space on the target drive. |
| 3 | **Copy** | Transfers new and modified files. Runs last so it benefits from maximum available disk space and clean paths. |
| 4 | **Prune** | Removes any empty directories left behind by moves and deletes. |

This ordering prevents path collisions (a copy landing where a move should
rename) and maximizes available storage before the heaviest I/O phase.

---

## JIT Self-Healing Mechanisms

All JIT checks live in the `SyncDirs` action methods in
[`backend.py`](../src/core/backend.py). They run **per-file, immediately before
the operation**, catching any drift since the compare phase.

### Copy: Target Already Exists & Matches

**Location**: [`_copy_file`](../src/core/backend.py) — the JIT block before `robust_copy`.

**Scenario**: Between compare and sync, the target file was placed by another
process, a previous partial run, or manual user action.

**What happens**:

```
Pre-flight check:
  Is target already a file on disk?
    ├─ Yes → Compare source_stat vs target_stat
    │         (size must match, mtime within 2-second FAT32 tolerance)
    │   ├─ Match → Skip the copy, update mirror entry, return success
    │   └─ No match → Proceed with normal robust_copy
    └─ No → Proceed with normal robust_copy
```

**Why it matters**: Avoids redundantly copying gigabytes over a slow NAS link
when the file is already there and identical. The 2-second `mtime` tolerance
accounts for FAT32 and SMB timestamp rounding.

### Copy: Source Vanished Before Transfer

**Location**: [`_copy_file`](../src/core/backend.py) — the first guard.

**Scenario**: A transient file (temp download, editor swap file) was captured
during the scan but was removed before the sync batch reached it.

**What happens**:

```
Pre-flight check:
  Does source file still exist on disk?
    ├─ No → Log warning, return failure, continue batch
    └─ Yes → Proceed with copy
```

**Why it matters**: Without this check, `robust_copy` would raise
`FileNotFoundError`, which `_execute_batch` would catch as a generic exception.
The explicit JIT check provides a clearer warning log and cleaner return value.

### Move: Source Already Gone, Target Exists

**Location**: [`_move_file`](../src/core/backend.py) — the JIT block.

**Scenario**: The user (or another tool) already moved the file externally. The
old path is gone but the new path already has the file.

**What happens**:

```
Pre-flight check:
  Does source file exist?
    ├─ No → Does target file exist?
    │   ├─ Yes → Self-heal: update mirror (old→new), return success
    │   └─ No → Phantom: purge stale mirror record, return failure
    └─ Yes → Proceed with normal robust_move
```

**Why it matters**: The mirror database expected the file at the old path.
Without healing, subsequent syncs would keep trying to move a non-existent file
and generate repeated errors.

### Move: Both Source and Target Missing

**Location**: Same JIT block in [`_move_file`](../src/core/backend.py).

**Scenario**: The file was deleted entirely — from both the old and new
locations — likely by the user cleaning up outside of FastMirror.

**What happens**: The phantom mirror record is purged so it doesn't pollute
future comparisons. The operation is reported as a failure since no useful work
could be done.

### Delete: File Already Missing

**Location**: [`_delete_file`](../src/core/backend.py).

**Scenario**: The target file was already deleted externally (by the user,
antivirus quarantine, or another sync tool).

**What happens**:

```
Pre-flight check:
  Does target file exist on disk?
    ├─ No → Purge phantom mirror entry, return success (idempotent)
    └─ Yes → Proceed with normal robust_delete
```

**Why it matters**: Deletion is inherently idempotent. If the file is already
gone, the desired state is already achieved. The mirror is cleaned up to prevent
the phantom record from generating false "only in target" entries in future
comparisons.

---

## Atomic Writes & Crash Safety

`robust_copy` in [`file_ops.py`](../src/core/file_ops.py) uses a **write-to-temp-then-replace** pattern:

```
1.  Write to <target>.tmp     (shutil.copy2 to staging file)
2.  os.replace(<target>.tmp, <target>)   (atomic rename)
```

This ensures that:

- **The target is never partially written**. If the process crashes mid-copy,
  only the `.tmp` file is corrupt — the real target either doesn't exist yet
  (first backup) or retains its previous version.
- **Stale `.tmp` files are cleaned up** on the next attempt (pre-cleaned at the
  top of `robust_copy` and excluded from `CstmPath.get_from_dir` scans).
- **A `finally` block** guarantees cleanup of the `.tmp` file even if the thread
  is aborted via `SystemExit`.

---

## Permission Recovery on Windows

When operations fail due to file attribute restrictions (read-only, hidden,
system), `file_ops.py` automatically attempts recovery before retrying:

```
unlock_file_attributes(path):
  1. Win32 API: SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL)
  2. Fallback: os.chmod(path, stat.S_IWRITE)
```

This is invoked:

- On the **target** before overwriting via `robust_copy`.
- On **both source and target** before moving via `robust_move`.
- On the **target** before deleting via `robust_delete`.

---

## Network Resilience & Retry Strategy

All three file operations (`robust_copy`, `robust_move`, `robust_delete`)
implement the same retry pattern:

```
Parameters:
  max_retries     = 3     (configurable)
  initial_delay   = 1.0s  (configurable)
  backoff_factor  = 2.0   (configurable)

Retry sequence:  1s → 2s → 4s  (then raise)

Exceptions that trigger retries:
  - OSError (network drops, timeout, sharing violations)
  - PermissionError (file locked by antivirus, indexer)

Exceptions that fail immediately (no retry):
  - FileNotFoundError (source genuinely doesn't exist)
  - winerror 2 or 3 (path not found — permanent)
```

---

## Mirror Cache Consistency

The mirror database (SQLite) stays consistent with the filesystem through
several mechanisms:

| Event | Mirror Update |
|-------|--------------|
| File copied successfully | `mirror.add_path(root, target)` — upserts the new path + stats hash |
| File moved successfully | `mirror.replace_path(root, old, new)` — atomic delete + insert |
| File deleted successfully | `mirror.remove_path(root, target)` — removes the entry |
| JIT self-heal (copy skip) | `mirror.add_path(root, target)` — heals the missing entry |
| JIT self-heal (move) | `mirror.replace_path(root, old, new)` — heals the stale entry |
| Phantom cleanup (delete) | `mirror.remove_path(root, target)` — purges ghost |
| Phantom cleanup (move) | `mirror.remove_path(root, source)` — purges ghost |
| Exclusion rules changed | Hash mismatch detected → existing cache for root is wiped |
| Rebuild requested | `mirror.reset(root)` → full FS rescan → fresh `add_path` batch |

---

## Empty Directory Pruning Safety

After files are deleted or moved, the engine prunes empty directories upward:

```
For each directory that contained a deleted/moved file:
  while directory is empty:
    ├─ Is it a protected root (source or target root)?  → STOP
    ├─ parent == current (UNC share root)?              → STOP
    ├─ Directory doesn't exist (already pruned)?        → ascend to parent
    ├─ Directory is empty?                              → rmdir, ascend
    └─ Directory is NOT empty?                          → STOP
```

**Safety guarantees**:

- **Root directories are never deleted**. Both source and target roots are added
  to a `protected_roots` set before pruning begins.
- **UNC root infinite loop prevention**. On network shares like `\\server\share`,
  ascending past the root would loop forever (`parent == current`). The explicit
  guard breaks the loop.
- **Subdirectories pruned before parents**. Directories are sorted by path
  length (longest first), ensuring children are removed before their parents are
  tested.

---

## Cooperative Cancellation

Both `CompareDirs` and `SyncDirs` support cooperative cancellation via
`threading.Event`:

- **Between phases**: Checked at every phase boundary (after scan, after link,
  after compare, after each sync operation type).
- **Inside batch loops**: Checked at every file iteration in `_execute_batch`.
- **During popup wait**: Checked every 200ms while waiting for the user
  confirmation popup.

Cancellation is **purely cooperative** — it never kills threads or interrupts
I/O mid-operation. The current file operation always completes before the
cancellation is honored, preventing partial writes and file corruption.

```
Cancellation flow:
  cancel_requested.set()
    → Current file operation finishes normally
    → Next loop iteration checks is_set() → breaks
    → Remaining files in batch are skipped
    → Remaining phases are skipped
    → SyncDirs logs "aborted due to cancellation request"
```

---

## Corner-Case Reference Table

Quick lookup of all handled edge cases:

| # | Scenario | Handler | Outcome |
|---|----------|---------|---------|
| 1 | Source file removed between compare & sync | `_copy_file` JIT guard | Skipped with warning, batch continues |
| 2 | Target already exists and matches source | `_copy_file` JIT self-heal | Copy skipped, mirror healed |
| 3 | File already moved externally | `_move_file` JIT self-heal | Mirror healed, success returned |
| 4 | File deleted from both source and target | `_move_file` phantom handler | Mirror purged, failure returned |
| 5 | Target file already deleted externally | `_delete_file` JIT guard | Mirror purged, success (idempotent) |
| 6 | Read-only or hidden file on target | `unlock_file_attributes` | Attributes cleared, retry succeeds |
| 7 | Network share drops mid-transfer | `robust_copy/move/delete` retries | Exponential backoff, 3 attempts |
| 8 | Incomplete `.tmp` file from previous crash | `robust_copy` pre-cleanup | Stale `.tmp` removed before new write |
| 9 | Process crash during copy | `robust_copy` atomic staging | Only `.tmp` is corrupt, target untouched |
| 10 | `filecmp` stale cache | `filecmp.clear_cache()` at start | Fresh comparisons every run |
| 11 | User cancels during popup wait | `finally` block | Popup destroyed via main thread |
| 12 | Progress callback raises exception | `contextlib.suppress` | Exception swallowed, sync continues |
| 13 | Path longer than 259 characters | `check_length` in error context | Logged as error detail for diagnosis |
| 14 | Empty dirs after delete/move | `delete_empty_dirs` with root guard | Pruned up to (but never including) root |
| 15 | Parent == current on UNC root | `parent == current` check | Loop terminates cleanly |
| 16 | Overlapping target directories | `get_dirs_from_path` specificity scoring | Most-specific (deepest) root wins |
| 17 | Mirror exclusion rules changed | Exclusions hash mismatch | Stale cache auto-invalidated |
| 18 | SQLite DB locked by another process | `timeout=30.0` on connect | Waits up to 30s before error |

---

## Known Limitations

1. **Cross-volume moves are not atomic**. When `robust_move` operates across
   different drives, `shutil.move` falls back to `copy2 + unlink`. If the
   process crashes during the copy phase, a partial file may remain at the
   target. The retry cleanup logic detects size mismatches and removes
   incomplete targets, but a small window of vulnerability exists. In practice,
   move operations in FastMirror almost exclusively involve files within the
   same target volume (reorganizing after move detection), making this a
   theoretical rather than practical concern.

2. **Metadata comparison can miss same-size same-mtime changes**. When using
   `CompareMethod.METADATA`, two files with identical size and modification
   timestamp but different content will not be detected as different. This is by
   design — users who need byte-level verification can switch to
   `CompareMethod.CONTENT`.

3. **No concurrent sync stress testing**. While the SQLite WAL mode supports
   concurrent readers and the 30-second busy timeout handles lock contention,
   there are no automated tests exercising truly concurrent sync operations on
   the same target directory.
