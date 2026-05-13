"""Heartbeat thread fires periodic POSTs; stops cleanly on signal."""

from __future__ import annotations

import http.server
import socketserver
import threading
import time
from unittest.mock import patch

from docling_extractor.heartbeat import HeartbeatPoster


class _CountingHandler(http.server.BaseHTTPRequestHandler):
    hits: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.hits.append(
            {
                "path": self.path,
                "token": self.headers.get("X-Heartbeat-Token"),
                "body": body,
            }
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *args, **kwargs):  # silence
        pass


def _serve() -> socketserver.TCPServer:
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _CountingHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def test_heartbeat_thread_posts_at_interval():
    _CountingHandler.hits = []
    httpd = _serve()
    port = httpd.server_address[1]
    try:
        poster = HeartbeatPoster(
            url=f"http://127.0.0.1:{port}/internal/extraction/abc/heartbeat",
            token="t-1",
            interval_seconds=0.2,
        )
        poster.start()
        time.sleep(0.7)
        poster.stop()
    finally:
        httpd.shutdown()

    assert len(_CountingHandler.hits) >= 2
    assert all(h["token"] == "t-1" for h in _CountingHandler.hits)
    assert all(
        h["path"] == "/internal/extraction/abc/heartbeat"
        for h in _CountingHandler.hits
    )


def test_heartbeat_thread_swallows_network_errors():
    poster = HeartbeatPoster(
        url="http://127.0.0.1:1/no-server",  # nothing listening
        token="t-2",
        interval_seconds=0.1,
    )
    poster.start()
    time.sleep(0.3)
    poster.stop()  # must not raise
