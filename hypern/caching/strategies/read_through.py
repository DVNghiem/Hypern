import asyncio
from typing import Callable, Optional, TypeVar

import orjson

from hypern.caching.backend import BaseBackend

from .interface import CacheStrategy

T = TypeVar("T")


class ReadThroughStrategy(CacheStrategy[T]):
    """Read-Through: load from cache if available, otherwise load from backend"""

    def __init__(self, backend: BaseBackend, load_fn: Callable[[str], T], ttl: int):
        self.backend = backend
        self.load_fn = load_fn
        self.ttl = ttl

    async def get(self, key: str) -> Optional[T]:
        value = await self.backend.get(key)
        if value is not None:
            return orjson.loads(value) if isinstance(value, bytes) else value

        value = await self.load_fn(key)
        if value is not None:
            await self.set(key, value)
        return value

    async def set(self, key: str, value: T, ttl: Optional[int] = None) -> None:
        serialized_value = orjson.dumps(value)
        await self.backend.set(key, serialized_value, ttl or self.ttl)

    async def delete(self, key: str) -> None:
        await self.backend.delete(key)
