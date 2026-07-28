"""Shared helpers for the DB-driver patches.

All drivers follow the DB-API 2.0 cursor protocol, so the timing / span-shape /
transaction-detection logic is identical: time the ``execute``, read
``cursor.rowcount``, capture the nearest user frame, and — when the statement is
a ``COMMIT`` / ``BEGIN`` boundary — additionally emit a transaction span.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..util import nearest_user_frame


def _normalize_sql(sql: Any) -> str:
    try:
        text = sql.decode("utf-8", "replace") if isinstance(sql, (bytes, bytearray)) else str(sql)
        return " ".join(text.split()).strip()
    except Exception:
        return ""


def record_query(client: Any, sql: Any, duration_ms: float, rowcount: Optional[int]) -> None:
    """Emit a ``db_query`` span for one executed statement."""
    text = _normalize_sql(sql)
    if not text:
        return
    meta = None
    try:
        if rowcount is not None and int(rowcount) >= 0:
            meta = {"rowCount": int(rowcount)}
    except Exception:
        meta = None
    source = nearest_user_frame() if client.is_source_capture_on() else None
    client.record_span("db_query", text, duration_ms, source_location=source, meta=meta)


# Per-connection transaction start time (monotonic). Keyed by id() of the
# connection so we can time a BEGIN…COMMIT window opened via raw SQL. Weakly
# scoped by best-effort cleanup on COMMIT/ROLLBACK.
_txn_starts: "dict[int, float]" = {}


def _txn_boundary(client: Any, conn_id: Optional[int], sql_text: str) -> None:
    """Detect BEGIN / COMMIT / ROLLBACK issued as raw SQL and time the window.

    Emits a ``custom`` transaction span (``meta.kind='transaction'``) when a
    transaction closes, so the long_transaction detector can flag it.
    """
    if conn_id is None:
        return
    try:
        head = sql_text.lstrip().upper()
        if head.startswith("BEGIN") or head.startswith("START TRANSACTION"):
            _txn_starts[conn_id] = time.monotonic()
        elif head.startswith("COMMIT") or head.startswith("ROLLBACK") or head.startswith("END"):
            start = _txn_starts.pop(conn_id, None)
            if start is not None:
                duration_ms = (time.monotonic() - start) * 1000.0
                client.record_span(
                    "custom", "DB transaction", duration_ms, meta={"kind": "transaction"}
                )
    except Exception:
        pass


def _conn_id(cursor: Any) -> Optional[int]:
    try:
        conn = getattr(cursor, "connection", None)
        return id(conn) if conn is not None else None
    except Exception:
        return None


def instrument_execute(client: Any, cursor: Any, original: Any, sql: Any, *args: Any, **kwargs: Any) -> Any:
    """Time a cursor.execute/executemany call and record its span."""
    start = time.monotonic()
    try:
        return original(cursor, sql, *args, **kwargs)
    finally:
        try:
            duration_ms = (time.monotonic() - start) * 1000.0
            rowcount = getattr(cursor, "rowcount", None)
            record_query(client, sql, duration_ms, rowcount)
            _txn_boundary(client, _conn_id(cursor), _normalize_sql(sql))
        except Exception:
            pass


def instrument_commit(client: Any, conn: Any, original: Any, *args: Any, **kwargs: Any) -> Any:
    """Wrap ``connection.commit()`` to time a transaction opened via the driver's
    implicit/explicit begin. Emits a transaction span on commit."""
    conn_id = id(conn)
    start = _txn_starts.pop(conn_id, None)
    result = original(conn, *args, **kwargs)
    try:
        if start is not None:
            duration_ms = (time.monotonic() - start) * 1000.0
            client.record_span("custom", "DB transaction", duration_ms, meta={"kind": "transaction"})
    except Exception:
        pass
    return result


def mark_txn_begin(conn: Any) -> None:
    try:
        _txn_starts.setdefault(id(conn), time.monotonic())
    except Exception:
        pass
