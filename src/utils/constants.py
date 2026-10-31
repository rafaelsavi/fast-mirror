import os
import re
import sys

_IS_FROZEN = getattr(sys, 'frozen', False)

if _IS_FROZEN:
    EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, '_MEIPASS', EXE_DIR)
    ROOT_DIR = EXE_DIR

    # Check if portable data directory exists alongside the executable
    portable_data_dir = os.path.join(EXE_DIR, 'data')
    if os.path.isdir(portable_data_dir) or os.path.isfile(os.path.join(EXE_DIR, 'portable.txt')):
        DATA_DIR = portable_data_dir
    else:
        # Standard Windows LocalAppData location for installed applications
        local_app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        DATA_DIR = os.path.join(local_app_data, 'FastMirror', 'data')
else:
    ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
    BUNDLE_DIR = ROOT_DIR
    DATA_DIR = os.path.join(ROOT_DIR, 'data')

CONFIG_PATH = os.path.join(DATA_DIR, 'config.json')
PROFILES_DIR = os.path.join(DATA_DIR, 'profiles')
LOCAL_MIRROR_PATH = os.path.join(DATA_DIR, 'local_mirror.db')
LOGS_DIR = os.path.join(DATA_DIR, 'logs')


def _read_app_version() -> str:
    """Read version directly from package metadata or pyproject.toml."""
    try:
        from importlib.metadata import version

        return version('fast-mirror')
    except Exception:
        pass

    pyproject_path = os.path.join(ROOT_DIR, 'pyproject.toml')
    if os.path.isfile(pyproject_path):
        try:
            with open(pyproject_path, encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith('version'):
                        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', stripped)
                        if match:
                            return match.group(1)
        except Exception:
            pass

    return '1.0.0'


APP_VERSION = _read_app_version()
WINDOW_TITLE = f'FastMirror v{APP_VERSION}'
