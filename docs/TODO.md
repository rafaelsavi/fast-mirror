# TODO List

- Rethink buttons and checkboxes in main gui:
  - replace "use fast comparison based on metadata" by a radio button selection to configure comparison method
  - replace "rebuild local mirror" and "use fast scan based on local mirror" by a single checkbox asking if to reset mirror. In other cases assume always to local mirror.
  - add tooltip to buttons and checkboxes (for example "Save detailed report" is not clear what it means)
  - keep only "native" layout and remove option to change it
  - dont need "system overview" section in main gui
  - background colors in native theme are not consistent
- popup of confirmation to reset local mirror should come only and always when user starts an action that leads to that reset. (not only by selecting the checkbox)
- with 10k files, using filter in confirm actions window make it freeze
- add warning popup if closing confirm actions window by X
- windows native popup saying succesfull job is wrong sometimes
- in progress bar, dont crop unless it wouldnt fit
- see progress bar in taskbar
- explore more icon options because this is not very understandable when it's small
- Make main readme more clear about what it does and why it differs from common solutions (focus on mirror and frequent syncs of same folders)
- How to create app shortcut with proper icon? must it become an installable first?
- Fix drag delay. make a version without the progress bar too see if delay reduces. If it doesnt resolve, remove other things until finding root cause
