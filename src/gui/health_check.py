import contextlib
import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass

from utils.utils import DirectoryPair, format_size


@dataclass
class TargetHealth:
    path: str
    is_online: bool
    free_bytes: int = 0
    total_bytes: int = 0
    used_pct: float = 0.0
    free_str: str = '0 B'
    total_str: str = '0 B'
    warning: str | None = None
    error: str | None = None


def probe_single_target(path: str) -> TargetHealth:
    """Probe a single target path for reachability and disk storage capacity."""
    path_str = str(path)
    try:
        if not os.path.exists(path_str):
            return TargetHealth(
                path=path_str,
                is_online=False,
                error='Path is unreachable or disconnected',
            )

        usage = shutil.disk_usage(path_str)
        free_b = usage.free
        total_b = usage.total
        used_b = max(0, total_b - free_b)
        pct = (used_b / total_b * 100.0) if total_b > 0 else 0.0

        warning = None
        if free_b < 10 * (1024**3):  # Less than 10 GB
            warning = 'Low disk space (< 10 GB free)'

        return TargetHealth(
            path=path_str,
            is_online=True,
            free_bytes=free_b,
            total_bytes=total_b,
            used_pct=pct,
            free_str=format_size(free_b),
            total_str=format_size(total_b),
            warning=warning,
        )
    except Exception as e:
        return TargetHealth(
            path=path_str,
            is_online=False,
            error=str(e),
        )


def probe_targets_async(
    dirs: list[DirectoryPair],
    on_complete: Callable[[list[TargetHealth]], None],
):
    """Probe all configured backup target paths in a non-blocking background thread."""

    def _worker():
        results = [probe_single_target(dir_pair.target) for dir_pair in dirs]
        with contextlib.suppress(Exception):
            on_complete(results)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
