# FastMirror — Data Storage, File Locations & Migration Guide

This guide explains how **FastMirror** stores its configuration files, profiles, cache databases, and logs on Windows, how it protects your settings across application updates, and how to back up or migrate your configuration to another computer.

---

## Table of Contents

1. [Storage Architecture Overview](#storage-architecture-overview)
2. [File Locations Breakdown](#file-locations-breakdown)
   - [Installed Mode (Setup Wizard)](#installed-mode-setup-wizard)
   - [Portable Mode (ZIP Edition)](#portable-mode-zip-edition)
   - [Development Mode (Source Code)](#development-mode-source-code)
3. [Component Details](#component-details)
   - [Configuration Profiles (`profiles/`)](#configuration-profiles-profiles)
   - [Active Configuration Mirror (`config.json`)](#active-configuration-mirror-configjson)
   - [SQLite Mirror Database (`local_mirror.db`)](#sqlite-mirror-database-local_mirrordb)
   - [Diagnostic Logs & Reports (`logs/`)](#diagnostic-logs--reports-logs)
4. [Safety, Updates & Uninstallation](#safety-updates--uninstallation)
   - [Why Application Binaries and Data Are Separated](#why-application-binaries-and-data-are-separated)
   - [Updating FastMirror](#updating-fastmirror)
   - [Uninstalling FastMirror](#uninstalling-fastmirror)
5. [In-App Navigation (No Hidden Folders)](#in-app-navigation-no-hidden-folders)
6. [Backup & Migration Runbooks](#backup--migration-runbooks)
   - [Migrating Your Settings to a New PC](#migrating-your-settings-to-a-new-pc)
   - [Converting from Installed Mode to Portable Mode](#converting-from-installed-mode-to-portable-mode)
   - [Resetting Configuration to Factory Defaults](#resetting-configuration-to-factory-defaults)

---

## Storage Architecture Overview

FastMirror uses a **three-tier storage model** designed around official Microsoft Windows application standards:

- **Per-User Security**: Data is saved inside the user's personal profile (`%LOCALAPPDATA%`), requiring zero administrative rights or UAC elevation.
- **Update Resilience**: Application executables and user data live in separate directories so updates never overwrite your backup pairs, schedules, or cached file indexes.
- **Portable Freedom**: Running portably keeps all files inside the local program folder, leaving zero trace in the Windows registry or user profile.

---

## File Locations Breakdown

### Installed Mode (Setup Wizard)
When installed using `FastMirror-Setup.exe`, files are organized as follows:

| Component | Path on Windows | Description |
| :--- | :--- | :--- |
| **Application Executable** | `%LOCALAPPDATA%\Programs\FastMirror\FastMirror.exe` | Main program binary and bundled resources. |
| **Active Configuration** | `%LOCALAPPDATA%\FastMirror\data\config.json` | Active backup pairs, schedules, and preferences. |
| **Named Profiles** | `%LOCALAPPDATA%\FastMirror\data\profiles\<Profile>.json` | Individual profile configurations (`Default.json`, `NAS.json`). |
| **Mirror Database** | `%LOCALAPPDATA%\FastMirror\data\local_mirror.db` | SQLite index caching destination file paths and blake2b hashes. |
| **Database WAL / SHM** | `%LOCALAPPDATA%\FastMirror\data\local_mirror.db-wal` | SQLite Write-Ahead Log enabling fast concurrent transactions. |
| **Session Logs** | `%LOCALAPPDATA%\FastMirror\data\logs\log_*.txt` | Timestamped execution records and error logs. |
| **Excel Audit Reports** | `%LOCALAPPDATA%\FastMirror\data\logs\compare_report_*.xlsx` | Generated spreadsheets when *Save detailed report* is checked. |

*(Note: `%LOCALAPPDATA%` corresponds to `C:\Users\Username\AppData\Local` on standard Windows installations).*

### Portable Mode (ZIP Edition)
When extracted from `FastMirror-Portable.zip`, FastMirror detects the presence of `portable.txt` and operates in self-contained mode:

```text
FastMirror-Portable/
├── FastMirror.exe                # Application executable
├── portable.txt                  # Portable mode marker
└── data/                         # All user data stored locally
    ├── config.json               # Active settings
    ├── profiles/                 # Saved configuration profiles
    │   └── Default.json
    ├── local_mirror.db           # SQLite cache database
    └── logs/                     # Logs and Excel audit files
```

### Development Mode (Source Code)
When launched from source (`python launch.pyw` or `uv run python launch.pyw`), data is stored in the repository root:
```text
fast-mirror/data/
```

---

## Component Details

### Configuration Profiles (`profiles/`)
- FastMirror stores each named profile as an independent JSON file in `data/profiles/<profile_name>.json`.
- When you create, clone, rename, or switch profiles in the GUI, FastMirror reads and writes directly to these files.
- **Atomic Writes**: Profiles are written to a temporary `.json.tmp` file and atomically renamed to prevent corruption if power is interrupted during a save.
- **Backup on Corruption**: If a profile file is ever modified externally with invalid JSON syntax, FastMirror preserves the damaged file as `<name>.corrupted_<timestamp>.json` and loads safe defaults rather than discarding data.

### Active Configuration Mirror (`config.json`)
- For seamless backward compatibility and external tool integration, the currently active profile is always mirrored to `data/config.json`.
- It tracks the `active_profile` key so FastMirror re-opens your last-used profile automatically on the next launch.

### SQLite Mirror Database (`local_mirror.db`)
- FastMirror accelerates repeated scans to slow destinations (such as external USB hard drives or network NAS shares over SMB/Wi-Fi) by indexing destination files locally.
- **WAL Mode (`Write-Ahead Logging`)**: Operates with high concurrency, allowing worker threads to query the cache without locking out GUI status updates.
- **Fingerprint Invalidation**: The database stores an exclusion fingerprint. If you change your exclusion rules, FastMirror automatically detects the change and refreshes the index.
- **Rebuilding**: You can wipe and rebuild the local index at any time by checking **Rebuild mirror** in the Actions panel.

### Diagnostic Logs & Reports (`logs/`)
- **Text Logs**: Every synchronization session generates a timestamped text file `log_YYYY-MM-DD_HH-MM-SS.txt` in the `logs/` directory.
- **Excel Comparison Spreadsheets**: When the **Save detailed report** option is enabled, FastMirror exports an Excel workbook `compare_report_YYYY-MM-DD_HH-MM-SS.xlsx` listing every compared file, file sizes, modification timestamps, and status flags (`only source`, `only target`, `modified`, `moved`, `same`).

---

## Safety, Updates & Uninstallation

### Why Application Binaries and Data Are Separated
In standard Windows desktop software architecture, executable files and user state must never share the same folder.
- FastMirror places binaries in `%LOCALAPPDATA%\Programs\FastMirror\`.
- FastMirror places user settings in `%LOCALAPPDATA%\FastMirror\data\`.

### Updating FastMirror
When you download and run a newer installer (e.g. upgrading from `v0.1.0` to `v0.2.0`):
1. Inno Setup safely updates the executable files inside `%LOCALAPPDATA%\Programs\FastMirror\`.
2. **Your `%LOCALAPPDATA%\FastMirror\data\` directory is left completely untouched.**
3. When you open the updated FastMirror, all your directory pairs, profiles, scheduled backup times, and cached file databases are immediately available.

### Uninstalling FastMirror
If you choose to uninstall FastMirror via Windows **Settings $\rightarrow$ Apps $\rightarrow$ Installed apps**:
1. Windows removes the program files and shortcuts from `%LOCALAPPDATA%\Programs\FastMirror\`.
2. **Your backup configuration and mirror database in `%LOCALAPPDATA%\FastMirror\data\` are intentionally preserved.** This guarantees that an accidental uninstallation will never wipe out your customized backup configurations or audit logs.
3. If you want to perform a 100% clean wipe, simply delete the `%LOCALAPPDATA%\FastMirror` folder in Windows Explorer.

---

## In-App Navigation (No Hidden Folders)

Windows hides the `AppData` folder by default. FastMirror provides direct one-click shortcuts inside the graphical user interface:

- **Open Profiles Folder**:
  - Right-click the **Profile** dropdown in the top toolbar $\rightarrow$ click **📂 Open Profiles Folder**.
  - Windows Explorer opens directly to `%LOCALAPPDATA%\FastMirror\data\profiles\`.
- **Open Logs Folder**:
  - In the bottom-right **Activity Log** panel, click the **📁 Open Log Folder** button.
  - Windows Explorer opens directly to `%LOCALAPPDATA%\FastMirror\data\logs\`.
- **Browse Past Reports**:
  - In the **Actions** toolbar, click **Past reports...** to open the interactive report viewer, allowing you to view file sizes, open spreadsheets, or delete old logs with one click.

---

## Backup & Migration Runbooks

### Migrating Your Settings to a New PC

To transfer all your FastMirror profiles and backup settings to a new computer:

1. **On your current PC**:
   - Open FastMirror, right-click the **Profile** dropdown $\rightarrow$ select **Open Profiles Folder**.
   - Copy the `profiles/` folder and `config.json` to a USB flash drive or cloud storage.
2. **On your new PC**:
   - Install FastMirror from `FastMirror-Setup.exe`.
   - Launch FastMirror once, then close it (this creates the data folders).
   - Right-click the **Profile** dropdown $\rightarrow$ select **Open Profiles Folder**.
   - Paste your saved profile JSON files into this folder.
   - Re-open FastMirror. All your directory pairs, exclusions, and schedules will appear immediately!

### Converting from Installed Mode to Portable Mode

If you want to move your existing configuration onto a portable USB drive:
1. Download and extract `FastMirror-Portable.zip` onto your USB drive.
2. Copy the contents of `%LOCALAPPDATA%\FastMirror\data\` into the `data\` folder on your USB drive next to `FastMirror.exe`.
3. Launch `FastMirror.exe` from the USB drive. It will run with your exact existing settings.

### Resetting Configuration to Factory Defaults

To reset your active configuration to clean factory defaults:
- **In GUI**: Click the **New Config** button in the Actions panel (or right-click the Profile dropdown $\rightarrow$ **Reset to Defaults**).
- **Manual Clean Wipe**: Close FastMirror, press <kbd>Win</kbd> + <kbd>R</kbd>, enter `%LOCALAPPDATA%\FastMirror`, and delete or rename the `data` folder. FastMirror will regenerate a fresh default profile upon the next launch.
