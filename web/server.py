#!/usr/bin/env python3
"""
Stdlib-only HTTP server for the Heimdex caption-comparison viewer.

This is what Replit serves. It imports NOTHING outside the Python standard
library (no boto3 / anthropic / Pillow), so it runs with zero pip installs.

Routes:
    GET /              -> web/index.html
    GET /index.html    -> web/index.html
    GET /api/comparison-> data/comparison.live.json if present, else
                          data/comparison.sample.json

Media (videos, keyframes) are loaded by the browser directly from the presigned
S3 URLs baked into the comparison JSON — the server never touches AWS.

Binds 0.0.0.0; the port comes from --port (default: $PORT or 5000).
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"

INDEX_HTML = ROOT / "index.html"
LIVE_JSON = DATA_DIR / "comparison.live.json"
SAMPLE_JSON = DATA_DIR / "comparison.sample.json"


def comparison_file() -> Path:
    """Prefer the live (uploaded, presigned) file; fall back to the committed sample."""
    return LIVE_JSON if LIVE_JSON.exists() else SAMPLE_JSON


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter, prefixed logs
        print(f"  {self.address_string()} {fmt % args}")

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_text(self, text: str, content_type: str, status: int = 200):
        self._send_bytes(text.encode("utf-8"), content_type, status)

    def _handle(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            if not INDEX_HTML.exists():
                self._send_text("index.html missing", "text/plain; charset=utf-8", 500)
                return
            self._send_bytes(INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            return

        if path == "/api/comparison":
            cf = comparison_file()
            if not cf.exists():
                self._send_text(
                    json.dumps({"error": f"no comparison file ({cf.name})"}),
                    "application/json; charset=utf-8",
                    404,
                )
                return
            # Pass through verbatim (already valid JSON).
            self._send_bytes(cf.read_bytes(), "application/json; charset=utf-8")
            return

        if path == "/api/health":
            self._send_text(
                json.dumps({"ok": True, "comparison": comparison_file().name}),
                "application/json; charset=utf-8",
            )
            return

        self._send_text("Not found", "text/plain; charset=utf-8", 404)

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")))
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    cf = comparison_file()
    print("Heimdex caption viewer")
    print(f"  comparison : {cf}  ({'LIVE' if cf == LIVE_JSON else 'sample'})")
    print(f"  listening  : http://{args.host}:{args.port}")
    print()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
