# TODO List

- [x] request popup confirmation before resetting the DB
- remove all personal paths and information from project, except for my configuration files should not be part of git. can this be applied retroatevelly to existing commits in the main. question.
- [x] modernize GUI (Sun Valley ttk light theme, modular panel components, pystray tray management)
- [x] make action selection popup more useful; find a way of improving the load-up speed and submit/close speed when there are thousands of files (optimized single-pass O(N) grouping, deferred rendering, direct metadata extraction, and O(1) submission lookup)
- [x] implement rich frontend productivity enhancements:
  - [x] real-time Telemetry Bar (animated scanning, determinate progress, file count, transfer speed, current file display, and direct stop button)
  - [x] pre-flight Target Health & Storage Diagnostics (non-blocking background probe of target reachability and remaining disk capacity)
  - [x] simplified exclusion tag chips and dedicated manager modal (presets removed to reduce visual noise)
  - [x] past reports and history browser (`ReportsWindow` for browsing, opening in Excel, and cleaning past reports)
  - [x] side-by-side visual diff inspector card in confirmation popup with file type badges and date/size deltas
  - [x] log console live search with match stepping and quick clipboard copy
- make better strategy for place to store db and configuration files
- [ ] evaluate and implement backend/core architecture simplifications (see [ARCHITECTURE_SIMPLIFICATIONS.md](ARCHITECTURE_SIMPLIFICATIONS.md))
- I dont understand how the "Classification" of ignore pattern works. Is this really necessary? or is it a bloated display artifact
- Fix drag delay by finding first commit where it began
