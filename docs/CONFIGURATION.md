# FastMirror — Configuration & Exclusion Patterns Guide

This guide details all configuration options for **FastMirror**, including directory mapping rules, network path requirements, exclusion pattern syntax, and scheduling rules.

---

## Table of Contents

1. [Configuration File Overview](#configuration-file-overview)
2. [Configuring Directory Pairs (`entry_paths`)](#configuring-directory-pairs-entry_paths)
   - [Local Drives](#local-drives)
   - [Network Shares (UNC Paths)](#network-shares-unc-paths)
   - [Path Validation Semantics](#path-validation-semantics)
3. [Exclusion Patterns (`entry_exclusions`)](#exclusion-patterns-entry_exclusions)
   - [Pattern Syntax (`gitwildmatch`)](#pattern-syntax-gitwildmatch)
   - [Directory Pruning vs. File Exclusion](#directory-pruning-vs-file-exclusion)
   - [Recommended Exclusion List](#recommended-exclusion-list)
4. [Scheduler Settings](#scheduler-settings)
   - [Weekdays (`week_days`)](#weekdays-week_days)
   - [Times (`entry_times`)](#times-entry_times)
   - [Scheduling Watchdog Logic](#scheduling-watchdog-logic)
5. [Synchronization Flags](#synchronization-flags)
   - [Fast Mirror Scanning](#fast-mirror-scanning)
   - [Metadata vs. Content Comparison](#metadata-vs-content-comparison)
   - [Confirmation and Default Actions](#confirmation-and-default-actions)
   - [Reporting](#reporting)
6. [Complete `config.json` Template](#complete-configjson-template)

---

## Configuration File Overview

Settings are stored in `data/config.json` (template in [`config.example.json`](../config.example.json)).

- The file is saved automatically when clicking **Save** in the *GUI Configuration* panel.
- On startup, the GUI reads `config.json` via [`load_config()`](../src/gui/gui.py#L457-L478).
- If `config.json` is corrupted, the application backs it up to `config.json_old.json` and resets to default values.
- You can safely edit `config.json` with a text editor while the application is not running.

---

## Configuring Directory Pairs (`entry_paths`)

Each entry in `entry_paths` defines a one-way backup synchronization pair mapping a **source directory** to a **target directory**.

In the GUI, pairs are entered as:
```text
SOURCE -> TARGET
```

In `config.json`, they are saved as a list of two-element string arrays:
```json
"entry_paths": [
    [
        "D:\\Photos",
        "\\\\192.168.1.100\\Backup\\Photos"
    ],
    [
        "E:\\Documents",
        "F:\\Backup\\Documents"
    ]
]
```

### Local Drives
- Use standard Windows drive letter notation: `C:\Users\Username\Documents`, `D:\`, `E:\Projects`.
- In JSON, escape backslashes: `"D:\\Projects"`.

### Network Shares (UNC Paths)
- The tool supports Universal Naming Convention (UNC) paths over SMB/CIFS networks:
  ```text
  \\192.168.1.100\SharedFolder\Backup
  \\NAS-SERVER\Volume1\Backup
  ```
- Make sure the network share is accessible in Windows Explorer without requiring a credentials prompt prior to starting a backup.

### Path Validation Semantics

When validating paths in [`EntryPaths.parse_line()`](../src/gui/widgets.py#L40-L55):
1. **Source directory**: Must exist (`os.path.isdir(source)`). If the source disk is disconnected, the line is marked invalid and ignored.
2. **Target directory**: Must either exist already, or its immediate parent directory must exist (`os.path.isdir(os.path.dirname(os.path.realpath(target)))`). This allows defining a new destination subdirectory that `SyncDirs` will automatically create.

---

## Exclusion Patterns (`entry_exclusions`)

Exclusion patterns prevent unwanted, temporary, or cache files from being analyzed or copied.

In the GUI, patterns are entered as comma-separated values in the **Exclusions** field:
```text
$RECYCLE.BIN, **\.git\**, **\.venv\**, **\__pycache__\**, **\~$*, Temp, Cache
```

In `config.json`, they are stored as a string array:
```json
"entry_exclusions": [
    "$RECYCLE.BIN",
    "**\\.git\\**",
    "**\\.idea\\**",
    "**\\.mypy_cache\\**",
    "**\\.pytest_cache\\**",
    "**\\.venv\\**",
    "**\\___*\\**",
    "**\\__pycache__\\**",
    "**\\~$*",
    "Temp",
    "Cache"
]
```

### Pattern Syntax (`gitwildmatch`)

Exclusions use [`pathspec`](https://github.com/cpburnz/python-pathspec) implementing the Git `.gitignore` wildmatch specification:

| Pattern | Matches | Description |
| :--- | :--- | :--- |
| `$RECYCLE.BIN` | `$RECYCLE.BIN` | Matches the root Windows recycle bin folder. |
| `**\.git\**` | Any `.git` folder anywhere | Matches any directory named `.git` and all contents inside it. |
| `**\.venv\**` | Any virtual environment | Excludes Python virtual environment folders anywhere in the tree. |
| `**\__pycache__\**` | Python bytecode caches | Excludes all compiled Python cache directories. |
| `**\~$*` | Office temporary lock files | Matches temporary lock files like `~$Document.docx`. |
| `Folder` | Any folder named `Folder` | Matches `Folder` or any subdirectory named `Folder`. |
| `*.tmp` | All `.tmp` files | Matches all files ending with `.tmp`. |

> [!NOTE]
> The engine automatically translates Windows backslashes (`\`) into forward slashes (`/`) internally before evaluating against `pathspec`.

### Directory Pruning vs. File Exclusion

During [`CstmPath.get_from_dir()`](../src/core/file.py#L110-L131), the scanner inspects each directory before walking its contents:

```python
dirs[:] = [d for d in dirs if not spec.match_file((rel_root / d).as_posix())]
```

If a directory matches an exclusion pattern (e.g. `.git` or `.venv`), it is pruned **immediately in place**. The scanner never reads the contents or metadata of files inside that directory, dramatically reducing execution time on deep repositories.

### Recommended Exclusion List

For everyday Windows usage, the following set is strongly recommended:

```text
$RECYCLE.BIN, System Volume Information, **\.git\**, **\.idea\**, **\.vscode\**, **\.venv\**, **\__pycache__\**, **\.pytest_cache\**, **\.mypy_cache\**, **\~$*, **\*.tmp
```

---

## Scheduler Settings

Automate recurring backups using the built-in scheduler.

### Weekdays (`week_days`)

Configured using a list of 3-letter uppercase weekday identifiers:

| Identifier | Day |
| :---: | :---: |
| `"MON"` | Monday |
| `"TUE"` | Tuesday |
| `"WED"` | Wednesday |
| `"THU"` | Thursday |
| `"FRI"` | Friday |
| `"SAT"` | Saturday |
| `"SUN"` | Sunday |

Example:
```json
"week_days": ["MON", "WED", "FRI"]
```

### Times (`entry_times`)

Configured as an array of 24-hour `HH:MM` time strings:

```json
"entry_times": [
    "12:00",
    "20:30"
]
```

- Invalid time formats are ignored with a warning in the log.
- Multiple times can be added per day.

### Scheduling Watchdog Logic

Every 1000 milliseconds, the GUI watchdog computes the next appointment by scanning up to 10,080 minutes (one full week ahead):

```python
for i in range(60 * 24 * 7):
    future = now + datetime.timedelta(minutes=i)
    if (future.weekday() in days and
        f'{future.hour:02d}:{future.minute:02d}' in times and
        self.last_realized_sync != future):
        next_appointment = future
        break
```

When the current system time rounded to the nearest minute matches `next_appointment`, a background synchronization is automatically spawned.

---

## Synchronization Flags

### Fast Mirror Scanning
- **`checkbox_var_use_mirror`** (`bool`):
  - When `true`: Uses `local_mirror.db` to load target files. Target disk is not traversed.
  - When `false`: Scans the target filesystem directly and updates the mirror database table.

- **`checkbox_var_build_mirror`** (`bool`):
  - When `true`: Wipes the existing table in `local_mirror.db` for the target and performs a full rebuild scan.
  - *Note: `checkbox_var_use_mirror` and `checkbox_var_build_mirror` are mutually exclusive.*

### Metadata vs. Content Comparison
- **`checkbox_var_metadata_comparison`** (`bool`):
  - When `true`: Compares file size and modification timestamp hash (`CompareMethod.METADATA`). Fast and non-intrusive.
  - When `false`: Performs byte-level binary comparison (`CompareMethod.CONTENT`) using `filecmp.cmp`. Accurate, but reads all matching file contents from disk/network.

### Confirmation and Default Actions
- **`checkbox_var_confirm_sync`** (`bool`):
  - When `true`: Displays the interactive review popup before any files are copied, moved, or deleted.
  - When `false`: Immediately executes synchronization based on `checkbox_default_actions`.

- **`checkbox_default_actions`** (`list[str]`):
  - Subset of `["copy", "move", "delete"]`. Controls which actions are pre-checked in the confirmation dialog or executed in unattended mode.

### Reporting
- **`checkbox_var_save_report`** (`bool`):
  - When `true`: Exports `logs/compare_report_YYYY-MM-DD_HH-MM-SS.xlsx` detailing all scanned files, statuses, and sizes.

---

## Complete `config.json` Template

Use this template to create or reset your configuration manually:

```json
{
    "entry_paths": [
        [
            "D:\\Projects",
            "\\\\192.168.1.100\\Backup\\Projects"
        ]
    ],
    "week_days": [
        "MON",
        "TUE",
        "WED",
        "THU",
        "FRI",
        "SAT",
        "SUN"
    ],
    "entry_times": [
        "21:00"
    ],
    "entry_exclusions": [
        "$RECYCLE.BIN",
        "System Volume Information",
        "**\\.git\\**",
        "**\\.venv\\**",
        "**\\__pycache__\\**",
        "**\\~$*"
    ],
    "log_levels": [
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL"
    ],
    "checkbox_default_actions": [
        "copy",
        "move",
        "delete"
    ],
    "checkbox_var_use_mirror": true,
    "checkbox_var_build_mirror": false,
    "checkbox_var_metadata_comparison": true,
    "checkbox_var_confirm_sync": true,
    "checkbox_var_save_report": false
}
```
