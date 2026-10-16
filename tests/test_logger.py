import os
import sys

src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../src'))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from utils.constants import ROOT_DIR  # noqa: E402
from utils.logger import Logger, is_test_or_agent_mode, resolve_log_dir  # noqa: E402


def test_is_test_or_agent_mode_detection(monkeypatch):
    # Pytest is in sys.modules, so it should be True
    assert is_test_or_agent_mode() is True

    # Test explicit env flags
    monkeypatch.setenv('AUTOMATIC_BACKUP_TESTING', '1')
    assert is_test_or_agent_mode() is True

    monkeypatch.setenv('ANTIGRAVITY_AGENT', '1')
    assert is_test_or_agent_mode() is True


def test_logger_does_not_populate_production_logs_in_test_mode():
    prod_logs = os.path.join(ROOT_DIR, 'logs')
    resolved = resolve_log_dir()

    # In test mode, resolved directory must NEVER be the production logs directory
    assert resolved != prod_logs

    # Log directory should be isolated from ROOT_DIR
    from utils.logger import logger

    count_before = len(os.listdir(prod_logs)) if os.path.exists(prod_logs) else 0

    logger.info('Test isolation message - should not touch production logs')
    logger.debug('Debug message during test isolation')

    count_after = len(os.listdir(prod_logs)) if os.path.exists(prod_logs) else 0
    assert count_before == count_after


def test_logger_respects_custom_log_dir(tmp_path, monkeypatch):
    custom_dir = str(tmp_path / 'custom_logs')
    monkeypatch.setenv('AUTOMATIC_BACKUP_LOG_DIR', custom_dir)

    assert resolve_log_dir() == os.path.abspath(custom_dir)


def test_logger_delay_flag_prevents_empty_files(tmp_path):
    Logger.reset()
    test_log_dir = str(tmp_path / 'delay_test')

    inst = Logger(log_dir=test_log_dir, enable_file_logging=True)
    assert inst.save_path is not None

    # Before emitting any log record, file must NOT exist on disk due to delay=True
    assert not os.path.exists(inst.save_path)

    # After emitting a record, the file should be created
    inst.info('First message triggers file creation')
    assert os.path.exists(inst.save_path)

    Logger.reset()


def test_logger_reset_closes_file_handles(tmp_path):
    Logger.reset()
    test_log_dir = str(tmp_path / 'lock_test')

    inst = Logger(log_dir=test_log_dir, enable_file_logging=True)
    inst.info('Lock test message')
    save_path = inst.save_path
    assert save_path is not None and os.path.exists(save_path)

    # Reset must close the file handle so that on Windows os.remove succeeds without WinError 32
    Logger.reset()

    os.remove(save_path)
    assert not os.path.exists(save_path)
