"""Starlette / FastAPI (ASGI) auto-instrumentation.

FastAPI is built on Starlette, so wrapping ``Starlette.__call__`` covers both. A
trace is opened per HTTP request; the matched route pattern (e.g.
``/users/{id}``) is read from ``scope['route']`` once the router has resolved
it, falling back to the request path.
"""

from __future__ import annotations

from typing import Any

from ..util import memory_delta_mb, memory_snapshot
from . import web

_PATCHED = False


def install(client: Any) -> None:
    global _PATCHED
    if _PATCHED:
        return
    try:
        from starlette.applications import Starlette
    except Exception:
        return  # Starlette/FastAPI not installed — skip silently.

    if getattr(Starlette.__call__, "_metrixwire", False):
        _PATCHED = True
        return

    original = Starlette.__call__

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope.get("type") != "http":
            return await original(self, scope, receive, send)

        method = scope.get("method", "GET")
        path = web.path_only(scope.get("path") or "/")
        trace = client.start_trace(web.route_label(method, path), method)
        if trace is None:
            return await original(self, scope, receive, send)

        start_mem = memory_snapshot()
        state = {"status_code": 200, "bytes": 0}

        async def wrapped_send(message):  # type: ignore[no-untyped-def]
            try:
                mtype = message.get("type")
                if mtype == "http.response.start":
                    state["status_code"] = int(message.get("status", 200))
                elif mtype == "http.response.body":
                    body = message.get("body") or b""
                    try:
                        state["bytes"] += len(body)
                    except Exception:
                        pass
            except Exception:
                pass
            return await send(message)

        def _refine_route() -> None:
            # Starlette sets scope['route'] once the endpoint is matched.
            try:
                route_obj = scope.get("route")
                pattern = getattr(route_obj, "path", None)
                if pattern:
                    trace.route = web.route_label(method, pattern)
            except Exception:
                pass

        try:
            result = await original(self, scope, receive, wrapped_send)
            _refine_route()
            client.finish_trace(
                trace, status_code=state["status_code"], response_bytes=state["bytes"],
                memory_mb=memory_delta_mb(start_mem),
            )
            return result
        except Exception as exc:
            client.capture_exception(exc)
            _refine_route()
            client.finish_trace(trace, status_code=500, memory_mb=memory_delta_mb(start_mem))
            raise

    __call__._metrixwire = True  # type: ignore[attr-defined]
    Starlette.__call__ = __call__
    _PATCHED = True
