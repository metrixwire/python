"""Generic WSGI middleware — the escape hatch for bare or unsupported WSGI apps.

Most frameworks are traced automatically by their dedicated patch (Flask,
Django). For a bare WSGI app (``wsgiref``) or a framework the SDK doesn't patch,
wrap the app once::

    from metrixwire.wsgi import MetrixWireMiddleware
    app = MetrixWireMiddleware(app)

A trace is opened per request with route/status/response-bytes/memory captured —
no per-route setup. Defensive throughout: tracing never affects the response.
"""

from __future__ import annotations

from typing import Any

from .client import client
from .util import memory_delta_mb, memory_snapshot
from .patches import web


class MetrixWireMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    def __call__(self, environ, start_response):  # type: ignore[no-untyped-def]
        method = environ.get("REQUEST_METHOD", "GET")
        path = web.path_only(environ.get("PATH_INFO") or "/")
        trace = client.start_trace(web.route_label(method, path), method)
        if trace is None:
            return self.app(environ, start_response)

        start_mem = memory_snapshot()
        state = {"status_code": 200, "bytes": 0}

        def wrapped_start_response(status, headers, exc_info=None):  # type: ignore[no-untyped-def]
            try:
                state["status_code"] = int(str(status).split(" ", 1)[0])
            except Exception:
                pass
            return start_response(status, headers, exc_info)

        try:
            result = self.app(environ, wrapped_start_response)
        except Exception as exc:
            client.capture_exception(exc)
            client.finish_trace(
                trace, status_code=500, memory_mb=memory_delta_mb(start_mem)
            )
            raise

        def _iter():  # type: ignore[no-untyped-def]
            try:
                for chunk in result:
                    try:
                        state["bytes"] += len(chunk)
                    except Exception:
                        pass
                    yield chunk
            finally:
                try:
                    if hasattr(result, "close"):
                        result.close()
                except Exception:
                    pass
                client.finish_trace(
                    trace,
                    status_code=state["status_code"],
                    response_bytes=state["bytes"],
                    memory_mb=memory_delta_mb(start_mem),
                )

        return _iter()
