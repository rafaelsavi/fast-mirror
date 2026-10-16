import sys
import threading
import traceback

from core.file import CustomException
from utils.logger import logger


class KillableThread(threading.Thread):
    """A subclass of threading.Thread with a kill() method using line trace."""

    def __init__(self, *args, **keywords):
        super().__init__(*args, **keywords)
        self.killed = False
        self.exc: BaseException | None = None

    def start(self):
        """Start the thread."""
        self.__run_backup = self.run
        self.run = self.__run  # Force the Thread to install our trace.
        super().start()

    def __run(self):
        """Hacked run function, which installs the trace."""
        self.exc = None
        try:
            sys.settrace(self.globaltrace)
            self.__run_backup()
            self.run = self.__run_backup
        except CustomException as e:
            self.exc = e
            logger.critical(f'Processing thread was stopped abruptly because of exception: {e}')
        except Exception as e:
            self.exc = e
            logger.critical(f'Processing thread was stopped abruptly because of exception:\n{traceback.format_exc()}')

    def globaltrace(self, frame, why, arg):
        if why == 'call':
            return self.localtrace
        else:
            return None

    def localtrace(self, frame, why, arg):
        if self.killed and why == 'line':
            logger.warning('Background process was stopped')
            raise SystemExit()
        return self.localtrace

    def kill(self):
        self.killed = True

    def join(self, *args):
        super().join(*args)
        if self.exc:
            raise self.exc
