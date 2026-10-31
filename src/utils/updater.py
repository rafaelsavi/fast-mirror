"""
In-app update checker for FastMirror.

Queries GitHub Releases API asynchronously in a background thread to determine
if a newer version is available, parse release notes, and extract direct download links
for Setup and Portable packages without blocking the UI thread.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from utils.constants import APP_VERSION, GITHUB_API_LATEST_RELEASE, GITHUB_RELEASES_URL
from utils.logger import logger


def parse_version(version_str: str) -> tuple[int, ...]:
    """
    Parse a version string (e.g. 'v1.2.0', '1.2.0', 'v1.0') into an integer tuple.

    Strips leading 'v' characters and extracts numeric components. Non-numeric suffixes
    (e.g. -beta, -rc) are handled cleanly by extracting purely numeric components.
    """
    cleaned = version_str.strip().lstrip('vV')
    parts = re.findall(r'\d+', cleaned)
    return tuple(int(p) for p in parts) if parts else (0,)


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    """Return True if candidate version is strictly higher than current version according to SemVer."""
    cand_tuple = parse_version(candidate)
    curr_tuple = parse_version(current)
    max_len = max(len(cand_tuple), len(curr_tuple))
    cand_padded = cand_tuple + (0,) * (max_len - len(cand_tuple))
    curr_padded = curr_tuple + (0,) * (max_len - len(curr_tuple))
    return cand_padded > curr_padded


@dataclass
class ReleaseInfo:
    """Structured release metadata extracted from the GitHub Releases API."""

    version: str
    tag_name: str
    title: str
    html_url: str
    body: str
    published_at: str
    setup_download_url: str | None = None
    portable_download_url: str | None = None
    is_newer: bool = False


def parse_release_payload(data: dict[str, Any], current_version: str = APP_VERSION) -> ReleaseInfo:
    """Parse raw JSON release payload from GitHub API into a ReleaseInfo instance."""
    tag = str(data.get('tag_name', ''))
    version = tag.lstrip('vV').strip()
    title = str(data.get('name') or tag)
    html_url = str(data.get('html_url') or GITHUB_RELEASES_URL)
    body = str(data.get('body') or '')
    published_at = str(data.get('published_at') or '')[:10]

    setup_url: str | None = None
    portable_url: str | None = None

    assets = data.get('assets', [])
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get('name', '')).lower()
            dl_url = str(asset.get('browser_download_url', ''))
            if not dl_url:
                continue
            if 'setup' in name and name.endswith('.exe') or name.endswith('.exe') and setup_url is None:
                setup_url = dl_url
            elif 'portable' in name and name.endswith('.zip') or name.endswith('.zip') and portable_url is None:
                portable_url = dl_url

    is_newer = is_newer_version(version, current_version)

    return ReleaseInfo(
        version=version,
        tag_name=tag,
        title=title,
        html_url=html_url,
        body=body,
        published_at=published_at,
        setup_download_url=setup_url,
        portable_download_url=portable_url,
        is_newer=is_newer,
    )


def fetch_latest_release(
    url: str = GITHUB_API_LATEST_RELEASE,
    timeout: float = 4.0,
    current_version: str = APP_VERSION,
) -> ReleaseInfo | None:
    """
    Fetch the latest release descriptor from GitHub API synchronously with timeout.

    Returns ReleaseInfo on success, or None if response is non-200.
    """
    req = urllib.request.Request(
        url,
        headers={
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': f'FastMirror-App/{current_version}',
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            return None
        payload = json.loads(response.read().decode('utf-8'))
        return parse_release_payload(payload, current_version=current_version)


def check_for_updates_async(
    callback: Callable[[ReleaseInfo | None, str | None], None],
    current_version: str = APP_VERSION,
    timeout: float = 4.0,
    url: str = GITHUB_API_LATEST_RELEASE,
) -> threading.Thread:
    """
    Check for updates asynchronously in a daemon background thread.

    Invokes callback(release_info, error_message) upon completion.
    """

    def _worker():
        try:
            info = fetch_latest_release(url=url, timeout=timeout, current_version=current_version)
            callback(info, None)
        except urllib.error.HTTPError as ex:
            logger.debug(f'Update check HTTP error: {ex.code} {ex.reason}')
            callback(None, f'GitHub API error ({ex.code})')
        except urllib.error.URLError as ex:
            logger.debug(f'Update check network error: {ex.reason}')
            callback(None, 'Network connection unavailable')
        except Exception as ex:
            logger.debug(f'Update check unexpected error: {ex}')
            callback(None, str(ex))

    thread = threading.Thread(target=_worker, name='UpdateCheckerThread', daemon=True)
    thread.start()
    return thread
