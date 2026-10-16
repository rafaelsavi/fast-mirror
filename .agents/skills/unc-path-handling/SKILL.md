---
name: unc-path-handling
description: >-
  Guidelines, test patterns, and troubleshooting procedures for Windows UNC and SMB network paths
  (e.g. \\192.168.1.100\Share) in the automatic-backup repository. Use when modifying path manipulation,
  testing remote network shares, or debugging UNC-related exceptions.
---

# Windows UNC & SMB Path Handling Runbook

This guide details how to work with and test Windows Universal Naming Convention (UNC) paths in this repository.

---

## 1. Why UNC Paths Require Special Handling
In Windows:
- Local paths start with a drive letter: `D:\Photos\2025\image.jpg`
- UNC paths reference network shares: `\\192.168.1.100\Photos\2025\image.jpg`

### The Commonpath Bug
In standard Python on Windows:
```python
import ntpath
ntpath.splitdrive(r'\\192.168.1.100\Photos')
# Returns: ('\\\\192.168.1.100\\Photos', '')
```
Because the second item is `''` (no leading backslash), `ntpath.isabs()` treats the share root as **relative**, while subpaths with a leading slash (`\2025\image.jpg`) are treated as **absolute**.
Calling `os.path.commonpath([subpath, share_root])` throws:
```text
ValueError: Can't mix absolute and relative paths
```

### The Blocking I/O Gotcha
Calling `os.path.realpath()`, `os.path.abspath()`, or `Path.resolve()` on a UNC path issues network Win32 API calls (`GetFinalPathNameByHandle`). If the remote host is sleeping or offline:
- Python blocks for 30–60 seconds per call.
- The UI worker thread hangs completely.

---

## 2. Standard Implementation Pattern

Always use pure lexical manipulation using `pathlib.Path`:

```python
from pathlib import Path

def _to_path(p: str | Path) -> Path:
    # Normalize slashes and strip trailing backslash
    s = str(p).replace('/', '\\').rstrip('\\')
    return Path(s)

def is_subpath_of(child: Path, parent: Path) -> bool:
    try:
        return child.is_relative_to(parent)
    except (ValueError, TypeError):
        return False
```

### Specificity Matching for Root Folders
When resolving which `DirectoryPair` a file belongs to:
```python
matching_dirs = []
for d in dirs:
    for root_str in (d.dir1, d.dir2):
        if not root_str:
            continue
        root = _to_path(root_str)
        if target.is_relative_to(root):
            # (number of parts, string length)
            specificity = (len(root.parts), len(str(root)))
            matching_dirs.append((specificity, d))

if not matching_dirs:
    raise FileNotFoundError(f'Could not identify root folders of path <{path}>.')

# Pick the most specific match
matching_dirs.sort(key=lambda item: item[0], reverse=True)
best_dir = matching_dirs[0][1]
```

---

## 3. Writing Unit Tests for UNC Paths Without Live Network

Do NOT attempt to connect to a real network share during unit tests. You can test UNC path logic offline using synthetic strings and `PureWindowsPath`:

```python
import pytest
from core.backend import SyncDirs
from utils.utils import DirectoryPair

def test_unc_path_containment():
    sync = SyncDirs()
    dirs = [
        DirectoryPair(
            dir1=r'\\192.168.1.100\Share\2025',
            dir2=r'D:\Backup\2025',
            name='Photos'
        )
    ]
    test_file = r'\\192.168.1.100\Share\2025\Trip\photo.jpg'
    resolved = sync.get_dirs_from_path(test_file, dirs)
    assert resolved == dirs[0]
```

---

## 4. Troubleshooting Checklist
When a user reports:
`Could not identify root folders of path <\\server\share\...>`:
1. Check if the directory pair in `config.json` has trailing slashes (e.g. `\\server\share\` vs `\\server\share`).
2. Verify that `_to_path` strips trailing slashes on both the target file and root directory.
3. Check if forward slashes were introduced (`//server/share`).
4. Ensure no code called `os.path.commonpath`.
5. Run `uv run pytest tests/test_core.py -k "test_get_dirs_from_path"` to verify all edge cases.
