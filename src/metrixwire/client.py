"""The SDK singleton + the internal trace lifecycle helpers used by patches.

The SDK is zero-config: ``metrixwire.init()`` is called once and every request,
database query, cache op and outbound HTTP call is instrumented automatically.
There is no manual span API on the public surface — only a
``capture_exception()`` escape hatch (mirroring Node/PHP) for frameworks that
swallow their own errors. Everything here is defensive: instrumentation must
never throw into the host application.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from .config import Config, build_config
from .context import get_current_trace, reset_current_trace, set_current_trace
from .transport import Transport
from .trace import Span, Trace, exception_meta, iso_millis


class _Client:
    def __init__(self) -> None:
        self.config: Optional[Config] = None
        self.transport: Optional[Transport] = None

    def init(self, **opts: Any) -> None:
        if self.config is not None:
            return  # already initialised — no-op
        self.config = build_config(**opts)
        self.transport = Transport(self.config)
        if self.config.enabled:
            self.transport.start()
            self._install_patches()

    def _install_patches(self) -> None:
        # Import lazily so a broken/optional patch can never break init().
        try:
            from .patches import install_all

            install_all(self)
        except Exception:
            pass

    # ── trace lifecycle (internal — called by patches) ───────────────────────

    def start_trace(self, route: str, method: Optional[str]) -> Optional[Trace]:
        if not self._enabled():
            return None
        try:
            now = time.time()
            trace = Trace(
                route=route,
                method=method,
                started_at=iso_millis(now),
                start_monotonic=time.monotonic(),
            )
            token = set_current_trace(trace)
            # Stash the reset token on the trace so finish_trace can restore.
            trace.meta.setdefault("__internal__", {})
            trace.meta["__internal__"]["token"] = token
            return trace
        except Exception:
            return None

    def finish_trace(
        self,
        trace: Optional[Trace],
        status_code: int = 200,
        response_bytes: int = 0,
        memory_mb: int = 0,
    ) -> None:
        if trace is None or not self._enabled():
            return
        try:
            trace.duration_ms = int(round((time.monotonic() - trace.start_monotonic) * 1000))
            # captureException may have already flagged this as an error — keep it.
            if status_code >= 500:
                trace.status = "error"
            if response_bytes and response_bytes > 0:
                trace.meta["responseBytes"] = int(response_bytes)
            if memory_mb and memory_mb > 0:
                trace.meta["memoryMb"] = int(memory_mb)
            self._enqueue(trace)
        finally:
            self._pop_trace(trace)

    def _pop_trace(self, trace: Trace) -> None:
        try:
            internal = trace.meta.pop("__internal__", None)
            token = internal.get("token") if internal else None
            if token is not None:
                reset_current_trace(token)
        except Exception:
            pass

    def _enqueue(self, trace: Trace) -> None:
        try:
            # Strip internal bookkeeping before serializing.
            trace.meta.pop("__internal__", None)
            if self.transport is not None:
                self.transport.enqueue(trace.to_dict())
        except Exception:
            pass

    # ── span recording (internal — called by patches) ────────────────────────

    def record_span(
        self,
        type: str,
        description: str,
        duration_ms: float,
        source_location: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._enabled() or not description:
            return
        trace = get_current_trace()
        if trace is None:
            return
        try:
            now = time.time()
            started_at = iso_millis(now - (duration_ms / 1000.0))
            trace.add_span(
                Span(
                    type=type,
                    description=description,
                    started_at=started_at,
                    duration_ms=int(round(max(0.0, duration_ms))),
                    source_location=source_location,
                    meta=meta or None,
                )
            )
        except Exception:
            pass

    def capture_exception(self, exc: BaseException) -> None:
        """Attach an exception to the active trace and flag it as an error.

        The one public escape hatch — for frameworks that catch their own
        errors before our patch can observe them. Never throws.
        """
        if not self._enabled():
            return
        trace = get_current_trace()
        if trace is None or exc is None:
            return
        try:
            em = exception_meta(exc)
            if em:
                trace.meta["exception"] = em
            trace.status = "error"
        except Exception:
            pass

    def flush(self) -> None:
        try:
            if self.transport is not None:
                self.transport.flush()
        except Exception:
            pass

    # ── helpers ──────────────────────────────────────────────────────────────

    def _enabled(self) -> bool:
        return bool(self.config and self.config.enabled)

    def is_source_capture_on(self) -> bool:
        return bool(self.config.capture_source) if self.config else True


# Singleton — the SDK's internal surface (patches call into this).
client = _Client()
