"""Flask auto-instrumentation.

We wrap ``flask.Flask.wsgi_app`` — the single entry point every Flask request
passes through — so a trace is opened for each request with no per-app or
per-route setup. The matched URL rule (e.g. ``/users/<id>``) is used as the
route when available; otherwise we fall back to the request path.
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
        import flask
    except Exception:
        return  # Flask not installed — skip silently.

    if getattr(flask.Flask.wsgi_app, "_metrixwire", False):
        _PATCHED = True
        return

    original = flask.Flask.wsgi_app

    def wsgi_app(self, environ, start_response):  # type: ignore[no-untyped-def]
        method = environ.get("REQUEST_METHOD", "GET")
        path = web.path_only(environ.get("PATH_INFO") or environ.get("RAW_URI") or "/")
        route = web.route_label(method, path)
        trace = client.start_trace(route, method)
        if trace is None:
            return original(self, environ, start_response)

        start_mem = memory_snapshot()
        state = {"status_code": 200, "bytes": 0}

        def _refine_route() -> None:
            # Prefer the matched URL rule (e.g. /users/<id>) for stable
            # aggregation. Match the app's URL map against this request's environ
            # directly — this doesn't depend on Flask's request context still
            # being active (it isn't, once wsgi_app has returned).
            try:
                adapter = self.url_map.bind_to_environ(environ)
                rule, _ = adapter.match(return_rule=True)
                if getattr(rule, "rule", None):
                    trace.route = web.route_label(method, rule.rule)
            except Exception:
                pass

        def wrapped_start_response(status, headers, exc_info=None):  # type: ignore[no-untyped-def]
            try:
                state["status_code"] = int(str(status).split(" ", 1)[0])
            except Exception:
                pass
            return start_response(status, headers, exc_info)

        try:
            # The full dispatch (routing + view + error handling) happens inside
            # this call, so the matched rule is available immediately after it.
            result = original(self, environ, wrapped_start_response)
            _refine_route()
        except Exception as exc:
            client.capture_exception(exc)
            _refine_route()
            client.finish_trace(
                trace, status_code=500, response_bytes=state["bytes"],
                memory_mb=memory_delta_mb(start_mem),
            )
            raise

        # Tally response bytes as the iterable is consumed, then finish.
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

    wsgi_app._metrixwire = True  # type: ignore[attr-defined]
    flask.Flask.wsgi_app = wsgi_app
    _PATCHED = True
