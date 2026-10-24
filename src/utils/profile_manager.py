"""
Configuration Profile Manager for FastMirror.

Handles creation, loading, saving, cloning, renaming, deletion, importing,
and exporting of named configuration profiles stored in data/profiles/.
"""

import contextlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from utils.constants import CONFIG_PATH
from utils.logger import logger

# Disallowed characters in Windows file stems: \ / : * ? " < > |
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_profile_name(name: str) -> str:
    """
    Sanitize and validate a profile name for safe filesystem usage on Windows.

    Strips whitespace, replaces invalid Windows filename characters with underscores,
    and prevents directory traversal.
    """
    raw = name.strip()
    if not raw or raw in ('.', '..'):
        raise ValueError('Profile name cannot be empty or relative path.')
    cleaned = _INVALID_FILENAME_CHARS.sub('_', raw)
    # Collapse multiple consecutive underscores
    cleaned = re.sub(r'_+', '_', cleaned)
    # Remove leading/trailing dots, spaces, or underscores which Windows forbids in file stems
    cleaned = cleaned.strip('._ ')
    if not cleaned:
        raise ValueError('Profile name cannot be empty or contain only invalid characters.')
    return cleaned


class ProfileManager:
    """Manages named JSON configuration profiles in data/profiles/ with backward-compatible sync."""

    DEFAULT_PROFILE_NAME = 'Default'

    def __init__(
        self,
        profiles_dir: str | Path | None = None,
        config_path: str | Path | None = None,
    ):
        self.config_path = Path(config_path or CONFIG_PATH).resolve()
        default_pdir = self.config_path.parent / 'profiles'
        self.profiles_dir = Path(profiles_dir or default_pdir).resolve()

    def ensure_profiles_dir(self) -> Path:
        """
        Ensure the profiles directory exists.

        If the profiles directory is newly created or empty:
        - If config_path exists and contains valid JSON, seed it as 'Default.json'.
        - Otherwise, create an empty 'Default.json' profile.
        """
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        default_profile_path = self.get_profile_path(self.DEFAULT_PROFILE_NAME)

        # Migrate any stray legacy *.deleted_*.json files into .deleted/
        deleted_dir = self.profiles_dir / '.deleted'
        for stray in self.profiles_dir.glob('*.deleted_*.json'):
            with contextlib.suppress(Exception):
                deleted_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(stray), str(deleted_dir / stray.name))

        existing_jsons = [f for f in self.profiles_dir.glob('*.json') if self._is_valid_profile_file(f)]
        if not existing_jsons:
            if self.config_path.is_file():
                try:
                    with open(self.config_path, encoding='utf-8') as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self.save_profile(self.DEFAULT_PROFILE_NAME, data, sync_active_config=False)
                        logger.info(f"Seeded '{self.DEFAULT_PROFILE_NAME}' profile from existing '{self.config_path}'")
                        return self.profiles_dir
                except Exception as e:
                    logger.warning(f"Could not seed default profile from '{self.config_path}': {e}")

            # Create default empty profile
            self.save_profile(self.DEFAULT_PROFILE_NAME, {}, sync_active_config=False)

        elif not default_profile_path.is_file():
            # If profiles exist but Default is missing, copy the first available or create empty
            first_file = existing_jsons[0]
            try:
                with open(first_file, encoding='utf-8') as f:
                    first_data = json.load(f)
            except Exception:
                first_data = {}
            self.save_profile(self.DEFAULT_PROFILE_NAME, first_data, sync_active_config=False)

        return self.profiles_dir

    @staticmethod
    def _is_valid_profile_file(file: Path) -> bool:
        """
        Check if a file in profiles_dir is a valid active profile JSON file.

        Ignores hidden files, backups, temporary files, and deleted files.
        """
        if not file.is_file():
            return False
        name = file.name
        if name.startswith('.'):
            return False
        if '.deleted' in name.lower() or name.lower().endswith('.bak') or name.lower().endswith('.tmp'):
            return False
        return file.suffix.lower() == '.json'

    def list_profiles(self) -> list[str]:
        """
        Return a sorted list of available profile names.

        Guarantees that at least 'Default' is included in the list.
        """
        self.ensure_profiles_dir()
        profiles: list[str] = []
        for file in self.profiles_dir.glob('*.json'):
            if self._is_valid_profile_file(file):
                profiles.append(file.stem)

        if self.DEFAULT_PROFILE_NAME not in profiles:
            profiles.append(self.DEFAULT_PROFILE_NAME)

        profiles.sort(key=lambda x: (x != self.DEFAULT_PROFILE_NAME, x.lower()))
        return profiles

    def get_profile_path(self, name: str) -> Path:
        """Return the absolute Path for a given profile name."""
        clean_name = sanitize_profile_name(name)
        return self.profiles_dir / f'{clean_name}.json'

    def load_profile(self, name: str) -> dict[str, Any]:
        """
        Load and parse the JSON configuration for the specified profile.

        Raises FileNotFoundError if the profile does not exist, or ValueError if JSON is invalid.
        """
        path = self.get_profile_path(name)
        if not path.is_file():
            if name == self.DEFAULT_PROFILE_NAME:
                self.ensure_profiles_dir()
            if not path.is_file():
                raise FileNotFoundError(f"Profile '{name}' does not exist at {path}")

        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Profile '{name}' root must be a JSON object, got {type(data).__name__}")
            return data
        except Exception as e:
            logger.error(f"Failed to read profile '{name}' from '{path}': {e}")
            raise

    def save_profile(
        self,
        name: str,
        config_vars: dict[str, Any],
        sync_active_config: bool = True,
    ) -> Path:
        """
        Atomically save configuration settings to the named profile.

        If sync_active_config is True, also syncs to config_path with 'active_profile': name
        to maintain full backward compatibility with non-GUI tools and scripts.
        """
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        clean_name = sanitize_profile_name(name)
        target_path = self.get_profile_path(clean_name)

        data_to_write = dict(config_vars)
        data_to_write['active_profile'] = clean_name

        tmp_path = target_path.with_suffix('.json.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data_to_write, f, indent=4)
        tmp_path.replace(target_path)

        logger.info(f"Configuration profile '{clean_name}' successfully saved to '{target_path}'")

        if sync_active_config:
            self._sync_to_global_config(clean_name, data_to_write)

        return target_path

    def _sync_to_global_config(self, active_profile_name: str, data: dict[str, Any]):
        """Mirror the active profile data into config_path for backward compatibility."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_global = self.config_path.with_suffix('.json.tmp')
            with open(tmp_global, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            tmp_global.replace(self.config_path)
        except Exception as e:
            logger.warning(f"Could not sync active profile to global config '{self.config_path}': {e}")

    def create_profile(
        self,
        name: str,
        config_vars: dict[str, Any] | None = None,
    ) -> Path:
        """Create a new profile with the given name and initial configuration."""
        clean_name = sanitize_profile_name(name)
        target_path = self.get_profile_path(clean_name)
        if target_path.is_file():
            raise FileExistsError(f"A profile named '{clean_name}' already exists.")

        initial_data = config_vars if config_vars is not None else {}
        return self.save_profile(clean_name, initial_data, sync_active_config=True)

    def clone_profile(self, source_name: str, new_name: str) -> Path:
        """Clone an existing profile into a new profile."""
        source_data = self.load_profile(source_name)
        return self.create_profile(new_name, source_data)

    def rename_profile(self, old_name: str, new_name: str) -> Path:
        """
        Rename an existing profile.

        The 'Default' profile cannot be renamed.
        """
        clean_old = sanitize_profile_name(old_name)
        clean_new = sanitize_profile_name(new_name)

        if clean_old.lower() == self.DEFAULT_PROFILE_NAME.lower():
            raise ValueError(f"The '{self.DEFAULT_PROFILE_NAME}' profile cannot be renamed.")

        old_path = self.get_profile_path(clean_old)
        new_path = self.get_profile_path(clean_new)

        if not old_path.is_file():
            raise FileNotFoundError(f"Profile '{clean_old}' does not exist.")
        if new_path.is_file() and clean_old.lower() != clean_new.lower():
            raise FileExistsError(f"A profile named '{clean_new}' already exists.")

        data = self.load_profile(clean_old)
        data['active_profile'] = clean_new
        old_path.unlink()
        return self.save_profile(clean_new, data, sync_active_config=True)

    def delete_profile(self, name: str) -> bool:
        """
        Delete a profile file from disk.

        The 'Default' profile cannot be deleted.
        A safety backup copy is archived to .deleted/ with a timestamp.
        """
        clean_name = sanitize_profile_name(name)
        if clean_name.lower() == self.DEFAULT_PROFILE_NAME.lower():
            raise ValueError(f"The '{self.DEFAULT_PROFILE_NAME}' profile cannot be deleted.")

        path = self.get_profile_path(clean_name)
        if not path.is_file():
            return False

        backup_copy: Path | None = None
        with contextlib.suppress(Exception):
            deleted_dir = self.profiles_dir / '.deleted'
            deleted_dir.mkdir(parents=True, exist_ok=True)
            backup_copy = deleted_dir / f'{clean_name}_{int(time.time())}.json'
            shutil.copyfile(path, backup_copy)

        path.unlink()
        msg = f"Deleted profile '{clean_name}'"
        if backup_copy is not None:
            msg += f' (backup copy saved at {backup_copy})'
        logger.info(msg)
        return True

    def get_active_profile_name(self) -> str:
        """Read the active profile name from config_path, or default to 'Default'."""
        if self.config_path.is_file():
            try:
                with open(self.config_path, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    active = data.get('active_profile')
                    if active and isinstance(active, str):
                        clean = sanitize_profile_name(active)
                        if self.get_profile_path(clean).is_file():
                            return clean
            except Exception:
                pass
        return self.DEFAULT_PROFILE_NAME

    def set_active_profile_name(self, name: str):
        """Update the active_profile property in config_path."""
        clean_name = sanitize_profile_name(name)
        if not self.config_path.is_file():
            self._sync_to_global_config(clean_name, {'active_profile': clean_name})
            return

        try:
            with open(self.config_path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                data['active_profile'] = clean_name
                self._sync_to_global_config(clean_name, data)
        except Exception as e:
            logger.warning(f"Could not record active profile name to '{self.config_path}': {e}")

    def export_profile(self, config_vars: dict[str, Any], target_path: str | Path) -> Path:
        """Atomically export configuration data to any file path on disk."""
        target = Path(target_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f'{target.suffix}.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(config_vars, f, indent=4)
        tmp.replace(target)
        logger.info(f"Configuration successfully exported to '{target}'")
        return target

    def import_profile(self, source_path: str | Path) -> dict[str, Any]:
        """Read and validate a configuration JSON file from any location on disk."""
        source = Path(source_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f'File not found: {source}')
        with open(source, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f'Expected JSON object at root, got {type(data).__name__}')
        return data
