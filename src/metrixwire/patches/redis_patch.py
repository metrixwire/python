"""redis-py auto-instrumentation (cache spans).

Patches ``redis.client.Redis.execute_command`` so every Redis operation becomes
a ``custom`` span tagged ``meta.kind='cache'`` for the slow_cache_op detector.
For read ops (GET/HGET/...), ``meta.hit`` records whether the key existed.
"""

from __future__ import annotations

import time
from typing import Any

_PATCHED = False

# Read ops where a ``None``/empty reply means a cache miss.
_READ_OPS = {"GET", "MGET", "HGET", "HMGET", "GETRANGE", "GETSET", "HGETALL"}


def install(client: Any) -> None:
    global _PATCHED
    if _PATCHED:
        return
    try:
        from redis.client import Redis
    except Exception:
        return

    if getattr(Redis.execute_command, "_metrixwire", False):
        _PATCHED = True
        return

    original = Redis.execute_command

    def execute_command(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        start = time.monotonic()
        op = ""
        try:
            op = str(args[0]).upper() if args else ""
        except Exception:
            op = ""
        result = None
        try:
            result = original(self, *args, **kwargs)
            return result
        finally:
            try:
                duration_ms = (time.monotonic() - start) * 1000.0
                meta = {"kind": "cache", "op": op or "CACHE"}
                if op in _READ_OPS:
                    meta["hit"] = result is not None and result != [] and result != {}
                client.record_span("custom", op or "CACHE", duration_ms, meta=meta)
            except Exception:
                pass

    execute_command._metrixwire = True  # type: ignore[attr-defined]
    Redis.execute_command = execute_command  # type: ignore[assignment]
    _PATCHED = True
