from __future__ import annotations

from unittest.mock import MagicMock, patch

from gui.health_check import TargetHealth, probe_single_target
from gui.widgets import EntryPaths
from utils.utils import DirectoryPair, StorageRoot
from utils.volume import (
    DRIVE_FIXED,
    DRIVE_REMOVABLE,
    VolumeInfo,
    _format_serial,
    find_drive_by_serial,
    get_volume_info,
    split_path_root,
)


def test_split_path_root():
    # Local Windows drive paths
    drive, sub = split_path_root('C:\\data\\photos')
    assert drive == 'C:\\'
    assert sub == 'data\\photos'

    drive, sub = split_path_root('C:\\')
    assert drive == 'C:\\'
    assert sub == ''

    drive, sub = split_path_root('D:')
    assert drive == 'D:\\'
    assert sub == ''

    # UNC paths
    root, sub = split_path_root('\\\\backupserver\\share\\folder\\subfolder')
    assert root == '\\\\backupserver\\share'
    assert sub == 'folder\\subfolder'

    root, sub = split_path_root('\\\\backupserver\\share')
    assert root == '\\\\backupserver\\share'
    assert sub == ''

    root, sub = split_path_root('\\\\backupserver')
    assert root == '\\\\backupserver'
    assert sub == ''

    # Relative paths
    root, sub = split_path_root('some\\relative\\path')
    assert root == 'some\\relative\\path'
    assert sub == ''


def test_storage_root_dataclass():
    root = StorageRoot(
        name='Photos_Backup',
        path='E:\\Backup',
        serial='A4B1-9C32',
        label='PHOTOS_HDD',
    )
    d = root.to_dict()
    assert d == {
        'name': 'Photos_Backup',
        'path': 'E:\\Backup',
        'serial': 'A4B1-9C32',
        'label': 'PHOTOS_HDD',
    }

    reconstructed = StorageRoot.from_dict(d)
    assert reconstructed.name == 'Photos_Backup'
    assert reconstructed.path == 'E:\\Backup'
    assert reconstructed.serial == 'A4B1-9C32'
    assert reconstructed.label == 'PHOTOS_HDD'

    # Fallback default name
    minimal = StorageRoot.from_dict({'path': '\\\\nas\\share'}, default_name='NAS_Root')
    assert minimal.name == 'NAS_Root'
    assert minimal.serial is None
    assert minimal.label is None


def test_format_serial():
    assert _format_serial(0x12345678) == '1234-5678'
    assert _format_serial(0x00000000) == '0000-0000'
    assert _format_serial(0xA4B19C32) == 'A4B1-9C32'


def test_volume_info_properties():
    v1 = VolumeInfo(
        drive='E:',
        serial='A4B1-9C32',
        label='PHOTOS',
        fs_type='NTFS',
        drive_type=DRIVE_REMOVABLE,
    )
    assert v1.is_removable is True
    assert v1.display_tag == 'PHOTOS [A4B1-9C32]'

    v2 = VolumeInfo(
        drive='C:',
        serial='0011-2233',
        label='',
        fs_type='NTFS',
        drive_type=DRIVE_FIXED,
    )
    assert v2.is_removable is False
    assert v2.display_tag == '[0011-2233]'


def test_get_volume_info_unc_returns_none_zero_network_io():
    # Never query UNC shares
    assert get_volume_info('\\\\nas\\share\\folder') is None
    assert get_volume_info('\\\\nas\\share') is None
    assert get_volume_info('') is None
    assert get_volume_info('invalid_path') is None


def test_get_volume_info_live_system():
    # C: drive is universally available on Windows
    info = get_volume_info('C:\\')
    if info is not None:
        assert info.drive == 'C:'
        assert len(info.serial) == 9  # e.g. "XXXX-XXXX"
        assert '-' in info.serial
        assert info.drive_type in (DRIVE_FIXED, DRIVE_REMOVABLE)


