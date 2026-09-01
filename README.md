# metrixwire (Python)

Zero-config APM SDK for **Python**. Call `init()` once — every request, database query, cache op and outbound HTTP call is instrumented automatically. There is no manual span API and no middleware to wire up. Non-blocking: if the MetrixWire endpoint is down, your app keeps running normally.

## Installation

```bash
pip install metrixwire
```

Zero required dependencies — the core uses only the standard library.

## Usage

```python
import metrixwire

metrixwire.init(api_key="mw_...")
```

That's it. Do this once, as early as possible in your process (before your server starts). Every HTTP request becomes a **trace**, and every query / HTTP call / cache op within it becomes a **span**.

### Auto-init as early as possible

Import and init at the very top of your entry module (or a `sitecustomize.py` on your `PYTHONPATH`) so the patches are installed before your framework and drivers are used:

```python
# sitecustomize.py — or the first lines of your app's entry point
import metrixwire
metrixwire.init()  # reads METRIXWIRE_KEY / METRIXWIRE_ENDPOINT / METRIXWIRE_ENABLED from env
```

With no arguments, `init()` reads its config from the environment:

| Env var | Purpose |
|---|---|
| `METRIXWIRE_KEY` | Project API key (required to enable) |
| `METRIXWIRE_ENDPOINT` | Ingest URL — base or full `/ingest` (default `https://metrixwire.com/ingest`) |
| `METRIXWIRE_ENABLED` | `false` to disable entirely |

A missing API key runs the SDK **disabled** — it never raises.

## How the automatic tracing works

A trace is opened for **every incoming request** by patching each framework's single entry point — no middleware, no per-route setup:

| Framework | Traced automatically | How |
|---|---|---|
| **Flask** | ✅ | wraps `Flask.wsgi_app`; route from the matched URL rule (`/users/<id>`) |
| **Django** | ✅ | patches `WSGIHandler.__call__` and `ASGIHandler.__call__`; route from the resolver match |
| **FastAPI · Starlette** | ✅ | wraps `Starlette.__call__` (ASGI); route from the matched pattern (`/users/{id}`) |
| **Bare / other WSGI** (`wsgiref`, …) | ✅ | wrap once with `metrixwire.wsgi.MetrixWireMiddleware` |

For a bare or unsupported WSGI app:

```python
from metrixwire.wsgi import MetrixWireMiddleware
app = MetrixWireMiddleware(app)
```

Each trace records the route, HTTP status, response byte size (for the large-response detector), memory growth (for the memory-spike detector), and any unhandled exception.

## Automatically instrumented libraries

Installed via `init()` — each is best-effort: if the library isn't importable it's skipped silently.

| Library | Span | How |
|---|---|---|
| **psycopg2** | `db_query` (`rowCount`) | patches `psycopg2.extensions.cursor.execute`/`executemany` |
| **psycopg (v3)** | `db_query` (`rowCount`) | patches `psycopg.Cursor.execute`/`executemany` |
| **sqlite3** | `db_query` (`rowCount`) | patches `sqlite3.Cursor.execute`/`executemany` |
| **PyMySQL · mysqlclient** | `db_query` (`rowCount`) | patches the driver's `Cursor.execute`/`executemany` |
| **Django ORM · SQLAlchemy** | `db_query` | automatic — they run on the drivers above |
| **requests** | `http_call` (`statusCode`) | patches `Session.request` |
| **stdlib `http.client` / `urllib`** | `http_call` (`statusCode`) | patches `HTTPConnection.request`/`getresponse` |
| **redis-py** | cache (`custom`, `kind=cache`) | patches `Redis.execute_command` (records hit/miss) |
| **DB transactions** | `custom` (`kind=transaction`) | times `BEGIN…COMMIT` / `connection.commit()` |

Database spans also capture a `sourceLocation` (`file.py:42`) pointing at the nearest application frame.

## `init` options

```python
metrixwire.init(
    api_key="mw_...",                        # required (or METRIXWIRE_KEY)
    endpoint="https://metrixwire.com/ingest",  # default; base URL is accepted too
    flush_interval_ms=5000,                   # how often batches are sent
    enabled=True,                             # set False to disable entirely
    timeout_ms=3000,                          # send timeout (short, non-blocking)
    max_batch=20,                             # flush immediately once this many are queued
    capture_source=True,                      # capture the file:line a span originated from
)
```

## Escape hatch

Requests, queries, HTTP calls and cache ops are all captured automatically. The one manual helper — for frameworks that catch their own errors before the SDK sees them — is:

```python
import metrixwire

try:
    ...
except Exception as e:
    metrixwire.capture_exception(e)   # attach it to the active trace
    raise
```

## Non-blocking behavior

- Traces are batched and sent **off the request path** on a background daemon thread with a short timeout.
- **All** transport errors are swallowed — instrumentation never throws into your app.
- A final flush runs at process exit (`atexit`); you can also call `metrixwire.flush()` before a short-lived process exits.
