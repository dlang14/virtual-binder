"""Rebuild the page data in the background after the collection changes.

Changes that arrive while a build is running fold into one more build, so a burst of adds costs two builds at most, and a
build never runs twice at once. `run` does the build and returns (ok, message, pending), where pending is how many rows are
waiting on a price.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional, Tuple


class Rebuilder:
    def __init__(self, run: Callable[[], Tuple[bool, str, int]]):
        self._run, self._lock = run, threading.Lock()
        self._running = self._again = False
        self._thread: Optional[threading.Thread] = None
        self._status = {"state": "idle", "ok": None, "message": "", "pending": 0, "builds": 0}

    def request(self) -> None:
        with self._lock:
            if self._running:
                self._again = True
                return
            self._running, self._status["state"] = True, "running"
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            try:
                ok, message, pending = self._run()
            except Exception as e:  # a failed build must not leave the state stuck on "running"
                ok, message, pending = False, f"build failed to start: {e}", 0
            with self._lock:
                self._status.update(ok=ok, message=message, pending=pending, builds=self._status["builds"] + 1)
                if not self._again:
                    self._running, self._status["state"] = False, "idle"
                    return
                self._again = False

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def wait(self) -> None:
        """Block until no build is running (for tests and shutdown)."""
        t = self._thread
        if t:
            t.join()
