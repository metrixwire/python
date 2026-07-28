"""SDK configuration + env fallbacks.

``init()`` reads these env vars when the matching argument is omitted:
``METRIXWIRE_KEY``, ``METRIXWIRE_ENDPOINT``, ``METRIXWIRE_ENABLED``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_ENDPOINT = "http://localhost:3000/ingest"
DEFAULT_FLUSH_INTERVAL_MS = 5000
DEFAULT_TIMEOUT_MS = 3000
DEFAULT_MAX_BATCH = 20


def _env(key: str) -> Optional[str]:
    v = os.environ.get(key)
    if v is None or v == "":
        return None
    return v


def _env_bool(key: str) -> Optional[bool]:
    v = _env(key)
    if v is None:
        return None
    return v.strip().lower() in ("1", "true", "yes", "on")


def normalize_endpoint(endpoint: str) -> str:
    """Accept a base URL or the full ``/ingest`` URL.

    If it doesn't already end with ``/ingest``, append it — identical to the
    Node/PHP transports.
    """
    url = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
    if not url.endswith("/ingest"):
        url += "/ingest"
    return url


@dataclass
class Config:
    api_key: str
    endpoint: str
    flush_interval_ms: int
    enabled: bool
    timeout_ms: int
    max_batch: int
    capture_source: bool


def build_config(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    flush_interval_ms: Optional[int] = None,
    enabled: Optional[bool] = None,
    timeout_ms: Optional[int] = None,
    max_batch: Optional[int] = None,
    capture_source: Optional[bool] = None,
) -> Config:
    """Merge explicit args, env fallbacks and defaults into a Config.

    A missing API key means the SDK runs disabled (never throws) — matching the
    other SDKs.
    """
    key = api_key if api_key is not None else (_env("METRIXWIRE_KEY") or "")
    ep = endpoint if endpoint is not None else _env("METRIXWIRE_ENDPOINT")
    want_enabled = enabled if enabled is not None else _env_bool("METRIXWIRE_ENABLED")
    if want_enabled is None:
        want_enabled = True

    return Config(
        api_key=key or "",
        endpoint=normalize_endpoint(ep or DEFAULT_ENDPOINT),
        flush_interval_ms=int(flush_interval_ms if flush_interval_ms is not None else DEFAULT_FLUSH_INTERVAL_MS),
        # Disabled unless we actually have a key — never crash on a missing key.
        enabled=bool(want_enabled) and bool(key),
        timeout_ms=int(timeout_ms if timeout_ms is not None else DEFAULT_TIMEOUT_MS),
        max_batch=int(max_batch if max_batch is not None else DEFAULT_MAX_BATCH),
        capture_source=bool(capture_source) if capture_source is not None else True,
    )
