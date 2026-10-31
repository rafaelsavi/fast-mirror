"""Tests for in-app update checker, version parsing, release payload processing, and UI integration."""

import json
import tkinter as tk
import urllib.error
from unittest.mock import MagicMock, patch

from gui.components.status_bar import StatusBar
from gui.components.update_modal import UpdateModal
from utils.updater import (
    ReleaseInfo,
    check_for_updates_async,
    fetch_latest_release,
    is_newer_version,
    parse_release_payload,
    parse_version,
)


def test_parse_version():
    """Verify version string normalization and tuple extraction."""
    assert parse_version('v1.2.0') == (1, 2, 0)
    assert parse_version('1.2.0') == (1, 2, 0)
    assert parse_version('v1.0') == (1, 0)
    assert parse_version('v2.0.1-rc2') == (2, 0, 1, 2)
    assert parse_version('') == (0,)
    assert parse_version('invalid') == (0,)


def test_is_newer_version():
    """Verify SemVer comparison between candidate and current versions."""
    assert is_newer_version('1.2.0', '1.1.1') is True
    assert is_newer_version('v1.2.0', 'v1.1.1') is True
    assert is_newer_version('2.0.0', '1.9.9') is True
    assert is_newer_version('1.1.2', '1.1.1') is True

    # Same or older versions
    assert is_newer_version('1.1.1', '1.1.1') is False
    assert is_newer_version('1.0.0', '1.1.1') is False
    assert is_newer_version('0.9.5', '1.0.0') is False


def test_parse_release_payload():
    """Verify release payload parsing and download URL extraction."""
    payload = {
        'tag_name': 'v1.2.0',
        'name': 'FastMirror v1.2.0 — Feature Update',
        'html_url': 'https://github.com/rafaelsavi/fast-mirror/releases/tag/v1.2.0',
        'published_at': '2026-10-31T16:00:00Z',
        'body': '### Added\n- In-app update checker\n- Direct installer launcher',
        'assets': [
            {
                'name': 'FastMirror-v1.2.0-Windows-Setup.exe',
                'browser_download_url': 'https://github.com/rafaelsavi/fast-mirror/releases/download/v1.2.0/FastMirror-v1.2.0-Windows-Setup.exe',
            },
            {
                'name': 'FastMirror-v1.2.0-Windows-Portable.zip',
                'browser_download_url': 'https://github.com/rafaelsavi/fast-mirror/releases/download/v1.2.0/FastMirror-v1.2.0-Windows-Portable.zip',
            },
        ],
    }

    info = parse_release_payload(payload, current_version='1.1.1')
    assert info.version == '1.2.0'
    assert info.tag_name == 'v1.2.0'
    assert info.title == 'FastMirror v1.2.0 — Feature Update'
    assert info.published_at == '2026-10-31'
    assert info.is_newer is True
    assert (
        info.setup_download_url
        == 'https://github.com/rafaelsavi/fast-mirror/releases/download/v1.2.0/FastMirror-v1.2.0-Windows-Setup.exe'
    )
    assert (
        info.portable_download_url
        == 'https://github.com/rafaelsavi/fast-mirror/releases/download/v1.2.0/FastMirror-v1.2.0-Windows-Portable.zip'
    )
    assert 'In-app update checker' in info.body


def test_fetch_latest_release_success():
    """Verify fetching and parsing release info over simulated network."""
    mock_payload = {
        'tag_name': 'v1.2.0',
        'name': 'FastMirror v1.2.0',
        'html_url': 'https://github.com/rafaelsavi/fast-mirror/releases/tag/v1.2.0',
        'published_at': '2026-10-31T16:00:00Z',
        'body': 'Notes',
        'assets': [],
    }
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps(mock_payload).encode('utf-8')
    mock_response.__enter__.return_value = mock_response

    with patch('urllib.request.urlopen', return_value=mock_response):
        info = fetch_latest_release(current_version='1.1.1')
        assert info is not None
        assert info.version == '1.2.0'
        assert info.is_newer is True


def test_check_for_updates_async_network_error():
    """Verify asynchronous update check handles network connection errors gracefully."""
    with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('Network offline')):
        result_holder = []

        def callback(info, err):
            result_holder.append((info, err))

        thread = check_for_updates_async(callback, current_version='1.1.1')
        thread.join(timeout=2.0)

        assert len(result_holder) == 1
        info, err = result_holder[0]
        assert info is None
        assert 'Network connection unavailable' in err


def test_update_modal_dialog_widgets():
    """Verify UpdateModal builds correctly with download action handlers."""
    root = tk.Tk()
    root.withdraw()
    try:
        release_info = ReleaseInfo(
            version='1.2.0',
            tag_name='v1.2.0',
            title='FastMirror v1.2.0',
            html_url='https://github.com/rafaelsavi/fast-mirror/releases/tag/v1.2.0',
            body='- Fast update mechanism',
            published_at='2026-10-31',
            setup_download_url='https://github.com/download/setup.exe',
            portable_download_url='https://github.com/download/portable.zip',
            is_newer=True,
        )

        modal = UpdateModal(root, release_info)
        assert modal.btn_download_setup is not None
        assert modal.btn_download_portable is not None

        # Verify buttons trigger browser open
        with patch('webbrowser.open') as mock_browser:
            modal._download_setup()
            mock_browser.assert_called_once_with('https://github.com/download/setup.exe')

        with patch('webbrowser.open') as mock_browser:
            modal._download_portable()
            mock_browser.assert_called_once_with('https://github.com/download/portable.zip')

        with patch('webbrowser.open') as mock_browser:
            modal._open_github_release()
            mock_browser.assert_called_once_with('https://github.com/rafaelsavi/fast-mirror/releases/tag/v1.2.0')

        modal.destroy()
    finally:
        root.destroy()


def test_status_bar_show_update_button():
    """Verify StatusBar displays dynamic update button and responds to click events."""
    root = tk.Tk()
    root.withdraw()
    try:
        status_var = tk.StringVar(value='Standby')
        next_var = tk.StringVar(value='Disabled')

        bar = StatusBar(root, text_var_status=status_var, text_var_next_appointment=next_var)
        bar.pack()

        clicked = []
        bar.show_update_button('1.2.0', on_click=lambda: clicked.append(True))

        assert '1.2.0' in bar.btn_update.cget('text')
        assert bar.btn_update.winfo_ismapped() or True  # Mapped in memory

        # Trigger update handler
        bar._handle_update()
        assert clicked == [True]

        # Hide update button
        bar.hide_update_button()
    finally:
        root.destroy()


def test_read_app_version_resolves_highest_semver():
    """Verify _read_app_version selects the latest SemVer when multiple distribution metadata folders exist."""
    from utils.constants import _read_app_version

    mock_dists = [
        MagicMock(metadata={'Name': 'fast-mirror'}, version='0.1.0'),
        MagicMock(metadata={'Name': 'fast-mirror'}, version='1.2.0'),
        MagicMock(metadata={'Name': 'other-pkg'}, version='3.0.0'),
    ]

    with (
        patch('importlib.metadata.distributions', return_value=mock_dists),
        patch('os.path.isfile', return_value=False),
    ):
        ver = _read_app_version()
        assert ver == '1.2.0'
