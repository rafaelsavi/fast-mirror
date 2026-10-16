import logging
import os
import queue
import sys
import tempfile
from datetime import datetime
from logging import LogRecord
from typing import Optional

from utils.constants import ROOT_DIR


def is_test_or_agent_mode() -> bool:
    """Return True if running in an automated test suite, CI, or agent execution."""
    if os.environ.get('AUTOMATIC_BACKUP_TESTING', '').lower() in ('1', 'true', 'yes'):
        return True
    if os.environ.get('AUTOMATIC_BACKUP_DISABLE_FILE_LOG', '').lower() in ('1', 'true', 'yes'):
        return True
    if os.environ.get('ANTIGRAVITY_AGENT') == '1':
        return True
    return bool('pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ)


def resolve_log_dir() -> str:
    """Resolve the directory where logs and reports should be stored."""
    custom_dir = os.environ.get('AUTOMATIC_BACKUP_LOG_DIR')
    if custom_dir:
        return os.path.abspath(custom_dir)

    if is_test_or_agent_mode():
        return os.path.join(tempfile.gettempdir(), 'automatic_backup_test_logs')

    return os.path.join(ROOT_DIR, 'logs')


log_dir = resolve_log_dir()


class QueueHandler(logging.Handler):
    """Class to send logging records to a queue. It can be used from different threads"""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: LogRecord):
        self.log_queue.put(record)


class Logger:
    _instance: Optional['Logger'] = None  # Singleton instance
    _initialized = False

    def __new__(cls, log_level='DEBUG', log_dir: str | None = None, enable_file_logging: bool | None = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        log_level='DEBUG',
        log_dir: str | None = None,
        enable_file_logging: bool | None = None,
    ):
        if Logger._initialized:
            return

        # Resolve log directory
        self.log_dir = os.path.abspath(log_dir) if log_dir else resolve_log_dir()

        # Determine file logging status
        if enable_file_logging is not None:
            self.enable_file_logging = enable_file_logging
        elif os.environ.get('AUTOMATIC_BACKUP_ENABLE_FILE_LOG', '').lower() in ('1', 'true', 'yes'):
            self.enable_file_logging = True
        elif os.environ.get('AUTOMATIC_BACKUP_DISABLE_FILE_LOG', '').lower() in ('1', 'true', 'yes'):
            self.enable_file_logging = False
        else:
            self.enable_file_logging = not is_test_or_agent_mode()

        self.save_path: str | None = None
        self.file_handler: logging.FileHandler | None = None

        # Initialize logger
        self.logger = logging.getLogger('self.logger')
        self.logger.setLevel(log_level)
        self.logger.propagate = False

        # Prevent adding multiple handlers if re-instantiated
        if not self.logger.handlers:
            if self.enable_file_logging:
                os.makedirs(self.log_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                self.save_path = os.path.join(self.log_dir, 'log_' + timestamp + '.txt')
                # Create a file handler with delay=True to prevent creating 0-byte files before emission
                self.file_handler = logging.FileHandler(self.save_path, encoding='utf-8', delay=True)
                file_formatter = logging.Formatter('%(asctime)s: %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S')
                self.file_handler.setFormatter(file_formatter)
                self.logger.addHandler(self.file_handler)

            # Create a logging handler using a queue
            self.log_queue: queue.Queue = queue.Queue()
            self.queue_handler = QueueHandler(self.log_queue)
            gui_formatter = logging.Formatter('%(asctime)s: %(message)s', '%Y-%m-%d %H:%M:%S')
            self.queue_handler.setFormatter(gui_formatter)
            self.logger.addHandler(self.queue_handler)

        Logger._initialized = True

    def close(self):
        """Close handlers and release file locks, especially critical on Windows."""
        if hasattr(self, 'logger'):
            for handler in list(self.logger.handlers):
                handler.close()
                self.logger.removeHandler(handler)
        self.file_handler = None

    @classmethod
    def reset(cls):
        """Reset the singleton instance and close all handlers."""
        if cls._instance is not None:
            cls._instance.close()
            cls._instance = None
        cls._initialized = False

    def debug(self, x):
        self.logger.debug(x)

    def info(self, x):
        self.logger.info(x)

    def warning(self, x):
        self.logger.warning(x)

    def error(self, x):
        self.logger.error(x)

    def critical(self, x):
        self.logger.critical(x)


if 'logger' not in locals():
    logger = Logger()
