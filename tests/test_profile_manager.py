"""Unit tests for the ProfileManager and profile workflows."""

import json

import pytest

from utils.profile_manager import ProfileManager, sanitize_profile_name


def test_sanitize_profile_name():
    """Verify name sanitization replaces illegal Windows filename characters and trims."""
    assert sanitize_profile_name('  My Profile  ') == 'My Profile'
    assert sanitize_profile_name('NAS:Backup/Photos*') == 'NAS_Backup_Photos'
    assert sanitize_profile_name('Valid_123-Name') == 'Valid_123-Name'

    with pytest.raises(ValueError, match='empty'):
        sanitize_profile_name('   ')

    with pytest.raises(ValueError, match='empty'):
        sanitize_profile_name(':::***???')

    with pytest.raises(ValueError, match='relative path'):
        sanitize_profile_name('..')


def test_profile_manager_ensure_and_seed(tmp_path):
    """Verify ProfileManager creates profiles directory and seeds Default from config.json if present."""
    p_dir = tmp_path / 'profiles'
    cfg_file = tmp_path / 'config.json'

    # Seed config file
    sample_config = {
        'entry_paths': [['D:\\Photos', '\\\\nas\\photos']],
        'week_days': ['MON', 'FRI'],
        'toggle_auto_scroll': True,
    }
    with open(cfg_file, 'w', encoding='utf-8') as f:
        json.dump(sample_config, f)

    mgr = ProfileManager(profiles_dir=p_dir, config_path=cfg_file)
    assert p_dir.exists() is False

    profiles = mgr.list_profiles()
    assert profiles == ['Default']
    assert (p_dir / 'Default.json').exists()

    loaded = mgr.load_profile('Default')
    assert loaded['entry_paths'] == [['D:\\Photos', '\\\\nas\\photos']]
    assert loaded['week_days'] == ['MON', 'FRI']


def test_profile_manager_create_and_list(tmp_path):
    """Verify creating, listing, and ordering profiles."""
    p_dir = tmp_path / 'profiles'
    cfg_file = tmp_path / 'config.json'
    mgr = ProfileManager(profiles_dir=p_dir, config_path=cfg_file)

    mgr.create_profile('Work Backup', {'week_days': ['MON', 'TUE']})
    mgr.create_profile('Photos', {'week_days': ['SUN']})

    profiles = mgr.list_profiles()
    # Default is always first, followed by alphabetical
    assert profiles == ['Default', 'Photos', 'Work Backup']

    with pytest.raises(FileExistsError):
        mgr.create_profile('Work Backup')


def test_profile_manager_save_and_sync_global_config(tmp_path):
    """Verify saving a profile updates both the profile JSON and global config.json."""
    p_dir = tmp_path / 'profiles'
    cfg_file = tmp_path / 'config.json'
    mgr = ProfileManager(profiles_dir=p_dir, config_path=cfg_file)

    mgr.save_profile('NAS Sync', {'entry_times': ['12:00']}, sync_active_config=True)

    nas_file = p_dir / 'NAS Sync.json'
    assert nas_file.exists()
    with open(nas_file, encoding='utf-8') as f:
        nas_data = json.load(f)
    assert nas_data['entry_times'] == ['12:00']
    assert nas_data['active_profile'] == 'NAS Sync'

    # Global config file was synced
    assert cfg_file.exists()
    with open(cfg_file, encoding='utf-8') as f:
        cfg_data = json.load(f)
    assert cfg_data['entry_times'] == ['12:00']
    assert cfg_data['active_profile'] == 'NAS Sync'
    assert mgr.get_active_profile_name() == 'NAS Sync'


def test_profile_manager_clone_and_rename(tmp_path):
    """Verify cloning and renaming profiles."""
    p_dir = tmp_path / 'profiles'
    cfg_file = tmp_path / 'config.json'
    mgr = ProfileManager(profiles_dir=p_dir, config_path=cfg_file)

    mgr.save_profile('Original', {'entry_times': ['08:00']})
    mgr.clone_profile('Original', 'Clone')

    assert 'Clone' in mgr.list_profiles()
    clone_data = mgr.load_profile('Clone')
    assert clone_data['entry_times'] == ['08:00']

    # Rename Clone -> RenamedClone
    mgr.rename_profile('Clone', 'RenamedClone')
    assert 'Clone' not in mgr.list_profiles()
    assert 'RenamedClone' in mgr.list_profiles()

    # Cannot rename Default
    with pytest.raises(ValueError, match='Default'):
        mgr.rename_profile('Default', 'SomethingElse')


def test_profile_manager_delete(tmp_path):
    """Verify deleting profiles with safety backup and Default protection."""
    p_dir = tmp_path / 'profiles'
    cfg_file = tmp_path / 'config.json'
    mgr = ProfileManager(profiles_dir=p_dir, config_path=cfg_file)

    mgr.create_profile('Temporary', {'week_days': ['SAT']})
    assert 'Temporary' in mgr.list_profiles()

    assert mgr.delete_profile('Temporary') is True
    assert 'Temporary' not in mgr.list_profiles()
    assert mgr.list_profiles() == ['Default']

    # Backup file archived in .deleted/ subfolder
    deleted_backups = list((p_dir / '.deleted').glob('*.json'))
    assert len(deleted_backups) == 1
    assert 'Temporary_' in deleted_backups[0].name

    # Legacy stray *.deleted_*.json files are ignored in list_profiles and migrated
    stray = p_dir / 'Stray.deleted_9999.json'
    stray.write_text('{"entry_paths": []}', encoding='utf-8')
    assert 'Stray.deleted_9999' not in mgr.list_profiles()
    assert mgr.list_profiles() == ['Default']
    # ensure_profiles_dir migrated it
    assert (p_dir / '.deleted' / 'Stray.deleted_9999.json').exists()

    # Cannot delete Default
    with pytest.raises(ValueError, match='Default'):
        mgr.delete_profile('Default')


def test_profile_manager_import_and_export(tmp_path):
    """Verify importing from and exporting to arbitrary file locations."""
    p_dir = tmp_path / 'profiles'
    cfg_file = tmp_path / 'config.json'
    mgr = ProfileManager(profiles_dir=p_dir, config_path=cfg_file)

    external_export = tmp_path / 'outside' / 'custom_job.json'
    data_to_export = {'entry_paths': [['C:\\Src', 'D:\\Tgt']], 'week_days': ['WED']}

    mgr.export_profile(data_to_export, external_export)
    assert external_export.is_file()

    imported = mgr.import_profile(external_export)
    assert imported['entry_paths'] == [['C:\\Src', 'D:\\Tgt']]
    assert imported['week_days'] == ['WED']

    with pytest.raises(FileNotFoundError):
        mgr.import_profile(tmp_path / 'nonexistent.json')

    corrupt_file = tmp_path / 'corrupt.json'
    corrupt_file.write_text('{bad json', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        mgr.import_profile(corrupt_file)
