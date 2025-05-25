import logging
import os
import queue
from datetime import datetime

from utils.constants import ROOT_DIR

log_dir = os.path.join(ROOT_DIR, 'logs')


class QueueHandler(logging.Handler):
    """Class to send logging records to a queue. It can be used from different threads"""

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(record)


class Logger:
    def __init__(self, log_level='DEBUG'):
        # Build save path
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        save_path = os.path.join(self.log_dir, 'log_' + timestamp + '.txt')

        # Initialize logger
        self.logger = logging.getLogger('self.logger')
        self.logger.setLevel(log_level)

        # Create a file handler
        file_handler = logging.FileHandler(save_path)
        file_formatter = logging.Formatter('%(asctime)s: %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

        # Create a logging handler using a queue
        self.log_queue = queue.Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        gui_formatter = logging.Formatter('%(asctime)s: %(message)s', '%Y-%m-%d %H:%M:%S')
        self.queue_handler.setFormatter(gui_formatter)
        self.logger.addHandler(self.queue_handler)

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
