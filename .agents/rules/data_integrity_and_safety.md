# Data Integrity & Safety Rules

As an automated backup and synchronization tool, **data safety is the highest priority**. Under no circumstances should an operation result in silent data loss, file truncation, or unintended overwrites.

---

## 1. Non-Destructive File Sync Guarantees
- **No silent deletions**: Never delete files on source or target unless:
  1. The user configuration explicitly enables it (`allow_file_deletion: true`).
  2. The confirmation popup was approved by the user (or dry-run passed with explicit rules).
- **Graceful handling of permission errors**: If a file cannot be read, copied, or removed due to permissions, log the exception clearly and continue to the next file without aborting the entire sync batch.

---

## 2. File Metadata & Timestamp Preservation
- Synchronization relies on comparing modification timestamps (`mtime` / `mtime_ns`) and file sizes.
- Whenever copying files:
  - Always preserve timestamps using `shutil.copystat(src, dst)` or `os.utime(dst, ns=(atime_ns, mtime_ns))`.
  - Failing to preserve timestamps causes identical files to be repeatedly copied on every subsequent run.
- Keep in mind network filesystems (SMB/FAT32) have different timestamp granularities:
  - NTFS: 100-nanosecond precision.
  - FAT32: 2-second precision.
  - SMB: typically 1-millisecond to 100-nanosecond precision.
  - When comparing timestamps, allow a small tolerance threshold (e.g. 1-2 seconds) if sizes match.

---

## 3. Cross-Volume & Cross-Share Transfers
- Moving files between different Windows drive letters (`D:\` to `E:\`) or to UNC network shares (`D:\` to `\\server\share\`) cannot use atomic `os.rename()` (`WinError 17: The system cannot move the file to a different disk drive`).
- `shutil.move()` performs a copy-then-delete.
- If network connection drops mid-transfer:
  - Verify destination file size before deleting the source.
  - Use atomic rename from a temporary file (e.g. `dst_file.tmp -> dst_file`) when writing large files to prevent leaving corrupted half-copied files.

---

## 4. Exclusion & Filter Rules
- Always evaluate exclusion patterns (e.g. `.git/`, temporary files, `.tmp`, system files) before copying.
- Use `pathspec` or configured ignore patterns consistently.
- Never traverse into recursion loops caused by symlinks or directory junctions (use `follow_symlinks=False`).
