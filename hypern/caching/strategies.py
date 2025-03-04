import asyncio
import time
from abc import ABC, abstractmethod
from typing import Callable, Generic, Optional, TypeVar

import orjson

from .backend import BaseBackend

T = TypeVar("T")


class CacheStrategy(ABC, Generic[T]):
    """Base class for cache strategies"""

    @abstractmethod
    async def get(self, key: str) -> Optional[T]:
        pass

    @abstractmethod
    async def set(self, key: str, value: T, ttl: Optional[int] = None) -> None:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass


class CacheEntry(Generic[T]):
    """Represents a cached item with metadata"""

    def __init__(
        self,
        value: T,
        created_at: float,
        ttl: int,
        revalidate_after: Optional[int] = None,
    ):
        self.value = value
        self.created_at = created_at
        self.ttl = ttl
        self.revalidate_after = revalidate_after
        self.is_revalidating = False

    def is_stale(self) -> bool:
        """Check if entry is stale and needs revalidation"""
        now = time.time()
        return self.revalidate_after is not None and now > (
            self.created_at + self.revalidate_after
        )

    def is_expired(self) -> bool:
        """Check if entry has completely expired"""
        now = time.time()
        return now > (self.created_at + self.ttl)

    def to_json(self) -> bytes:
        """Serialize entry to JSON"""
        return orjson.dumps(
            {
                "value": self.value,
                "created_at": self.created_at,
                "ttl": self.ttl,
                "revalidate_after": self.revalidate_after,
                "is_revalidating": self.is_revalidating,
            }
        )

    @classmethod
    def from_json(cls, data: bytes) -> "CacheEntry[T]":
        """Deserialize entry from JSON"""
        parsed = orjson.loads(data)
        return cls(
            value=parsed["value"],
            created_at=parsed["created_at"],
            ttl=parsed["ttl"],
            revalidate_after=parsed["revalidate_after"],
        )


class StaleWhileRevalidateStrategy(CacheStrategy[T]):
    """
    Implements stale-while-revalidate caching strategy.
    Allows serving stale content while revalidating in the background.
    """

    def __init__(
        self,
        backend: BaseBackend,
        revalidate_after: int,
        ttl: int,
        revalidate_fn: Callable[..., T],
    ):
        """
        Initialize the caching strategy.

        Args:
            backend (BaseBackend): The backend storage for caching.
            revalidate_after (int): The time in seconds after which the cache should be revalidated.
            ttl (int): The time-to-live for cache entries in seconds.
            revalidate_fn (Callable[..., T]): The function to call for revalidating the cache.

        Attributes:
            backend (BaseBackend): The backend storage for caching.
            revalidate_after (int): The time in seconds after which the cache should be revalidated.
            ttl (int): The time-to-live for cache entries in seconds.
            revalidate_fn (Callable[..., T]): The function to call for revalidating the cache.
            _revalidation_locks (dict): A dictionary to manage revalidation locks.
        """
        self.backend = backend
        self.revalidate_after = revalidate_after
        self.ttl = ttl
        self.revalidate_fn = revalidate_fn
        self._revalidation_locks: dict = {}

    async def get(self, key: str) -> Optional[T]:
        entry = await self.backend.get(key)
        if not entry:
            return None

        if isinstance(entry, bytes):
            entry = CacheEntry.from_json(entry)

        # If entry is stale but not expired, trigger background revalidation
        if entry.is_stale() and not entry.is_expired():
            if not entry.is_revalidating:
                entry.is_revalidating = True
                await self.backend.set(key, entry.to_json())
                asyncio.create_task(self._revalidate(key))
            return entry.value

        # If entry is expired, return None
        if entry.is_expired():
            return None

        return entry.value

    async def set(self, key: str, value: T, ttl: Optional[int] = None) -> None:
        entry = CacheEntry(
            value=value,
            created_at=time.time(),
            ttl=ttl or self.ttl,
            revalidate_after=self.revalidate_after,
        )
        await self.backend.set(key, entry.to_json(), ttl=ttl)

    async def delete(self, key: str) -> None:
        await self.backend.delete(key)

    async def _revalidate(self, key: str) -> None:
        """Background revalidation of cached data"""
        try:
            # Prevent multiple simultaneous revalidations
            if key in self._revalidation_locks:
                return
            self._revalidation_locks[key] = True

            # Get fresh data
            fresh_value = await self.revalidate_fn(key)

            # Update cache with fresh data
            await self.set(key, fresh_value)
        finally:
            self._revalidation_locks.pop(key, None)


class CacheAsideStrategy(CacheStrategy[T]):
    """
    Implements cache-aside (lazy loading) strategy.
    Data is loaded into cache only when requested.
    """

    def __init__(
        self,
        backend: BaseBackend,
        load_fn: Callable[[str], T],
        ttl: int,
        write_through: bool = False,
    ):
        self.backend = backend
        self.load_fn = load_fn
        self.ttl = ttl
        self.write_through = write_through

    async def get(self, key: str) -> Optional[T]:
        # Try to get from cache first
        value = await self.backend.get(key)
        if value:
            if isinstance(value, bytes):
                value = orjson.loads(value)
            return value

        # On cache miss, load from source
        value = await self.load_fn(key)
        if value is not None:
            await self.set(key, value)
        return value

    async def set(self, key: str, value: T, ttl: Optional[int] = None) -> None:
        await self.backend.set(key, value, ttl or self.ttl)

        # If write-through is enabled, update the source
        if self.write_through:
            await self._write_to_source(key, value)

    async def delete(self, key: str) -> None:
        await self.backend.delete(key)

    async def _write_to_source(self, key: str, value: T) -> None:
        """Write to the source in write-through mode"""
        if hasattr(self.load_fn, "write"):
            await self.load_fn.write(key, value)


def cache_with_strategy(
    strategy: CacheStrategy, key_prefix: str | None = None, ttl: int = 3600
):
    """
    Decorator for using cache strategies
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"{key_prefix or func.__name__}:{hash(str(args) + str(kwargs))}"

            result = await strategy.get(cache_key)
            if result is not None:
                return result

            # Execute function and cache result
            result = await func(*args, **kwargs)
            if result is not None:
                await strategy.set(cache_key, result, ttl)

            return result

        return wrapper

    return decorator
