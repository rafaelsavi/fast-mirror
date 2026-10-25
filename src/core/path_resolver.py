import os
from pathlib import Path, PureWindowsPath

from core.file import CstmPathType
from utils.utils import DirectoryPair


def _to_path(p: CstmPathType) -> Path | PureWindowsPath:
    p_str = str(p)
    if os.name != 'nt' and ('\\' in p_str or (len(p_str) >= 2 and p_str[1] == ':')):
        return PureWindowsPath(p_str)
    return Path(p)


def get_dirs_from_path(path: CstmPathType, dirs: list[DirectoryPair] | None) -> DirectoryPair:
    """Find the corresponding source and target directories for a given path."""
    p = _to_path(path)

    best_pair: DirectoryPair | None = None
    best_score = (-1, -1)

    for dir_pair in dirs or []:
        for root_str in (dir_pair.source, dir_pair.target):
            root = _to_path(root_str)
            try:
                if p == root or p.is_relative_to(root):
                    score = (len(root.parts), len(str(root)))
                    if score > best_score:
                        best_score = score
                        best_pair = dir_pair
            except (ValueError, TypeError):
                continue

    if best_pair is not None:
        return best_pair

    raise FileNotFoundError(f"Could not identify root folders of path '{path}'. Dirs: {dirs}")
