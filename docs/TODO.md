# TODO

## Main GUI

- [x] Simplify the main GUI controls:
  - [x] Replace the metadata-comparison checkbox with a radio-button selection for the comparison method.
  - [x] Replace the separate mirror rebuild and fast-scan options with one checkbox to reset the local mirror; otherwise, always use the mirror.
  - [x] Add tooltips to buttons and checkboxes, clarifying options such as saving a detailed report.
  - [x] Keep only the native layout and remove the theme switch.
  - [x] Remove the System Overview section.
- [x] Make background colors consistent in the native theme.
- [x] Explore clearer icons that remain understandable at small sizes.
- [x] Add taskbar progress indication.

# Launcher

- [ ] Explain ways of changing the app to easily create a Windows shortcut with the existing launcher and icon.

## Sync and confirmation behavior

- [x] Show the local-mirror reset confirmation only when the user starts an action that will reset it, and always show it for such actions.
- [ ] Investigate why the Windows native popup sometimes reports a successful job incorrectly.

## Performance and responsiveness

## Completed

- [x] Remove drag-and-drop functionality completely to eliminate interface delays and simplify path management.
- [x] Show the full current file path in the progress bar when it fits; truncate only when it does not.
- [x] Simplify the root README into a landing page and preserve the detailed documentation in [`USER_GUIDE.md`](USER_GUIDE.md).
- [x] Confirm before cancelling via the confirmation window's Close (`X`) button.
