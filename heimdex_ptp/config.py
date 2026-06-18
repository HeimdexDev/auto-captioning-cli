"""Shared constants and small dependency-free helpers used across stages."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 2000

KEYFRAMES_BUCKET = "heimdex-video-archive-keyframes"
RAW_BUCKET = "heimdex-video-archive-raw"

# SigV4 presigned-URL maximum lifetime (7 days).
MAX_EXPIRES = 7 * 24 * 3600  # 604800

# Default read-only input locations (never modified by the pipeline).
DEFAULT_KEYFRAMES_DIR = Path.home() / "Downloads" / "caption_scenes" / "images"
DEFAULT_SCENES_JSONL = Path.home() / "Downloads" / "caption_scenes" / "scenes.jsonl"
DEFAULT_SKILL_DIR = Path(__file__).resolve().parent.parent / "skill"

IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


# ---------------------------------------------------------------------------
# .env loading — never override values already in the real environment, so
# host Secrets (Replit) and exported shell vars always win.
# ---------------------------------------------------------------------------

def load_dotenv(path: Path) -> None:
    """Parse simple ``KEY=VALUE`` lines into ``os.environ`` without overriding.

    Handles an optional ``export `` prefix, surrounding quotes, and ``#``
    comments. A key already present in the environment is left untouched.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_env_files(*candidates: Path) -> None:
    """Load several candidate .env paths in order (first value wins)."""
    for c in candidates:
        load_dotenv(c)


# ---------------------------------------------------------------------------
# S3 URL parsing — always derive keys from the URL bytes in scenes.jsonl so we
# never retype Korean channel names (the NFC/NFD trap).
# ---------------------------------------------------------------------------

def url_to_bucket_key(url: str) -> tuple[str, str]:
    """Parse an ``https://<bucket>.s3[.<region>].amazonaws.com/<key>`` URL.

    Returns ``(bucket, key)`` with the key bytes preserved (percent-decoded).
    """
    p = urlparse(url)
    bucket = p.netloc.split(".s3")[0]
    key = unquote(p.path).lstrip("/")
    return bucket, key


def s3key_from_url(url: str) -> str:
    """Return just the S3 key for a keyframe/media URL."""
    return unquote(urlparse(url).path).lstrip("/")
