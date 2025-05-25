import sys
import threading
import traceback

from core.file import CustomException
from utils.logger import logger


class KillableThread(threading.Thread):
    """A subclass of threading.Thread, with a kill() method."""

    def __init__(self, *args, **keywords):
        threading.Thread.__init__(self, *args, **keywords)
        self.killed = False

    def start(self):
        """Start the thread."""
        self.__run_backup = self.run
        self.run = self.__run  # Force the Thread to install our trace.
        threading.Thread.start(self)

    def __run(self):
        """Hacked run function, which installs the trace."""
        self.exc = None
        try:
            sys.settrace(self.globaltrace)
            self.__run_backup()
            self.run = self.__run_backup
        except CustomException as e:
            logger.critical(f'Processing thread was stopped abruptly because of exception: {e}')
        except Exception:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            msg = ''.join(traceback.format_tb(exc_tb))
            logger.critical(f'Processing thread was stopped abruptly because of exception {exc_type}:\n{msg}')

    def globaltrace(self, frame, why, arg):
        if why == 'call':
            return self.localtrace
        else:
            return None

    def localtrace(self, frame, why, arg):
        if self.killed and why == 'line':
            global gui
            logger.warning('Background process was stopped')
            raise SystemExit()
        return self.localtrace

    def kill(self):
        self.killed = True

    def join(self, *args):
        threading.Thread.join(self, *args)
        if self.exc:
            raise self.exc
