# Automatic Backup — Agent Guidelines & Repository Architecture

Welcome to the **Automatic Backup** codebase. This repository provides automated, multi-threaded directory mirroring, synchronization, and backup between local Windows drives and remote SMB / UNC network shares (e.g. NAS storage).

---

## 1. Tech Stack & Environment
- **Platform**: Windows 10 / 11 (requires native Windows support for UNC network paths, `winsound`, `winico` tray icon, and `ctypes.windll.kernel32`).
- **Python**: Python 3.10+ (tested with 3.13) managed via `uv`.
- **GUI**: Tkinter / CustomTkinter / `ttkwidgets` with custom worker threads.
- **Database**: SQLite3 (`local_mirror.db`) operating in WAL (`Write-Ahead Logging`) mode for lightning-fast hash caching and path tracking.
- **Tooling**:
  - Package manager: `uv`
  - Test runner: `pytest` (`uv run pytest`)
  - Linter & Formatter: `ruff` (`uv run ruff check .` / `uv run ruff format .`)
  - Type checker: `mypy` (`uv run mypy src`)

---

## 2. Inviolable Core Principles

### A. Windows UNC & Network Path Safety
1. **NEVER use `os.path.commonpath` with UNC root paths** (`\\server\share`). Python's `ntpath.splitdrive` returns an empty path component, causing `ntpath.commonpath` to treat the root share as a relative path and raise `ValueError: Can't mix absolute and relative paths`.
2. **Never execute blocking network I/O during path comparisons**. Do NOT call `os.path.realpath()` or `Path.resolve()` on remote paths; they perform blocking SMB queries (`GetFinalPathNameByHandle`) that freeze if the network is slow or sleeping. Use purely lexical matching (`pathlib.Path.is_relative_to()`).
3. **Always use specificity scoring for root directories**: When resolving which `DirectoryPair` matches a file, score by `(len(root.parts), len(str(root)))` to avoid prefix collisions (`D:\Photos` vs `D:\Photos_Archive`) and prefer nested roots over drive roots.

### B. Tkinter Thread Safety
1. **Tkinter widgets must only be manipulated on the main thread**. Never update UI labels, progress bars, or open dialogs directly from background worker threads.
2. **Dispatch UI operations via `root_gui.after(0, callback)`**.
3. **Clean up modal popups**: If a worker thread stops or is cancelled while waiting on a user confirmation popup (`ConfirmationPopup`), the popup must be destroyed via a `try...finally` block to prevent orphaned, hanging GUI windows.

### C. SQLite Connection & File Handle Hygiene on Windows
1. Windows strictly locks open files. Any leaked SQLite connection prevents database deletion, renaming, or replacement with `PermissionError: [WinError 32]`.
2. `with sqlite3.connect(...) as conn:` only controls transactions; it **does NOT close the connection**. Always use `with contextlib.closing(sqlite3.connect(...)) as conn:` or call `conn.close()` explicitly in a `finally` block.

### D. Data Safety & Non-Destructive Backup
1. **Preserve metadata**: File modification timestamps (`mtime_ns`) and attributes must always be preserved during copies (`shutil.copystat`).
2. **Never delete without confirmation**: Deletions and overwrites must respect user settings (`allow_file_deletion`, `delete_empty_dirs`, and confirmation popups).
3. **Safe tree ascension**: When pruning empty directories (`delete_empty_dirs`), always terminate if `parent == current` to prevent infinite loops when ascending network root shares (`\\server\share\`).

### E. Test & Agent Logging Isolation
1. **Never write test or agent logs into production `logs/`**: Automated test runs (`pytest`) and agent executions must never populate the production `logs/` folder.
2. **Context-Aware Dynamic Logger**: `src.utils.logger.Logger` automatically routes logs and reports to temporary directories when in test/agent mode (`ANTIGRAVITY_AGENT=1`, `AUTOMATIC_BACKUP_TESTING=1`, or running under `pytest`).

---

## 3. Directory Layout
```
automatic-backup/
├── .agents/                  # Agent rules and skills
│   ├── rules/                # Modular domain rules (network paths, GUI, SQLite, safety)
│   └── skills/               # Runbooks (verification, diagnostics, testing)
├── src/
│   ├── core/
│   │   ├── backend.py        # Core synchronization engine (SyncDirs, CompareDirs)
│   │   ├── file_ops.py       # Atomic file operations (robust_copy, robust_move, robust_delete, unlock)
│   │   ├── path_resolver.py  # Specificity-scored root path resolution & UNC path conversions
│   │   ├── mirror.py         # SQLite-based file mirror cache (MirrorDatabase)
│   │   └── file.py           # Custom path and file wrappers (CstmPath, File)
│   ├── gui/
│   │   ├── gui.py            # Main application window & scheduler watchdog (Gui)
│   │   ├── confirmation_popup.py # Action selection modal & CheckboxTreeView
│   │   ├── tray.py           # System tray integration (TrayableTk via Winico)
│   │   ├── worker_thread.py  # Background worker thread execution & cancellation
│   │   ├── widgets.py        # Custom UI controls & form fields
│   │   └── components/       # Modular GUI panels (Actions, Log, Paths, Schedule, Status, Telemetry)
│   └── utils/
│       ├── utils.py          # DirectoryPair, byte conversion, path sanitizers
│       └── logger.py         # Context-aware logging configuration and formatting
├── tests/
│   ├── conftest.py           # Test isolation fixtures
│   ├── test_e2e.py           # End-to-end integration workflows
│   ├── test_paths.py         # Path resolution and UNC share tests
│   ├── test_file_ops.py      # Robust file operations, locks, and retries
│   ├── test_sync.py          # Directory synchronization & comparison
│   ├── test_mirror.py        # SQLite mirror database and concurrency tests
│   ├── test_confirmation_popup.py # Action confirmation popup & treeview
│   ├── test_gui.py           # GUI scheduler, settings, and TextLogger
│   └── test_logger.py        # Logging handlers and log isolation
├── config.example.json       # Template configuration file (copy to config.json)
├── pyproject.toml            # Dependencies, Ruff rules, and Mypy settings
└── docs/                     # Architecture, Development, and Configuration guides
```

---

## 4. Mandatory Verification Checklist
Before submitting any changes or completing a task:
1. `uv run pytest` — All tests must pass (100% pass rate).
2. `uv run ruff check .` — Zero linting errors or warnings.
3. `uv run ruff format --check .` — Formatting conforms to repository style.
4. `test_config_json_entry_paths_resolution` must succeed against the real `config.json` (or skip if not present).
