"""Minimal HTTP health server for Cloud Run worker containers.

Cloud Run requires every container to serve HTTP on $PORT (default 8080).
Worker processes (monitor, scheduler) have no web server, so they fail
Cloud Run health checks without this. Starts a daemon thread — dies when
the main process exits.
"""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_):
        pass  # silence access logs


def start_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    print(f"==> Starting health server on port {port}...")
    server = HTTPServer(("0.0.0.0", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"==> Health server running in background thread.")
