# GUI & Threading Safety Rules

The application uses **Tkinter / CustomTkinter** for its interface and runs long-running filesystem backup tasks inside a background worker thread (`WorkerThread`).

Follow these strict concurrency and thread-safety rules:

---

## 1. Tkinter Single-Thread Rule
- Tkinter's underlying Tcl/Tk interpreter is **NOT thread-safe**.
- **Never call Tkinter widgets, update variables, or invoke methods directly from a background thread**. Doing so causes silent crashes, corrupted visual state, or hard-to-reproduce segfaults on Windows.
- **Rule:** Any operation that touches GUI components from `SyncDirs` or `WorkerThread` MUST be scheduled on the main thread via:
  ```python
  self.root_gui.after(0, callable_func)
  ```

---

## 2. Modal Confirmation Popup Lifecycle
During backup runs, when user confirmation is needed (e.g. deleting or replacing files):
- The worker thread calls `open_confirmation_popup()`.
- The dialog widget is created on the main thread via `root_gui.after(0, create_popup)`.
- The worker thread pauses using a `threading.Event` (`result_event.wait(0.2)`).

### Mandatory Cleanup Protocol
If the worker thread is terminated, stopped by the user, or encounters an exception while waiting for confirmation:
- The popup window would remain orphaned on screen, blocking the GUI or holding references.
- **Rule:** Always wrap popup wait loops in a `try...finally` block that cleans up the popup if the wait ends without a set event:
  ```python
  try:
      while not result_event.is_set():
          result_event.wait(0.2)
  finally:
      if not result_event.is_set():
          def cleanup_popup():
              p = popup_holder.get('popup')
              if p and hasattr(p, 'popup'):
                  try:
                      if p.popup.winfo_exists():
                          p.popup.destroy()
                  except Exception:
                      pass
          self.root_gui.after(0, cleanup_popup)
  ```

---

## 3. Worker Thread Cancellation & Graceful Shutdown
- Long-running sync loops (e.g. scanning files, moving batches) must regularly poll cancellation flags.
- Check `self.worker_thread.stopped()` or equivalent before processing the next file.
- When cancellation is triggered:
  1. Abort the current loop immediately.
  2. Do NOT leave partial files in the destination (clean up temporary `.tmp` copy targets).
  3. Close any open file handles and SQLite transactions.
  4. Signal GUI completion (`worker_finished`) so UI buttons re-enable properly.

---

## 4. Audio Chimes & OS Notifications
- Windows system notifications (such as `winsound.PlaySound('SystemQuestion', winsound.SND_ALIAS | winsound.SND_ASYNC)`) must be called asynchronously (`SND_ASYNC`) so they do not block execution.
- System tray integration uses the bundled `winico` DLL. If loading fails on non-standard Windows configurations, catch the exception and log a warning; never let tray failure prevent GUI initialization.
