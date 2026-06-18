#!/usr/bin/env python3
"""
Web server for the Heimdex caption viewer.

STATIC serving (the page, the compare JSON, the try-it catalog) is STDLIB-ONLY —
it starts and serves with zero pip installs. The interactive
``POST /api/caption`` endpoint LAZILY imports ``anthropic`` only when a caption is
requested, so a Repl that hasn't installed it (or has no API key) still serves the
gallery; the button just returns a clear "not configured" error.

Routes:
    GET  /                -> web/index.html
    GET  /index.html      -> web/index.html
    GET  /api/comparison  -> data/comparison.live.json else comparison.sample.json
    GET  /api/catalog     -> data/catalog.live.json else catalog.sample.json
    GET  /api/health      -> status (incl. whether live captioning is configured)
    POST /api/caption     -> generate the 3 temporal references for {scene_id}

Security: the ANTHROPIC_API_KEY lives only on the server (a Replit Secret); it is
never sent to the browser. The browser only ever sees presigned media URLs.

Cost/abuse guard (public demo, your key): results are CACHED per scene_id (a scene
bills at most once, ever), requests are rate-limited per IP (token bucket) with a
global daily cap, and frames-per-request + max_tokens are bounded.

Binds 0.0.0.0; port from --port (default $PORT or 5000).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
sys.path.insert(0, str(PROJECT_ROOT))  # so we can import heimdex_ptp lazily

INDEX_HTML = ROOT / "index.html"
LIVE_JSON = DATA_DIR / "comparison.live.json"
SAMPLE_JSON = DATA_DIR / "comparison.sample.json"
CATALOG_LIVE = DATA_DIR / "catalog.live.json"
CATALOG_SAMPLE = DATA_DIR / "catalog.sample.json"
CACHE_FILE = DATA_DIR / "caption_cache.json"

# --- caps / limits (env-tunable) ---
MAX_FRAMES = int(os.environ.get("CAPTION_MAX_FRAMES", "12"))
MAX_TOKENS = int(os.environ.get("CAPTION_MAX_TOKENS", "1500"))
RATE_BURST = int(os.environ.get("CAPTION_RATE_BURST", "4"))        # tokens per IP
RATE_REFILL_SEC = float(os.environ.get("CAPTION_RATE_REFILL_SEC", "20"))  # 1 token / N sec
GLOBAL_DAILY_CAP = int(os.environ.get("CAPTION_GLOBAL_DAILY_CAP", "150"))
FETCH_TIMEOUT = 20


def _load_dotenv_no_override(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def comparison_file() -> Path:
    return LIVE_JSON if LIVE_JSON.exists() else SAMPLE_JSON


def catalog_file() -> Path:
    return CATALOG_LIVE if CATALOG_LIVE.exists() else CATALOG_SAMPLE


class RateLimiter:
    """Per-IP token bucket + a global daily counter (anti-burst / backstop)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[str, list] = {}  # ip -> [tokens, last_ts]
        self._global_count = 0
        self._global_day = None

    def allow(self, ip: str) -> tuple[bool, str]:
        now = time.time()
        with self._lock:
            day = int(now // 86400)
            if day != self._global_day:
                self._global_day, self._global_count = day, 0
            if self._global_count >= GLOBAL_DAILY_CAP:
                return False, "daily cap reached"
            tokens, last = self._buckets.get(ip, [float(RATE_BURST), now])
            tokens = min(RATE_BURST, tokens + (now - last) / RATE_REFILL_SEC)
            if tokens < 1.0:
                self._buckets[ip] = [tokens, now]
                return False, "rate limited"
            tokens -= 1.0
            self._buckets[ip] = [tokens, now]
            self._global_count += 1
            return True, ""


class Cache:
    """Persistent per-scene caption cache (a scene bills at most once)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        try:
            self._data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            self._data = {}

    def get(self, key: str):
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
            except Exception:
                pass


_limiter = RateLimiter()
_cache = Cache(CACHE_FILE)


def _catalog_index() -> dict[str, dict]:
    cf = catalog_file()
    if not cf.exists():
        return {}
    try:
        return {e["scene_id"]: e for e in json.loads(cf.read_text(encoding="utf-8"))}
    except Exception:
        return {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _client_ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For")
        return (fwd.split(",")[0].strip() if fwd else self.client_address[0])

    # ---- GET ----
    def _handle_get(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            if INDEX_HTML.exists():
                self._send(INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(b"index.html missing", "text/plain; charset=utf-8", 500)
        elif path == "/api/comparison":
            cf = comparison_file()
            if cf.exists():
                self._send(cf.read_bytes(), "application/json; charset=utf-8")
            else:
                self._json({"error": "no comparison file"}, 404)
        elif path == "/api/catalog":
            cf = catalog_file()
            if cf.exists():
                self._send(cf.read_bytes(), "application/json; charset=utf-8")
            else:
                self._json([], 200)
        elif path == "/api/health":
            self._json({
                "ok": True,
                "comparison": comparison_file().name,
                "catalog": catalog_file().name if catalog_file().exists() else None,
                "captioning_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
            })
        else:
            self._send(b"Not found", "text/plain; charset=utf-8", 404)

    def do_GET(self):
        self._handle_get()

    def do_HEAD(self):
        self._handle_get()

    # ---- POST /api/caption ----
    def do_POST(self):
        if urlparse(self.path).path != "/api/caption":
            self._send(b"Not found", "text/plain; charset=utf-8", 404)
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._json({"error": "bad request body"}, 400)
            return

        scene_id = (body or {}).get("scene_id")
        if not scene_id:
            self._json({"error": "scene_id required"}, 400)
            return

        cached = _cache.get(scene_id)
        if cached is not None:
            self._json({"scene_id": scene_id, "claude_references": cached, "cached": True})
            return

        if not os.environ.get("ANTHROPIC_API_KEY"):
            self._json({"error": "live captioning is not configured on this server"}, 503)
            return

        ok, why = _limiter.allow(self._client_ip())
        if not ok:
            self._json({"error": why}, 429)
            return

        entry = _catalog_index().get(scene_id)
        if not entry or not entry.get("frames"):
            self._json({"error": f"unknown scene or no frames: {scene_id}"}, 404)
            return

        # fetch the presigned frame images (capped) and base64 via the helper
        try:
            images = []
            for url in entry["frames"][:MAX_FRAMES]:
                with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:
                    images.append(r.read())
        except Exception as e:
            self._json({"error": f"could not fetch frames: {e}"}, 502)
            return

        try:
            from heimdex_ptp.caption_api import caption_from_images
            result = caption_from_images(scene_id, images, max_tokens=MAX_TOKENS)
        except Exception as e:
            self._json({"error": f"generation failed: {type(e).__name__}: {e}"}, 502)
            return

        _cache.put(scene_id, result["claude_references"])
        self._json({**result, "cached": False})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")))
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    # let the key reach the endpoint locally; on Replit the Secret is already in env
    _load_dotenv_no_override(PROJECT_ROOT / ".env")

    print("Heimdex caption viewer")
    print(f"  comparison : {comparison_file().name}")
    print(f"  catalog    : {catalog_file().name if catalog_file().exists() else '(none)'}")
    print(f"  captioning : {'ON' if os.environ.get('ANTHROPIC_API_KEY') else 'OFF (no ANTHROPIC_API_KEY)'}")
    print(f"  listening  : http://{args.host}:{args.port}\n")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
