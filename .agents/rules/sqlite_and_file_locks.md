# SQLite & File Lock Rules on Windows

The application uses an SQLite database (`local_mirror.db` / `MirrorDatabase`) to track mirrored file paths, hashes, and timestamps.
Windows enforces mandatory file locking, making file handle hygiene critical.

Adhere to the following rules:

---

## 1. The Python `sqlite3.connect()` Context Manager Trap
In Python's `sqlite3` library:
```python
# WARNING: THIS DOES NOT CLOSE THE CONNECTION!
with sqlite3.connect(db_path) as conn:
    conn.execute(...)
# conn is STILL OPEN here!
```
- The context manager on a connection object only controls **transactions** (`commit` / `rollback`). It **NEVER calls `conn.close()`**.
- On Windows, leaving a connection open keeps an active OS handle to `local_mirror.db`.
- Attempting to delete, vacuum, rename, or copy the database while a connection is open results in:
  ```text
  PermissionError: [WinError 32] The process cannot access the file because it is being used by another process
  ```

### The Mandatory Solution
Always wrap short-lived connections in `contextlib.closing`, or ensure `conn.close()` is called in a `finally` block:
```python
import contextlib
import sqlite3

with contextlib.closing(sqlite3.connect(self.path, timeout=30.0)) as conn:
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.commit()
```

---

## 2. WAL Mode (`Write-Ahead Logging`)
- SQLite should operate in WAL mode (`PRAGMA journal_mode=WAL;`).
- WAL mode allows multiple concurrent readers to access the database without blocking the background writer thread.
- Note that WAL mode produces temporary companion files:
  - `<dbname>-wal`
  - `<dbname>-shm`
- Never assume the database consists of a single file when copying or inspecting disk files.
- Before deleting or replacing a database file in tests, make sure connections are closed so SQLite can checkpoint and remove `-wal` / `-shm`.

---

## 3. Database Maintenance (`VACUUM`)
- The `vacuum()` method defragments the database and reclaims disk space after large file deletions.
- Ensure `VACUUM` runs with a closed connection afterwards:
  ```python
  with contextlib.closing(sqlite3.connect(self.path)) as conn:
      conn.execute('VACUUM;')
      conn.commit()
  ```

---

## 4. Resetting Windows File Attributes
When syncing files from read-only sources or attributes (e.g. archived camera SD cards, Windows system files):
- Windows file copies can copy read-only attributes, preventing future overwrites or deletions.
- Use `ctypes.windll.kernel32.SetFileAttributesW` or `os.chmod` to clear the read-only attribute (`FILE_ATTRIBUTE_NORMAL = 0x80`) before attempting to modify or overwrite files on destination paths.
