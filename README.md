# FastMirror

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](https://www.microsoft.com/windows/)

**A one-way folder mirror for recurring backups to external drives and network shares.**

FastMirror is for people who regularly copy changes from the same source folders to the same destinations. Its local index of the target helps avoid repeatedly listing every file on a slow network share, while move detection can save transferring files that were simply renamed or moved.

It is designed for repeated backups, not two-way synchronization or file versioning. The first scan may take longer while the target is indexed. Review proposed actions before syncing, especially deletions.

## Quick start

**Requirements:** Windows 10 or 11, Python 3.10+, and [uv](https://docs.astral.sh/uv/).

```powershell
git clone https://github.com/rafaelsavi/fast-mirror.git
cd fast-mirror
uv sync
uv run python -m gui.gui
```

In the app, add a source folder and its target, then run a comparison or synchronization. The first run scans the target; later runs can use the local index. If you change the target outside FastMirror, rebuild the index before relying on it.

## Why FastMirror?

- **Faster repeated scans:** a local SQLite index reduces repeated file listings on network targets.
- **Less unnecessary transfer:** detected moves and renames can be handled on the target instead of copying the file again.
- **Control over changes:** review proposed copy, move, and delete actions before applying them, or schedule recurring runs.

FastMirror mirrors in one direction—from source to target. It does not merge changes made independently on both sides. Deletions may be part of a mirror operation, so check the proposed actions and your settings before unattended use.

## Learn more

- [Full user guide](docs/USER_GUIDE.md)
- [Configuration and exclusions](docs/CONFIGURATION.md)
- [How the synchronization engine works](docs/ARCHITECTURE.md)
- [Synchronization robustness](docs/SYNC_ROBUSTNESS.md)
- [Development and testing](docs/DEVELOPMENT.md)

---

Personal project by Rafael Savi. Licensed under the [MIT License](LICENSE).
