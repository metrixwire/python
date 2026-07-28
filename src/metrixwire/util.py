"""Shared best-effort helpers for the instrumentation patches.

All functions here are defensive and never raise: source-location capture,
memory measurement, and response-size accounting. If a measurement can't be
taken we return a neutral value rather than let instrumentation break the app.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

# The SDK's own package directory — frames under it are ours and skipped when
# finding the nearest user frame. Computed from this file's location so it's
# exact (a loose "metrixwire" substring would wrongly match a repo/app that
# merely lives under a path containing that word).
_SDK_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep

# Frames whose files live inside these path fragments are library/runtime code
# (installed dependencies or the stdlib) and are skipped too.
_SKIP_FRAGMENTS = (
    os.sep + "site-packages" + os.sep,
    os.sep + "dist-packages" + os.sep,
    os.sep + "lib" + os.sep + "python",
)


def _is_sdk_or_library(filename: str) -> bool:
    if filename.startswith(_SDK_DIR):
        return True
    return any(fragment in filename for fragment in _SKIP_FRAGMENTS)


def nearest_user_frame() -> Optional[str]:
    """Return ``file.py:42`` for the closest application (non-library) frame.

    Walks up the current stack, skipping the SDK itself and installed
    third-party packages, so a db_query span points at the line the developer
    actually wrote. Best-effort — returns ``None`` if nothing suitable is found.
    """
    try:
        frame = sys._getframe(1)
    except Exception:
        return None
    try:
        first_fallback: Optional[str] = None
        while frame is not None:
            filename = frame.f_code.co_filename or ""
            lineno = frame.f_lineno
            if filename and not filename.startswith("<"):
                loc = "%s:%d" % (os.path.basename(filename), lineno)
                if first_fallback is None:
                    first_fallback = loc
                if not _is_sdk_or_library(filename):
                    return loc
            frame = frame.f_back
        return first_fallback
    except Exception:
        return None
    finally:
        del frame


def _rss_bytes() -> int:
    """Current resident-set size in bytes, best-effort (0 if unavailable)."""
    try:
        import resource

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is KB on Linux, bytes on macOS. Normalise heuristically:
        # values below ~4 GB are almost certainly KB (i.e. Linux).
        if sys.platform == "darwin":
            return int(maxrss)
        return int(maxrss) * 1024
    except Exception:
        return 0


def memory_snapshot() -> int:
    """A monotonic-ish memory snapshot in bytes for computing a request delta."""
    return _rss_bytes()


def memory_delta_mb(start_bytes: int) -> int:
    """Megabytes of RSS growth since ``start_bytes`` (0 if it shrank/unknown)."""
    try:
        if start_bytes <= 0:
            return 0
        delta = _rss_bytes() - start_bytes
        if delta <= 0:
            return 0
        return int(round(delta / (1024 * 1024)))
    except Exception:
        return 0
