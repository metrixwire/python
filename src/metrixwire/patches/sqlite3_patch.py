"""sqlite3 auto-instrumentation (stdlib).

On modern CPython ``sqlite3.Cursor`` is an immutable type, so we can't patch its
``execute`` in place. Instead we wrap ``sqlite3.connect`` to return a Connection
subclass whose ``execute`` / ``cursor().execute`` are instrumented — subclasses
are mutable. Every query becomes a ``db_query`` span with ``rowCount``.
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
        import sqlite3
    except Exception:
        return

    orig_connect = sqlite3.connect
    if getattr(orig_connect, "_metrixwire", False):
        _PATCHED = True
        return

    base_conn = sqlite3.Connection
    base_cursor = sqlite3.Cursor

    class MetrixWireCursor(base_cursor):  # type: ignore[misc, valid-type]
        def execute(self, sql, parameters=(), /):  # type: ignore[no-untyped-def]
            return db.instrument_execute(client, self, base_cursor.execute, sql, parameters)

        def executemany(self, sql, seq_of_parameters, /):  # type: ignore[no-untyped-def]
            return db.instrument_execute(client, self, base_cursor.executemany, sql, seq_of_parameters)

    class MetrixWireConnection(base_conn):  # type: ignore[misc, valid-type]
        def cursor(self, factory=MetrixWireCursor):  # type: ignore[no-untyped-def]
            return super().cursor(factory)

        # Connection.execute is a convenience that creates a cursor internally;
        # route it through our instrumented cursor.
        def execute(self, sql, parameters=(), /):  # type: ignore[no-untyped-def]
            cur = self.cursor()
            return cur.execute(sql, parameters)

        def executemany(self, sql, seq_of_parameters, /):  # type: ignore[no-untyped-def]
            cur = self.cursor()
            return cur.executemany(sql, seq_of_parameters)

    def connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("factory", MetrixWireConnection)
        return orig_connect(*args, **kwargs)

    connect._metrixwire = True  # type: ignore[attr-defined]
    sqlite3.connect = connect
    _PATCHED = True
