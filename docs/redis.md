# Redis

Hypern provides a Redis client with connection pooling, backed by the Rust `redis` crate and `deadpool-redis` for pool management.

## Quick Start

```python
from hypern.redis import RedisPool

redis = RedisPool("redis://127.0.0.1/")

# Basic operations
redis.set("key", "value", ex=60)  # SET with 60s expiry
value = redis.get("key")           # GET
redis.delete("key")                # DEL
```

## API Reference

### RedisPool

```python
RedisPool(url, pool_size=16)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | — | Redis connection URL (e.g. `redis://127.0.0.1/`) |
| `pool_size` | `int` | `16` | Maximum number of connections |

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `get` | `get(key) -> Optional[str]` | Get a key's value. Returns `None` if not found. |
| `set` | `set(key, value, ex=None)` | Set a key. Optional `ex` sets expiry in seconds. |
| `delete` | `delete(key) -> int` | Delete a key. Returns number of keys removed. |
| `expire` | `expire(key, seconds) -> bool` | Set expiry on an existing key. |
| `incr` | `incr(key) -> int` | Increment a key by 1. Returns the new value. |
| `publish` | `publish(channel, message) -> int` | Publish to a pub/sub channel. Returns subscriber count. |
| `ping` | `ping() -> bool` | Check if the Redis server is reachable. |

## Examples

### Session store

```python
import json

redis = RedisPool("redis://127.0.0.1/")

def create_session(user_id: str, data: dict, ttl: int = 3600) -> str:
    session_id = generate_session_id()
    redis.set(f"session:{session_id}", json.dumps(data), ex=ttl)
    return session_id

def get_session(session_id: str) -> dict | None:
    raw = redis.get(f"session:{session_id}")
    if raw is None:
        return None
    return json.loads(raw)
```

### Rate limiting

```python
def check_rate_limit(client_ip: str, max_requests: int = 100, window: int = 60) -> bool:
    key = f"rate:{client_ip}"
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, window)
    return count <= max_requests
```

### Pub/Sub publishing

```python
redis.publish("events", json.dumps({"type": "user.created", "id": "123"}))
```

## Integration with JWTAuth

Use Redis to store JWT refresh token JTIs for cross-process token blacklisting:

```python
from hypern.auth import JWTAuth
from hypern.redis import RedisPool

redis = RedisPool("redis://127.0.0.1/")
jwt = JWTAuth(secret="my-secret")

# On token creation
token = jwt.encode({"user_id": "123"})
redis.set(f"jwt:{token_jti}", "1", ex=3600)

# On token validation
def validate_token(token: str) -> bool:
    payload = jwt.decode(token)
    jti = payload.get("jti")
    if jti and redis.get(f"jwt:{jti}") is None:
        return False  # Token has been revoked
    return True
```
