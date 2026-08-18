"""In-process rate limiting for auth endpoints.

Known limitation, accepted (SPEC.md §7): the store is a module-level dict, so
limits are per gunicorn worker. With `--workers 2` the effective allowance
doubles and blocking is inconsistent between requests. That is tolerable for an
invite-scale app and is not tolerable for a public one — the replacement is a
`login_attempts` table, not a bigger dict.

Buckets are namespaced so login and registration are limited independently.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
# (bucket, key) -> [attempt timestamps]
_attempts: dict[tuple[str, str], list[float]] = {}
# (bucket, key) -> blocked-until timestamp
_blocked: dict[tuple[str, str], float] = {}


def _prune(now: float, window_seconds: float, entry: list[float]) -> list[float]:
    return [t for t in entry if now - t < window_seconds]


def is_blocked(bucket: str, key: str) -> bool:
    now = time.time()
    with _lock:
        until = _blocked.get((bucket, key))
        if until is None:
            return False
        if until <= now:
            _blocked.pop((bucket, key), None)
            return False
        return True


def retry_after_seconds(bucket: str, key: str) -> int:
    now = time.time()
    with _lock:
        until = _blocked.get((bucket, key), now)
    return max(0, int(until - now))


def record_failure(
    bucket: str, key: str, *, max_attempts: int, window_minutes: int, block_minutes: int
) -> None:
    now = time.time()
    window_seconds = window_minutes * 60
    with _lock:
        entry = _prune(now, window_seconds, _attempts.get((bucket, key), []))
        entry.append(now)
        _attempts[(bucket, key)] = entry
        if len(entry) >= max_attempts:
            _blocked[(bucket, key)] = now + block_minutes * 60
            _attempts.pop((bucket, key), None)


def reset(bucket: str, key: str) -> None:
    with _lock:
        _attempts.pop((bucket, key), None)
        _blocked.pop((bucket, key), None)


def clear_all() -> None:
    """Test helper. Never called from application code."""
    with _lock:
        _attempts.clear()
        _blocked.clear()
