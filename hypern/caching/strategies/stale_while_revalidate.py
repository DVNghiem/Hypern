import asyncio
import time
from typing import Callable, Dict, Optional, TypeVar

from hypern.caching.backend import BaseBackend
from hypern.caching.entry import CacheEntry

from .interface import CacheStrategy

T = TypeVar("T")


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
        revalidate_fn: Callable[[str], T],
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
        self._revalidation_locks: Dict[str, asyncio.Lock] = {}

    async def get(self, key: str) -> Optional[T]:
        entry_data = await self.backend.get(key)
        if not entry_data:
            return None

        entry = CacheEntry.from_json(entry_data)

        if entry.is_stale() and not entry.is_expired():
            if not entry.is_revalidating:
                entry.is_revalidating = True
                await self.backend.set(key, entry.to_json())
                asyncio.create_task(self._revalidate(key))
            return entry.value

        if entry.is_expired():
            await self.backend.delete(key)
            return None

        return entry.value

    async def set(self, key: str, value: T, ttl: Optional[int] = None) -> None:
        entry = CacheEntry(
            value=value,
            created_at=time.time(),
            ttl=ttl or self.ttl,
            revalidate_after=self.revalidate_after,
        )
        await self.backend.set(key, entry.to_json(), ttl=ttl or self.ttl)

    async def delete(self, key: str) -> None:
        await self.backend.delete(key)

    async def _revalidate(self, key: str) -> None:
        lock = self._revalidation_locks.setdefault(key, asyncio.Lock())
        async with lock:
            fresh_value = await self.revalidate_fn(key)
            await self.set(key, fresh_value)
