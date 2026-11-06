# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version is centrally maintained in `pyproject.toml`.

## [Unreleased]

## [1.4.0] - 2026-11-06

### Added
- **Hardware Volume Serial Keying for Mirror Database (`mirror.py`, `volume.py`)**:
  - Automatically isolates local and external drive caches in SQLite (`data/local_mirror.db`) using hardware Volume Serial numbers (`[SERIAL]\subpath`).
  - Sequentially connecting different physical USB/external drives mapped to the same drive letter (e.g. `E:\`) cleanly separates their cached files and metadata.
  - Transparently preserves cache continuity when a physical drive's letter shifts (e.g. `E:\` $\to$ `F:\`).
  - Added seamless one-time automatic database migration for legacy drive-letter cache records.
- **Batch Endpoint Re-binding with `Change Drive...` (`directory_pairs_modal.py`)**:
  - Replaced manual "Storage Roots" configuration with a streamlined `Change Drive...` action inside the Directory Backup Pairs Manager.
  - Automatically aggregates active drives and network servers (grouping multi-share UNC endpoints under the root server) and provides live before $\to$ after preview when batch-updating pairs.

### Changed
- **Clean Health Check & Status Display (`directory_pairs_modal.py`, `paths_panel.py`)**:
  - Simplified pair status indicators to clean `🟢 Online`, `🔴 Missing Src`, `🔴 Target Offline`, and `🟡 Low Space`, eliminating visual clutter.
- **Auto-Directory Creation for Fresh Targets (`file.py`)**:
  - Gracefully handles non-existent target root folders on new backup drives, scanning empty sets without failure and automatically provisioning directories during sync.

## [1.3.0] - 2026-11-05

### Changed
- **Python 3.13 Runtime Baseline & Toolchain Alignment (`pyproject.toml`)**:
  - Upgraded minimum supported Python specification from `>=3.10` to `>=3.13`, aligning local development, CI/CD runners, and standalone compilation with the modern Python runtime.
  - Modernized static analysis targets for Ruff (`target-version = "py313"`) and Mypy (`python_version = "3.13"`).
  - Modernized project documentation and setup guides to reflect the Python 3.13+ platform requirement.

## [1.2.6] - 2026-11-05

### Fixed
- **Case-Insensitive SQLite Mirror Collation (`mirror.py`)**:
  - Enforced `COLLATE NOCASE` on `rel_path` in `mirror_cache` table schema and path operations (`exists`, `remove_path`, `replace_path`), preventing duplicate cache records when directory or file casing changes.
  - Added automatic database migration in `MirrorDatabase.init()` to upgrade legacy case-sensitive tables and deduplicate existing case-variant rows safely.
- **Treeview Sorting Folder Preservation (`checkbox_treeview.py`)**:
  - Fixed column sorting in the action confirmation popup so directory group nodes remain pinned at the top above individual file items when sorting in descending order.
- **Launcher Mutex Lifecycle (`launch.pyw`)**:
  - Reordered Python virtual environment activation in `launch.pyw` to execute prior to acquiring the Win32 single-instance mutex, eliminating premature mutex lockups during launcher re-spawning.
- **Desktop Shortcut for Frozen Executables (`shortcut.py`)**:
  - Resolved desktop shortcut creation when running from compiled standalone binaries (`FastMirror.exe`), targeting the native executable directly with embedded icons rather than attempting to launch via `launch.pyw` and `pythonw.exe`.
- **Inno Setup Default Version Alignment (`installer.iss`)**:
  - Synchronized default fallback installer version definition with current release.

## [1.2.5] - 2026-11-01

### Fixed
- **Physical Disk Casing Reconciliation for Case Renames (`file_ops.py`, `backend.py`)**:
  - Implemented `ensure_directory_case()` and `rename_case_safe()` to ensure that when folders or files undergo case-only renames (e.g. `04 - Encontro vendraminis Caeté` → `04 - Encontro Vendraminis Caeté`), the physical directory structure and filenames on the target disk are actually updated in-place on Windows filesystems.
  - Added collision-proof two-step rename fallback (`.__fm_case_<pid>_<nanoseconds>__`) with automatic rollback for SMB network shares, Samba, and FAT/exFAT volumes that reject direct case replacement with `ERROR_ALREADY_EXISTS`.
  - Added session-wide in-memory directory verification cache (`_verified_dir_cache`) in `SyncDirs`, ensuring $O(1)$ fast paths for bulk file moves within the same directory.
  - Enhanced `CompareDirs.link_files()` to recognize case-only path changes directly, preventing unnecessary deletion and re-copy cycles even when file names are not globally unique across the directory tree.

## [1.2.4] - 2026-11-01

### Added
- **Multi-Version Changelog Aggregation (`updater.py`)**:
  - Automatically queries the GitHub Releases list and aggregates release notes across all intermediate versions when jumping across versions (e.g. v1.0.0 $\rightarrow$ v1.2.4).
  - Automatically sanitizes redundant download footers and SmartScreen notices, presenting a unified, chronological changelog in the update dialog.
  - Implemented automatic fallback from the releases list endpoint to the single latest release endpoint if needed.

## [1.2.3] - 2026-11-01

### Documentation
- **Architecture & User Flow Alignment**:
  - Synchronized User Guide, Data Storage & Migration Guide, and System Architecture specifications with the seamless 1-click update flow, live chunked progress tracking, and Win32 named mutex concurrency lifecycle.

## [1.2.2] - 2026-11-01

### Added
- **Seamless 1-Click Update & Restart (`UpdateModal`)**:
  - Implemented background chunked downloading (`download_installer_chunked`) with real-time download progress tracking directly within the update dialog.
  - Added "Restart & Install Now" action that spawns the downloaded setup wizard and cleanly shuts down FastMirror (`finalize_quit(force=True)`), preventing locked file collisions (`WinError 32`).
  - Added browser download guidance banner with a dedicated 1-click "Close FastMirror Now" action to ensure clean upgrades when downloading via external browsers.
- **Dedicated Single-Instance Mutex Management (`single_instance.py`)**:
  - Encapsulated Win32 Named Mutex lifecycle (`Local\FastMirror_SingleInstance`) with explicit kernel cleanup (`release_single_instance()`), releasing mutex handles immediately upon application shutdown or update handoff.

### Fixed
- **Installer Running Instance Gatekeeping**:
  - Configured `AppMutex=Local\FastMirror_SingleInstance,FastMirror_SingleInstance` in `packaging/installer.iss` to immediately detect running instances at setup launch, preventing users from advancing to installation while the previous version is active.
  - Added `CloseApplicationsFilter=FastMirror.exe,*` for Windows Restart Manager.

## [1.2.1] - 2026-10-31

### Fixed
- **Shortcut & Desktop Icon Rendering**:
  - Configured Windows Start Menu and Desktop shortcuts to resolve the application icon directly from `FastMirror.exe` PE binary resources (`IconFilename: "{app}\{#AppExeName}"`), eliminating blank or generic sheet icons in Windows Explorer.
  - Linked `UninstallDisplayIcon` in Windows Settings and Control Panel directly to `FastMirror.exe`.
  - Added explicit copying of `app_icon.ico` into `{app}\gui\` as an additional filesystem asset.
- **Installer Upgrade In-Place Cleaning**:
  - Configured Inno Setup `[InstallDelete]` to purge `{app}\_internal` prior to extracting updated files, eliminating orphaned `.dist-info` directories and stale dependency DLLs from earlier installations.
  - Hardened runtime version resolution (`_read_app_version()`) to prioritize bundled `pyproject.toml` and evaluate the highest SemVer from installed distribution metadata.
- **Test Suite Module Teardown Stability**:
  - Replaced per-test `tk.Tk` root instantiation in `test_new_profile_modal.py` with a module-scoped fixture, preventing rapid Tcl interpreter recreation and Win32 file lock collisions.

## [1.2.0] - 2026-10-31

### Added
- **Asynchronous In-App Update Checker (`updater.py`)**:
  - Automatically queries the GitHub Releases API in a background daemon thread 2 seconds after startup, comparing the latest release tag against `APP_VERSION` via SemVer.
  - Displays a prominent, one-click `⚡ Update: vX.Y.Z` button in the top status bar when a newer release is detected.
  - Adds a "Check for Updates..." action to the Windows system tray context menu and updates tray tooltip with new version availability.
  - Integrates an interactive "Check for Updates" button directly into the Help & Documentation modal (`HelpModal`).
- **Update Notification Dialog (`UpdateModal`)**:
  - Modern modal window displaying the new version, release date, and release notes fetched directly from GitHub.
  - Provides direct one-click download buttons for the Windows Setup installer (`.exe`) and Portable edition (`.zip`) along with GitHub release links.
  - Offline-safe and rate-limit resilient: fails silently during startup or offline conditions with zero unhandled exceptions or UI disruption.

## [1.1.1] - 2026-10-31

### Fixed
- **Windows Kernel SMB Network Hang**:
  - Guarded against fallback `os.stat` queries on remote UNC network paths (`\\server\share`) during mirror cache preparation (`MirrorDatabase.add_path`), preventing 25–30s synchronous network redirector (`mup.sys`) stalls and desktop freezing when shares are offline or indexing.
- **Test Suite Desktop Freezing & Window Manager Optimization**:
  - Migrated offscreen window parking coordinates from `+25000+25000` to standard Win32 parked coordinates (`-32000-32000`), preventing Windows Desktop Window Manager (DWM) from inflating virtual multi-monitor bounding boxes.
  - Bypassed synchronous `ctypes.windll.user32.UpdateWindow` desktop paint flushes in test mode.
  - Isolated the Windows clipboard in-memory during tests, preventing global OS clipboard locking and `WM_CLIPBOARDUPDATE` storms across other running desktop applications.
  - Resolved Python 3.13 Tkinter garbage collection shutdown crash (`Tcl_AsyncDelete`) on `Variable.__del__`.

## [1.1.0] - 2026-10-31

### Added
- **Integrated Help & Quick Guide Modal (`HelpModal`)**:
  - Added dedicated interactive help dialog accessible via the top status bar `? Help (F1)` button, keyboard shortcut <kbd>F1</kbd>, and system tray context menu.
  - Features 4 structured tabs: Quick Start (step-by-step workflow guide), Features & Options (comparison modes, actions, SQLite WAL cache, exclusions, automation), Keyboard Shortcuts reference table, and About & Diagnostics with direct folder openers.
- **Contextual Tooltips**:
  - Baked comprehensive, informative tooltips across all interactive controls and status badges in the main window (PathsPanel, SchedulePanel, StatusBar, TelemetryBar, LogPanel) and all dialogs (ConfirmationPopup, DirectoryPairsModal, ExclusionsModal, ReportsWindow).
  - Enhanced `ToolTip` with automatic text wrapping (`wraplength=360`) for clean display without screen boundary clipping.

## [1.0.0] - 2026-10-31

First official production release, representing the culmination of the 2025–2026 development cycle. Provides automated, multi-threaded directory mirroring, synchronization, and backup between local Windows drives and remote SMB/UNC network shares with SQLite WAL caching and a modern desktop GUI.

### Added
- **Core Synchronization Engine**:
  - High-performance one-way directory mirroring and backup for Windows.
  - Native Windows UNC and SMB network share support (`\\server\share`).
  - Intelligent move and rename detection to prevent re-copying existing files.
  - SQLite WAL-mode target mirror cache (`local_mirror.db`) for rapid repeated comparisons without full network re-scans.
  - Specificity scoring for directory pair resolution and lexical UNC path containment.
  - Atomic, robust file operations with metadata preservation (`mtime_ns`, file attributes) and automatic retry handling.
- **Graphical User Interface**:
  - Modern desktop interface with Sun Valley (`sv-ttk`) light theme and high-contrast silhouette icon set.
  - System tray minimization and background operation via `pystray`.
  - Windows Taskbar progress states (normal, paused, error) and single-instance mutex guard.
  - Action selection confirmation modal with hierarchical TreeView, quick filter buttons, search filter, and move origin diffs.
  - Non-blocking target health check and disk space telemetry.
  - Flexible schedule configuration with 8-day candidate run planning and system sleep prevention during active jobs.
  - Profile management for saving, cloning, exporting, and switching between different backup configurations.
  - Windows toast notifications with click-to-restore and automatic error navigation.
  - Desktop shortcut creator CLI and integration.
- **Packaging & CI/CD**:
  - PyInstaller freeze compatibility and standalone executable specification.
  - Inno Setup installer script for standard Windows Setup wizard.
  - Automated GitHub Actions release pipeline for tagged version builds.

