# FastMirror — Development & Contribution Guide

This guide covers developer environment setup, testing, code quality gates, Windows standalone packaging, and the automated CI/CD release workflow for the **FastMirror** project.

---

## Table of Contents

1. [Development Environment Setup](#development-environment-setup)
   - [Prerequisites](#prerequisites)
   - [Setup with uv (Recommended)](#setup-with-uv-recommended)
   - [Setup with pip & venv](#setup-with-pip--venv)
   - [Enabling Git Hooks](#enabling-git-hooks)
2. [Project Layout](#project-layout)
3. [Unified Verification Runner (`scripts/verify.py`)](#unified-verification-runner-scriptsverifypy)
4. [Testing with Pytest](#testing-with-pytest)
   - [Running Tests](#running-tests)
   - [Headless Window Suppression](#headless-window-suppression)
   - [Writing New Tests](#writing-new-tests)
5. [Code Quality & Tooling](#code-quality--tooling)
   - [Linting & Formatting with Ruff](#linting--formatting-with-ruff)
   - [Type Checking with Mypy](#type-checking-with-mypy)
   - [Privacy Hygiene Scanner](#privacy-hygiene-scanner)
6. [Windows Packaging & Installer Compilation](#windows-packaging--installer-compilation)
   - [Automated Build Script (`packaging/build.py`)](#automated-build-script-packagingbuildpy)
   - [PyInstaller Freezing (`fastmirror.spec`)](#pyinstaller-freezing-fastmirrorspec)
   - [Inno Setup 6 Installer Wizard (`installer.iss`)](#inno-setup-6-installer-wizard-installeriss)
7. [Zero-Effort Automated Release Flow](#zero-effort-automated-release-flow)
   - [Single Source of Truth Versioning](#single-source-of-truth-versioning)
   - [GitHub Actions Release Pipeline](#github-actions-release-pipeline)
8. [Windows Platform Rules](#windows-platform-rules)
   - [UNC & Network Path Safety](#unc--network-path-safety)
   - [SQLite File Lock Hygiene](#sqlite-file-lock-hygiene)
   - [Tkinter Threading Safety](#tkinter-threading-safety)

---

## Development Environment Setup

### Prerequisites
- **Operating System**: Windows 10 or Windows 11 (requires native Windows APIs for UNC paths, `winsound`, and system tray).
- **Python**: Version **3.10** or higher (Python 3.13 recommended).
- **Package Manager**: [uv](https://docs.astral.sh/uv/) (recommended for instant dependency resolution) or standard `pip`.

### Setup with uv (Recommended)

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/rafaelsavi/fast-mirror.git
   cd fast-mirror
   ```

2. **Sync the virtual environment:**
   ```powershell
   uv sync
   ```

3. **Launch the application from source:**
   ```powershell
   uv run python launch.pyw
   ```

### Setup with pip & venv

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
python launch.pyw
```

### Enabling Git Hooks

FastMirror includes pre-configured Git hooks in `.githooks/` for automated privacy scanning and pre-push quality gates. Enable them with:

```powershell
git config core.hooksPath .githooks
```

- **Pre-Commit Hook**: Scans all staged files to ensure no personal machine paths (`C:\Users\Username\...`, private IPs, developer folders) are committed.
- **Pre-Push Hook**: Runs the full verification suite (`scripts/verify.py --check-version`) before allowing pushes to remote.

---

## Project Layout

```text
fast-mirror/
├── .agents/                  # Agent architecture guidelines and modular rules
├── .github/workflows/ci.yml  # Unified CI/CD testing and automated release workflow
├── .githooks/                # Git pre-commit (privacy) and pre-push (quality gate)
├── data/                     # Local development data (gitignored)
│   ├── config.json           # Active configuration mirror
│   ├── local_mirror.db       # SQLite WAL target cache database
│   ├── profiles/             # User configuration profiles
│   └── logs/                 # Persistent logs and Excel comparison reports
├── packaging/                # Freezing and installer configurations
│   ├── build.py              # Automated PyInstaller & Inno Setup compiler
│   ├── fastmirror.spec       # PyInstaller standalone spec
│   └── installer.iss         # Inno Setup 6 installer wizard script
├── scripts/
│   └── verify.py             # Unified local & CI quality gate runner
├── src/
│   ├── core/                 # Backend engines (linking, mirroring, comparing, file ops)
│   ├── gui/                  # Tkinter UI, threads, custom widgets, system tray
│   └── utils/                # Constants, helpers, logger, profile manager
├── tests/                    # Pytest test suite (100% headless)
├── CHANGELOG.md              # User-facing release notes (Keep a Changelog format)
├── launch.pyw                # DPI-aware, single-instance launcher
└── pyproject.toml            # Single source of truth for dependencies and version
```

---

## Unified Verification Runner (`scripts/verify.py`)

Run the entire quality gate locally with one command:

```powershell
uv run python scripts/verify.py --check-version
```

This runner sequentially validates all six quality gates:
1. `ruff format --check .`: Code formatting conformance (120 char limit, single quotes).
2. `ruff check .`: Static linter with zero errors or warnings.
3. `mypy src`: Strict static type checking.
4. `check_privacy_and_paths()`: Scans tracked files for hardcoded personal paths.
5. `validate_version_and_changelog()`: Ensures `pyproject.toml` version matches `CHANGELOG.md`.
6. `pytest`: Executes the full 211-test suite.

Auto-fix formatting and linting issues with:
```powershell
uv run python scripts/verify.py --fix
```

---

## Testing with Pytest

### Running Tests

```powershell
# Run the entire test suite
uv run pytest

# Run with verbose output and test names
uv run pytest -v

# Run a specific test module
uv run pytest tests/test_sync.py
```

### Headless Window Suppression

FastMirror's test suite runs **100% headless and silent** via centralized hooks in `tests/conftest.py`:
- All `tk.Tk` and `tk.Toplevel` instances are automatically placed off-screen (`+25000+25000`) and withdrawn.
- OS-level focus stealing (`grab_set`, `focus_force`) is safely no-opped so test runs never steal keyboard focus from your active apps.
- Windows audio chimes (`winsound.PlaySound`) are globally silenced.
- All widget logic, geometry managers (`update_idletasks()`), treeviews, and virtual events execute with full fidelity in memory.

### Writing New Tests

Always use pytest's `tmp_path` fixture for filesystem tests:

```python
def test_custom_sync_behavior(tmp_path):
    src = tmp_path / "source"
    tgt = tmp_path / "target"
    src.mkdir()
    tgt.mkdir()
    (src / "document.txt").write_text("content", encoding="utf-8")
    # Execute test logic...
```

---

## Code Quality & Tooling

### Linting & Formatting with Ruff

```powershell
# Check code style and linting
uv run ruff check .
uv run ruff format --check .

# Auto-format and fix autofixable issues
uv run ruff format .
uv run ruff check --fix .
```

### Type Checking with Mypy

```powershell
uv run mypy src
```

### Privacy Hygiene Scanner

FastMirror enforces strict privacy standards to prevent developer paths, personal usernames, or internal subnets from being committed to public repositories.

Rules:
- Never hardcode personal paths (`C:\Users\Username\...`, `D:\Projects\...`).
- Use placeholders (`C:\Users\Username\...`) or relative paths in docs and tests.
- The privacy scanner runs automatically via `.githooks/pre-commit` and `scripts/verify.py`.

---

## Windows Packaging & Installer Compilation

### Automated Build Script (`packaging/build.py`)

Compile the standalone executable, portable ZIP, and Inno Setup installer wizard in one step:

```powershell
uv run python packaging/build.py
```

This automates:
1. Freezing `FastMirror.exe` using PyInstaller (`packaging/fastmirror.spec`).
2. Packaging `FastMirror-v<version>-Windows-Portable.zip` with `portable.txt`.
3. Compiling `FastMirror-v<version>-Windows-Setup.exe` with Inno Setup 6 (`ISCC.exe`).

### Inno Setup 6 Installer Wizard (`installer.iss`)

- Configured for per-user installation into `%LOCALAPPDATA%\Programs\FastMirror`.
- Requires zero UAC administrative elevation (`PrivilegesRequired=lowest`).
- Safely excludes `portable.txt` so installed instances always use `%LOCALAPPDATA%\FastMirror\data\`.
- Preserves all user data during updates and uninstalls.

---

## Zero-Effort Automated Release Flow

FastMirror uses a fully automated CI/CD release workflow (`.github/workflows/ci.yml`):

### Single Source of Truth Versioning
Application version is maintained exclusively in **`pyproject.toml`**:
```toml
[project]
name = "fast-mirror"
version = "0.1.0"
```

### Automated Release on Push
To publish a new release:
1. Bump `version = "X.Y.Z"` in `pyproject.toml`.
2. Add a matching entry under `## [X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md`.
3. Commit and push to `main`:
   ```powershell
   git add pyproject.toml CHANGELOG.md
   git commit -m "chore: bump version to X.Y.Z"
   git push origin main
   ```
4. **GitHub Actions automatically**:
   - Runs the full verification suite (`scripts/verify.py --ci`).
   - Detects the new version and creates Git tag `vX.Y.Z`.
   - Extracts release notes directly from `CHANGELOG.md`.
   - Compiles standalone `FastMirror.exe`, `FastMirror-Portable.zip`, and `FastMirror-Setup.exe`.
   - Publishes the GitHub Release with attached Windows binaries!

---

## Windows Platform Rules

1. **Never use `os.path.commonpath` with Windows UNC paths** (`\\server\share`). Python's `ntpath.splitdrive` treats root shares as relative paths, causing `ValueError`. Use purely lexical `Path.is_relative_to()`.
2. **Never execute blocking network I/O (`os.path.realpath`, `Path.resolve`) during path comparisons**.
3. **Always close SQLite connections explicitly** using `with contextlib.closing(sqlite3.connect(...)) as conn:` to avoid `WinError 32` file locks.
4. **Tkinter is single-threaded**: Dispatch all background thread UI updates via `root_gui.after(0, callback)`.
