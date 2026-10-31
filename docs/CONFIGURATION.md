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

## Configuration & Profile Overview

FastMirror supports **Multiple Configuration Profiles** stored in `profiles/<profile_name>.json` (located in `%LOCALAPPDATA%\FastMirror\data\profiles\` when installed via Setup, or `<app_dir>\data\profiles\` in portable mode), with active settings mirrored in `config.json` for full backward compatibility.

### Toolbar Controls
- **Profile Selector**: A dropdown combobox (`Profile: [ Default ▾ ]`) directly in the toolbar. Selecting any profile immediately loads its directory pairs, exclusions, schedules, comparison method, and preferences into the GUI.
- **Save (`Ctrl+S`)**: Saves the current UI settings and directory pairs atomically to the active profile file (`data/profiles/<name>.json`) and mirrors them to `data/config.json`.
- **+ New**: Opens the **New Profile** modal prompting for a profile name and starting configuration template:
  - 🔘 **Based on current profile ('<active>')**: Copies current directory pairs, ignore patterns, schedules, and synchronization options.
  - 🔘 **Blank profile**: Starts clean with empty directory pairs and default settings.
- **Delete**: Prompts for confirmation and deletes the active profile from `data/profiles/`, switching back to `Default` (`Default` profile cannot be deleted).

### Context Menus & Advanced Operations
- **Right-Click Combobox**: Access profile actions:
  - `🔄 Reload Profile (Ctrl+R)` (reverts in-session modifications back to saved state)
  - `📋 Clone Active Profile...` (duplicate profile under a new name)
  - `✏️ Rename Active Profile...` (rename profile file and UI selection)
  - `📁 Import Profile from File...` (import any JSON config into the profile)
  - `📂 Open Profiles Folder` (opens `data/profiles/` in Windows Explorer)
  - `🧹 Reset to Defaults` (reset active configuration to default values)
- **Right-Click Save**:
  - `💾 Save to Active Profile`
  - `💾 Save As / Export to File...` (export config to any destination on disk)

### Launcher CLI Arguments
FastMirror supports launching directly into a specific profile:
```bash
# Launch with the 'NAS' profile active
python launch.pyw --profile "NAS"

# Launch with an external configuration file
python launch.pyw --config "D:\Backups\custom_job.json"
```

### Safety & Offline Protection
- **Offline / Disconnected Safety**: All configured directory pairs (local and remote UNC network shares) are preserved across saves even if network shares or external drives are temporarily unreachable when saving.
- **Atomic Writes**: Profiles and global configuration are written to temporary `.tmp` files first and atomically replaced, eliminating file corruption risks.
- **Error Handling**: Corrupted or invalid JSON files are preserved without data loss and backed up (`<profile>.corrupted_<timestamp>.json`).

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

When validating paths in [`EntryPaths.parse_line()`](../src/gui/widgets.py):
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

During [`CstmPath.get_from_dir()`](../src/core/file.py), the scanner inspects each directory before walking its contents:

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

The scheduler calculates the next upcoming execution using [`calculate_next_run()`](../src/gui/scheduler.py):

```python
def calculate_next_run(
    days: list[int],
    times: list[str],
    now: datetime.datetime | None = None,
    last_run: datetime.datetime | None = None,
) -> datetime.datetime | None:
    ...
```

Instead of iterating through thousands of individual minutes, it parses configured times and evaluates target candidate dates across the next 8 days, directly computing the earliest valid future appointment. Every 1000 milliseconds, the GUI watchdog compares current time against this appointment and spawns background synchronization when reached.

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
  - When `true`: Exports `data/logs/compare_report_YYYY-MM-DD_HH-MM-SS.xlsx` detailing all scanned files, statuses, and sizes.

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
