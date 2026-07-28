"""MetrixWire — zero-config APM SDK for Python.

Call :func:`init` once, as early as possible in your process. Every HTTP request
becomes a **trace**, and every database query, outbound HTTP call and cache op
within it becomes a **span** — automatically, with no manual span API and no
middleware to wire up (a generic WSGI middleware is available as an escape hatch
for bare apps: ``metrixwire.wsgi.MetrixWireMiddleware``).

    import metrixwire
    metrixwire.init(api_key="mw_...")

Non-blocking: traces are batched and sent off the request path on a background
daemon thread with a short timeout; all transport errors are swallowed so
monitoring never breaks or slows the host application.
"""

from __future__ import annotations

from typing import Any, Optional

from .client import client

__all__ = ["init", "capture_exception", "flush"]
__version__ = "0.1.0"


def init(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    flush_interval_ms: Optional[int] = None,
    enabled: Optional[bool] = None,
    timeout_ms: Optional[int] = None,
    max_batch: Optional[int] = None,
    capture_source: Optional[bool] = None,
) -> None:
    """Initialise the SDK and install auto-instrumentation. Idempotent.

    Any argument left as ``None`` falls back to an environment variable
    (``METRIXWIRE_KEY``, ``METRIXWIRE_ENDPOINT``, ``METRIXWIRE_ENABLED``) and
    then a default. A missing API key runs the SDK disabled rather than raising.
    """
    client.init(
        api_key=api_key,
        endpoint=endpoint,
        flush_interval_ms=flush_interval_ms,
        enabled=enabled,
        timeout_ms=timeout_ms,
        max_batch=max_batch,
        capture_source=capture_source,
    )


def capture_exception(exc: BaseException) -> None:
    """Attach an exception to the active trace and flag it as an error.

    The single manual escape hatch — for frameworks that catch their own errors
    before the SDK can observe them. Never throws.
    """
    client.capture_exception(exc)


def flush() -> None:
    """Flush any queued traces now (e.g. before a short-lived process exits)."""
    client.flush()
