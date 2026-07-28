"""PyMySQL auto-instrumentation.

Patches ``pymysql.cursors.Cursor.execute`` / ``executemany`` so MySQL queries
become ``db_query`` spans with ``rowCount``. Skips silently if PyMySQL isn't
installed.
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
        from pymysql import cursors
    except Exception:
        return

    Cursor = cursors.Cursor
    if getattr(Cursor.execute, "_metrixwire", False):
        _PATCHED = True
        return

    orig_execute = Cursor.execute
    orig_executemany = Cursor.executemany

    def execute(self, query, args=None):  # type: ignore[no-untyped-def]
        return db.instrument_execute(client, self, orig_execute, query, args)

    def executemany(self, query, args):  # type: ignore[no-untyped-def]
        return db.instrument_execute(client, self, orig_executemany, query, args)

    execute._metrixwire = True  # type: ignore[attr-defined]
    try:
        Cursor.execute = execute  # type: ignore[assignment]
        Cursor.executemany = executemany  # type: ignore[assignment]
        _PATCHED = True
    except (TypeError, AttributeError):
        pass
