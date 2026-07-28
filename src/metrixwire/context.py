"""The active-trace store, backed by :mod:`contextvars`.

``contextvars`` gives us the right isolation semantics automatically: each
thread and each asyncio task sees its own current trace, so concurrent requests
(sync WSGI worker threads or async ASGI tasks) never bleed spans into each
other. All accessors are defensive — instrumentation must never throw.
"""

from __future__ import annotations

import contextvars
from typing import Optional

from .trace import Trace

_current_trace: "contextvars.ContextVar[Optional[Trace]]" = contextvars.ContextVar(
    "metrixwire_current_trace", default=None
)


def get_current_trace() -> Optional[Trace]:
    try:
        return _current_trace.get()
    except Exception:
        return None


def set_current_trace(trace: Optional[Trace]) -> "contextvars.Token":
    return _current_trace.set(trace)


def reset_current_trace(token: "contextvars.Token") -> None:
    try:
        _current_trace.reset(token)
    except Exception:
        pass
