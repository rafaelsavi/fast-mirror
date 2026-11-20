"""VS Code-style sticky nested group header overlay for CustomCheckboxTreeView."""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from gui.components.checkbox_treeview import CustomCheckboxTreeView


class StickyTreeHeader:
    """
    Maintain frozen ancestor folder headers pinned beneath a Treeview's column headings.

    As the user scrolls through long nested directory groups, every scrolled-out ancestor
    folder (from top-level root down to the deepest active parent folder) stays pinned in a
    synchronized overlay Treeview directly below the column headings.
    """

    _MAX_STICKY_DEPTH = 8
    _MIN_VISIBLE_BODY_ROWS = 2
    _STYLE_NAME = 'Sticky.Treeview'
    _SENTINEL_IID = 'sticky::__sentinel__'

    def __init__(
        self,
        tree: CustomCheckboxTreeView,
        on_context_menu: Callable[[Any, str], None] | None = None,
        on_item_selected: Callable[[Any], None] | None = None,
    ):
        self.tree = tree
        self.on_context_menu = on_context_menu
        self.on_item_selected = on_item_selected

        self._sticky_ids: tuple[str, ...] = ()
        self._sticky_to_real: dict[str, str] = {}
        self._metrics: tuple[int, int, int] | None = None
        self._updating: bool = False
        self._scheduled_after_id: str | None = None
        self._pending_force_refresh: bool = False
        self._dragging_separator: bool = False
        self._hovered_sticky_iid: str | None = None
        self._last_col_widths: tuple[tuple[str, int, int, str], ...] | None = None

        style = ttk.Style(tree)
        with contextlib.suppress(tk.TclError):
            style.layout(self._STYLE_NAME, [(f'{self._STYLE_NAME}.treearea', {'sticky': 'nswe'})])
            style.configure(
                self._STYLE_NAME,
                background='#f1f5f9',
                fieldbackground='#f1f5f9',
                foreground='#0f172a',
                borderwidth=0,
                relief='flat',
            )

        self.container = tk.Frame(tree, bg='#cbd5e1', bd=0, highlightthickness=0)
        self.sticky_tree = ttk.Treeview(
            self.container,
            columns=tree['columns'],
            show='tree',
            selectmode='none',
            style=self._STYLE_NAME,
        )
        self.sticky_tree.pack(fill='both', expand=True, pady=(0, 1))

        self.sticky_tree.tag_configure('sticky_row', background='#f1f5f9', foreground='#0f172a')
        self.sticky_tree.tag_configure('sticky_hover', background='#e2e8f0', foreground='#0f172a')

        # Sticky overlay interactions
        self.sticky_tree.bind('<Button-1>', self._on_click)
        self.sticky_tree.bind('<Button-3>', self._on_right_click)
        self.sticky_tree.bind('<MouseWheel>', self._on_mousewheel)
        self.sticky_tree.bind('<Motion>', self._on_motion)
        self.sticky_tree.bind('<Leave>', self._on_leave)

        # Keep overlay synchronized with layout, tree open/close, column resize, and keyboard navigation
        self.tree.bind('<Configure>', lambda _e: self.schedule_update(), add='+')
        self.tree.bind('<<TreeviewOpen>>', lambda _e: self.schedule_update(), add='+')
        self.tree.bind('<<TreeviewClose>>', lambda _e: self.schedule_update(), add='+')
        self.tree.bind('<Button-1>', self._on_tree_button_press, add='+')
        self.tree.bind('<B1-Motion>', self._on_tree_drag, add='+')
        self.tree.bind('<ButtonRelease-1>', self._on_tree_button_release, add='+')
        self.tree.bind('<KeyRelease-Up>', lambda _e: self.ensure_selected_visible(), add='+')
        self.tree.bind('<KeyRelease-Prior>', lambda _e: self.ensure_selected_visible(), add='+')

    def get_sticky_folder_ids(self) -> tuple[str, ...]:
        """Return the tuple of currently pinned real folder item IDs (outermost to innermost)."""
        return self._sticky_ids

    def _get_folder_ancestors(self, item_id: str) -> list[str]:
        """Return strict folder ancestors of item_id ordered from root down to immediate parent."""
        ancestors: list[str] = []
        folder_nodes: set[str] = getattr(self.tree, '_folder_nodes', set())
        curr = self.tree.parent(item_id)
        while curr:
            if curr in folder_nodes:
                ancestors.append(curr)
            curr = self.tree.parent(curr)
        ancestors.reverse()
        return ancestors

    def _measure_metrics(self) -> tuple[int, int, int] | None:
        """Return (x_offset, heading_height, row_height) for the main Treeview, or None if unmapped."""
        if not self.tree.winfo_exists() or not self.tree.winfo_ismapped():
            return None
        tree_h = self.tree.winfo_height()
        if tree_h <= 2:
            return None

        if self._metrics is not None:
            return self._metrics

        scan_limit = min(80, tree_h)
        for probe_y in range(1, scan_limit, 2):
            row = self.tree.identify_row(probe_y)
            if row:
                bbox = self.tree.bbox(row)
                if bbox and len(bbox) == 4 and bbox[3] > 0:
                    self._metrics = (int(bbox[0]), int(bbox[1]), int(bbox[3]))
                    return self._metrics
        return None

    def _compute_sticky_folders(self, heading_h: int, row_h: int) -> list[str]:
        """Compute the nested ancestor folder chain currently scrolled above the viewport."""
        tree_h = self.tree.winfo_height()
        viewport_rows = max(0, (tree_h - heading_h) // row_h)
        max_sticky = min(self._MAX_STICKY_DEPTH, max(0, viewport_rows - self._MIN_VISIBLE_BODY_ROWS))
        if max_sticky <= 0:
            return []

        sticky: list[str] = []
        half_row = max(1, row_h // 2)
        for depth in range(max_sticky):
            y_curr = heading_h + depth * row_h + half_row
            y_next = heading_h + (depth + 1) * row_h + half_row
            if y_next >= tree_h:
                break

            row_curr = self.tree.identify_row(y_curr)
            row_next = self.tree.identify_row(y_next)
            if not row_curr or not row_next:
                break

            anc_curr = self._get_folder_ancestors(row_curr)
            anc_next = self._get_folder_ancestors(row_next)
            if len(anc_curr) <= depth or len(anc_next) <= depth:
                break
            if anc_curr[depth] != anc_next[depth]:
                break
            sticky.append(anc_curr[depth])

        return sticky

    def sync_column_widths(self) -> None:
        """Mirror exact column widths and alignments from the main Treeview to the sticky Treeview."""
        if not self.tree.winfo_exists() or not self.sticky_tree.winfo_exists():
            return
        all_cols = ('#0', *(str(c) for c in self.tree['columns']))
        snapshot: list[tuple[str, int, int, str]] = []
        for col in all_cols:
            cfg = self.tree.column(col)
            snapshot.append(
                (
                    col,
                    int(cfg.get('width', 100)),
                    int(cfg.get('minwidth', 20)),
                    str(cfg.get('anchor', 'w')),
                )
            )
        snapshot_tuple = tuple(snapshot)
        if snapshot_tuple == self._last_col_widths:
            return
        self._last_col_widths = snapshot_tuple
        for col, width, minwidth, anchor in snapshot_tuple:
            self.sticky_tree.column(col, width=width, minwidth=minwidth, anchor=cast(Any, anchor), stretch=False)

    def sync_xview(self, first: str | float | None = None) -> None:
        """Keep the sticky overlay horizontally aligned with the main Treeview."""
        if not self._sticky_ids or not self.sticky_tree.winfo_exists():
            return
        with contextlib.suppress(tk.TclError, ValueError):
            pos = float(first) if first is not None else float(self.tree.xview()[0])
            self.sticky_tree.xview_moveto(pos)

    def schedule_update(self, force_refresh: bool = False) -> None:
        """Coalesce sticky header updates to run once after pending Tk layout events."""
        if force_refresh:
            self._pending_force_refresh = True
        if self._scheduled_after_id is not None or not self.tree.winfo_exists():
            return

        def _run() -> None:
            self._scheduled_after_id = None
            force = self._pending_force_refresh
            self._pending_force_refresh = False
            self.update(force_refresh=force)

        with contextlib.suppress(tk.TclError):
            self._scheduled_after_id = self.tree.after_idle(_run)

    def update(self, force_refresh: bool = False) -> None:
        """Recompute active ancestor folders and render or hide the sticky header overlay."""
        if self._updating or not self.tree.winfo_exists() or not self.container.winfo_exists():
            return
        self._updating = True
        try:
            metrics = self._measure_metrics()
            if metrics is None:
                self._hide()
                return

            x_offset, heading_h, row_h = metrics
            new_sticky = tuple(self._compute_sticky_folders(heading_h, row_h))
            if not new_sticky:
                self._hide()
                return

            self.sync_column_widths()

            if new_sticky != self._sticky_ids:
                self._rebuild_sticky_rows(new_sticky)
            elif force_refresh:
                self._refresh_sticky_rows(new_sticky)

            tree_w = self.tree.winfo_width()
            overlay_w = max(1, tree_w - 2 * x_offset)
            overlay_h = len(new_sticky) * row_h + 1
            self.container.place(x=x_offset, y=heading_h, width=overlay_w, height=overlay_h)
            self.container.lift()
            self.sync_xview()
        except tk.TclError:
            pass
        finally:
            self._updating = False

    def _hide(self) -> None:
        if self._sticky_ids:
            self._sticky_ids = ()
            self._sticky_to_real.clear()
        self._hovered_sticky_iid = None
        with contextlib.suppress(tk.TclError):
            self.container.place_forget()

    def _rebuild_sticky_rows(self, new_sticky: tuple[str, ...]) -> None:
        """Populate sticky_tree with the ordered nested ancestor folders plus a clipped sentinel child."""
        existing_roots = self.sticky_tree.get_children('')
        if existing_roots:
            self.sticky_tree.delete(*existing_roots)
        self._sticky_to_real.clear()
        self._hovered_sticky_iid = None

        parent_sticky = ''
        for real_iid in new_sticky:
            sticky_iid = f'sticky::{real_iid}'
            self._sticky_to_real[sticky_iid] = real_iid
            text = self.tree.item(real_iid, 'text')
            values = self.tree.item(real_iid, 'values')
            img = self.tree.get_item_image(real_iid)
            self.sticky_tree.insert(
                parent=parent_sticky,
                index='end',
                iid=sticky_iid,
                text=text,
                values=values,
                image=img if img is not None else '',
                tags=('sticky_row',),
                open=True,
            )
            parent_sticky = sticky_iid

        # Clipped sentinel child ensures Tk displays the [-] open indicator on the deepest sticky folder
        if parent_sticky:
            self.sticky_tree.insert(parent=parent_sticky, index='end', iid=self._SENTINEL_IID, text='')

        self.sticky_tree.configure(height=len(new_sticky))
        self.sticky_tree.yview_moveto(0.0)
        self._sticky_ids = new_sticky

    def _refresh_sticky_rows(self, sticky_ids: tuple[str, ...]) -> None:
        """Refresh text, values, and checkbox+folder icon of existing sticky rows in place."""
        for real_iid in sticky_ids:
            sticky_iid = f'sticky::{real_iid}'
            if not self.tree.exists(real_iid) or not self.sticky_tree.exists(sticky_iid):
                continue
            img = self.tree.get_item_image(real_iid)
            self.sticky_tree.item(
                sticky_iid,
                text=self.tree.item(real_iid, 'text'),
                values=self.tree.item(real_iid, 'values'),
                image=img if img is not None else '',
            )

    def _on_click(self, event: tk.Event[Any]) -> str:
        """Handle checkbox toggle, collapse indicator click, or scroll-to-folder click."""
        sticky_iid = self.sticky_tree.identify_row(event.y)
        real_iid = self._sticky_to_real.get(sticky_iid)
        if not real_iid or not self.tree.exists(real_iid):
            return 'break'

        elem = self.sticky_tree.identify_element(event.x, event.y)
        if 'indicator' in elem:
            self.tree.item(real_iid, open=False)
            self.scroll_to_folder(real_iid)
            return 'break'

        if 'image' in elem:
            hit_w = getattr(self.tree, '_checkbox_hit_width', 19)
            is_icon_part = event.x >= hit_w and 'image' in self.sticky_tree.identify_element(event.x - hit_w, event.y)
            if not is_icon_part:
                if self.tree.tag_has('unchecked', real_iid) or self.tree.tag_has('tristate', real_iid):
                    self.tree._check_ancestor(real_iid)
                    self.tree._check_descendant(real_iid)
                else:
                    self.tree._uncheck_descendant(real_iid)
                    self.tree._uncheck_ancestor(real_iid)
                self.tree.refresh_group_stats()
                self.update(force_refresh=True)
                return 'break'

        self.scroll_to_folder(real_iid)
        return 'break'

    def _on_right_click(self, event: tk.Event[Any]) -> str:
        """Delegate right-click context menu on a sticky folder row to the popup handler."""
        sticky_iid = self.sticky_tree.identify_row(event.y)
        real_iid = self._sticky_to_real.get(sticky_iid)
        if real_iid and self.tree.exists(real_iid) and self.on_context_menu is not None:
            self.tree.selection_set(real_iid)
            if self.on_item_selected is not None:
                self.on_item_selected(None)
            self.on_context_menu(event, real_iid)
        return 'break'

    def _on_mousewheel(self, event: tk.Event[Any]) -> str:
        """Forward mousewheel scrolling over the sticky overlay to the main Treeview."""
        if event.delta:
            units = int(-1 * (event.delta / 120))
            if units == 0:
                units = -1 if event.delta > 0 else 1
            self.tree.yview_scroll(units, 'units')
        return 'break'

    def _on_motion(self, event: tk.Event[Any]) -> None:
        sticky_iid = self.sticky_tree.identify_row(event.y)
        if sticky_iid not in self._sticky_to_real:
            sticky_iid = ''
        if sticky_iid == self._hovered_sticky_iid:
            return
        if self._hovered_sticky_iid and self.sticky_tree.exists(self._hovered_sticky_iid):
            self.sticky_tree.item(self._hovered_sticky_iid, tags=('sticky_row',))
        self._hovered_sticky_iid = sticky_iid or None
        if sticky_iid and self.sticky_tree.exists(sticky_iid):
            self.sticky_tree.item(sticky_iid, tags=('sticky_hover',))

    def _on_leave(self, _event: tk.Event[Any]) -> None:
        if self._hovered_sticky_iid and self.sticky_tree.exists(self._hovered_sticky_iid):
            self.sticky_tree.item(self._hovered_sticky_iid, tags=('sticky_row',))
        self._hovered_sticky_iid = None

    def _on_tree_button_press(self, event: tk.Event[Any]) -> None:
        self._dragging_separator = self.tree.identify_region(event.x, event.y) == 'separator'

    def _on_tree_drag(self, _event: tk.Event[Any]) -> None:
        if self._dragging_separator:
            self.sync_column_widths()

    def _on_tree_button_release(self, _event: tk.Event[Any]) -> None:
        if self._dragging_separator:
            self._dragging_separator = False
            self.sync_column_widths()
            self.update()

    def _find_visible_position(self, target_iid: str) -> tuple[int | None, int]:
        """Return (0-based visible index of target_iid, total visible rows) in DFS order."""
        target_idx: int | None = None
        count = 0
        stack = list(reversed(self.tree.get_children('')))
        while stack:
            iid = stack.pop()
            if iid == target_iid and target_idx is None:
                target_idx = count
            count += 1
            if self.tree.item(iid, 'open'):
                children = self.tree.get_children(iid)
                if children:
                    stack.extend(reversed(children))
        return target_idx, count

    def scroll_to_folder(self, folder_iid: str) -> None:
        """Scroll the main Treeview so folder_iid sits uncovered right below its ancestor headers."""
        if not self.tree.exists(folder_iid):
            return
        target_idx, total_visible = self._find_visible_position(folder_iid)
        if target_idx is not None and total_visible > 0:
            depth = len(self._get_folder_ancestors(folder_iid))
            top_row_idx = max(0, target_idx - depth)
            self.tree.yview_moveto(top_row_idx / total_visible)

        self.tree.selection_set(folder_iid)
        self.tree.focus(folder_iid)
        self.tree.focus_set()
        if self.on_item_selected is not None:
            self.on_item_selected(None)
        self.update()

    def ensure_item_visible(self, item_id: str) -> None:
        """Scroll up if item_id's top edge is obscured beneath active sticky headers."""
        if not self._sticky_ids or not item_id or not self.tree.exists(item_id):
            return
        metrics = self._measure_metrics()
        if metrics is None:
            return
        _, heading_h, row_h = metrics
        bbox = self.tree.bbox(item_id)
        if not bbox or len(bbox) != 4:
            return
        sticky_bottom = heading_h + len(self._sticky_ids) * row_h
        if bbox[1] < sticky_bottom:
            units_up = (sticky_bottom - bbox[1] + row_h - 1) // row_h
            self.tree.yview_scroll(-units_up, 'units')
            self.update()

    def ensure_selected_visible(self) -> None:
        """Ensure the currently focused or first selected row is not covered by sticky headers."""
        target = self.tree.focus()
        if not target:
            sel = self.tree.selection()
            target = sel[0] if sel else ''
        if target:
            self.ensure_item_visible(target)
