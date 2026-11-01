"""
In-app update checker for FastMirror.

Queries GitHub Releases API asynchronously in a background thread to determine
if a newer version is available, parse release notes, and extract direct download links
for Setup and Portable packages without blocking the UI thread.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from utils.constants import (
    APP_VERSION,
    GITHUB_API_LATEST_RELEASE,
    GITHUB_API_RELEASES_LIST,
    GITHUB_RELEASES_URL,
)
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


def clean_release_body(body: str) -> str:
    """Extract release notes while omitting redundant download links and smartscreen footers."""
    # Split on markdown horizontal rule if present
    parts = re.split(r'\n\s*---\s*\n', body)
    clean = parts[0].strip() if parts else body.strip()
    # Remove any trailing "### Downloads" section if no delimiter was used
    dl_match = re.search(r'\n\s*###\s+Downloads', clean, re.IGNORECASE)
    if dl_match:
        clean = clean[: dl_match.start()].strip()
    return clean


def aggregate_releases_payload(
    releases: list[dict[str, Any]], current_version: str = APP_VERSION
) -> ReleaseInfo | None:
    """
    Parse a list of releases from GitHub API and aggregate changelogs for all intermediate versions.

    If candidate versions exceed current_version by multiple releases (e.g. updating from 1.0.0
    to 1.2.3), the release notes of all newer intermediate versions are aggregated chronologically,
    ensuring the user sees the complete history of changes.
    """
    if not releases:
        return None

    parsed_candidates: list[ReleaseInfo] = []
    for item in releases:
        if not isinstance(item, dict) or item.get('draft'):
            continue
        parsed_candidates.append(parse_release_payload(item, current_version=current_version))

    if not parsed_candidates:
        return None

    # Sort descending by SemVer
    parsed_candidates.sort(key=lambda r: parse_version(r.version), reverse=True)
    latest = parsed_candidates[0]

    # Filter all newer releases
    newer = [r for r in parsed_candidates if is_newer_version(r.version, current_version)]

    if not newer:
        return latest

    if len(newer) == 1:
        return newer[0]

    # Multiple intermediate versions exist: aggregate changelogs chronologically
    sections: list[str] = []
    for idx, rel in enumerate(newer):
        header = f'### What’s New in v{rel.version}'
        if idx == 0:
            header += ' (Latest)'
        clean_notes = clean_release_body(rel.body) or 'General performance improvements and bug fixes.'
        sections.append(f'{header}\n\n{clean_notes}')

    combined_body = '\n\n---\n\n'.join(sections)

    return ReleaseInfo(
        version=latest.version,
        tag_name=latest.tag_name,
        title=f'FastMirror v{latest.version} ({len(newer)} updates)',
        html_url=latest.html_url,
        body=combined_body,
        published_at=latest.published_at,
        setup_download_url=latest.setup_download_url,
        portable_download_url=latest.portable_download_url,
        is_newer=True,
    )


def fetch_latest_release(
    url: str = GITHUB_API_RELEASES_LIST,
    timeout: float = 4.0,
    current_version: str = APP_VERSION,
) -> ReleaseInfo | None:
    """
    Fetch release metadata from GitHub API synchronously with timeout.

    Supports both:
    1. GitHub Releases List (JSON array), aggregating changelogs across multiple version jumps.
    2. GitHub Latest Release (JSON dict), parsing the single latest release.
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
        if isinstance(payload, list):
            return aggregate_releases_payload(payload, current_version=current_version)
        if isinstance(payload, dict):
            return parse_release_payload(payload, current_version=current_version)
        return None


def check_for_updates_async(
    callback: Callable[[ReleaseInfo | None, str | None], None],
    current_version: str = APP_VERSION,
    timeout: float = 4.0,
    url: str = GITHUB_API_RELEASES_LIST,
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
            # Fallback to single latest release if full list endpoint is blocked or non-standard
            if url == GITHUB_API_RELEASES_LIST:
                try:
                    fallback_info = fetch_latest_release(
                        url=GITHUB_API_LATEST_RELEASE,
                        timeout=timeout,
                        current_version=current_version,
                    )
                    callback(fallback_info, None)
                    return
                except Exception:
                    pass
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


def get_default_installer_download_path(version: str) -> str:
    """Return the destination filesystem path in %TEMP% for a downloaded installer executable."""
    clean_ver = version.lstrip('vV').strip()
    return os.path.join(tempfile.gettempdir(), f'FastMirror-v{clean_ver}-Windows-Setup.exe')


def download_installer_chunked(
    url: str,
    target_path: str,
    progress_callback: Callable[[int, int | None], None] | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = 30.0,
) -> str:
    """
    Download the installer executable from url to target_path in 64 KB chunks.

    Writes to a temporary .part file first and renames upon full download to avoid
    corrupted or partially downloaded binaries.
    """
    req = urllib.request.Request(
        url,
        headers={
            'Accept': 'application/octet-stream,*/*',
            'User-Agent': f'FastMirror-App/{APP_VERSION}',
        },
    )
    part_path = target_path + '.part'
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_length_str = response.headers.get('Content-Length')
        total_bytes = int(content_length_str) if content_length_str and content_length_str.isdigit() else None
        downloaded = 0
        chunk_size = 64 * 1024

        with open(part_path, 'wb') as f:
            while True:
                if cancel_event and cancel_event.is_set():
                    f.close()
                    with contextlib.suppress(Exception):
                        os.remove(part_path)
                    raise InterruptedError('Download cancelled by user')

                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_bytes)

    if os.path.exists(target_path):
        with contextlib.suppress(Exception):
            os.remove(target_path)
    os.replace(part_path, target_path)
    return target_path


def download_installer_async(
    url: str,
    target_path: str,
    on_progress: Callable[[int, int | None], None],
    on_complete: Callable[[str | None, str | None], None],
    cancel_event: threading.Event | None = None,
) -> threading.Thread:
    """
    Download the installer asynchronously in a background worker thread.

    Invokes on_progress(bytes_downloaded, total_bytes) periodically and
    on_complete(target_path_or_none, error_message_or_none) upon completion.
    """

    def _worker():
        try:
            path = download_installer_chunked(
                url=url,
                target_path=target_path,
                progress_callback=on_progress,
                cancel_event=cancel_event,
            )
            on_complete(path, None)
        except InterruptedError:
            on_complete(None, 'Download cancelled')
        except urllib.error.URLError as ex:
            logger.warning(f'Installer download network error: {ex.reason}')
            on_complete(None, f'Network error: {ex.reason}')
        except Exception as ex:
            logger.warning(f'Installer download failed: {ex}')
            on_complete(None, str(ex))

    thread = threading.Thread(target=_worker, name='InstallerDownloaderThread', daemon=True)
    thread.start()
    return thread
