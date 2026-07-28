"""stdlib ``http.client`` auto-instrumentation.

Patching ``HTTPConnection.request`` (to capture method/path/host) and
``HTTPConnection.getresponse`` (to capture the status and close the timing)
covers the stdlib client and everything built on it (``urllib.request``, and —
as a fallback — libraries that don't go through ``requests``). Each call becomes
an ``http_call`` span. We deliberately skip the SDK's own ingest calls so
instrumentation never traces itself.
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
        import http.client as httpclient
    except Exception:
        return

    Conn = httpclient.HTTPConnection
    if getattr(Conn.request, "_metrixwire", False):
        _PATCHED = True
        return

    orig_request = Conn.request
    orig_getresponse = Conn.getresponse

    def request(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            self._metrixwire_method = str(method).upper()
            self._metrixwire_url = str(url).split("?", 1)[0]
            self._metrixwire_start = time.monotonic()
        except Exception:
            pass
        return orig_request(self, method, url, *args, **kwargs)

    def getresponse(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        resp = orig_getresponse(self, *args, **kwargs)
        try:
            method = getattr(self, "_metrixwire_method", "GET")
            path = getattr(self, "_metrixwire_url", "/")
            start = getattr(self, "_metrixwire_start", None)
            host = getattr(self, "host", "") or ""
            port = getattr(self, "port", None)
            scheme = "https" if type(self).__name__ == "HTTPSConnection" else "http"
            hostport = host if not port or port in (80, 443) else "%s:%s" % (host, port)
            full = "%s://%s%s" % (scheme, hostport, path if path.startswith("/") else "/" + path)
            # Never trace our own ingest POSTs.
            if "/ingest" in full:
                return resp
            duration_ms = (time.monotonic() - start) * 1000.0 if start else 0.0
            status = None
            try:
                status = int(getattr(resp, "status", 0)) or None
            except Exception:
                status = None
            meta = {"statusCode": status} if status else None
            client.record_span("http_call", "%s %s" % (method, full), duration_ms, meta=meta)
        except Exception:
            pass
        return resp

    request._metrixwire = True  # type: ignore[attr-defined]
    Conn.request = request  # type: ignore[assignment]
    Conn.getresponse = getresponse  # type: ignore[assignment]
    _PATCHED = True
