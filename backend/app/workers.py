"""Background loops: poll the scanner inbox and run the hourly branch sync. One daemon thread, stoppable."""
import logging
import threading

from .config import settings
from .services import scanner, sync

log = logging.getLogger("livingdoc.workers")


class Workers:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="livingdoc-workers", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stop.is_set():
            try:
                scanner.process_scanner_inbox(settings.default_branch)
                sync.sync_if_due()
            except Exception:  # a failing tick must never kill the loop
                log.exception("worker tick failed")
            self._stop.wait(max(1, settings.scanner_poll_seconds))
