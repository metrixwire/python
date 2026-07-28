"""psycopg (v3) auto-instrumentation.

psycopg v3 exposes ``psycopg.Cursor`` (and ``AsyncCursor``). We patch the sync
``Cursor.execute`` / ``executemany`` so queries become ``db_query`` spans with
``rowCount``. Skips silently if psycopg v3 isn't installed.
"""

from __future__ import annotations

from typing import Any

from . import db

_PATCHED = False


def install(client: Any) -> None:
    global _PATCHED
    if _PATCHED:
        return
    try:
        import psycopg  # psycopg v3
    except Exception:
        return

    Cursor = getattr(psycopg, "Cursor", None)
    if Cursor is None or getattr(Cursor.execute, "_metrixwire", False):
        _PATCHED = bool(Cursor is not None)
        return

    orig_execute = Cursor.execute
    orig_executemany = getattr(Cursor, "executemany", None)

    def execute(self, query, params=None, **kwargs):  # type: ignore[no-untyped-def]
        return db.instrument_execute(client, self, orig_execute, query, params, **kwargs)

    execute._metrixwire = True  # type: ignore[attr-defined]
    try:
        Cursor.execute = execute  # type: ignore[assignment]
        if orig_executemany is not None:
            def executemany(self, query, params_seq, **kwargs):  # type: ignore[no-untyped-def]
                return db.instrument_execute(client, self, orig_executemany, query, params_seq, **kwargs)

            Cursor.executemany = executemany  # type: ignore[assignment]
    except (TypeError, AttributeError):
        return

    # Transaction timing via connection.commit (best-effort).
    try:
        Connection = getattr(psycopg, "Connection", None)
        if Connection is not None:
            orig_commit = Connection.commit

            def commit(self):  # type: ignore[no-untyped-def]
                return db.instrument_commit(client, self, orig_commit)

            Connection.commit = commit  # type: ignore[assignment]
    except (TypeError, AttributeError):
        pass

    _PATCHED = True
