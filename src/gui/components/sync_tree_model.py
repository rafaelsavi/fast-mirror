"""Pure data model and lexical path utilities for the synchronization review hierarchy."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from gui.widgets import Action


class FolderNode:
    """Node in directory tree used for multi-level folder hierarchy with compaction."""

    def __init__(self, name: str, path_key: str):
        self.name = name
        self.path_key = path_key
        self.children: dict[str, FolderNode] = {}
        self.files: list[tuple[str, Action, str, str, dict[str, Any]]] = []


def _extract_relative_folder_parts(
    target_path: str,
    root_dir: str | None = None,
    common_prefix_parts: list[str] | None = None,
) -> tuple[list[str], str]:
    """Extract full directory parts from root and filename without blocking network I/O."""
    if not target_path or target_path in ('-', '(none)'):
        return [], ''

    p = Path(target_path)
    filename = p.name or target_path

    raw_parts = list(p.parent.parts)
    parts: list[str] = []
    for part in raw_parts:
        cleaned = part.rstrip('\\/')
        if cleaned:
            parts.append(cleaned)
    return parts, filename


def _format_move_origin(src_val: str, tgt_val: str) -> str:
    """Format a smart diff-based relative origin string for Move operations."""
    src_parts, src_name = _extract_relative_folder_parts(src_val)
    tgt_parts, tgt_name = _extract_relative_folder_parts(tgt_val)

    name_changed = src_name != tgt_name
    name_case_only = name_changed and (src_name.lower() == tgt_name.lower())

    # 1. Exact same folder path (including case): file-only rename
    if src_parts == tgt_parts:
        if name_case_only:
            return f'Case rename: {src_name} → {tgt_name}'
        if name_changed:
            return f'Renamed from: {src_name}'
        return f'from: {src_val}'

    # 2. Same folder hierarchy, only folder casing changed
    if len(src_parts) == len(tgt_parts) and [pt.lower() for pt in src_parts] == [pt.lower() for pt in tgt_parts]:
        diff_pairs = [(s, t) for s, t in zip(src_parts, tgt_parts, strict=False) if s != t]
        old_seg = '\\'.join(s for s, _ in diff_pairs)
        new_seg = '\\'.join(t for _, t in diff_pairs)
        if name_changed:
            return f'Case rename: {old_seg}\\{src_name} → {new_seg}\\{tgt_name}'
        return f'Case rename: {old_seg} → {new_seg}'

    # Find longest common case-insensitive prefix between src_parts and tgt_parts
    common_len = 0
    for s_part, t_part in zip(src_parts, tgt_parts, strict=False):
        if s_part.lower() == t_part.lower():
            common_len += 1
        else:
            break

    # 3. Moved UP from a subfolder inside the target directory
    if common_len == len(tgt_parts) and len(src_parts) > len(tgt_parts):
        sub_rel = '\\'.join(src_parts[common_len:])
        if name_changed:
            return f'Moved up from: .\\{sub_rel}\\{src_name}'
        return f'Moved up from: .\\{sub_rel}\\'

    # 4. Moved DOWN into a subfolder from an ancestor directory
    if common_len == len(src_parts) and len(tgt_parts) > len(src_parts):
        parent_name = src_parts[-1] if src_parts else ''
        if name_changed:
            return (
                f'Moved down from: .\\{src_name} (in {parent_name}\\)'
                if parent_name
                else f'Moved down from: .\\{src_name}'
            )
        return f'Moved down from: .\\ (in {parent_name}\\)' if parent_name else 'Moved down from: .\\ (parent folder)'

    # 5. Divergent folder branches: show path from 1 folder above the divergence point (or share-relative)
    if common_len >= 1:
        start_idx = max(1, common_len - 1)
        rel_branch = '\\'.join(src_parts[start_idx:])
        prefix = '...\\' if start_idx > 1 else ''
        if name_changed:
            return f'from: {prefix}{rel_branch}\\{src_name}'
        return f'from: {prefix}{rel_branch}\\'

    # Fallback: completely different roots
    full_src_dir = '\\'.join(src_parts)
    if name_changed:
        return f'from: {full_src_dir}\\{src_name}' if full_src_dir else f'Renamed from: {src_name}'
    return f'from: {full_src_dir}\\' if full_src_dir else f'from: {src_val}'


def _compact_trie(node: FolderNode, is_root: bool = False) -> FolderNode:
    """Recursively compact single-child folder chains into single path nodes (VS Code style)."""
    for k in list(node.children.keys()):
        node.children[k] = _compact_trie(node.children[k], is_root=False)

    if not is_root and len(node.files) == 0 and len(node.children) == 1:
        only_child = next(iter(node.children.values()))
        compacted = FolderNode(f'{node.name} \\ {only_child.name}', only_child.path_key)
        compacted.children = only_child.children
        compacted.files = only_child.files
        return compacted
    return node


def get_file_category_group(path: str) -> str:
    """Return category group: 'image', 'document', 'media', 'code', 'archive', or 'other'."""
    if not path or path in ('-', '(none)'):
        return 'other'
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico'):
        return 'image'
    if ext in ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.mp3', '.wav', '.flac', '.m4a'):
        return 'media'
    if ext in ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.csv', '.rtf'):
        return 'document'
    if ext in ('.zip', '.tar', '.gz', '.7z', '.rar', '.bz2', '.xz'):
        return 'archive'
    if ext in (
        '.py',
        '.js',
        '.ts',
        '.html',
        '.css',
        '.json',
        '.xml',
        '.yaml',
        '.yml',
        '.md',
        '.sh',
        '.bat',
        '.ps1',
        '.sql',
    ):
        return 'code'
    return 'other'


def get_file_type_badge(path: str) -> tuple[str, str]:
    """Return an icon and readable file type category for a given path."""
    if not path or path in ('-', '(none)'):
        return ('📄', 'File')
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico'):
        return ('🖼️', f'Image ({ext})')
    if ext in ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.mp3', '.wav', '.flac', '.m4a'):
        return ('🎬', f'Media ({ext})')
    if ext in ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.csv', '.rtf'):
        return ('📄', f'Document ({ext})')
    if ext in ('.zip', '.tar', '.gz', '.7z', '.rar', '.bz2', '.xz'):
        return ('📦', f'Archive ({ext})')
    if ext in (
        '.py',
        '.js',
        '.ts',
        '.html',
        '.css',
        '.json',
        '.xml',
        '.yaml',
        '.yml',
        '.md',
        '.sh',
        '.bat',
        '.ps1',
        '.sql',
    ):
        return ('💻', f'Code/Config ({ext})')
    if ext in ('.exe', '.msi', '.dll'):
        return ('⚙️', f'Binary ({ext})')
    if ext:
        return ('📄', f'{ext.upper()[1:]} File')
    return ('📄', 'File')
