# FastMirror — Agent Guidelines

Please refer to the detailed guidelines and modular rules in [`.agents/`](.agents):

- **Main Agent Manifesto**: [`.agents/AGENTS.md`](.agents/AGENTS.md)
- **Rules**:
  - [Windows & Network Path Handling Rules](.agents/rules/windows_network_paths.md)
  - [GUI & Threading Safety Rules](.agents/rules/gui_and_threading.md)
  - [SQLite & File Lock Rules on Windows](.agents/rules/sqlite_and_file_locks.md)
  - [Data Integrity & Safety Rules](.agents/rules/data_integrity_and_safety.md)
- **Skills**:
  - [Codebase Verification](.agents/skills/verify-codebase/SKILL.md)
  - [UNC & Network Path Handling](.agents/skills/unc-path-handling/SKILL.md)
  - [Diagnose Sync Errors](.agents/skills/diagnose-sync-errors/SKILL.md)

---

## Inviolable Rules Summary
1. **Never use `os.path.commonpath` with Windows UNC paths** (`\\server\share`). Python's `ntpath.splitdrive` treats root shares as relative paths, causing `ValueError: Can't mix absolute and relative paths`. Use lexical `Path.is_relative_to()`.
2. **Never perform blocking network I/O (`os.path.realpath`, `Path.resolve`) during path comparisons**.
3. **Tkinter is single-threaded**: Dispatch all UI updates from background threads via `root_gui.after(0, callback)`.
4. **Always close SQLite connections on Windows** using `contextlib.closing(sqlite3.connect(...))` to prevent `WinError 32` file locks.
5. **Never write test or agent logs to production `data/logs/`**: All test runs and automated agent executions are isolated via `tests/conftest.py` and `is_test_or_agent_mode()`.
6. **Always use `scratch/` for temporary agent scripts and artifacts**: Never create temporary or scratch files (e.g. `scratch_*.py`) in the repository root; all temporary exploratory scripts, benchmarks, and debug dumps must be placed inside the `scratch/` directory.
7. **Always verify changes** with `uv run pytest` and `uv run ruff check .`.
