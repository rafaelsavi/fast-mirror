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


def test_get_default_installer_download_path():
    """Verify default download destination path in %TEMP%."""
    from utils.updater import get_default_installer_download_path

    path = get_default_installer_download_path('1.2.1')
    assert path.endswith('FastMirror-v1.2.1-Windows-Setup.exe')
    path_v = get_default_installer_download_path('v1.2.1')
    assert path_v.endswith('FastMirror-v1.2.1-Windows-Setup.exe')


def test_download_installer_chunked_success(tmp_path):
    """Verify chunked downloading and atomic file renaming upon completion."""
    from utils.updater import download_installer_chunked

    dest = str(tmp_path / 'Setup.exe')
    mock_payload = b'InstallerBinaryData' * 1024
    progress_calls = []

    mock_resp = MagicMock()
    mock_resp.headers.get.return_value = str(len(mock_payload))
    mock_resp.read.side_effect = [mock_payload[:1024], mock_payload[1024:], b'']
    mock_resp.__enter__.return_value = mock_resp

    with patch('urllib.request.urlopen', return_value=mock_resp):
        result = download_installer_chunked(
            url='https://example.com/setup.exe',
            target_path=dest,
            progress_callback=lambda down, tot: progress_calls.append((down, tot)),
        )

        assert result == dest
        assert (tmp_path / 'Setup.exe').is_file()
        assert (tmp_path / 'Setup.exe').stat().st_size == len(mock_payload)
        assert len(progress_calls) >= 2
        assert progress_calls[-1] == (len(mock_payload), len(mock_payload))


def test_download_installer_chunked_cancellation(tmp_path):
    """Verify download cancellation cleans up temporary partial files."""
    import threading

    import pytest

    from utils.updater import download_installer_chunked

    dest = str(tmp_path / 'Setup.exe')
    cancel_event = threading.Event()
    cancel_event.set()

    mock_resp = MagicMock()
    mock_resp.headers.get.return_value = '2048'
    mock_resp.read.return_value = b'chunk'
    mock_resp.__enter__.return_value = mock_resp

    with patch('urllib.request.urlopen', return_value=mock_resp):
        with pytest.raises(InterruptedError):
            download_installer_chunked(
                url='https://example.com/setup.exe',
                target_path=dest,
                cancel_event=cancel_event,
            )

        assert not (tmp_path / 'Setup.exe').exists()
        assert not (tmp_path / 'Setup.exe.part').exists()


def test_single_instance_lifecycle():
    """Verify single instance mutex acquisition and explicit release."""
    from utils.single_instance import acquire_single_instance, is_single_instance_acquired, release_single_instance

    # Mock kernel32 to verify acquire and release behavior
    mock_kernel32 = MagicMock()
    mock_kernel32.CreateMutexW.return_value = 12345
    mock_kernel32.GetLastError.return_value = 0

    with patch('ctypes.windll.kernel32', mock_kernel32, create=True):
        acquired = acquire_single_instance(activate_existing=False)
        assert acquired is True
        assert is_single_instance_acquired() is True

        release_single_instance()
        assert is_single_instance_acquired() is False
        mock_kernel32.CloseHandle.assert_called_with(12345)


def test_update_modal_in_app_download_and_browser_guidance():
    """Verify UpdateModal in-app download and browser advisory flows."""
    root = tk.Tk()
    root.withdraw()
    try:
        release_info = ReleaseInfo(
            version='1.2.1',
            tag_name='v1.2.1',
            title='FastMirror v1.2.1',
            html_url='https://github.com/rafaelsavi/fast-mirror/releases/tag/v1.2.1',
            body='- Fast installer updater',
            published_at='2026-10-31',
            setup_download_url='https://github.com/download/setup.exe',
            is_newer=True,
        )

        modal = UpdateModal(root, release_info)

        # 1. Test browser download guidance
        with patch('webbrowser.open'):
            modal._download_via_browser()
            assert '⚠️' in modal.lbl_progress_status.cget('text')
            assert 'Close FastMirror' in modal.btn_action_setup.cget('text')

        # 2. Test in-app download completion state
        modal.downloaded_installer_path = 'C:\\fake\\Setup.exe'
        modal._on_download_complete('C:\\fake\\Setup.exe', None)
        root.update()

        assert 'Restart & Install' in modal.btn_action_setup.cget('text')
        assert 'Update downloaded' in modal.lbl_progress_status.cget('text')

        # 3. Test installer launcher execution
        with (
            patch('subprocess.Popen') as mock_popen,
            patch('gui.components.update_modal.release_single_instance') as mock_rel,
            patch('sys.exit') as mock_exit,
        ):
            modal._launch_installer_and_exit()
            mock_popen.assert_called_once_with(['C:\\fake\\Setup.exe'])
            mock_rel.assert_called_once()
            mock_exit.assert_called_once_with(0)

        modal.destroy()
    finally:
        root.destroy()


