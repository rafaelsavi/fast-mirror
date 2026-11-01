import contextlib
import ctypes
import errno
import os
import shutil
import stat
import time
from pathlib import Path

from utils.logger import logger


def get_actual_case_name(path: str | os.PathLike[str]) -> str | None:
    """Return the exact casing of a file or directory name as stored on disk using os.scandir."""
    path_str = str(path).rstrip('\\/')
    if not path_str:
        return None

    parent = os.path.dirname(path_str)
    base = os.path.basename(path_str)
    if not parent or not os.path.exists(parent):
        return None
    try:
        base_lower = base.lower()
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.name.lower() == base_lower:
                    return entry.name
    except Exception as e:
        logger.debug(f"scandir failed for '{path_str}': {e}")
    return None


def rename_case_safe(
    old_path: str | os.PathLike[str],
    new_path: str | os.PathLike[str],
    max_retries: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
) -> None:
    """Safely rename a file or directory in-place when only casing changes, handling SMB/FAT collision semantics."""
    old_str = str(old_path)
    new_str = str(new_path)
    unlock_file_attributes(old_str)

    delay = initial_delay
    for attempt in range(1, max(1, max_retries) + 1):
        # Attempt 1: Direct in-place rename / replace
        try:
            os.replace(old_str, new_str)
            return
        except OSError:
            pass

        # Attempt 2: Two-step rename via temporary intermediate name (required by some SMB/FAT filesystems)
        parent_dir = os.path.dirname(old_str)
        temp_name = f'.__fm_case_{os.getpid()}_{time.time_ns()}__'
        temp_path = os.path.join(parent_dir, temp_name)
        try:
            os.replace(old_str, temp_path)
            os.replace(temp_path, new_str)
            return
        except (OSError, PermissionError) as e:
            if os.path.exists(temp_path):
                with contextlib.suppress(Exception):
                    os.replace(temp_path, old_str)
            unlock_file_attributes(old_str)
            if attempt == max(1, max_retries):
                logger.error(f"Failed to case-rename '{old_str}' -> '{new_str}': {e}")
                raise
            time.sleep(delay)
            delay *= backoff_factor


def ensure_directory_case(target_dir: str | os.PathLike[str], verified_cache: set[str] | None = None) -> None:
    """
    Ensure all directory path components on disk exist and match the exact casing of target_dir.
    If an existing directory has differing case (e.g. '04 - event' vs '04 - Event'), rename it on disk.
    """
    target_dir_str = str(target_dir).rstrip('\\/')
    if not target_dir_str:
        return
    if verified_cache is not None and target_dir_str in verified_cache:
        return

    p = Path(target_dir_str)
    parts = p.parts
    if not parts:
        return

    if p.anchor:
        current = Path(p.anchor)
        components = parts[1:]
    else:
        current = Path('.')
        components = parts

    for part in components:
        expected_path = current / part
        expected_str = str(expected_path).rstrip('\\/')
        if verified_cache is not None and expected_str in verified_cache:
            current = expected_path
            continue

        if os.path.exists(expected_str):
            actual_name = get_actual_case_name(expected_str)
            if actual_name and actual_name != part and actual_name.lower() == part.lower():
                actual_path = current / actual_name
                try:
                    rename_case_safe(str(actual_path), expected_str)
                    logger.info(f"Corrected directory case on disk: '{actual_path}' -> '{expected_str}'")
                except Exception as e:
                    logger.warning(f"Could not correct directory casing for '{actual_path}' -> '{expected_str}': {e}")
        else:
            os.makedirs(expected_str, exist_ok=True)

        if verified_cache is not None:
            verified_cache.add(expected_str)
        current = expected_path

    if verified_cache is not None:
        verified_cache.add(target_dir_str)


def unlock_file_attributes(path: str | os.PathLike[str]) -> bool:
    """Attempt to clear read-only / hidden / system attributes on Windows or make writable via chmod."""
    path_str = str(path)
    if not os.path.exists(path_str):
        return False

    success = False
    if hasattr(ctypes, 'windll') and hasattr(ctypes.windll, 'kernel32'):
        try:
            file_attribute_normal = 0x80
            res = ctypes.windll.kernel32.SetFileAttributesW(path_str, file_attribute_normal)
            if res != 0:
                success = True
            else:
                logger.debug(f"Windows refused to change attributes on '{path_str}'.")
        except Exception as e:
            logger.debug(f"SetFileAttributesW failed for '{path_str}': {e}")

    try:
        os.chmod(path_str, stat.S_IWRITE)
        success = True
    except Exception as e:
        logger.debug(f"chmod failed for '{path_str}': {e}")

    return success


