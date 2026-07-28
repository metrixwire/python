"""Shared helpers for the web-framework patches.

Deriving a route label, computing status/error, and tallying response bytes are
the same across Flask/Django/Starlette/WSGI, so they live here. Everything is
defensive — a tracing failure must never affect the response.
"""

from __future__ import annotations

from typing import Optional


def path_only(raw: Optional[str]) -> str:
    """Strip the query string so paths aggregate: ``/users/1?x=2`` -> ``/users/1``."""
    try:
        if not raw:
            return "/"
        return raw.split("?", 1)[0] or "/"
    except Exception:
        return "/"


def route_label(method: Optional[str], path: str) -> str:
    """``GET /users/:id`` style label."""
    m = (method or "GET").upper()
    return "%s %s" % (m, path or "/")


def status_from_code(status_code: int, has_exception: bool) -> str:
    try:
        if has_exception or (status_code and int(status_code) >= 500):
            return "error"
    except Exception:
        pass
    return "success"
