"""Centralized color palettes and typography constants for FastMirror GUI."""

from __future__ import annotations

FONT_TITLE = ('Segoe UI', 11, 'bold')
FONT_SUBTITLE = ('Segoe UI', 9)
FONT_BODY = ('Segoe UI', 9)
FONT_BODY_BOLD = ('Segoe UI', 9, 'bold')
FONT_SMALL = ('Segoe UI', 8)
FONT_SMALL_BOLD = ('Segoe UI', 8, 'bold')
FONT_MONO = ('Consolas', 9)

TREEVIEW_TAG_COLORS: dict[str, dict[str, str]] = {
    'copy_tag': {'background': '#f6fff8'},
    'move_tag': {'background': '#f0f7ff'},
    'delete_tag': {'background': '#fff5f5'},
    'folder_tag': {'background': '#ffffff'},
    'highlight_match': {'background': '#fff59d'},
    'selected_row': {'background': '#0078d7', 'foreground': '#ffffff'},
}

BADGE_PALETTES: dict[str, dict[str, str]] = {
    'neutral': {
        'bg': '#f1f5f9',
        'fg': '#64748b',
        'border': '#e2e8f0',
        'hover_bg': '#e2e8f0',
    },
    'neutral_bold': {
        'bg': '#f1f5f9',
        'fg': '#334155',
        'border': '#cbd5e1',
        'hover_bg': '#e2e8f0',
    },
    'info': {
        'bg': '#e0f2fe',
        'fg': '#0369a1',
        'border': '#bae6fd',
        'hover_bg': '#bae6fd',
    },
    'warning': {
        'bg': '#fef3c7',
        'fg': '#b45309',
        'border': '#fde68a',
        'hover_bg': '#fde68a',
    },
    'error': {
        'bg': '#fee2e2',
        'fg': '#b91c1c',
        'border': '#fecaca',
        'hover_bg': '#fecaca',
    },
    'success': {
        'bg': '#dcfce7',
        'fg': '#15803d',
        'border': '#bbf7d0',
        'hover_bg': '#bbf7d0',
    },
    'primary': {
        'bg': '#dbeafe',
        'fg': '#1d4ed8',
        'border': '#bfdbfe',
        'hover_bg': '#bfdbfe',
    },
}

FILTER_BTN_PALETTES: dict[str, dict[str, str]] = {
    'all': {
        'inactive_text': 'All',
        'inactive_bg': '#ffffff',
        'inactive_fg': '#1e293b',
        'hover_bg': '#e2e8f0',
        'active_bg': '#0078d7',
        'active_fg': '#ffffff',
    },
    'copy': {
        'inactive_text': '🟢 Copy: 0 files (0 B)',
        'inactive_bg': '#ffffff',
        'inactive_fg': '#15803d',
        'hover_bg': '#dcfce7',
        'active_bg': '#15803d',
        'active_fg': '#ffffff',
    },
    'move': {
        'inactive_text': '🔵 Move: 0 files (0 B)',
        'inactive_bg': '#ffffff',
        'inactive_fg': '#1d4ed8',
        'hover_bg': '#dbeafe',
        'active_bg': '#1d4ed8',
        'active_fg': '#ffffff',
    },
    'delete': {
        'inactive_text': '🔴 Delete: 0 files (0 B)',
        'inactive_bg': '#ffffff',
        'inactive_fg': '#b91c1c',
        'hover_bg': '#fee2e2',
        'active_bg': '#b91c1c',
        'active_fg': '#ffffff',
    },
}
