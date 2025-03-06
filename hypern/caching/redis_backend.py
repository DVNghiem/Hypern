import pickle
from typing import Any, Optional

from redis import asyncio as aioredis

from hypern.logging import logger

from .backend import BaseBackend


class RedisBackend(BaseBackend):
    def __init__(
        self,
        url: str = "redis://localhost:6379",
        encoding: str = "utf-8",
        decode_responses: bool = False,
        **kwargs,
    ):
        """
        Initialize Redis backend with aioredis

        Args:
            url: Redis connection URL
            encoding: Character encoding to use
            decode_responses: Whether to decode response bytes to strings
            **kwargs: Additional arguments passed to aioredis.from_url
        """
        self.redis = aioredis.from_url(
            url, encoding=encoding, decode_responses=decode_responses, **kwargs
        )
        self._encoding = encoding

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from Redis

        Args:
            key: Cache key

        Returns:
            Deserialized Python object or None if key doesn't exist
        """
        try:
            value = await self.redis.get(key)
            if value is not None:
                return pickle.loads(value)
            return None
        except Exception as e:
            logger.error(f"Error getting cache key {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Set value in Redis with optional TTL

        Args:
            key: Cache key
            value: Python object to store
            ttl: Time to live in seconds

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            serialized = pickle.dumps(value)
            if ttl is not None:
                await self.redis.setex(key, ttl, serialized)
            else:
                await self.redis.set(key, serialized)
            return True
        except Exception as e:
            logger.error(f"Error setting cache key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete key from Redis

        Args:
            key: Cache key to delete

        Returns:
            bool: True if key was deleted, False otherwise
        """
        try:
            return bool(await self.redis.delete(key))
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {e}")
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching pattern

        Args:
            pattern: Redis key pattern to match

        Returns:
            int: Number of keys deleted
        """
        try:
            keys = await self.redis.keys(pattern)
            if keys:
                return await self.redis.delete(*keys)
            return len(keys)
        except Exception as e:
            logger.error(f"Error deleting keys matching {pattern}: {e}")
            return 0

    async def exists(self, key: str) -> bool:
        """
        Check if key exists

        Args:
            key: Cache key to check

        Returns:
            bool: True if key exists, False otherwise
        """
        try:
            return bool(await self.redis.exists(key))
        except Exception as e:
            logger.error(f"Error checking existence of key {key}: {e}")
            return False

    async def ttl(self, key: str) -> int:
        """
        Get TTL of key in seconds

        Args:
            key: Cache key

        Returns:
            int: TTL in seconds, -2 if key doesn't exist, -1 if key has no TTL
        """
        try:
            return await self.redis.ttl(key)
        except Exception as e:
            logger.error(f"Error getting TTL for key {key}: {e}")
            return -2

    async def incr(self, key: str, amount: int = 1) -> int | None:
        """
        Increment value by amount

        Args:
            key: Cache key
            amount: Amount to increment by

        Returns:
            int: New value after increment or None on error
        """
        try:
            return await self.redis.incrby(key, amount)
        except Exception as e:
            logger.error(f"Error incrementing key {key}: {e}")
            return None

    async def set_nx(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Set key only if it doesn't exist (SET NX operation)

        Args:
            key: Cache key
            value: Value to set
            ttl: Optional TTL in seconds

        Returns:
            bool: True if key was set, False otherwise
        """
        try:
            serialized = pickle.dumps(value)
            if ttl is not None:
                return await self.redis.set(key, serialized, nx=True, ex=ttl)
            return await self.redis.set(key, serialized, nx=True)
        except Exception as e:
            logger.error(f"Error setting NX for key {key}: {e}")
            return False

    async def clear(self) -> bool:
        """
        Clear all keys from the current database

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            await self.redis.flushdb()
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False

    async def close(self) -> None:
        """Close Redis connection"""
        await self.redis.close()

    async def ping(self) -> bool:
        """
        Check Redis connection

        Returns:
            bool: True if connection is alive, False otherwise
        """
        try:
            return await self.redis.ping()
        except Exception:
            return False
