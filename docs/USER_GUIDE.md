# FastMirror — Desktop User Guide

[![Platform Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg?logo=windows)](https://www.microsoft.com/windows/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
[![Database: SQLite WAL](https://img.shields.io/badge/database-SQLite%20WAL-003B57.svg?logo=sqlite)](https://sqlite.org/)

**FastMirror** is an automated, one-way folder mirroring and backup application for Windows. It lets you mirror important local folders to external drives or network storage shares (`\\server\share`).

Unlike generic copy tools that re-read every file across slow Wi-Fi or SMB network connections, FastMirror uses a local target cache to perform lightning-fast incremental checks, detects when files were renamed or moved so they don't need to be transferred again, and lets you visually preview every change before anything is touched.

---

## Table of Contents

1. [Downloading & Installing (No Python Needed)](#downloading--installing-no-python-needed)
   - [Setup Installer (Recommended)](#1-setup-installer-recommended)
   - [Portable Edition (ZIP)](#2-portable-edition-zip)
2. [Quick Start: Your First Backup in 3 Minutes](#quick-start-your-first-backup-in-3-minutes)
3. [User Interface Tour](#user-interface-tour)
   - [Top Toolbar & Profile Management](#top-toolbar--profile-management)
   - [Paths & Directory Pairs Panel](#paths--directory-pairs-panel)
   - [Exclusion Filters](#exclusion-filters)
   - [Weekly Scheduler Panel](#weekly-scheduler-panel)
   - [Backup Options & Comparison Modes](#backup-options--comparison-modes)
   - [Interactive Action Confirmation Dialog](#interactive-action-confirmation-dialog)
   - [Windows System Tray & Notifications](#windows-system-tray--notifications)
   - [Activity Log Panel & History Reports](#activity-log-panel--history-reports)
4. [Safety Features & Invariants](#safety-features--invariants)
5. [Frequently Asked Questions (FAQ)](#frequently-asked-questions-faq)
6. [Additional Guides](#additional-guides)

---

## Downloading & Installing (No Python Needed)

You do **not** need Python, Git, or command-line tools to use FastMirror. Download pre-compiled Windows releases directly from GitHub:

👉 **[Download Latest Release on GitHub](https://github.com/rafaelsavi/fast-mirror/releases/latest)**

### 1. Setup Installer (Recommended)
- **File**: `FastMirror-v<version>-Windows-Setup.exe`
- **Installation**: Double-click the installer and follow the prompt.
- **Per-User Setup**: Installs directly into your user profile (`%LOCALAPPDATA%\Programs\FastMirror`). Does **not** require Windows Administrator elevation or UAC prompts.
- **Shortcuts**: Automatically adds Start Menu and Desktop shortcuts.
- **Seamless Upgrades**: Installing future updates will automatically replace the program files while keeping all your profiles, schedules, and mirror database completely intact.

### 2. Portable Edition (ZIP)
- **File**: `FastMirror-v<version>-Windows-Portable.zip`
- **Installation**: Right-click the ZIP file $\rightarrow$ **Extract All...** to any folder (e.g. on a USB flash drive or external hard drive).
- **Self-Contained**: Double-click `FastMirror.exe` to run. All configurations, profiles, and databases are stored locally in the same folder without touching your Windows user profile.

---

## Quick Start: Your First Backup in 3 Minutes

Follow these three simple steps to run your first backup:

```text
Step 1: Add Folders          Step 2: Quick Compare          Step 3: Sync Now
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│ Source -> Target    │ ──► │ Review Proposed     │ ──► │ Safely Apply        │
│ Directory Pairs     │     │ Changes & Volumes   │     │ Approved Operations │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

1. **Add Your Directory Pair**:
   - In the **Paths & Directory Pairs** panel on the left, click **+ Add Pair**.
   - Browse or paste your **Source** folder (e.g. `D:\Photos` or `C:\Users\Username\Documents`).
   - Browse or paste your **Target** backup destination (e.g. `E:\Backup\Photos` or `\\NAS\Storage\Photos`).
   - Click **Save Pair**.

2. **Run a Quick Compare**:
   - In the top Actions toolbar, click **Quick Compare**.
   - FastMirror scans your source folder, loads the destination index, and displays an **interactive confirmation popup**.
   - The popup lists every planned `COPY`, `MOVE`, and `DELETE` operation with individual file sizes, timestamps, and total volumes.

3. **Execute the Backup**:
   - Review the proposed operations. If there are deletions you wish to prevent, simply uncheck them.
   - Click **Proceed with Sync** (or press <kbd>Enter</kbd>).
   - FastMirror safely copies new/modified files, moves renamed files, and updates the index.

---

## User Interface Tour

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│ FastMirror v1.2.3                   Profile: [ Default ▾ ] [Save] [+ New] [Del] │
├───────────────────────────────────┬─────────────────────────────────────────────┤
│ PATHS & DIRECTORY PAIRS           │ ACTIONS & SETTINGS                          │
│ [ + Add Pair ] [ Edit Pairs ]     │ [ Quick Compare ]  [ Sync Now ]  [ Reports ]│
│                                   │ Comparison Mode: (•) Metadata  ( ) Content  │
│ 📁 D:\Photos                      │ [✓] Use mirror cache   [ ] Rebuild mirror   │
│  └─► \\NAS\Backup\Photos          │ [✓] Confirm before sync [ ] Save Excel report│
│      Status: Reachable (142 GB)   ├─────────────────────────────────────────────┤
│                                   │ WEEKLY SCHEDULE                             │
│ 📁 C:\Users\Username\Documents    │ Days: [✓] Mon [✓] Wed [✓] Fri [ ] Sun       │
│  └─► E:\Backups\Documents         │ Times: [ 20:30 ] [ + Add Time ]             │
│      Status: Reachable (18 GB)    │ Next Run: Today at 20:30 (in 3h 15m)        │
├───────────────────────────────────┴─────────────────────────────────────────────┤
│ ACTIVITY LOG                                [INFO] [WARNING] [ERROR] [📁 Folder] │
│ 14:15:02: Scanning D:\Photos...                                                 │
│ 14:15:05: Comparison complete: 3 to copy (14.2 MB), 1 to move, 0 to delete      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Top Toolbar, Help & Profile Management

FastMirror allows you to organize different backup sets into **Profiles** (e.g. `Default`, `Work Projects`, `Family Media`, `NAS Backup`):

- **Help & Quick Guide (`? Help (F1)`)**: Click the **? Help (F1)** button in the top status bar or press <kbd>F1</kbd> anywhere in the application to open the integrated quick start guide, feature reference, and keyboard shortcuts list.
- **Contextual Tooltips**: Hover your mouse over any button, input field, checkbox, or status indicator across the application to view instant, non-blocking tooltips explaining its behavior and usage tips.
- **Profile Selector (`Profile: [ Default ▾ ]`)**: Instantly switches between different sets of directory pairs, schedules, and settings.
- **Save (`Ctrl+S`)**: Saves any modifications to the active profile.
- **+ New**: Creates a new profile. You can start clean with a blank profile or clone the settings of the currently active profile.
- **Delete**: Deletes the selected profile (the `Default` profile cannot be deleted).
- **Right-Click Context Menu**:
  - Right-click the **Profile** dropdown to access advanced actions:
    - `🔄 Reload Profile (Ctrl+R)`: Discard unsaved changes and reload from disk.
    - `📋 Clone Active Profile...`: Duplicate the current profile under a new name.
    - `✏️ Rename Active Profile...`: Rename the active profile.
    - `📁 Import Profile...`: Import a configuration file from another computer.
    - `📂 Open Profiles Folder`: Opens the folder containing your profile JSON files in Windows Explorer.
    - `🧹 Reset to Defaults`: Resets the active profile to factory settings.

---

### Paths & Directory Pairs Panel

This panel displays all configured one-way backup paths:

- **Source $\rightarrow$ Target Mapping**: Each card shows the local folder path and where it mirrors to.
- **Destination Health & Reachability**: FastMirror automatically verifies whether destinations (like USB drives or network shares) are plugged in and connected, displaying free disk space chips.
- **Right-Click Card Menu**: Right-click any directory card to:
  - Open Source or Target in Windows Explorer.
  - Temporarily disable the pair without deleting it.
  - Delete or reorder pairs.

---

### Exclusion Filters

To prevent copying temporary files, caches, or system folders:

1. Click **Exclusions** in the Paths panel.
2. FastMirror supports familiar `.gitignore`-style wildcard syntax:
   - `$RECYCLE.BIN` / `System Volume Information`: Windows system folders (ignored by default).
   - `\~$*`: Microsoft Office temporary lock files.
   - `*.tmp` / `*.bak`: Temporary and backup files.
   - `node_modules/` / `__pycache__/`: Development caches.
3. Ignored folders are skipped instantly during traversal, dramatically speeding up scans.

---

### Weekly Scheduler Panel

Set up unattended background backups:

- **Days of the Week**: Check the days you want FastMirror to run (e.g. Monday, Wednesday, Friday).
- **Execution Times**: Enter daily backup times in 24-hour format (e.g. `13:00`, `20:30`). You can add multiple times per day.
- **Next Scheduled Run**: Displays a live countdown to the next automated backup appointment.
- **Schedule Toggle**: Click **Enable Schedule** in the Actions panel. When enabled, FastMirror will run automatically at the scheduled times even when minimized to the Windows system tray.

---

### Backup Options & Comparison Modes

- **Comparison Mode**:
  - **Metadata (Default & Recommended)**: Compares file size and nanosecond modification timestamps (`mtime_ns`). Lightning fast—ideal for daily backups over Wi-Fi or network shares.
  - **Content (Byte-by-Byte)**: Computes cryptographic hashes of file contents. Thorough, but reads every file's entire content from disk.
- **Use Mirror Cache**: Recommended. Uses the local SQLite index to avoid repeatedly querying every file on remote network shares.
- **Rebuild Mirror**: Forces FastMirror to scan the destination filesystem from scratch and rebuild the local index. Use this if you manually modified files on the destination outside FastMirror.
- **Confirm Before Sync**: Recommended. Displays the interactive confirmation popup before applying changes.
- **Save Detailed Report**: Generates a timestamped Excel (`.xlsx`) workbook auditing every compared file and operation.

---

### Interactive Action Confirmation Dialog

When you run a comparison or click **Sync Now**, FastMirror opens a safety review window:

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Review Synchronization Actions                                      [  X  ]     │
│ 3 to copy (14.2 MB)  •  1 to move (520 KB)  •  2 to delete (1.1 MB)             │
├─────────────────────────────────────────────────────────────────────────────────┤
│ [✓] Action   Source Path                    Target Path                 Size    │
│ ─────────────────────────────────────────────────────────────────────────────── │
│  ☑  COPY     D:\Photos\vacation_01.jpg     \\NAS\Photos\vacation_01.jpg  4.2 MB │
│  ☑  COPY     D:\Photos\vacation_02.jpg     \\NAS\Photos\vacation_02.jpg  5.1 MB │
│  ☑  MOVE     D:\Photos\Trip\map.png        \\NAS\Photos\Travel\map.png 520 KB   │
│  ☐  DELETE   (none)                        \\NAS\Photos\old_draft.txt    1.1 MB │
├─────────────────────────────────────────────────────────────────────────────────┤
│ [ Uncheck All Deletions ]  [ Select All ]  [ Filter: __________ ]               │
│                                                 [ Cancel ]  [ Proceed with Sync]│
└─────────────────────────────────────────────────────────────────────────────────┘
```

- **Visual Group Badges**: Displays exact count and cumulative transfer size for each category.
- **Uncheck Deletions Safety Button**: Click **Uncheck All Deletions** to instantly deselect all removal operations while keeping additions and moves enabled.
- **Individual Checkboxes**: You can uncheck any specific file operation to skip it during the current run.
- **Filter Search Bar (<kbd>Ctrl+F</kbd>)**: Quickly search for filenames or folder paths in large sync sets.
- **Keyboard Shortcuts**: Press <kbd>Enter</kbd> to proceed with approved operations, or <kbd>Esc</kbd> to cancel.

---

### Windows System Tray & Notifications

FastMirror integrates directly into the Windows notification area (bottom-right system tray):

- **Minimize to Tray**: Click the minimize button or close the window; FastMirror will prompt to keep running silently in the background.
- **Tray Icon**: The FastMirror icon appears in the Windows system tray. Hovering over it shows the current status and time until the next scheduled backup.
- **Right-Click Tray Menu**:
  - `Restore Window`: Brings FastMirror to the front.
  - `Quick Compare Now`: Triggers an immediate comparison.
  - `Sync Now`: Executes backup for all enabled pairs.
  - `Exit`: Safely closes FastMirror, prompting to save if you have unsaved configuration changes.
- **Windows Balloon / Toast Notifications**: Notifies you when scheduled backups complete, or alerts you if a target share was unreachable.

---

### Activity Log Panel & History Reports

- **Real-Time Log Stream**: View real-time progress, file transfer speeds, and diagnostic messages.
- **Level Filters**: Filter log messages by severity (`INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- **Open Log Folder**: Click the **📁 Folder** button in the top-right of the log panel to open the persistent log directory in Windows Explorer.
- **Past Reports Browser**: Click **Past reports...** in the Actions toolbar to open the interactive report viewer, allowing you to open historical Excel reports or clean up old logs.

---

## Safety Features & Invariants

FastMirror is engineered with strict data safety rules:

1. **One-Way Mirroring Only**: Changes flow exclusively from Source to Destination. FastMirror **never** modifies, overwrites, or deletes files on your source computer.
2. **Atomic Writes**: All destination file transfers write to a temporary `.tmp` file first before replacing the final destination file. If power fails or the network disconnects midway, your existing destination files remain uncorrupted.
3. **Preserves Timestamps & Attributes**: File modification dates (`mtime_ns`) and attributes are copied accurately (`copystat`).
4. **Safe Move Execution**: When files are renamed or moved on the source, FastMirror executes atomic moves on the target rather than re-uploading gigabytes over the network.
5. **No Blind Deletions**: Deletions are optional, can be globally disabled in settings, and are visually highlighted in the confirmation popup.

---

## Frequently Asked Questions (FAQ)

### What happens if my external hard drive or NAS is unplugged?
FastMirror performs a non-blocking reachability probe before attempting any synchronization. If the destination drive is disconnected, FastMirror logs a clear warning, skips the unreachable pair safely, and proceeds with other available pairs without failing or corrupting data.

### How do I update to a newer version?
FastMirror automatically checks for new releases on startup without slowing down your system. When an update is available:
1. Click the `⚡ Update: vX.Y.Z` button in the top status bar or select **Check for Updates...** from the System Tray menu.
2. Review the release notes and click **Update & Restart** (or choose **In Browser** if you prefer downloading manually).
3. FastMirror downloads the installer in the background with real-time progress.
4. When ready, click **Restart & Install Now**. FastMirror will cleanly close itself, release system locks, and launch the installer wizard. Once completed, the updated version will automatically launch with all your profiles, schedules, and mirror caches preserved.

### Will FastMirror ever delete files from my original Source folders?
**No, never.** FastMirror is strictly a one-way mirror. It only ever writes to or removes obsolete files from the **Target** destination. Your Source files are treated as read-only inputs.

### How do I make FastMirror start automatically when Windows boots?
1. Press <kbd>Win</kbd> + <kbd>R</kbd>, type `shell:startup`, and press <kbd>Enter</kbd>.
2. Copy your **FastMirror** desktop shortcut into the opened Startup folder.
3. When Windows starts, FastMirror will launch automatically into the system tray and monitor your weekly backup schedule.

### Can I back up to network shares (e.g. Synology, QNAP, TrueNAS, Windows Server)?
**Yes.** FastMirror has native support for Windows Universal Naming Convention (UNC) paths over SMB networks (e.g. `\\192.168.1.100\Backups\Photos` or `\\mynas\share`). Its local SQLite mirror cache is specially designed to eliminate the slowdowns typical of network shares.

---

## Additional Guides

- 💾 **[Data Storage, File Locations & Migration Guide](DATA_AND_STORAGE.md)**: Details on where configuration files and databases live, update safety, and how to migrate your settings to a new PC.
- ⚙️ **[Advanced Configuration & Exclusions Guide](CONFIGURATION.md)**: Advanced JSON options, command-line arguments, and wildcard pattern matching.
- 💻 **[Developer & Testing Guide](DEVELOPMENT.md)**: For developers wishing to run FastMirror from source, run tests, or contribute.
