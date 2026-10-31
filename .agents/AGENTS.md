# FastMirror — Agent Guidelines & Repository Architecture

Welcome to the **FastMirror** codebase. This repository provides automated, multi-threaded directory mirroring, synchronization, and backup between local Windows drives and remote SMB / UNC network shares (e.g. NAS storage).

---

## 1. Tech Stack & Environment
- **Platform**: Windows 10 / 11 (requires native Windows support for UNC network paths, `winsound`, `pystray` system tray integration, and `ctypes.windll.kernel32`).
- **Python**: Python 3.10+ (tested with 3.13) managed via `uv`.
- **GUI**: Tkinter / `sv-ttk` (Sun Valley theme) / `ttkwidgets` with custom worker threads.
- **Database**: SQLite3 (`data/local_mirror.db`) operating in WAL (`Write-Ahead Logging`) mode for lightning-fast hash caching and path tracking.
- **Packaging & Installer**: PyInstaller (`packaging/fastmirror.spec`, `packaging/build.py`) and Inno Setup 6 (`packaging/installer.iss`).
- **Tooling**:
  - Package manager: `uv`
  - Unified verification: `uv run python scripts/verify.py`
  - Test runner: `pytest` (`uv run pytest`)
  - Linter & Formatter: `ruff` (`uv run ruff check .` / `uv run ruff format .`)
  - Type checker: `mypy` (`uv run python -m mypy src`)

---

## 2. Inviolable Core Principles

### A. Windows UNC & Network Path Safety
1. **NEVER use `os.path.commonpath` with UNC root paths** (`\\server\share`). Python's `ntpath.splitdrive` returns an empty path component, causing `ntpath.commonpath` to treat the root share as a relative path and raise `ValueError: Can't mix absolute and relative paths`. Use lexical `Path.is_relative_to()`.
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
1. **Never write test or agent logs into production `data/logs/`**: Automated test runs (`pytest`) and agent executions must never populate the production `data/logs/` folder.
2. **Context-Aware Dynamic Logger**: `src.utils.logger.Logger` automatically routes logs and reports to temporary directories when in test/agent mode (`ANTIGRAVITY_AGENT=1`, `AUTOMATIC_BACKUP_TESTING=1`, or running under `pytest`).

### F. Scratch File & Temporary Artifact Hygiene
1. **Always use the `scratch/` directory**: Never create temporary scripts, test snippets, debug dumps, or experimental benchmarks in the workspace root (e.g. `scratch_*.py`).
2. **Confine all exploratory code**: All agent-created temporary files must strictly reside in `scratch/` to keep the root directory clean and prevent accidental repository clutter.

### G. Single Source of Truth Versioning & CHANGELOG
1. **Single Source of Truth**: Application version is maintained exclusively in [`pyproject.toml`](../pyproject.toml) (`version = "X.Y.Z"`). It is dynamically resolved at runtime in `src.utils.constants.APP_VERSION`.
2. **Changelog Parity**: Whenever `version` is bumped in `pyproject.toml`, document user-facing release notes under `## [X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md`.

### H. Automated Zero-Effort CI/CD Release Flow
1. **Zero Manual Tagging**: Never manually run `git tag` or create GitHub releases by hand.
2. **Automated Release on Push**: Pushing to `main` with a bumped `version` in `pyproject.toml` automatically causes GitHub Actions to:
   - Run the unified verification suite (`scripts/verify.py --ci`).
   - Detect that remote tag `v<version>` does not exist yet.
   - Automatically create and push Git tag `v<version>`.
   - Automatically extract release notes from `CHANGELOG.md`.
   - Compile standalone Windows executable (`FastMirror.exe`), Portable ZIP (`FastMirror-Portable.zip`), and Inno Setup Windows installer (`FastMirror-Setup.exe`).
   - Automatically publish the GitHub Release with binary assets attached.

