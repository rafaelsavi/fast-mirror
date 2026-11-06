"""
Windows Volume and Drive Identity Utilities for FastMirror.

Provides pure Win32 API volume information extraction (Volume Serial Number, Volume Label,
drive types, and dynamic drive letter discovery) via ctypes.windll.kernel32.
Guarantees zero network I/O on UNC paths and graceful fallbacks in non-Windows environments.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Any

from utils.logger import logger
from utils.utils import sanitize_path

# Windows Drive Types
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6


@dataclass
class VolumeInfo:
    """Represents physical/filesystem volume metadata for a Windows drive."""

    drive: str  # e.g. "E:" or "E:\\"
    serial: str  # formatted 32-bit hex string: "A4B1-9C32"
    label: str  # e.g. "PHOTOS_HDD"
    fs_type: str = ''  # e.g. "NTFS", "exFAT", "FAT32"
    drive_type: int = DRIVE_UNKNOWN

    @property
    def is_removable(self) -> bool:
        return self.drive_type == DRIVE_REMOVABLE

    @property
    def display_tag(self) -> str:
        """User-friendly summary, e.g. 'PHOTOS_HDD [A4B1-9C32]' or '[A4B1-9C32]'."""
        if self.label:
            return f'{self.label} [{self.serial}]'
        return f'[{self.serial}]'


def _format_serial(serial_val: int) -> str:
    """Format an unsigned 32-bit integer as a Windows Volume Serial Number (e.g. 'A4B1-9C32')."""
    return f'{(serial_val >> 16) & 0xFFFF:04X}-{serial_val & 0xFFFF:04X}'


def get_volume_info(path: str) -> VolumeInfo | None:
    """
    Retrieve unique volume metadata for a Windows drive letter path.

    Returns None for UNC paths or if the drive is not mounted / unavailable.
    Guarantees zero network I/O on UNC paths (adhering to Rule #2).
    """
    clean_path = sanitize_path(path)
    if clean_path.startswith('\\\\'):
        # Inviolable Rule #2: Never perform network queries or comparisons on remote UNC shares
        return None

    if len(clean_path) < 2 or clean_path[1] != ':':
        return None

    drive_letter = clean_path[:2].upper()
    drive_root = drive_letter + '\\'

    # Graceful fallback for non-Windows test environments
    kernel32: Any = getattr(getattr(ctypes, 'windll', None), 'kernel32', None)
    if kernel32 is None:
        return None

    try:
        vol_name = ctypes.create_unicode_buffer(260)
        serial_num = ctypes.c_ulong()
        max_component_len = ctypes.c_ulong()
        flags = ctypes.c_ulong()
        fs_name = ctypes.create_unicode_buffer(260)

        success = kernel32.GetVolumeInformationW(
            drive_root,
            vol_name,
            ctypes.sizeof(vol_name),
            ctypes.byref(serial_num),
            ctypes.byref(max_component_len),
            ctypes.byref(flags),
            fs_name,
            ctypes.sizeof(fs_name),
        )

        if not success:
            return None

        drive_type = kernel32.GetDriveTypeW(drive_root)
        serial_str = _format_serial(serial_num.value)

        return VolumeInfo(
            drive=drive_letter,
            serial=serial_str,
            label=vol_name.value.strip(),
            fs_type=fs_name.value.strip(),
            drive_type=drive_type,
        )
    except Exception as e:
        logger.debug(f"Could not query volume information for '{drive_root}': {e}")
        return None


def get_all_drives() -> list[VolumeInfo]:
    """Scan and return volume information for all currently mounted Windows drive letters."""
    kernel32: Any = getattr(getattr(ctypes, 'windll', None), 'kernel32', None)
    if kernel32 is None:
        return []

    results: list[VolumeInfo] = []
    try:
        bitmask = kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                letter = chr(ord('A') + i) + ':'
                info = get_volume_info(letter)
                if info is not None:
                    results.append(info)
    except Exception as e:
        logger.debug(f'Error listing logical drives: {e}')

    return results


def find_drive_by_serial(serial: str) -> VolumeInfo | None:
    """
    Search connected Windows drive letters (C: through Z:) for a specific Volume Serial Number.

    Returns the matching VolumeInfo or None if the drive is not connected.
    """
    clean_target = serial.strip().upper()
    if not clean_target:
        return None

    for drive_info in get_all_drives():
        if drive_info.serial.upper() == clean_target:
            return drive_info

    return None


def split_path_root(full_path: str) -> tuple[str, str]:
    r"""
    Split a path into its storage root (drive root or UNC root share) and relative subpath.

    Examples:
        'E:\Backup\Photos' -> ('E:\', 'Backup\Photos')
        'E:\'               -> ('E:\', '')
        '\\nas\backup\Photos' -> ('\\nas\backup', 'Photos')
        '\\nas\backup'    -> ('\\nas\backup', '')

    """
    clean = sanitize_path(full_path).strip()
    if clean.startswith('\\\\'):
        # UNC share format: \\server\share\subpath...
        parts = [p for p in clean.split('\\') if p]
        if len(parts) >= 2:
            root = f'\\\\{parts[0]}\\{parts[1]}'
            sub = '\\'.join(parts[2:]) if len(parts) > 2 else ''
            return root, sub
        return clean, ''

    if len(clean) >= 2 and clean[1] == ':':
        drive = clean[:2].upper() + '\\'
        sub = clean[2:].lstrip('\\')
        return drive, sub

    return clean, ''


def normalize_root_path(path: str) -> str:
    r"""Normalize a root path so bare drive letters end in '\' and folders/UNC paths do not."""
    clean = sanitize_path(path).strip().strip('"\'').rstrip('\\')
    if len(clean) == 2 and clean[1] == ':':
        return clean.upper() + '\\'
    return clean


def extract_endpoint_root(full_path: str) -> str:
    r"""
    Extract the top-level drive letter or UNC server address from a path.

    Examples:
        'F:\Galeria Mine' -> 'F:\'
        '\\nas\share\Sub' -> '\\nas'

    """
    clean = sanitize_path(full_path).strip().strip('"\'')
    if clean.startswith('\\\\'):
        parts = [p for p in clean.split('\\') if p]
        if parts:
            return f'\\\\{parts[0]}'
        return clean
    if len(clean) >= 2 and clean[1] == ':':
        return clean[:2].upper() + '\\'
    return ''


def matches_root_prefix(full_path: str, root_path: str) -> bool:
    """Return True if full_path equals or is nested inside root_path on a directory boundary."""
    p_norm = sanitize_path(full_path).rstrip('\\').lower()
    r_norm = sanitize_path(root_path).rstrip('\\').lower()
    if not r_norm:
        return False
    return p_norm == r_norm or p_norm.startswith(r_norm + '\\')


def replace_root_prefix(full_path: str, old_root: str, new_root: str) -> str:
    """Replace old_root prefix with new_root on a directory boundary without creating double slashes."""
    if not matches_root_prefix(full_path, old_root):
        return full_path
    old_norm = sanitize_path(old_root).rstrip('\\')
    new_norm = sanitize_path(new_root).rstrip('\\')
    sub = sanitize_path(full_path).rstrip('\\')[len(old_norm) :].lstrip('\\')
    if sub:
        return f'{new_norm}\\{sub}'
    return normalize_root_path(new_norm)
