"""Daemon-thread heartbeat poster for the extractor subprocess.

Posts an empty-ish JSON body to a URL on a fixed interval, including
a token header. All network errors are swallowed — the backend's
watchdog is the source of truth for liveness; if a POST fails, the
next POST will succeed or the watchdog will time us out. No backoff,
no retries, no metrics. Keep this tiny."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


class HeartbeatPoster:
    def __init__(self, url: str, token: str, interval_seconds: float) -> None:
        self._url = url
        self._token = token
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        # First beat goes immediately so the watchdog sees us within
        # one poll interval instead of two.
        self._post_once()
        while not self._stop.wait(self._interval):
            self._post_once()

    def _post_once(self) -> None:
        body = json.dumps(
            {"ts": datetime.now(timezone.utc).isoformat()}
        ).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Heartbeat-Token": self._token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5):
                pass
        except (urllib.error.URLError, OSError, TimeoutError):
            return  # backend is unreachable or slow — try again next tick
