"""Redis integration for Hypern.

Provides a connection-pooled Redis client backed by Rust
(``deadpool-redis`` + ``redis`` crate).

Example::

    from hypern.redis import RedisPool

    redis = RedisPool("redis://127.0.0.1/")
    redis.set("key", "value", ex=60)
    val = redis.get("key")
"""

from hypern._hypern import RedisPool

__all__ = ["RedisPool"]
