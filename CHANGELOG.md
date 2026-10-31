# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version is centrally maintained in `pyproject.toml`.

## [Unreleased]

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

