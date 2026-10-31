# FastMirror

[![Platform Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg?logo=windows)](https://www.microsoft.com/windows/)
[![Release](https://img.shields.io/github/v/release/rafaelsavi/fast-mirror?color=2ea44f&logo=github)](https://github.com/rafaelsavi/fast-mirror/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Database: SQLite WAL](https://img.shields.io/badge/database-SQLite%20WAL-003B57.svg?logo=sqlite)](https://sqlite.org/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB.svg?logo=python)](https://www.python.org/)

**Automated, accelerated one-way folder mirroring and backup for Windows to external drives and network shares (NAS).**

FastMirror is designed for anyone who regularly backs up important local folders to an external hard drive or a network storage share (`\\server\share`). Its local target index avoids slow repeated file listings over Wi-Fi or SMB, while move detection saves hours of bandwidth by moving or renaming files directly on the destination instead of transferring them all over again.

---

## 📥 Download & Installation (Windows 10 / 11)

**No Python or programming knowledge required!** Pre-compiled standalone releases are available on GitHub:

👉 **[Download the Latest Release on GitHub](https://github.com/rafaelsavi/fast-mirror/releases/latest)**

| Edition | File | Best For |
| :--- | :--- | :--- |
| 📦 **Installer (Recommended)** | `FastMirror-v1.0.0-Windows-Setup.exe` | **Most users.** Runs a standard setup wizard without requiring administrator elevation. Installs to your user profile, adds Start Menu & Desktop shortcuts, and seamlessly preserves your configuration during updates. |
| 🧳 **Portable Edition** | `FastMirror-v1.0.0-Windows-Portable.zip` | **USB flash drives & external drives.** Unzip and double-click `FastMirror.exe`. Fully self-contained—keeps all settings, database caches, and logs inside its local folder without touching your Windows user profile. |

---

## 🚀 Quick Start (3 Steps)

1. **Add Your Folders**:
   - In the **Paths & Directory Pairs** panel on the left, click **+ Add Pair** (or press `Enter` in the text field).
   - Choose your **Source** folder (e.g. `D:\Photos` or `C:\Users\Username\Documents`) and your **Target** destination (e.g. `E:\Backup` or `\\NAS\Storage\Photos`).
2. **Review Proposed Changes**:
   - Click **Quick Compare** to see what has changed without altering any files.
   - FastMirror displays an interactive preview of planned `COPY`, `MOVE`, and `DELETE` operations. You can selectively uncheck items (such as accidental deletions) before proceeding.
3. **Run or Schedule Backup**:
   - Click **Sync Now** to apply the approved actions.
   - *(Optional)* Check days of the week and times in the **Weekly Schedule** panel to let FastMirror mirror automatically in the background while minimized to the Windows system tray.

---

## ✨ Key Features

- **⚡ Instant Network Scans**: Caches destination file trees in a local SQLite database (`Write-Ahead Logging` mode). Repeated scans over slow SMB network shares or Wi-Fi take seconds instead of minutes.
- **🔄 Smart Move & Rename Detection**: Recognizes when files were renamed or reorganized on your source drive. It executes atomic moves directly on the destination rather than deleting and re-uploading gigabytes of data.
- **🛡️ Visual Safety Confirmation**: An interactive dialog previews all proposed additions, moves, and deletions with file size badges, timestamps, and aggregate group volumes before any file is touched.
- **📁 Multi-Profile Support**: Switch between distinct backup configurations (`Default`, `Office Work`, `Photo Archive`, `NAS Storage`) with one click from the toolbar.
- **🕒 Weekly Automation**: Schedule recurring backups by choosing specific days of the week and times.
- **🔔 Windows System Tray Integration**: Minimizes seamlessly to the Windows notification tray with customizable background notifications and one-click restoration.
- **🚫 Wildcard & Git-Style Exclusions**: Ignore temporary files, caches, and system folders using familiar `.gitignore`-style wildcard patterns (e.g. `$RECYCLE.BIN`, `\~$*`, `*.tmp`, `node_modules/`).
- **📊 Detailed Audit Reports**: Export rich color-coded Excel (`.xlsx`) spreadsheets comparing source and destination trees side by side.

---

## 📚 Complete Documentation

Documentation is organized by role and expertise:

### 🙋‍♂️ Desktop Users (No Python Needed)
- 📖 **[Desktop User Guide](docs/USER_GUIDE.md)** — Step-by-step visual tour of the user interface, buttons, confirmation dialog, and everyday FAQ.
- 💾 **[Data Storage & Migration Guide](docs/DATA_AND_STORAGE.md)** — Where profiles and databases are saved, update safety, and how to migrate settings to a new PC.

### ⚙️ Power Users & System Administrators
- 🛠️ **[Configuration & Exclusions Guide](docs/CONFIGURATION.md)** — Advanced JSON schema reference, CLI launch flags (`--profile`, `--config`), and UNC network share handling.

### 💻 Developers & Contributors
- 💻 **[Development & Contribution Guide](docs/DEVELOPMENT.md)** — Developer setup with `uv`, unified verification runner (`scripts/verify.py`), packaging standalone executables, and automated CI/CD release flow.
- 🏗️ **[System Architecture](docs/ARCHITECTURE.md)** — In-depth analysis of the comparison engine, synchronization pipeline, and SQLite WAL caching.
- 🛡️ **[Synchronization Robustness](docs/SYNC_ROBUSTNESS.md)** — JIT self-healing mechanisms, atomic writes, Windows file lock handling, and cooperative cancellation.

---

## 🛠️ Running from Source (For Developers)

If you are developing or contributing to FastMirror:

**Requirements:** Windows 10/11, Python 3.10+, and [uv](https://docs.astral.sh/uv/).

```powershell
# 1. Clone the repository
git clone https://github.com/rafaelsavi/fast-mirror.git
cd fast-mirror

# 2. Sync dependencies and virtual environment
uv sync

# 3. Launch GUI
uv run python launch.pyw

# 4. Run automated verification (tests, linting, type checks)
uv run python scripts/verify.py --check-version
```

---

## 📄 License & Credits

Created by **Rafael Savi**. Licensed under the [MIT License](LICENSE).
