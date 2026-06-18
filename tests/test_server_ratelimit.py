"""RateLimiter: per-IP token bucket burst + denial (loads web/server.py by path)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("_srv", ROOT / "web" / "server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)


def test_burst_then_deny():
    rl = srv.RateLimiter()
    burst = srv.RATE_BURST
    for _ in range(burst):
        ok, _why = rl.allow("1.2.3.4")
        assert ok
    ok, why = rl.allow("1.2.3.4")  # one past burst
    assert not ok and why == "rate limited"


def test_separate_ips_independent():
    rl = srv.RateLimiter()
    assert rl.allow("10.0.0.1")[0]
    assert rl.allow("10.0.0.2")[0]


def test_static_serving_imports_are_stdlib_only():
    # importing the server must not pull anthropic/boto3 (zero-install static serve)
    import sys
    assert "anthropic" not in sys.modules
    assert "boto3" not in sys.modules
