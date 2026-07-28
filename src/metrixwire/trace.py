"""Trace/Span data model + ISO8601 (UTC, millisecond) formatting.

Nothing here is part of the public API — users never open a trace or build a
span by hand. The instrumentation layer (``patches/``) constructs these. Every
path is defensive: turning our internal state into the ingest wire format must
never throw into the host application.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# The wire contract is identical across every MetrixWire SDK (Node, PHP, Python):
#   Span: {type, description, startedAt, durationMs, sourceLocation?, meta?}
#   Trace: {route, method?, startedAt, durationMs, status, spans, meta?}
SpanType = str  # "db_query" | "http_call" | "custom"


def iso_millis(epoch_seconds: float) -> str:
    """Format an epoch time as ISO8601 UTC with millisecond precision.

    e.g. ``2026-07-14T10:00:00.000Z`` — matching the ingest contract exactly.
    """
    try:
        sec = int(epoch_seconds)
        ms = int(round((epoch_seconds - sec) * 1000))
        # Rounding can push us to 1000ms; carry it into the seconds.
        if ms >= 1000:
            sec += 1
            ms -= 1000
        base = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(sec))
        return "%s.%03dZ" % (base, ms)
    except Exception:
        # Never fail — fall back to a best-effort current timestamp.
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


@dataclass
class Span:
    """A single unit of work within a trace (db_query | http_call | custom)."""

    type: SpanType
    description: str
    started_at: str  # ISO8601
    duration_ms: int
    source_location: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "type": self.type,
            "description": self.description,
            "startedAt": self.started_at,
            "durationMs": self.duration_ms,
        }
        if self.source_location:
            out["sourceLocation"] = self.source_location
        if self.meta:
            out["meta"] = self.meta
        return out


@dataclass
class Trace:
    """One request / unit of work. Holds its spans and trace-level meta."""

    route: str
    method: Optional[str]
    started_at: str  # ISO8601
    start_monotonic: float  # time.monotonic() at open, for duration
    status: str = "success"
    duration_ms: int = 0
    spans: List[Span] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def add_span(self, span: Span) -> None:
        try:
            self.spans.append(span)
        except Exception:
            pass

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "route": self.route,
            "method": self.method,
            "startedAt": self.started_at,
            "durationMs": self.duration_ms,
            "status": self.status,
            "spans": [s.to_dict() for s in self.spans],
        }
        if self.meta:
            out["meta"] = self.meta
        return out


def exception_meta(exc: BaseException) -> Optional[Dict[str, Any]]:
    """Build the trace ``meta.exception`` payload from a thrown exception.

    ``stack`` keeps only the first ~8 lines — enough to fingerprint & guide a
    fix, matching the Node/PHP SDKs.
    """
    try:
        import traceback

        if exc is None:
            return None
        etype = type(exc).__name__
        message = str(exc)
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        # Flatten to individual lines, keep the first ~8.
        flat: List[str] = []
        for chunk in tb_lines:
            flat.extend(chunk.rstrip("\n").split("\n"))
        stack = "\n".join(flat[:8]) if flat else None
        out: Dict[str, Any] = {"type": etype, "message": message}
        if stack:
            out["stack"] = stack
        return out
    except Exception:
        return None