### I. Privacy Hygiene & Path Leak Prevention
1. **Never Hardcode Personal Paths**: Never commit personal user profile paths (`C:\Users\Username\...`), personal developer folders, private network shares, or AI assistant paths.
2. **Git Hook Enforcement**: Run `git config core.hooksPath .githooks` to enable the pre-commit privacy scanner and pre-push verification.

---

## 3. Directory Layout
```
fast-mirror/
├── .agents/                  # Agent rules and skills
│   ├── rules/                # Modular domain rules (network paths, GUI, SQLite, safety, release flow)
│   └── skills/               # Runbooks (verification, diagnostics, testing)
├── .github/
│   └── workflows/
│       └── ci.yml            # Unified CI/CD testing and automated Windows release workflow
├── .githooks/                # Git pre-commit (privacy scanner) and pre-push (quality gate)
├── data/                     # Runtime application data (ignored in git)
│   ├── config.json           # Active configuration
│   ├── local_mirror.db       # SQLite WAL target cache database
│   └── logs/                 # Persistent logs and Excel comparison reports
├── packaging/                # Build and distribution packaging
│   ├── build.py              # Automated PyInstaller & Inno Setup compiler
│   ├── fastmirror.spec       # PyInstaller standalone freezing specification
│   └── installer.iss         # Inno Setup 6 per-user setup wizard script
├── scratch/                  # Agent exploratory scripts and scratch tools (gitignored)
├── scripts/
│   └── verify.py             # Unified local & CI verification runner
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
│   │   ├── health_check.py   # Non-blocking target reachability & disk space prober
│   │   ├── scheduler.py      # Optimized 8-day candidate run calculator
│   │   ├── tray.py           # System tray integration (TrayableTk via pystray)
│   │   ├── icons.py          # Icon registry and tinting engine
│   │   ├── worker_thread.py  # Background worker thread execution & cancellation
│   │   ├── widgets.py        # Custom UI controls & form fields
│   │   ├── assets/icons/     # Modern 16x16 PNG icons
│   │   └── components/       # Modular GUI panels (Actions, Log, Paths, Schedule, Status, Telemetry, Modals)
│   └── utils/
│       ├── constants.py      # ROOT_DIR locator, APP_VERSION, and data folder paths
│       ├── utils.py          # DirectoryPair, byte conversion, path sanitizers
│       └── logger.py         # Context-aware logging configuration and formatting
├── tests/
│   ├── conftest.py           # Test isolation fixtures
│   ├── test_e2e.py           # End-to-end integration workflows
│   ├── test_paths.py         # Path resolution, UNC share tests, and config validation
│   ├── test_file_ops.py      # Robust file operations, locks, and retries
│   ├── test_sync.py          # Directory synchronization & comparison
│   ├── test_mirror.py        # SQLite mirror database and concurrency tests
│   ├── test_confirmation_popup.py # Action confirmation popup & treeview
│   ├── test_gui.py           # GUI scheduler, settings, and TextLogger
│   ├── test_gui_visual_emulation.py # UI widget event flow & visual invariant tests
│   ├── test_logger.py        # Logging handlers and log isolation
│   └── test_worker_thread.py # Worker thread execution & cancellation tests
├── CHANGELOG.md              # Keep a Changelog user-facing release notes
├── LICENSE                   # MIT License
├── config.example.json       # Template configuration file (copy to data/config.json)
├── launch.pyw                # Standalone GUI launcher (DPI-aware, single-instance mutex)
└── pyproject.toml            # Single source of truth for version and dependencies
```

---

## 4. Mandatory Verification Checklist
Before submitting any changes or completing a task, run the unified verification runner:
```powershell
uv run python scripts/verify.py --check-version
```
All six quality gates must pass:
1. `ruff format --check .` — Formatting conforms to repository style (single quotes, 120 line length).
2. `ruff check .` — Zero linting errors or warnings.
3. `mypy src` — Zero type checking errors.
4. `check_privacy_and_paths()` — Zero hardcoded local machine paths or private network shares.
5. `validate_version_and_changelog()` — `pyproject.toml` version matches `CHANGELOG.md`.
6. `pytest` — All test suites pass (100% pass rate).