def test_find_drive_by_serial():
    assert find_drive_by_serial('') is None
    assert find_drive_by_serial('   ') is None

    mock_drives = [
        VolumeInfo(drive='C:', serial='1111-2222', label='System', fs_type='NTFS', drive_type=DRIVE_FIXED),
        VolumeInfo(drive='F:', serial='A4B1-9C32', label='BACKUP_DRIVE', fs_type='exFAT', drive_type=DRIVE_REMOVABLE),
    ]

    with patch('utils.volume.get_all_drives', return_value=mock_drives):
        found = find_drive_by_serial('a4b1-9c32')  # Case-insensitive
        assert found is not None
        assert found.drive == 'F:'
        assert found.label == 'BACKUP_DRIVE'

        assert find_drive_by_serial('FFFF-FFFF') is None


def test_probe_single_target_relocated(tmp_path):
    target = 'E:\\Backup\\Data'

    relocated_drive = VolumeInfo(
        drive='G:',
        serial='A4B1-9C32',
        label='MY_EXT_DRIVE',
        fs_type='NTFS',
        drive_type=DRIVE_REMOVABLE,
    )

    # Simulate: drive E: is not present (or not matching), but found on G:
    with (
        patch('gui.health_check.get_volume_info', return_value=None),
        patch('gui.health_check.find_drive_by_serial', return_value=relocated_drive),
        patch('os.path.exists', return_value=True),
        patch('shutil.disk_usage', return_value=MagicMock(free=50 * 1024**3, total=100 * 1024**3)),
    ):
        result: TargetHealth = probe_single_target(target, expected_serial='A4B1-9C32')
        assert result.is_online is True
        assert result.path == target  # Original configured path
        assert result.resolved_path == 'G:\\Backup\\Data'
        assert result.warning is not None
        assert 'Relocated: detected on G:' in result.warning


def test_probe_single_target_wrong_drive():
    target = 'E:\\Backup\\Data'

    wrong_drive = VolumeInfo(
        drive='E:',
        serial='9999-8888',
        label='FAMILY_PHOTOS',
        fs_type='NTFS',
        drive_type=DRIVE_REMOVABLE,
    )

    # Simulate: E: has a completely different drive connected, and expected serial is not anywhere
    with (
        patch('gui.health_check.get_volume_info', return_value=wrong_drive),
        patch('gui.health_check.find_drive_by_serial', return_value=None),
    ):
        result: TargetHealth = probe_single_target(target, expected_serial='A4B1-9C32')
        assert result.is_online is False
        assert result.error is not None
        assert "Wrong drive on E:: found 'FAMILY_PHOTOS', expected [A4B1-9C32]" in result.error


def test_probe_single_target_disconnected():
    target = 'E:\\Backup\\Data'

    with (
        patch('gui.health_check.get_volume_info', return_value=None),
        patch('gui.health_check.find_drive_by_serial', return_value=None),
    ):
        result: TargetHealth = probe_single_target(target, expected_serial='A4B1-9C32')
        assert result.is_online is False
        assert result.error is not None
        assert 'Target drive is disconnected' in result.error


def test_entry_paths_enrichment_and_relocation(tmp_path):
    src_dir = tmp_path / 'SourceFolder'
    src_dir.mkdir()

    roots = {
        'BACKUP_ROOT': StorageRoot(
            name='BACKUP_ROOT',
            path='E:\\Backup',
            serial='A4B1-9C32',
            label='EXT_DRIVE',
        )
    }

    entry = EntryPaths()
    entry.storage_roots = roots
    entry.set([(str(src_dir), 'E:\\Backup\\SubFolder')])

    # Relocate E: -> H:
    relocated = VolumeInfo(
        drive='H:',
        serial='A4B1-9C32',
        label='EXT_DRIVE',
        fs_type='NTFS',
        drive_type=DRIVE_REMOVABLE,
    )

    with (
        patch('gui.widgets.get_volume_info', return_value=None),
        patch('gui.widgets.find_drive_by_serial', return_value=relocated),
    ):
        pairs: list[DirectoryPair] = entry.get_as_dir_pairs()
        assert len(pairs) == 1
        pair = pairs[0]
        assert pair.source == str(src_dir)
        # Resolved target reflects the relocated drive H:
        assert pair.target == 'H:\\Backup\\SubFolder'
        assert pair.target_root_name == 'BACKUP_ROOT'
        assert pair.target_subpath == 'SubFolder'
        assert pair.target_serial == 'A4B1-9C32'


