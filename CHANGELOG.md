# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version is centrally maintained in `pyproject.toml`.

## [Unreleased]

## [0.1.0] - 2026-10-31

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

