"""Background due-request dispatcher for FastAPI/runtime workers."""

from __future__ import annotations

import logging
import threading
import time

from .request_engine import RequestEngine


LOGGER = logging.getLogger(__name__)


class DueRequestWorker:
    """Periodically dispatch requests whose quiet window has elapsed."""

    def __init__(self, engine: RequestEngine, interval_seconds: float = 1.0) -> None:
        self.engine = engine
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="flexar-due-request-worker", daemon=True)
        self._thread.start()
        LOGGER.info("AMS_COMPONENT=WORKER Background request worker started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        LOGGER.info("AMS_COMPONENT=WORKER Background request worker stopped")

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.engine.update_time_states()
                processed = self.engine.process_due_dispatches()
                if processed:
                    LOGGER.info("AMS_COMPONENT=WORKER Processed %s due simulated request(s)", processed)
            except Exception:
                LOGGER.exception("Due-request worker tick failed")
