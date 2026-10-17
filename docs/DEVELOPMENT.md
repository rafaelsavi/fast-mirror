# Development & Testing Guide

This guide covers developer onboarding, environment setup, coding standards, automated testing, linting, and type checking for the **Automatic Backup Tool** project.

---

## Table of Contents

1. [Development Environment Setup](#development-environment-setup)
   - [Prerequisites](#prerequisites)
   - [Setup with uv (Recommended)](#setup-with-uv-recommended)
   - [Setup with pip & venv](#setup-with-pip--venv)
2. [Project Structure & Packaging](#project-structure--packaging)
3. [Running Tests](#running-tests)
   - [Test Directory Structure](#test-directory-structure)
   - [Executing Tests with Pytest](#executing-tests-with-pytest)
   - [Writing New Tests](#writing-new-tests)
4. [Code Quality & Tooling](#code-quality--tooling)
   - [Linting with Ruff](#linting-with-ruff)
   - [Formatting with Ruff](#formatting-with-ruff)
   - [Type Checking with Mypy](#type-checking-with-mypy)
5. [Windows-Specific Dependencies](#windows-specific-dependencies)
   - [Pystray System Tray](#pystray-system-tray)
   - [Windows API Calls](#windows-api-calls)
6. [Contribution Checklist](#contribution-checklist)

---

## Development Environment Setup

### Prerequisites

- **Windows 10 / 11**: The codebase uses Windows platform libraries (`winsound`, `ctypes.windll.kernel32`).
- **Python 3.10+**: Confirm your Python version with:
  ```powershell
  python --version
  ```
- **uv** (recommended for ultra-fast dependency management) or **pip**.

---

### Setup with uv (Recommended)

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/rafaelsavi/automatic-backup.git
   cd automatic-backup
   ```

2. **Initialize a virtual environment:**
   ```powershell
   uv venv
   ```

3. **Activate the environment:**
   ```powershell
   .\.venv\Scripts\activate
   ```

4. **Install the package in editable mode with development dependencies:**
   ```powershell
   uv pip install -e ".[dev]"
   ```

---

### Setup with pip & venv

1. **Create and activate the virtual environment:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

2. **Install editable package and dev tools:**
   ```powershell
   pip install -e ".[dev]"
   ```

---

## Project Structure & Packaging

The package is configured via [`pyproject.toml`](file:///d:/Rafael/Projects/Python/automatic-backup/pyproject.toml) using the `setuptools` build backend.

```
automatic-backup/
├── pyproject.toml            # Dependencies, tools, and build configuration
├── launch.pyw                # Headless launcher with auto-venv detection
├── config.json               # Default configuration
├── src/                      # Application source root (added to PYTHONPATH)
│   ├── core/                 # Backend engines (linking, mirroring, comparing)
│   ├── gui/                  # Tkinter interface, threads, and custom widgets
│   └── utils/                # Helpers, constants, and logging
├── tests/                    # Pytest test suite
└── notebooks/                # Exploratory notebooks
```

When installed with `-e .`, the `src` directory is linked into your virtual environment's `site-packages`, allowing absolute imports like `from core.file import CstmPath` or `from gui.gui import Gui`.

---

## Running Tests

### Test Directory Structure

```
tests/
├── conftest.py               # Test environment isolation fixtures
├── test_e2e.py               # End-to-end integration workflows
├── test_paths.py             # Path resolution and UNC share tests
├── test_file_ops.py          # Robust file operations, locks, and retries
├── test_sync.py              # Directory synchronization & comparison
├── test_mirror.py            # SQLite WAL mirror database tests
├── test_confirmation_popup.py# Action confirmation popup & treeview
├── test_gui.py               # GUI scheduler, settings, and TextLogger
├── test_logger.py            # Logging handlers and log isolation
└── TestData/                 # Local directory pairs for testing
    ├── Source/
    └── Target/
```

### Executing Tests with Pytest

Run the entire test suite using `pytest`:

```powershell
# Using uv
uv run pytest

# Or within an active virtual environment
pytest
```

#### Common Options:
```powershell
# Verbose output with individual test names
pytest -v

# Show stdout print/log output
pytest -s

# Stop on first failure
pytest -x

# Target a specific test file or function
pytest tests/test_mirror.py::test_add_and_exists_path
```

### Writing New Tests

Tests use standard pytest fixtures. When writing tests that interact with `MirrorDatabase` or the filesystem, always use `tmp_path` to avoid mutating real data:

```python
import os
import pytest
from core.mirror import MirrorDatabase

@pytest.fixture
def temp_mirror(tmp_path) -> MirrorDatabase:
    db_file = os.path.join(tmp_path, 'test_mirror.db')
    return MirrorDatabase(path=db_file)

def test_custom_mirror_operation(temp_mirror, tmp_path):
    root = str(tmp_path / "data")
    os.makedirs(root, exist_ok=True)
    sample_file = os.path.join(root, "sample.txt")
    with open(sample_file, "w") as f:
        f.write("data")
    
    temp_mirror.add_path(root, sample_file)
    assert temp_mirror.exists(root, sample_file)
```

---

## Code Quality & Tooling

Code quality rules are defined in [`pyproject.toml`](file:///d:/Rafael/Projects/Python/automatic-backup/pyproject.toml).

### Linting with Ruff

[Ruff](https://github.com/astral-sh/ruff) is an extremely fast Python linter replacing Flake8, Isort, and pydocstyle.

```powershell
# Run the linter
uv run ruff check .

# Automatically apply fixes where safe
uv run ruff check --fix .
```

Enabled rule categories:
- `D`: pydocstyle docstring standards
- `E` / `F`: Pyflakes & pycodestyle syntax and semantic errors
- `UP`: Pyupgrade (modern Python 3.10+ idioms)
- `B`: Flake8-bugbear (common design traps)
- `SIM`: Flake8-simplify (streamlined code constructs)
- `I`: Isort (deterministic import sorting)
- `Q`: Flake8-quotes (enforces single quotes)

### Formatting with Ruff

The project enforces consistent formatting:
- Line length: **120 characters**
- Quote style: **Single quotes (`'`)**
- Docstrings formatted automatically

```powershell
# Check formatting without modifying files
uv run ruff format --check .

# Reformat all files in place
uv run ruff format .
```

### Type Checking with Mypy

Static type checking is enforced using [mypy](https://mypy-lang.org/):

```powershell
uv run mypy src
```

Configuration in `pyproject.toml`:
```toml
[tool.mypy]
python_version = "3.10"
ignore_missing_imports = true
mypy_path = "src"
explicit_package_bases = true
```

---

## Windows-Specific Dependencies

### Pystray System Tray

System tray integration is implemented using `pystray` in [`src/gui/tray.py`](file:///d:/Rafael/Projects/Python/automatic-backup/src/gui/tray.py):
1. Pure Python implementation using native Windows `Shell_NotifyIconW` via `ctypes`.
2. Uses [`app_icon.ico`](file:///d:/Rafael/Projects/Python/automatic-backup/src/gui/app_icon.ico) directly via Pillow (`PIL.Image`).
3. Runs detached in a background thread without blocking Tkinter's event loop.
4. If running in a headless or test environment, system tray initialization gracefully degrades without crashing.

### Windows API Calls

The application utilizes Windows-specific functions:
- **`winsound.PlaySound`**: Plays notification chime (`SystemQuestion`) when the confirmation popup opens.
- **`ctypes.windll.kernel32.SetFileAttributesW`**: Resets read-only and locked attributes when copying files that would otherwise fail with `PermissionError`.
- **`os.startfile`**: Launches the default spreadsheet viewer when clicking **Open last report**.

### Windows UNC & SMB Network Paths Gotchas

When syncing to remote NAS / SMB shares (e.g. `\\192.168.1.100\Share`), keep these critical platform behaviors in mind:
- **Never use `os.path.commonpath` with UNC root shares**: Python's `ntpath.splitdrive` treats `\\server\share` as having an empty path segment, causing `ntpath.commonpath` to view it as a relative path and raise `ValueError: Can't mix absolute and relative paths` when paired with nested files.
- **Avoid blocking network I/O (`os.path.realpath`, `Path.resolve`) during path comparisons**: These calls query the network filesystem for reparse points and can block or hang if a network destination is unreachable or asleep. Always perform lexical matching using `pathlib.Path.is_relative_to()`.
- **Test against real configurations**: Automated tests in `tests/test_core.py` validate all entries in `config.json` against `get_dirs_from_path`.


---

## Contribution Checklist

Before submitting changes or committing code, ensure:

- [ ] All unit tests pass: `uv run pytest`
- [ ] Ruff linting passes with zero errors: `uv run ruff check .`
- [ ] Code formatting adheres to standards: `uv run ruff format .`
- [ ] Static type checking succeeds: `uv run mypy src`
- [ ] No regression on Windows file operations (e.g. UNC paths and attribute handling).
- [ ] Comments and docstrings are preserved and updated for modified methods.
