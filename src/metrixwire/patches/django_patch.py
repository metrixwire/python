"""Django auto-instrumentation.

We patch the WSGI and ASGI handler entry points
(``WSGIHandler.__call__`` / ``ASGIHandler.__call__``) so a trace is opened per
request. The route is refined to the resolver match (e.g. ``users/<int:id>``)
via ``request.resolver_match`` when Django has resolved it.
"""

from __future__ import annotations

from typing import Any

from ..util import memory_delta_mb, memory_snapshot
from . import web

_WSGI_PATCHED = False
_ASGI_PATCHED = False


def install(client: Any) -> None:
    _install_wsgi(client)
    _install_asgi(client)


def _route_from_path(method: str, path: str) -> str:
    """Resolve the URLconf pattern for a path (e.g. ``users/<int:id>/``).

    Independent of the request object — resolves the path directly against
    Django's resolver, which is stable and always available after setup.
    """
    try:
        from django.urls import resolve

        match = resolve(path)
        route = getattr(match, "route", None)
        if route:
            return web.route_label(method, "/" + str(route).lstrip("/"))
    except Exception:
        pass
    return web.route_label(method, path)


def _install_wsgi(client: Any) -> None:
    global _WSGI_PATCHED
    if _WSGI_PATCHED:
        return
    try:
        from django.core.handlers.wsgi import WSGIHandler
    except Exception:
        return

    if getattr(WSGIHandler.__call__, "_metrixwire", False):
        _WSGI_PATCHED = True
        return

    original = WSGIHandler.__call__

    def __call__(self, environ, start_response):  # type: ignore[no-untyped-def]
        method = environ.get("REQUEST_METHOD", "GET")
        path = web.path_only(environ.get("PATH_INFO") or "/")
        trace = client.start_trace(web.route_label(method, path), method)
        if trace is None:
            return original(self, environ, start_response)

        start_mem = memory_snapshot()
        state = {"status_code": 200, "bytes": 0}

        def wrapped_start_response(status, headers, exc_info=None):  # type: ignore[no-untyped-def]
            try:
                state["status_code"] = int(str(status).split(" ", 1)[0])
            except Exception:
                pass
            return start_response(status, headers, exc_info)

        try:
            response = original(self, environ, wrapped_start_response)
        except Exception as exc:
            client.capture_exception(exc)
            client.finish_trace(trace, status_code=500, memory_mb=memory_delta_mb(start_mem))
            raise

        # Django returns an HttpResponse (iterable). Refine the route from it.
        try:
            status_code = int(getattr(response, "status_code", state["status_code"]))
        except Exception:
            status_code = state["status_code"]
        try:
            content = getattr(response, "content", b"")
            byte_len = len(content) if content is not None else 0
        except Exception:
            byte_len = 0

        trace.route = _route_from_path(method, path)
        client.finish_trace(
            trace, status_code=status_code, response_bytes=byte_len,
            memory_mb=memory_delta_mb(start_mem),
        )
        return response

    __call__._metrixwire = True  # type: ignore[attr-defined]
    WSGIHandler.__call__ = __call__
    _WSGI_PATCHED = True


def _install_asgi(client: Any) -> None:
    global _ASGI_PATCHED
    if _ASGI_PATCHED:
        return
    try:
        from django.core.handlers.asgi import ASGIHandler
    except Exception:
        return

    if getattr(ASGIHandler.__call__, "_metrixwire", False):
        _ASGI_PATCHED = True
        return

    original = ASGIHandler.__call__

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

        try:
            result = await original(self, scope, receive, wrapped_send)
            trace.route = _route_from_path(method, path)
            client.finish_trace(
                trace, status_code=state["status_code"], response_bytes=state["bytes"],
                memory_mb=memory_delta_mb(start_mem),
            )
            return result
        except Exception as exc:
            client.capture_exception(exc)
            trace.route = _route_from_path(method, path)
            client.finish_trace(trace, status_code=500, memory_mb=memory_delta_mb(start_mem))
            raise

    __call__._metrixwire = True  # type: ignore[attr-defined]
    ASGIHandler.__call__ = __call__
    _ASGI_PATCHED = True
