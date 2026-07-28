"""psycopg2 auto-instrumentation.

``psycopg2.extensions.cursor`` is an immutable C type, so we can't patch its
``execute`` method in place. Instead we wrap ``psycopg2.connect`` to inject a
``cursor_factory`` that returns a *Python subclass* of the driver cursor whose
``execute`` / ``executemany`` we override — a subclass is mutable. Every Postgres
query then becomes a ``db_query`` span with ``rowCount``. ``connection.commit``
timing yields a transaction span. Covers anything running on psycopg2 (Django
ORM, SQLAlchemy, raw psycopg2).
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
        import psycopg2
        from psycopg2 import extensions
    except Exception:
        return

    base_cursor = extensions.cursor
    base_conn = extensions.connection

    class MetrixWireCursor(base_cursor):  # type: ignore[misc, valid-type]
        def execute(self, query, vars=None):  # type: ignore[no-untyped-def]
            return db.instrument_execute(client, self, base_cursor.execute, query, vars)

        def executemany(self, query, vars_list):  # type: ignore[no-untyped-def]
            return db.instrument_execute(client, self, base_cursor.executemany, query, vars_list)

    class MetrixWireConnection(base_conn):  # type: ignore[misc, valid-type]
        def cursor(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            # Default any un-specified cursor to our instrumented subclass while
            # honouring an explicitly requested cursor_factory.
            kwargs.setdefault("cursor_factory", MetrixWireCursor)
            return super().cursor(*args, **kwargs)

        def commit(self):  # type: ignore[no-untyped-def]
            return db.instrument_commit(client, self, base_conn.commit)

    orig_connect = psycopg2.connect
    if getattr(orig_connect, "_metrixwire", False):
        _PATCHED = True
        return

    def connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        # Only inject our connection_factory when the caller hasn't supplied one.
        if "connection_factory" not in kwargs:
            kwargs["connection_factory"] = MetrixWireConnection
        return orig_connect(*args, **kwargs)

    connect._metrixwire = True  # type: ignore[attr-defined]
    psycopg2.connect = connect
    _PATCHED = True
