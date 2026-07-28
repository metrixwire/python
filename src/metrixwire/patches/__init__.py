"""Auto-instrumentation registry.

``install_all`` runs every patch in its own ``try/except`` so one broken or
missing target can never stop the others — and never breaks ``init()``. Each
patch is idempotent (guards against double-patching) and skips silently when its
target library isn't importable.
"""

from __future__ import annotations

from typing import Any, Callable, List


def install_all(client: Any) -> None:
    patchers: List[Callable[[Any], None]] = []

    # Web frameworks (open one trace per request).
    from . import flask_patch, django_patch, starlette_patch

    patchers += [
        flask_patch.install,
        django_patch.install,
        starlette_patch.install,
    ]

    # DB drivers (db_query spans).
    from . import sqlite3_patch, psycopg2_patch, psycopg3_patch, pymysql_patch, mysqldb_patch

    patchers += [
        sqlite3_patch.install,
        psycopg2_patch.install,
        psycopg3_patch.install,
        pymysql_patch.install,
        mysqldb_patch.install,
    ]

    # Outbound HTTP (http_call spans).
    from . import requests_patch, httpclient_patch

    patchers += [requests_patch.install, httpclient_patch.install]

    # Cache (custom span, kind=cache).
    from . import redis_patch

    patchers += [redis_patch.install]

    for patcher in patchers:
        try:
            patcher(client)
        except Exception:
            # A single failing/absent target must never break the others.
            pass
