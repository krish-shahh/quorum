"""Lightweight in-memory cache for data fetching calls.

Reduces redundant yfinance/news API calls when multiple agents or
re-analyses hit the same ticker within a short window.

Default TTL: 1 hour (3600s). Configurable via ``data_cache_ttl`` config
key or ``TRADINGAGENTS_DATA_CACHE_TTL`` env var.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 3600  # 1 hour

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def cached(ttl: Optional[int] = None):
    """Decorator that caches function results by arguments.

    Usage::

        @cached(ttl=3600)
        def get_stock_data(ticker, start, end):
            ...
    """
    cache_ttl = ttl or _DEFAULT_TTL

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            key = _make_key(func.__name__, args, kwargs)
            now = time.monotonic()

            with _lock:
                if key in _cache:
                    ts, val = _cache[key]
                    if now - ts < cache_ttl:
                        return val

            result = func(*args, **kwargs)

            with _lock:
                _cache[key] = (now, result)

            return result

        wrapper.__wrapped__ = func
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


def invalidate(func_name: Optional[str] = None) -> int:
    """Clear cached entries. If func_name given, only clear that function's cache."""
    with _lock:
        if func_name is None:
            n = len(_cache)
            _cache.clear()
            return n
        keys_to_remove = [k for k in _cache if k.startswith(f"{func_name}:")]
        for k in keys_to_remove:
            del _cache[k]
        return len(keys_to_remove)


def cache_stats() -> dict[str, Any]:
    """Return cache statistics."""
    with _lock:
        now = time.monotonic()
        total = len(_cache)
        expired = sum(1 for ts, _ in _cache.values() if now - ts >= _DEFAULT_TTL)
        return {"total_entries": total, "expired": expired, "active": total - expired}


def _make_key(func_name: str, args: tuple, kwargs: dict) -> str:
    raw = f"{func_name}:{args}:{sorted(kwargs.items())}"
    return f"{func_name}:{hashlib.md5(raw.encode()).hexdigest()}"
