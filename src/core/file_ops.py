import ctypes
import errno
import os
import shutil
import stat
import time

from utils.logger import logger


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
            os.makedirs(target_dir, exist_ok=True)
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
) -> None:
    """Move file from source to target with exponential backoff retries and permission recovery."""
    source_str = str(source)
    target_str = str(target)
    target_existed_initially = os.path.isfile(target_str)
    delay = initial_delay

    if not os.path.isfile(source_str):
        raise FileNotFoundError(f"Source file does not exist: '{source_str}'")

    for attempt in range(1, max(1, max_retries) + 1):
        try:
            os.makedirs(os.path.dirname(target_str), exist_ok=True)
            shutil.move(source_str, target_str)
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
    if not os.path.isfile(path_str):
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
