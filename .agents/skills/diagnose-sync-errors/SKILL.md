---
name: diagnose-sync-errors
description: >-
  Diagnose and debug file synchronization failures, DirectoryPair resolution errors, path mismatch exceptions,
  and SQLite database lock issues in FastMirror. Use when a user reports sync, copy, move, or mirror errors.
---

# Diagnosing Synchronization & Backup Errors

This runbook guides you through identifying, isolating, and repairing errors reported during backup operations.

---

## 1. Common Exception Patterns & Root Causes

### A. Root Folder Identification Failure
**Log signature:**
```text
There was an error while moving file <path>. Exception: Could not identify root folders of path <path>. Dirs: [...]
```
- **Root Cause**: The file being moved does not match any configured `DirectoryPair.source` or `DirectoryPair.target`.
- **Key Suspects**:
  1. A UNC network path was passed to `os.path.commonpath`, which raised `ValueError: Can't mix absolute and relative paths`.
  2. Trailing slash discrepancy (`\\share\dir\` vs `\\share\dir`).
  3. Case sensitivity mismatch on Windows drive letters (`d:\` vs `D:\`).
  4. Path was transformed by `os.path.realpath` while offline or across symlinks.
- **Remedy**:
  - Verify `_to_path(path).is_relative_to(root)` is used instead of `commonpath`.
  - Check specificity scoring in `get_dirs_from_path`.
  - Run `uv run pytest tests/test_paths.py -k "test_get_dirs_from_path"`.

---

### B. Windows File Access Denied (`WinError 5`)
**Log signature:**
```text
PermissionError: [WinError 5] Access is denied: <path>
```
- **Root Cause**: The target file or source file has the Windows Read-Only attribute set (e.g. photos imported from SD card or read-only archive).
- **Remedy**:
  - Check if `SetFileAttributesW` is called to clear `FILE_ATTRIBUTE_READONLY` before overwriting or moving.
  - In `src/core/backend.py`, ensure:
    ```python
    import ctypes
    FILE_ATTRIBUTE_NORMAL = 0x80
    ctypes.windll.kernel32.SetFileAttributesW(target_path, FILE_ATTRIBUTE_NORMAL)
    ```

---

### C. File In Use By Another Process (`WinError 32`)
**Log signature:**
```text
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: <data/local_mirror.db>
```
- **Root Cause**: A previously opened SQLite connection or file stream was not closed.
- **Key Suspect**: `with sqlite3.connect(...) as conn:` was used without `contextlib.closing(conn)`.
- **Remedy**:
  - Wrap all SQLite connections in `contextlib.closing(sqlite3.connect(...))`.
  - Verify that `mirror_db.close()` or connection closing occurs before vacuuming or deleting.

---

### D. Cross-Drive Move Failure (`WinError 17`)
**Log signature:**
```text
OSError: [WinError 17] The system cannot move the file to a different disk drive
```
- **Root Cause**: Code attempted to use `os.rename()` or `Path.rename()` between two different drive letters or between a local drive and a UNC share.
- **Remedy**:
  - Use `shutil.move()`, which safely falls back to copy + delete across filesystems.

---

### E. Database Locked (`sqlite3.OperationalError`)
**Log signature:**
```text
sqlite3.OperationalError: database is locked
```
- **Root Cause**: Concurrent threads accessing SQLite without WAL mode enabled, or a transaction was held open for too long.
- **Remedy**:
  - Ensure `PRAGMA journal_mode=WAL;` is enabled during database setup.
  - Set a connection timeout: `sqlite3.connect(path, timeout=30.0)`.

---

## 2. Step-by-Step Diagnostic Workflow
When an error occurs:
1. **Extract the exact paths**: Find the source path, target path, and configured directory pairs from the log.
2. **Reproduce in a test**:
   - Add a minimal unit test to `tests/test_paths.py` or `tests/test_mirror.py` using synthetic paths that reproduce the exact structure without needing actual network hardware.
3. **Trace through `_to_path` and `get_dirs_from_path`**:
   - Verify that `is_relative_to` correctly identifies the relationship.
4. **Run the quality suite**:
   - `uv run pytest`
   - `uv run ruff check .`
