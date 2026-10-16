# Windows & Network Path Handling Rules

This repository operates on Windows local drives (e.g. `D:\`, `E:\`) and remote SMB / UNC network shares (e.g. `\\192.168.1.100\Share`).
Follow these mandatory guidelines whenever modifying path handling or core backup logic:

## 1. NEVER Use `os.path.commonpath` with Windows UNC Paths
Python's `ntpath.commonpath` implementation has a fundamental bug with UNC root shares (`\\server\share`). For a UNC root, `ntpath.splitdrive` returns an empty path component `''`. Because `''` has no leading slash, `ntpath.commonpath` classifies the UNC root share as a **relative path**, whereas any file inside it (e.g. `\2025\file.ext`) is classified as an **absolute path**.
Consequently, `os.path.commonpath([file_path, root_share])` raises:
`ValueError: Can't mix absolute and relative paths`

If a `try ... except ValueError` block surrounds this, the match is silently dropped and `FileNotFoundError` is thrown.
**Solution:** Always use lexical `pathlib.Path` or `pathlib.PureWindowsPath` with `.is_relative_to(root)` for path containment and prefix matching.

## 2. NEVER Perform Network I/O During Path Manipulation
Functions like `os.path.realpath()` and `Path.resolve()` on Windows issue blocking SMB network calls (`GetFinalPathNameByHandle`) when inspecting UNC paths. If a network host or NAS is disconnected, sleeping, or slow, these functions block or time out.
**Solution:** Keep path resolution lexical. Do not call `os.path.realpath` or `resolve()` on remote UNC paths unless an open file handle or symlink dereference is strictly required.

## 3. Specificity Scoring for Root Directory Matching
When resolving which `DirectoryPair` a file belongs to (in `get_dirs_from_path`), always score matches by root specificity (`(len(root.parts), len(str(root)))`):
- Avoid prefix substring collision (`D:\Data` matching `D:\Data_Extended\file.txt`).
- Prefer nested roots over drive roots (`D:\Photos` matching before `D:\`).

## 4. Guard Directory Tree Ascents
When cleaning empty parent directories (`delete_empty_dirs`), always guard against root traversal termination (`if parent == current: break`) to prevent infinite loops when ascending UNC shares (`\\server\share\`).

## 5. Validate Against Real User Configurations
Always run `uv run pytest`. The test suite includes `test_config_json_entry_paths_resolution`, which verifies that every real-world path in `config.json` correctly resolves without throwing errors.
