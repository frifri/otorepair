"""
Minimal "dev server" using only stdlib (no extra deps).

How to run (from this directory):
    otorepair "python server.py"

In another terminal:
    curl -s http://127.0.0.1:8765/

The handler raises on GET; Python logs a traceback to stderr while the process
keeps running — this hits the *live* path (regex → Haiku triage → fix).

Note: this process does not reload Python modules on disk. After a successful
fix, either stop and re-run otorepair, or use a real framework with --reload
for a "fixes itself while running" demo.

Stops automatically after EXAMPLE_SERVE_SECONDS (default 120) so you have time
to run curl in another terminal. After a fix, use EXAMPLE_SERVE_SECONDS=10 (or
similar) so otorepair exits quickly once the server is healthy.
"""

import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

SERVE_SECONDS = float(os.environ.get("EXAMPLE_SERVE_SECONDS", "120"))

LISTEN = ("127.0.0.1", 8765)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        raise RuntimeError(
            "intentional bug: replace this with a normal 200 response "
            "(e.g. self.send_response(200); self.end_headers(); self.wfile.write(b'ok'))"
        )

    def log_message(self, format: str, *args: object) -> None:
        pass


def _run_timed_server(httpd: HTTPServer) -> None:
    httpd.timeout = 0.5
    deadline = time.monotonic() + SERVE_SECONDS
    while time.monotonic() < deadline:
        httpd.handle_request()
    httpd.server_close()


if __name__ == "__main__":
    host, port = LISTEN
    print(f"serving on http://{host}:{port}/ (GET / to trigger the bug)")
    if SERVE_SECONDS > 0:
        print(f"(stopping after {SERVE_SECONDS:g}s — set EXAMPLE_SERVE_SECONDS to adjust)")
    httpd = HTTPServer(LISTEN, Handler)
    _run_timed_server(httpd)
    print("example server finished")
