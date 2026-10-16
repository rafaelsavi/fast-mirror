import os
import sys
import tempfile

src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../src'))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

_TEST_LOG_DIR = os.path.join(tempfile.gettempdir(), 'autobackup_pytest_logs')


def pytest_configure(config):
    """Ensure test mode and disable file logging flags are active before tests are loaded."""
    os.environ['AUTOMATIC_BACKUP_TESTING'] = '1'
    os.environ['AUTOMATIC_BACKUP_DISABLE_FILE_LOG'] = '1'
    os.environ['AUTOMATIC_BACKUP_LOG_DIR'] = _TEST_LOG_DIR
    os.makedirs(_TEST_LOG_DIR, exist_ok=True)
