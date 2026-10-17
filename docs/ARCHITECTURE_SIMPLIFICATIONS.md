# Architecture Simplification Proposals

This document records the architectural complexity audit conducted on 2026-10-17. These recommendations are preserved for future core/backend refactoring cycles.

---

## 1. Dual Thread Cancellation Systems & `sys.settrace`
- **Location**: [`src/gui/worker_thread.py`](../src/gui/worker_thread.py) vs [`src/core/backend.py`](../src/core/backend.py)
- **Current Pattern**:
  `KillableThread` hooks into the Python interpreter on every line via `sys.settrace(self.globaltrace)` to raise `SystemExit` asynchronously when killed. Concurrently, `SyncDirs` implements cooperative cancellation via `cancel_requested: threading.Event()`.
- **Issues**:
  - `sys.settrace` adds measurable interpreter overhead to every loop and function call.
  - Asynchronous termination risks interrupting atomic operations or leaving orphaned handles.
- **Proposal**:
  Rely exclusively on cooperative cancellation (`threading.Event`) checked at file loop iterations. Remove `KillableThread` and `sys.settrace` entirely.

---

## 2. JIT "Self-Healing" & Phantom Record Handling in File Loops
- **Location**: [`src/core/backend.py`](../src/core/backend.py) (`copy_files` and `move_files`)
- **Current Pattern**:
  Inside `copy_files` and `move_files`, complex branches perform `os.path.isfile(source)` and `os.path.isfile(target)` queries across remote SMB shares to detect if the mirror was stale, self-healing records mid-copy.
- **Issues**:
  - Mixes execution logic with cache reconciliation.
  - Adds repetitive, blocking network I/O during execution for non-existent target files.
- **Proposal**:
  Perform phantom pruning and mirror validation exclusively during `CompareDirs`. When `SyncDirs` executes, the work list should be considered authoritative.

---

## 3. Subclassing `pathlib.Path` in `CstmPath`
- **Location**: [`src/core/file.py`](../src/core/file.py)
- **Current Pattern**:
  `CstmPath` subclasses `pathlib.Path`, overriding `__truediv__` and `__rtruediv__` to carry state (`root_dir`, `_stats`, `_stats_hash`, `_stat_failed`).
- **Issues**:
  - `pathlib.Path` internal factory constructors (`__new__`, `_from_parts`) evolve across Python versions (3.10 vs 3.12 vs 3.13), making subclassing fragile.
  - Standard path operations frequently drop custom attributes when returning parent or resolved paths.
- **Proposal**:
  Adopt **composition over inheritance**: Create a lightweight `FileEntry` dataclass holding `path: Path`, `root_dir: Path`, and cached `stats: Stats | None`.

---

## 4. Dynamic Table Generation & Pickled Blobs in SQLite Mirror
- **Location**: [`src/core/mirror.py`](../src/core/mirror.py)
- **Current Pattern**:
  `MirrorDatabase` uses regex string sanitization to create dynamic table names for every unique root directory and exclusion configuration, storing entries via `sqlitedict` (pickled objects).
- **Issues**:
  - Table proliferation and abandoned orphaned tables when exclusion settings change.
  - Inability to perform standard relational indexing, joins, or bulk parameterized queries.
- **Proposal**:
  Replace `sqlitedict` with a single, clean SQLite table:
  ```sql
  CREATE TABLE IF NOT EXISTS mirror_cache (
      root_dir TEXT NOT NULL,
      rel_path TEXT NOT NULL,
      stats_hash TEXT NOT NULL,
      PRIMARY KEY (root_dir, rel_path)
  );
  ```

---

## 5. Global Filename Frequency Heuristic for Move Detection
- **Location**: [`src/core/backend.py`](../src/core/backend.py) (`link_files`)
- **Current Pattern**:
  Calculates `Counter(f.name)` across all files in source and target. If a filename is globally unique across the whole directory tree, it tests for a move.
- **Issues**:
  - If any file name occurs more than once (e.g. `index.html`, `main.py`, `photo.jpg`), the heuristic fails silently and falls back to delete + re-copy.
  - Counting all filenames across 50,000+ files requires multiple memory-intensive passes.
- **Proposal**:
  Match moves directly by hash dictionary lookup (`target_by_hash = {f.stats_hash: f for f in files_only_in_target}`). Any source file matching an existing target's hash is an unambiguous move/rename in $O(1)$ time.

---

## 6. Duplicated Progress and Error Loops Across File Operations
- **Location**: [`src/core/backend.py`](../src/core/backend.py) (`copy_files`, `move_files`, `delete_files`)
- **Current Pattern**:
  Each of the three methods implements identical boilerplate for cancellation checking, progress intervals, path length formatting, and exception collection (~120 duplicated lines).
- **Proposal**:
  Consolidate into a unified `_execute_batch(items, action_name, action_fn)` pipeline that encapsulates progress, retry handling, and logging.
