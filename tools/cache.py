"""
Digital Pathology — Persistent Computation Cache
SQLite-backed diskcache with 7-day TTL for expensive spatial computations.

Usage:
    @cached_computation("spatial_stats")
    def compute_ripley_k(cells: list, radii: list) -> dict:
        ...
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import wraps
from typing import Any, Callable

import diskcache

from config import CACHE_DIR, CACHE_TTL

logger = logging.getLogger(__name__)

_cache: diskcache.Cache | None = None


def get_cache() -> diskcache.Cache:
    """Return (or initialize) the global diskcache instance."""
    global _cache
    if _cache is None:
        _cache = diskcache.Cache(str(CACHE_DIR), timeout=1)
    return _cache


def make_cache_key(namespace: str, **kwargs: Any) -> str:
    """Generate a deterministic SHA-256 cache key from namespace + query params."""
    payload = json.dumps({"ns": namespace, **kwargs}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def cached_get(key: str) -> Any | None:
    """Retrieve a cached value; returns None on miss or error."""
    try:
        cache = get_cache()
        return cache.get(key)
    except Exception as exc:
        logger.debug("Cache read miss/error for key %s: %s", key[:16], exc)
        return None


def cached_set(key: str, value: Any, ttl: int = CACHE_TTL) -> None:
    """Store a value in the cache with TTL. Silently ignores errors."""
    try:
        cache = get_cache()
        cache.set(key, value, expire=ttl)
    except Exception as exc:
        logger.debug("Cache write error for key %s: %s", key[:16], exc)


def cached_computation(namespace: str, ttl: int = CACHE_TTL):
    """
    Decorator factory for synchronous computation functions.

    Usage:
        @cached_computation("density")
        def compute_density(cells, area_mm2) -> float:
            ...

    The cache key is derived from the namespace + all call arguments.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = make_cache_key(namespace, args=args, kwargs=kwargs)
            cached = cached_get(key)
            if cached is not None:
                logger.debug("Cache HIT  [%s] key=%s...", namespace, key[:12])
                return cached
            logger.debug("Cache MISS [%s] key=%s...", namespace, key[:12])
            result = func(*args, **kwargs)
            if result is not None:
                cached_set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator


def cached_api_call(namespace: str, ttl: int = CACHE_TTL):
    """
    Decorator factory for async API/IO functions (mirrors oncomoa_agent pattern).

    Usage:
        @cached_api_call("cell_loader")
        async def load_cells(path: str) -> list:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = make_cache_key(namespace, args=args, kwargs=kwargs)
            cached = cached_get(key)
            if cached is not None:
                logger.debug("Cache HIT  [%s] key=%s...", namespace, key[:12])
                return cached
            logger.debug("Cache MISS [%s] key=%s...", namespace, key[:12])
            result = await func(*args, **kwargs)
            if result is not None:
                cached_set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator


def clear_cache() -> None:
    """Clear all cached entries (useful for testing)."""
    get_cache().clear()
    logger.info("Cache cleared.")
