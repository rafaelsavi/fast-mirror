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

**No Python or programming knowledge required!** Simply download the pre-compiled executable from GitHub Releases:

👉 **[Download the Latest Release on GitHub](https://github.com/rafaelsavi/fast-mirror/releases/latest)**

| Edition | File | Best For |
| :--- | :--- | :--- |
| 📦 **Installer (Recommended)** | `FastMirror-v0.1.0-Windows-Setup.exe` | **Most users.** Runs a standard setup wizard without requiring administrator elevation. Installs to your user profile, adds Start Menu & Desktop shortcuts, and seamlessly preserves your configuration during updates. |
| 🧳 **Portable Edition** | `FastMirror-v0.1.0-Windows-Portable.zip` | **USB flash drives & external drives.** Unzip and double-click `FastMirror.exe`. Fully self-contained—keeps all settings, database caches, and logs inside its local folder without touching your Windows user profile. |

---

## 🚀 Quick Start (3 Steps)

1. **Add Your Folders**:
   - In the **Paths & Directory Pairs** panel, click **+ Add Pair** (or press `Enter` in the text field).
   - Choose your **Source** folder (e.g. `D:\Photos` or `C:\Users\Username\Documents`) and your **Target** destination (e.g. `E:\Backup` or `\\NAS\Storage\Photos`).
2. **Review Proposed Changes**:
   - Click **Quick Compare** to see what has changed without altering any files.
   - FastMirror displays an interactive preview of planned `COPY`, `MOVE`, and `DELETE` operations. You can selectively uncheck items (such as accidental deletions) before proceeding.
3. **Run or Schedule Backup**:
   - Click **Sync Now** to apply the approved actions.
   - *(Optional)* Check days of the week and times in the **Weekly Schedule** panel to let FastMirror mirror automatically in the background while minimized to the Windows system tray.

---

## 💾 Where Files & Configurations Are Saved

FastMirror strictly follows modern Windows application storage standards:

### 1. Installed Mode (`FastMirror-Setup.exe`)
When installed using the setup wizard, binaries reside in `%LOCALAPPDATA%\Programs\FastMirror\`, while all user data is safely stored in your Windows user profile:

| Item | Location | Purpose |
| :--- | :--- | :--- |
| **Active Settings** | `%LOCALAPPDATA%\FastMirror\data\config.json` | Stores active directory pairs, exclusions, schedules, and preferences. |
| **Backup Profiles** | `%LOCALAPPDATA%\FastMirror\data\profiles\<Name>.json` | Named configuration profiles (`Default`, `Work`, `NAS`, etc.). |
| **Mirror Database** | `%LOCALAPPDATA%\FastMirror\data\local_mirror.db` | SQLite database caching target file paths and hashes for instant diffing. |
| **Logs & Reports** | `%LOCALAPPDATA%\FastMirror\data\logs\` | Runtime diagnostic logs and optional Excel (`.xlsx`) comparison reports. |

> **💡 Safe Upgrades:** Updating FastMirror to a new version never touches or overwrites your `%LOCALAPPDATA%\FastMirror\data\` directory. Your folder pairs, schedules, and mirror index are preserved permanently.
>
> **📂 Instant Access in GUI:** You can open your profiles and logs folders at any time directly from the interface:
> - Right-click the **Profile** dropdown in the toolbar $\rightarrow$ **Open Profiles Folder**.
> - In the **Activity Log** panel, click the **📁 Open Log Folder** button.

### 2. Portable Mode (`FastMirror-Portable.zip`)
When running portably, all configuration, profile JSON files, the SQLite index, and logs are kept strictly inside the local `data\` subfolder next to `FastMirror.exe`.

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

## 🛠️ Running from Source (For Developers)

If you prefer to run or build FastMirror from source:

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
uv run python scripts/verify.py
```

---

## 📚 Complete Documentation

- 📖 **[User Guide](docs/USER_GUIDE.md)** — Detailed walkthrough of all interface panels, controls, and workflows.
- ⚙️ **[Configuration & Exclusions](docs/CONFIGURATION.md)** — JSON configuration schema, UNC path handling, and pattern matching.
- 🏗️ **[Architecture & Engine](docs/ARCHITECTURE.md)** — How the synchronization pipeline, move detector, and mirror cache work.
- 🛡️ **[Data Integrity & Safety Rules](docs/SYNC_ROBUSTNESS.md)** — Invariants for file locks, atomic operations, and metadata preservation.
- 💻 **[Development & Testing](docs/DEVELOPMENT.md)** — Building executables, Inno Setup compiler, and test suite execution.

---

## 📄 License & Credits

Created by **Rafael Savi**. Licensed under the [MIT License](LICENSE).