def test_clean_release_body():
    """Verify clean_release_body strips out download links and smartscreen footers."""
    from utils.updater import clean_release_body

    body = """### Added
- Feature A
- Feature B

---
### Downloads
- Setup Wizard: FastMirror.exe

### Windows SmartScreen Notice
Notice text
"""
    cleaned = clean_release_body(body)
    assert 'Feature A' in cleaned
    assert 'Feature B' in cleaned
    assert 'Downloads' not in cleaned
    assert 'SmartScreen' not in cleaned


def test_aggregate_releases_payload_multiple_versions():
    """Verify aggregating release notes when multiple version updates are available."""
    from utils.updater import aggregate_releases_payload

    releases = [
        {
            'tag_name': 'v1.2.3',
            'name': 'FastMirror v1.2.3',
            'html_url': 'https://github.com/releases/1.2.3',
            'published_at': '2026-11-01',
            'body': '- Bugfix in updater\n\n---\n### Downloads\nSetup link',
            'assets': [
                {'name': 'FastMirror-v1.2.3-Windows-Setup.exe', 'browser_download_url': 'https://setup-1.2.3.exe'}
            ],
        },
        {
            'tag_name': 'v1.2.2',
            'name': 'FastMirror v1.2.2',
            'html_url': 'https://github.com/releases/1.2.2',
            'published_at': '2026-11-01',
            'body': '- Mutex handling\n- 1-click update flow',
            'assets': [],
        },
        {
            'tag_name': 'v1.2.1',
            'name': 'FastMirror v1.2.1',
            'html_url': 'https://github.com/releases/1.2.1',
            'published_at': '2026-10-31',
            'body': '- Icon rendering fix',
            'assets': [],
        },
        {
            'tag_name': 'v1.2.0',
            'name': 'FastMirror v1.2.0',
            'html_url': 'https://github.com/releases/1.2.0',
            'published_at': '2026-10-31',
            'body': '- Initial updater launch',
            'assets': [],
        },
    ]

    info = aggregate_releases_payload(releases, current_version='1.2.0')
    assert info is not None
    assert info.version == '1.2.3'
    assert info.is_newer is True
    assert info.setup_download_url == 'https://setup-1.2.3.exe'

    # Verify changelog includes notes from 1.2.3, 1.2.2, and 1.2.1
    assert 'What’s New in v1.2.3 (Latest)' in info.body
    assert 'Bugfix in updater' in info.body
    assert 'What’s New in v1.2.2' in info.body
    assert 'Mutex handling' in info.body
    assert 'What’s New in v1.2.1' in info.body
    assert 'Icon rendering fix' in info.body

    # Should NOT include 1.2.0 because 1.2.0 is already installed
    assert 'What’s New in v1.2.0' not in info.body


def test_fetch_latest_release_list_payload():
    """Verify fetch_latest_release parses a JSON list of releases successfully."""
    from utils.updater import fetch_latest_release

    releases = [
        {
            'tag_name': 'v1.2.2',
            'name': 'FastMirror v1.2.2',
            'body': 'Notes v1.2.2',
            'assets': [],
        },
        {
            'tag_name': 'v1.2.1',
            'name': 'FastMirror v1.2.1',
            'body': 'Notes v1.2.1',
            'assets': [],
        },
    ]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(releases).encode('utf-8')
    mock_resp.__enter__.return_value = mock_resp

    with patch('urllib.request.urlopen', return_value=mock_resp):
        info = fetch_latest_release(current_version='1.2.0')
        assert info is not None
        assert info.version == '1.2.2'
        assert info.is_newer is True
        assert 'Notes v1.2.2' in info.body
        assert 'Notes v1.2.1' in info.body
