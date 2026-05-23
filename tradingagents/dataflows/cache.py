"""Lightweight in-memory cache for data fetching calls.

Reduces redundant yfinance/news API calls when multiple agents or
re-analyses hit the same ticker within a short window.

Two decorators:
  @cached(ttl=3600)          — fixed TTL, resolved at decoration time
  @cached_config("price")    — TTL from config["cache_ttls"][category],
                               resolved at call time (lazy)
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
_stats: dict[str, dict[str, int]] = {}  # func_name -> {hits, misses}


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
                        _track_hit(func.__name__)
                        return val

            _track_miss(func.__name__)
            result = func(*args, **kwargs)

            with _lock:
                _cache[key] = (now, result)

            return result

        wrapper.__wrapped__ = func
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


def cached_config(category: str):
    """Decorator that reads TTL from config at call time (lazy).

    Usage::

        @cached_config("price")
        def get_stock_data(ticker, start, end):
            ...

    Reads config["cache_ttls"][category] on every call so TTL changes
    take effect without restarting. Falls back to _DEFAULT_TTL if the
    category or config key is missing.
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            # Resolve TTL lazily from config
            try:
                from tradingagents.default_config import DEFAULT_CONFIG
                cache_ttl = DEFAULT_CONFIG.get("cache_ttls", {}).get(category, _DEFAULT_TTL)
            except Exception:
                cache_ttl = _DEFAULT_TTL

            key = _make_key(func.__name__, args, kwargs)
            now = time.monotonic()

            with _lock:
                if key in _cache:
                    ts, val = _cache[key]
                    if now - ts < cache_ttl:
                        _track_hit(func.__name__)
                        return val

            _track_miss(func.__name__)
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
    """Return cache statistics including per-function hit/miss counts."""
    with _lock:
        now = time.monotonic()
        total = len(_cache)
        expired = sum(1 for ts, _ in _cache.values() if now - ts >= _DEFAULT_TTL)
        return {
            "total_entries": total,
            "expired": expired,
            "active": total - expired,
            "per_function": dict(_stats),
        }


def _track_hit(func_name: str):
    if func_name not in _stats:
        _stats[func_name] = {"hits": 0, "misses": 0}
    _stats[func_name]["hits"] += 1


def _track_miss(func_name: str):
    if func_name not in _stats:
        _stats[func_name] = {"hits": 0, "misses": 0}
    _stats[func_name]["misses"] += 1


def _make_key(func_name: str, args: tuple, kwargs: dict) -> str:
    raw = f"{func_name}:{args}:{sorted(kwargs.items())}"
    return f"{func_name}:{hashlib.md5(raw.encode()).hexdigest()}"
