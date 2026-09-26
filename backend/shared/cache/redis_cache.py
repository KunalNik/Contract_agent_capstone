import json
import hashlib
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Optional, Dict
from functools import wraps

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)


def cache_enabled() -> bool:
    return os.getenv("CACHE_ENABLED", "false").lower() in ("1", "true", "yes")


class RedisCache:
    """Redis-based caching for CUAD analysis results (in-memory fallback)."""

    def __init__(self):
        self.redis_client = None
        self._connect()

    def _connect(self):
        """Connect to Redis only when caching is enabled; otherwise use a bounded in-memory cache."""
        if not cache_enabled():
            self.redis_client = InMemoryCache()
            return
        try:
            import redis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()
            logger.info("Connected to Redis cache")
        except Exception as e:
            logger.warning(f"Redis connection failed, using in-memory cache: {e}")
            self.redis_client = InMemoryCache()

    def get(self, key: str) -> Optional[Any]:
        """Get cached value"""
        try:
            value = self.redis_client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.error(f"Cache get failed for key {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Set cached value with TTL"""
        try:
            serialized = json.dumps(value, default=str)
            return self.redis_client.setex(key, ttl, serialized)
        except Exception as e:
            logger.error(f"Cache set failed for key {key}: {e}")
            return False

    def incr(self, key: str) -> int:
        """Atomically increment a counter (used for cache-generation invalidation)."""
        try:
            return int(self.redis_client.incr(key))
        except Exception as e:
            logger.error(f"Cache incr failed for key {key}: {e}")
            return 0

    def generate_key(self, prefix: str, *args) -> str:
        """Generate cache key from arguments (prefix kept readable for debugging)."""
        key_data = ':'.join(str(arg) for arg in args)
        return f"{prefix}:{hashlib.md5(key_data.encode()).hexdigest()}"


class InMemoryCache:
    """Fallback in-memory cache with TTL expiry and a size bound (LRU)."""

    def __init__(self, max_entries: int = 1000):
        self._cache: "OrderedDict[str, tuple]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_entries = max_entries

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at is not None and expires_at < time.time():
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value

    def setex(self, key: str, ttl: int, value: str) -> bool:
        with self._lock:
            self._cache[key] = (time.time() + ttl if ttl else None, value)
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
        return True

    def incr(self, key: str) -> int:
        with self._lock:
            _, value = self._cache.get(key, (None, "0"))
            new_value = int(value) + 1
            self._cache[key] = (None, str(new_value))
            return new_value

    def ping(self):
        return True


# Global cache instance
cache = RedisCache()


def cache_result(prefix: str, ttl: int = 3600, method: bool = False):
    """Decorator for caching function results.

    ``method=True`` excludes ``self`` from the key: its default repr contains a
    memory address, so keys never matched across instances and the cache only
    grew. Pass-through when CACHE_ENABLED is false.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not cache_enabled():
                return func(*args, **kwargs)
            key_args = args[1:] if method else args
            cache_key = cache.generate_key(prefix, *key_args, *sorted(kwargs.items()))

            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            result = func(*args, **kwargs)
            if result is not None:
                cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator
