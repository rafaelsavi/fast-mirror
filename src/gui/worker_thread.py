import threading
import traceback

from core.file import CustomException
from utils.logger import logger


class WorkerThread(threading.Thread):
    """Background worker thread supporting cooperative cancellation and exception capture."""

    def __init__(
        self,
        *args,
        cancel_event: threading.Event | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.cancel_event: threading.Event = cancel_event if cancel_event is not None else threading.Event()
        self.exc: BaseException | None = None

    def cancel(self):
        """Signal cooperative cancellation to the running thread."""
        self.cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self.cancel_event.is_set()

    def run(self):
        """Execute the thread target with exception capture and logging."""
        self.exc = None
        try:
            super().run()
        except CustomException as e:
            self.exc = e
            logger.critical(f'Processing thread was stopped abruptly because of exception: {e}')
        except Exception as e:
            self.exc = e
            logger.critical(f'Processing thread was stopped abruptly because of exception:\n{traceback.format_exc()}')

    def join(self, timeout: float | None = None):
        """Wait until thread terminates; re-raises any captured exception."""
        super().join(timeout=timeout)
        if self.exc:
            raise self.exc
