from typing import TypeVar

from .strategies.interface import CacheStrategy

T = TypeVar("T")


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
