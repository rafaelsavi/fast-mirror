# Windows & Network Path Handling Rules

This repository synchronizes files between local Windows drives (e.g. `D:\`, `E:\`, `C:\`) and remote SMB / UNC network shares (e.g. `\\192.168.1.100\Photos\`).
Adhere to the following mandatory rules whenever modifying path handling or core backup logic:

---

## 1. NEVER Use `os.path.commonpath` with Windows UNC Paths
Python's standard library `ntpath.commonpath` implementation has a known design limitation with UNC root shares (`\\server\share`).
- For a UNC root, `ntpath.splitdrive(r'\\server\share')` returns `('\\\\server\\share', '')`.
- Because the second element (path) is empty, `ntpath.commonpath` classifies `\\server\share` as a **relative path**, whereas any file or subdirectory inside it (e.g. `\2025\file.ext`) has a leading slash and is classified as an **absolute path**.
- Consequently, `os.path.commonpath([file_path, root_share])` raises:
  ```text
  ValueError: Can't mix absolute and relative paths
  ```
- **Rule:** Never use `os.path.commonpath` or `os.path.commonprefix` for path containment.
- **Solution:** Always use lexical `pathlib.Path` or `pathlib.PureWindowsPath` with `.is_relative_to(root)`:
  ```python
  def _to_path(p: str | Path) -> Path:
      s = str(p).replace('/', '\\').rstrip('\\')
      return Path(s)

  # Check containment purely lexically:
  if target_path.is_relative_to(root_path):
      ...
  ```

---

## 2. NEVER Perform Network I/O During Path Comparisons
Functions like `os.path.realpath()`, `os.path.abspath()`, and `Path.resolve()` on Windows issue blocking SMB network calls (`GetFinalPathNameByHandle` / Win32 file metadata queries) when given UNC paths.
- If a remote NAS or network share is sleeping, disconnected, or slow, these functions block or time out, freezing the entire application and GUI worker thread.
- Furthermore, `realpath()` on disconnected shares can return arbitrary or corrupted fallback strings.
- **Rule:** Keep all path comparisons, normalizations, and containment checks **100% lexical** in memory.
- **Solution:** Use `Path(str(p).replace('/', '\\').rstrip('\\'))` and string/path parts operations without calling `os.path.realpath` or `resolve()`.

---

## 3. Specificity Scoring for Root Directory Matching
When determining which `DirectoryPair` a file path belongs to (in `get_dirs_from_path`):
- Multiple directory pairs may have root paths on the same drive or share (e.g. `D:\Data` and `D:\Data\Subdir`, or `\\server\share\photos` and `\\server\share`).
- Naive string prefix matching (`str.startswith`) causes substring collisions: `D:\Data` incorrectly matches `D:\Data_Extended\file.txt`.
- **Rule:** Always score candidate matches by specificity:
  ```python
  specificity = (len(root.parts), len(str(root)))
  ```
  Pick the candidate with the highest specificity score.

---

## 4. Guard Directory Tree Ascents
When pruning empty directories (`delete_empty_dirs`):
- Walking up a directory tree using `path.parent` must be guarded against termination conditions.
- For UNC paths, `Path(r'\\server\share').parent` evaluates to `Path(r'\\server\share')` (itself).
- Without an explicit guard, ascending empty folders enters an infinite loop and hangs.
- **Rule:** Always include:
  ```python
  parent = current.parent
  if parent == current or parent in root_dirs:
      break
  ```

---

## 5. Slash and Case Normalization
- On Windows, paths are case-insensitive and slashes can be either `/` or `\`.
- Always strip trailing slashes when normalizing root paths so that `\\server\share\` and `\\server\share` match identically.
- Preserve the original casing when performing file operations, but perform case-insensitive comparisons where necessary.

---

## 6. Validate Against Real User Configurations
Always execute `uv run pytest`. The test suite includes `test_config_json_entry_paths_resolution` in `tests/test_core.py`, which validates every real-world path in `config.json` against `get_dirs_from_path` without requiring network access.