def test_profile_manager_strips_legacy_storage_roots(tmp_path):
    import json

    from utils.profile_manager import ProfileManager

    pm = ProfileManager(profiles_dir=tmp_path / 'profiles', config_path=tmp_path / 'config.json')
    profile_path = pm.get_profile_path('TestProfile')
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(
            {
                'storage_roots': {'OldRoot': {'name': 'OldRoot', 'path': 'E:\\'}},
                'entry_paths': [['C:\\SomeSource', 'E:\\Backup\\Docs']],
            }
        ),
        encoding='utf-8',
    )

    loaded = pm.load_profile('TestProfile')
    assert 'storage_roots' not in loaded
    assert loaded['entry_paths'] == [['C:\\SomeSource', 'E:\\Backup\\Docs']]


def test_endpoint_root_extraction_and_prefix_replacement():
    from utils.volume import extract_endpoint_root, matches_root_prefix, replace_root_prefix

    # Drives extract to X:\
    assert extract_endpoint_root('D:\\Folder\\Sub') == 'D:\\'
    assert extract_endpoint_root('E:\\') == 'E:\\'
    assert extract_endpoint_root('F:') == 'F:\\'

    # Multiple shares on the same NAS server group cleanly under \\server
    assert extract_endpoint_root('\\\\10.0.0.50\\ShareA\\Subfolder') == '\\\\10.0.0.50'
    assert extract_endpoint_root('\\\\10.0.0.50\\ShareB') == '\\\\10.0.0.50'
    assert extract_endpoint_root('\\\\backup-nas\\Photos') == '\\\\backup-nas'

    # Boundary-safe prefix matching (avoids D:\Photos vs D:\Photos_Archive collisions)
    assert matches_root_prefix('D:\\Photos\\2025', 'D:\\Photos') is True
    assert matches_root_prefix('D:\\Photos', 'D:\\Photos') is True
    assert matches_root_prefix('D:\\Photos_Archive\\2025', 'D:\\Photos') is False
    assert matches_root_prefix('E:\\Backup\\Photos', 'E:\\') is True
    assert matches_root_prefix('\\\\10.0.0.50\\ShareA\\Docs', '\\\\10.0.0.50') is True

    # Prefix replacement without double backslashes
    assert replace_root_prefix('E:\\Backup\\Photos', 'E:\\', 'F:\\') == 'F:\\Backup\\Photos'
    assert replace_root_prefix('E:\\Backup\\Photos', 'E:\\Backup', 'F:\\Archive') == 'F:\\Archive\\Photos'
    assert replace_root_prefix('D:\\Photos_Archive\\2025', 'D:\\Photos', 'E:\\Photos') == 'D:\\Photos_Archive\\2025'
    assert (
        replace_root_prefix('\\\\10.0.0.50\\ShareA\\Docs', '\\\\10.0.0.50', '\\\\10.0.0.99')
        == '\\\\10.0.0.99\\ShareA\\Docs'
    )


def test_entry_paths_specificity_and_ensure_roots(tmp_path):
    src_dir = tmp_path / 'SourceFolder'
    src_dir.mkdir()

    # Deliberately put generic Drive_E after nested Work_Root to verify specificity sorting
    roots = {
        'Work_Root': StorageRoot(name='Work_Root', path='E:\\Work', serial='WORK-2222', label='WORK'),
        'Drive_E': StorageRoot(name='Drive_E', path='E:\\', serial='GEN-1111', label='GENERAL'),
    }

    entry = EntryPaths()
    entry.storage_roots = roots
    entry.set([(str(src_dir), 'E:\\Work\\ProjectA')])

    pairs = entry.get_as_dir_pairs(resolve_relocation=False)
    assert len(pairs) == 1
    assert pairs[0].target_root_name == 'Work_Root'
    assert pairs[0].target_subpath == 'ProjectA'
    assert pairs[0].target_serial == 'WORK-2222'
    assert pairs[0].target == 'E:\\Work\\ProjectA'

    # Test ensure_roots_for_pairs auto-discovers new share/drive
    entry.set([(str(src_dir), '\\\\nas\\vault\\ProjectA')])
    entry.ensure_roots_for_pairs()
    assert 'nas_vault' in entry.storage_roots
    assert entry.storage_roots['nas_vault'].path == '\\\\nas\\vault'
