"""
Tiny stdlib HTTP server (like a stripped-down runserver).

**Broken state (for otorepair):** ``PORT`` must be set in the environment.
Running ``python app.py`` without ``PORT`` raises ``KeyError`` on startup →
crash path (no Haiku triage).

How to run:
    otorepair "python examples/crash_on_start/app.py"

Sanity check without otorepair:
    PORT=8765 python examples/crash_on_start/app.py

After a good fix you typically get ``os.environ.get("PORT", "8765")`` plus this
timed serve loop so the child exits and otorepair does not block forever.

    EXAMPLE_SERVE_SECONDS=30   # longer window for manual curl
    EXAMPLE_SERVE_SECONDS=0    # exit right after bind (no requests)
"""

import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ["PORT"])
SERVE_SECONDS = float(os.environ.get("EXAMPLE_SERVE_SECONDS", "5"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:
        pass


def _run_timed_server(httpd: HTTPServer) -> None:
    """Serve until wall-clock limit; periodic timeout wakes idle servers."""
    httpd.timeout = 0.5
    deadline = time.monotonic() + SERVE_SECONDS
    while time.monotonic() < deadline:
        httpd.handle_request()
    httpd.server_close()


if __name__ == "__main__":
    httpd = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"listening on http://127.0.0.1:{PORT}/")
    if SERVE_SECONDS > 0:
        print(f"(stopping after {SERVE_SECONDS:g}s — set EXAMPLE_SERVE_SECONDS to adjust)")
    _run_timed_server(httpd)
    print("example server finished")
