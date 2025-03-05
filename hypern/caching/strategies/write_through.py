import asyncio
from typing import Callable, Optional, TypeVar

import orjson

from hypern.caching.backend import BaseBackend

from .interface import CacheStrategy

T = TypeVar("T")


class WriteThroughStrategy(CacheStrategy[T]):
    """Write-Through: write to cache and backend at the same time"""

    def __init__(
        self, backend: BaseBackend, write_fn: Callable[[str, T], None], ttl: int
    ):
        self.backend = backend
        self.write_fn = write_fn
        self.ttl = ttl

    async def get(self, key: str) -> Optional[T]:
        value = await self.backend.get(key)
        return orjson.loads(value) if value else None

    async def set(self, key: str, value: T, ttl: Optional[int] = None) -> None:
        serialized_value = orjson.dumps(value)
        await asyncio.gather(
            self.backend.set(key, serialized_value, ttl or self.ttl),
            self.write_fn(key, value),
        )

    async def delete(self, key: str) -> None:
        await self.backend.delete(key)
