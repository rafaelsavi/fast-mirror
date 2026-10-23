# TODO

## Main GUI

- [ ] Simplify the main GUI controls:
  - [ ] Replace the metadata-comparison checkbox with a radio-button selection for the comparison method.
  - [ ] Replace the separate mirror rebuild and fast-scan options with one checkbox to reset the local mirror; otherwise, always use the mirror.
  - [ ] Add tooltips to buttons and checkboxes, clarifying options such as saving a detailed report.
  - [ ] Keep only the native layout and remove the theme switch.
  - [ ] Remove the System Overview section.
- [ ] Make background colors consistent in the native theme.
- [ ] Explore clearer icons that remain understandable at small sizes.
- [ ] Add taskbar progress indication.

## Sync and confirmation behavior

- [ ] Show the local-mirror reset confirmation only when the user starts an action that will reset it, and always show it for such actions.
- [ ] Warn before closing the confirmation window with its Close (`X`) button.
- [ ] Investigate why the Windows native popup sometimes reports a successful job incorrectly.

## Performance and responsiveness

- [ ] Prevent the confirmation-action filter from freezing with 10,000 files.
- [ ] Investigate drag-and-drop delay. First test a version without the progress bar; if the delay remains, isolate the cause by removing other components incrementally.

## Packaging and onboarding

- [ ] Document how to create an app shortcut with the proper icon, and determine whether an installer is needed.

## Completed

- [x] Show the full current file path in the progress bar when it fits; truncate only when it does not.
- [x] Simplify the root README into a landing page and preserve the detailed documentation in [`USER_GUIDE.md`](USER_GUIDE.md).