def robust_copy(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    verified_dir_cache: set[str] | None = None,
) -> None:
    """
    Copy file from source to target with exponential backoff retries for network resilience and permission recovery.

    Writes to a temporary staging file in the target directory and atomically replaces the destination.
    If transient errors, failures, or thread abortions (SystemExit) occur, incomplete files are guaranteed
    to be cleaned up in a finally block.
    """
    source_str = str(source)
    target_str = str(target)
    target_dir = os.path.dirname(target_str)
    temp_target = f'{target_str}.tmp'
    delay = initial_delay

    if not os.path.isfile(source_str):
        raise FileNotFoundError(f"Source file does not exist: '{source_str}'")

    for attempt in range(1, max(1, max_retries) + 1):
        completed = False
        try:
            ensure_directory_case(target_dir, verified_cache=verified_dir_cache)
            # Remove any stale temporary file left from an earlier crash or power loss
            if os.path.isfile(temp_target):
                try:
                    unlock_file_attributes(temp_target)
                    os.remove(temp_target)
                except Exception as pre_clean_err:
                    logger.debug(f"Could not remove stale temp file '{temp_target}': {pre_clean_err}")

            shutil.copy2(source_str, temp_target)
            if os.path.isfile(target_str):
                unlock_file_attributes(target_str)
            os.replace(temp_target, target_str)
            completed = True
            return
        except FileNotFoundError:
            # Permanent error (e.g. source disappeared) - fail fast without retries
            raise
        except (OSError, PermissionError) as e:
            if getattr(e, 'winerror', None) in (2, 3) or getattr(e, 'errno', None) == errno.ENOENT:
                raise

            unlock_file_attributes(target_str)

            if attempt == max(1, max_retries):
                raise

            logger.warning(
                f"Copy attempt {attempt}/{max_retries} for '{source_str}' -> '{target_str}' "
                f'failed with: {e}. Retrying in {delay:.1f}s...'
            )
            time.sleep(delay)
            delay *= backoff_factor
        finally:
            if not completed and os.path.isfile(temp_target):
                try:
                    unlock_file_attributes(temp_target)
                    os.remove(temp_target)
                    logger.warning(f"Cleaned up incomplete temporary target file after abort/failure: '{temp_target}'")
                except Exception as cleanup_err:
                    logger.debug(f"Failed to clean up temp file '{temp_target}': {cleanup_err}")


def robust_move(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    verified_dir_cache: set[str] | None = None,
) -> None:
    """
    Move file from source to target with exponential backoff retries,
    directory case reconciliation, and permission recovery.
    """
    source_str = str(source)
    target_str = str(target)
    target_existed_initially = os.path.isfile(target_str)
    delay = initial_delay

    if not os.path.isfile(source_str):
        raise FileNotFoundError(f"Source file does not exist: '{source_str}'")

    for attempt in range(1, max(1, max_retries) + 1):
        try:
            target_dir = os.path.dirname(target_str)
            ensure_directory_case(target_dir, verified_cache=verified_dir_cache)

            # Check if source and target resolve to the exact same file (in-place case rename or parent dir rename)
            same_file_case_insensitive = False
            with contextlib.suppress(Exception):
                same_file_case_insensitive = os.path.normcase(os.path.abspath(source_str)) == os.path.normcase(
                    os.path.abspath(target_str)
                )

            if same_file_case_insensitive:
                src_name = os.path.basename(source_str)
                tgt_name = os.path.basename(target_str)
                actual_name = get_actual_case_name(target_str) or src_name
                if actual_name != tgt_name:
                    actual_path = os.path.join(target_dir, actual_name)
                    rename_case_safe(actual_path, target_str)
                return

            shutil.move(source_str, target_str)
            actual_tgt_name = get_actual_case_name(target_str)
            expected_tgt_name = os.path.basename(target_str)
            if (
                actual_tgt_name
                and actual_tgt_name != expected_tgt_name
                and actual_tgt_name.lower() == expected_tgt_name.lower()
            ):
                rename_case_safe(os.path.join(target_dir, actual_tgt_name), target_str)
            return
        except FileNotFoundError:
            # Missing source is permanent - fail fast without retrying
            raise
        except (OSError, PermissionError) as e:
            if getattr(e, 'winerror', None) in (2, 3) or getattr(e, 'errno', None) == errno.ENOENT:
                raise

            unlock_file_attributes(target_str)
            unlock_file_attributes(source_str)

            if attempt == max(1, max_retries):
                if os.path.isfile(source_str) and os.path.isfile(target_str):
                    try:
                        source_size = os.path.getsize(source_str)
                        target_size = os.path.getsize(target_str)
                        if not target_existed_initially or target_size != source_size:
                            unlock_file_attributes(target_str)
                            os.remove(target_str)
                            logger.warning(
                                f"Cleaned up incomplete target file after failed move attempts: '{target_str}'"
                            )
                    except Exception as cleanup_err:
                        logger.debug(f"Failed to clean up partial target file '{target_str}': {cleanup_err}")
                raise

            logger.warning(
                f"Move attempt {attempt}/{max_retries} for '{source_str}' -> '{target_str}' "
                f'failed with: {e}. Retrying in {delay:.1f}s...'
            )
            time.sleep(delay)
            delay *= backoff_factor


def robust_delete(
    path: str | os.PathLike[str],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> None:
    """Delete file with permission recovery and exponential backoff retries."""
    path_str = str(path)
    if not os.path.lexists(path_str):
        return

    delay = initial_delay
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            unlock_file_attributes(path_str)
            os.remove(path_str)
            return
        except FileNotFoundError:
            # File is already gone; no need to retry deleting a missing file
            return
        except (OSError, PermissionError) as e:
            if getattr(e, 'winerror', None) in (2, 3) or getattr(e, 'errno', None) == errno.ENOENT:
                return

            unlock_file_attributes(path_str)
            if attempt == max(1, max_retries):
                raise

            logger.warning(
                f"Delete attempt {attempt}/{max_retries} for '{path_str}' failed with: {e}. Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
            delay *= backoff_factor
