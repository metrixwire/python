"""Batching transport: a background daemon thread flushes queued traces to the
ingest endpoint.

Every network path is wrapped so a dead or slow MetrixWire API can never crash
or block the host application: a short send timeout, all errors swallowed, and
sends that happen off the request path on a daemon thread. A final flush runs at
process exit (``atexit``).
"""

from __future__ import annotations

import atexit
import json
import threading
import urllib.request
from typing import Any, Dict, List, Optional

from .config import Config


class Transport:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._queue: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        # Wakes the worker for an immediate flush (batch full or manual flush).
        self._flush_event = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False

    def start(self) -> None:
        if self._started or not self._config.enabled:
            return
        self._started = True
        # Daemon thread: never keeps the interpreter alive on its own.
        self._thread = threading.Thread(
            target=self._run, name="metrixwire-transport", daemon=True
        )
        self._thread.start()
        # Last-chance flush on shutdown, so short-lived processes still report.
        try:
            atexit.register(self._on_exit)
        except Exception:
            pass

    def enqueue(self, trace: Dict[str, Any]) -> None:
        if not self._config.enabled:
            return
        try:
            with self._lock:
                self._queue.append(trace)
                full = len(self._queue) >= self._config.max_batch
            if full:
                # Flush immediately once the batch fills up.
                self._flush_event.set()
        except Exception:
            # Instrumentation must never throw into the host app.
            pass

    def flush(self) -> None:
        """Drain and send everything currently queued (blocking, best-effort)."""
        try:
            self._send_batch(self._drain())
        except Exception:
            pass

    # ── internals ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        interval = max(0.05, self._config.flush_interval_ms / 1000.0)
        while not self._stop.is_set():
            # Wake early if a flush was requested (batch full / manual flush).
            self._flush_event.wait(timeout=interval)
            self._flush_event.clear()
            try:
                self._send_batch(self._drain())
            except Exception:
                pass

    def _drain(self) -> List[Dict[str, Any]]:
        with self._lock:
            if not self._queue:
                return []
            batch = self._queue
            self._queue = []
            return batch

    def _send_batch(self, batch: List[Dict[str, Any]]) -> None:
        if not batch or not self._config.enabled or not self._config.api_key:
            return
        try:
            body = json.dumps({"traces": batch}).encode("utf-8")
        except Exception:
            return
        try:
            req = urllib.request.Request(
                self._config.endpoint,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self._config.api_key,
                },
            )
            timeout = self._config.timeout_ms / 1000.0
            resp = urllib.request.urlopen(req, timeout=timeout)
            try:
                resp.read()
            except Exception:
                pass
            try:
                resp.close()
            except Exception:
                pass
        except Exception:
            # Swallow everything — monitoring must never break the app.
            pass

    def _on_exit(self) -> None:
        try:
            self._stop.set()
            self._flush_event.set()
            # Final synchronous flush of anything still queued.
            self._send_batch(self._drain())
        except Exception:
            pass
