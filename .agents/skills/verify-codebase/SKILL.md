---
name: verify-codebase
description: >-
  Run the full quality gate for the FastMirror repository including the pytest test suite,
  real configuration path resolution validation, ruff linting, ruff formatting, and mypy type checking.
  Use whenever modifying code or before declaring a task complete.
---

# Codebase Verification Runbook

Follow this runbook to ensure that all changes adhere to project standards and introduce zero regressions.

## Prerequisites
- Working directory: Repository root (`fast-mirror`).
- Virtual environment: Managed with `uv`.
- Execution mode: On Windows, when running through terminal sandbox, if standard mode fails with permission errors, run with `BypassSandbox: true`.

---

## 1. Automated Test Suite
Execute the entire test suite using `pytest`:

```powershell
uv run pytest
```

### Targeted Test Verification
If modifying path resolution or backend sync logic:
```powershell
uv run pytest tests/test_paths.py -v -k "test_get_dirs_from_path or test_config_json"
```

If modifying database or lock management:
```powershell
uv run pytest tests/test_mirror.py -v
```

### Critical Test Requirements
- **`test_gui_visual_emulation.py`** must pass. All future changes in the frontend must validate all action paths, button clicks, corner cases (empty paths, invalid times, regex special characters, deletion safety uncheck, modal popups), and visual geometry invariants.
- **`test_config_json_entry_paths_resolution`** must pass. This test loads every path in the real `data/config.json` and ensures `get_dirs_from_path` resolves all sources and targets cleanly.
- **`test_wal_and_vacuum_close_connections`** must pass. This verifies that SQLite connections are properly closed on Windows so files can be deleted without `WinError 32`.
- **Zero Production Log Pollution**: Test executions are automatically isolated via `tests/conftest.py` and must not add files to `data/logs/`.

---

## 2. Linting & Style Validation
Run `ruff` to ensure compliance with repo rules:

```powershell
# Check for lint violations
uv run ruff check .

# Check formatting compliance (single quotes, 120 char line length)
uv run ruff format --check .
```

If safe fixes are available:
```powershell
uv run ruff check --fix .
uv run ruff format .
```

---

## 3. Static Type Checking
Run `mypy` against the source directory:

```powershell
uv run mypy src
```

Ensure no new type errors are introduced.

---

## 4. Verification Sign-Off Checklist
Before concluding work:
- [ ] `uv run pytest` reports 100% passed (0 failures).
- [ ] `uv run ruff check .` reports `All checks passed!`.
- [ ] `uv run ruff format --check .` reports all files correctly formatted.
- [ ] `uv run mypy src` reports success.
- [ ] All existing comments and docstrings in modified files have been preserved.
