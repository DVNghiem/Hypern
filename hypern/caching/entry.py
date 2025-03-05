import time
from typing import Generic, Optional, TypeVar
import orjson

T = TypeVar("T")

class CacheEntry(Generic[T]):
    """presentative cache with metadata"""
    def __init__(self, value: T, created_at: float, ttl: int, revalidate_after: Optional[int] = None):
        self.value = value
        self.created_at = created_at
        self.ttl = ttl
        self.revalidate_after = revalidate_after
        self.is_revalidating = False

    def is_stale(self) -> bool:
        return self.revalidate_after is not None and time.time() > (self.created_at + self.revalidate_after)

    def is_expired(self) -> bool:
        return time.time() > (self.created_at + self.ttl)

    def to_json(self) -> bytes:
        return orjson.dumps({
            "value": self.value,
            "created_at": self.created_at,
            "ttl": self.ttl,
            "revalidate_after": self.revalidate_after,
            "is_revalidating": self.is_revalidating,
        })

    @classmethod
    def from_json(cls, data: bytes) -> "CacheEntry[T]":
        parsed = orjson.loads(data)
        return cls(
            value=parsed["value"],
            created_at=parsed["created_at"],
            ttl=parsed["ttl"],
            revalidate_after=parsed["revalidate_after"]
        )
