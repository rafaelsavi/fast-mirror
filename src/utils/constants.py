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
    """Read version directly from pyproject.toml or installed package distribution metadata."""
    # 1. Single source of truth: check pyproject.toml if present (source repository / bundled)
    for base in (ROOT_DIR, BUNDLE_DIR):
        pyproject_path = os.path.join(base, 'pyproject.toml')
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

    # 2. Check installed/bundled distribution metadata, selecting the highest valid SemVer
    try:
        from importlib.metadata import distributions

        found_versions: list[str] = []
        for dist in distributions():
            dist_name = (
                dist.metadata['Name'] if (dist.metadata and 'Name' in dist.metadata) else getattr(dist, 'name', None)
            )
            if dist_name and dist_name.lower() == 'fast-mirror':
                ver = dist.version
                if ver:
                    found_versions.append(ver)

        if found_versions:

            def _ver_key(v: str) -> tuple[int, ...]:
                nums = re.findall(r'\d+', v)
                return tuple(int(n) for n in nums) if nums else (0,)

            found_versions.sort(key=_ver_key)
            return found_versions[-1]
    except Exception:
        pass

    return '1.2.3'


APP_VERSION = _read_app_version()
WINDOW_TITLE = f'FastMirror v{APP_VERSION}'

GITHUB_REPO = 'rafaelsavi/fast-mirror'
GITHUB_RELEASES_URL = f'https://github.com/{GITHUB_REPO}/releases'
GITHUB_API_LATEST_RELEASE = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
