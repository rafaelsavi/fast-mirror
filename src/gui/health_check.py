import contextlib
import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass

from utils.utils import DirectoryPair, format_size, sanitize_path
from utils.volume import find_drive_by_serial, get_volume_info


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
    resolved_path: str | None = None


def probe_single_target(
    path: str,
    expected_serial: str | None = None,
    expected_root_name: str | None = None,
) -> TargetHealth:
    """
    Probe a single target path for reachability, volume serial verification, and disk capacity.
    Supports empty/new drives where subfolders do not yet exist, and automatically detects
    drive letter shifts when expected_serial is provided.
    """
    path_str = sanitize_path(str(path))
    original_path = path_str
    warning: str | None = None
    resolved_path = path_str

    try:
        # Volume verification and dynamic letter relocation
        if expected_serial:
            vol_info = get_volume_info(path_str)
            if vol_info and vol_info.serial.upper() == expected_serial.upper():
                # Drive is online at expected mount letter
                pass
            else:
                # Drive is either on a different letter or a wrong drive is mounted at path_str
                relocated = find_drive_by_serial(expected_serial)
                if relocated:
                    new_drive = relocated.drive
                    resolved_path = new_drive + path_str[2:] if len(path_str) >= 2 and path_str[1] == ':' else path_str
                    warning = f'Relocated: detected on {new_drive}'
                    path_str = resolved_path
                elif vol_info:
                    # A different drive is currently mounted here
                    wrong_label = vol_info.label or vol_info.serial
                    return TargetHealth(
                        path=original_path,
                        is_online=False,
                        error=(
                            f"Wrong drive on {original_path[:2]}: found '{wrong_label}', expected [{expected_serial}]"
                        ),
                        resolved_path=resolved_path,
                    )
                else:
                    return TargetHealth(
                        path=original_path,
                        is_online=False,
                        error=f'Target drive is disconnected (expected [{expected_serial}])',
                        resolved_path=resolved_path,
                    )

        # Reachability and disk storage capacity
        will_create = False
        check_path = path_str
        if not os.path.exists(path_str):
            if expected_serial or path_str.startswith('\\\\'):
                # Walk up to an existing drive root or UNC share ancestor so missing subfolders can be created
                curr = path_str
                while curr and not os.path.exists(curr):
                    parent = os.path.dirname(curr)
                    if parent == curr:
                        break
                    curr = parent

                unc_valid = True
                if path_str.startswith('\\\\'):
                    unc_drive, _ = os.path.splitdrive(curr)
                    unc_valid = bool(unc_drive and unc_drive.startswith('\\\\'))

                if curr and unc_valid and os.path.exists(curr):
                    check_path = curr
                    will_create = True
                else:
                    return TargetHealth(
                        path=original_path,
                        is_online=False,
                        error='Path is unreachable or disconnected',
                        resolved_path=resolved_path,
                    )
            else:
                return TargetHealth(
                    path=original_path,
                    is_online=False,
                    error='Path is unreachable or disconnected',
                    resolved_path=resolved_path,
                )

        usage = shutil.disk_usage(check_path)
        free_b = usage.free
        total_b = usage.total
        used_b = max(0, total_b - free_b)
        pct = (used_b / total_b * 100.0) if total_b > 0 else 0.0

        if will_create:
            warning = (
                f'{warning}; Target folder will be created' if warning else 'Target folder will be created on sync'
            )

        if free_b < 10 * (1024**3):  # Less than 10 GB
            warning = f'{warning}; Low disk space (< 10 GB free)' if warning else 'Low disk space (< 10 GB free)'

        return TargetHealth(
            path=original_path,
            is_online=True,
            free_bytes=free_b,
            total_bytes=total_b,
            used_pct=pct,
            free_str=format_size(free_b),
            total_str=format_size(total_b),
            warning=warning,
            resolved_path=resolved_path,
        )
    except Exception as e:
        return TargetHealth(
            path=original_path,
            is_online=False,
            error=str(e),
            resolved_path=resolved_path,
        )


def probe_targets_async(
    dirs: list[DirectoryPair] | list[str],
    on_complete: Callable[[list[TargetHealth]], None],
):
    """Probe all configured backup target paths in a non-blocking background thread."""

    def _worker():
        results = []
        for d in dirs:
            if isinstance(d, DirectoryPair):
                results.append(
                    probe_single_target(
                        d.target,
                        expected_serial=d.target_serial,
                        expected_root_name=d.target_root_name,
                    )
                )
            else:
                results.append(probe_single_target(d))
        with contextlib.suppress(Exception):
            on_complete(results)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
