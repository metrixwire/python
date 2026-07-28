"""``requests`` auto-instrumentation.

Patches ``requests.sessions.Session.request`` so every outbound call becomes an
``http_call`` span described as ``GET https://host/path`` with the response
``statusCode``. Skips silently if ``requests`` isn't installed.
"""

from __future__ import annotations

import time
from typing import Any

_PATCHED = False


def install(client: Any) -> None:
    global _PATCHED
    if _PATCHED:
        return
    try:
        from requests import sessions
    except Exception:
        return

    Session = sessions.Session
    if getattr(Session.request, "_metrixwire", False):
        _PATCHED = True
        return

    original = Session.request

    def request(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
        start = time.monotonic()
        status_code = None
        try:
            resp = original(self, method, url, *args, **kwargs)
            try:
                status_code = int(getattr(resp, "status_code", 0)) or None
            except Exception:
                status_code = None
            return resp
        finally:
            try:
                duration_ms = (time.monotonic() - start) * 1000.0
                desc = "%s %s" % (str(method).upper(), _strip_query(url))
                meta = {"statusCode": status_code} if status_code else None
                client.record_span("http_call", desc, duration_ms, meta=meta)
            except Exception:
                pass

    request._metrixwire = True  # type: ignore[attr-defined]
    Session.request = request  # type: ignore[assignment]
    _PATCHED = True


def _strip_query(url: Any) -> str:
    try:
        return str(url).split("?", 1)[0]
    except Exception:
        return str(url)
