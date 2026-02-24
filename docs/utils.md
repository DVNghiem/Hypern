# Utilities

Hypern ships a collection of **Rust-accelerated utility functions** accessible from Python via `hypern.utils`. Every function is implemented in Rust with PyO3 bindings, giving you 5–50× speedups over equivalent pure-Python code while releasing the GIL where possible for safe concurrent use.

```python
from hypern.utils import (
    # Strings
    slugify, truncate, mask_email, mask_phone, mask_string,
    snake_to_camel, camel_to_snake, keys_to_camel, keys_to_snake,
    pad_left, pad_right, word_count, is_url_safe,
    # Pagination
    paginate, encode_cursor, decode_cursor, PageInfo,
    # Crypto & IDs
    random_token, random_bytes, sha256_hex,
    hmac_sha256_hex, hmac_sha256_bytes, secure_compare,
    b64_encode, b64_decode, b64url_encode, b64url_decode,
    uuid_v4, uuid_v7, fast_hash, fast_hash_bytes,
    # Time
    now_ms, now_sec, now_iso, format_timestamp,
    parse_iso, relative_time, elapsed_ms, ms_to_sec, sec_to_ms,
)
```

---

## String Helpers

### `slugify(text, separator="-")`

Convert arbitrary text into a URL-safe slug by lowercasing, replacing
non-alphanumeric characters with the separator, and collapsing duplicates.

```python
slugify("Hello World! 2024")       # "hello-world-2024"
slugify("Café Résumé", "_")        # "caf-rsum"
```

### `truncate(text, max_len, suffix="...")`

Truncate a string at `max_len` characters (including the suffix).

```python
truncate("abcdefghij", 7)          # "abcd..."
truncate("short", 10)              # "short"
```

### `mask_email(email)`

Mask an email address for display, preserving the first and last character of
the local part plus the full domain.

```python
mask_email("john@example.com")     # "j**n@example.com"
```

### `mask_phone(phone, keep_last=4)`

Mask a phone number, keeping only the last *N* visible digits.

```python
mask_phone("+1-234-567-8901")      # "*******8901"
mask_phone("5551234", 3)           # "****234"
```

### `mask_string(text, keep_start=1, keep_end=1)`

Generic masking — keep the first and last *N* characters visible, replace the
rest with `*`.

```python
mask_string("sensitive", 2, 2)     # "se*****ve"
```

### `snake_to_camel(text, upper_first=False)`

Convert `snake_case` to `camelCase` (or `PascalCase` with `upper_first=True`).

```python
snake_to_camel("hello_world")              # "helloWorld"
snake_to_camel("hello_world", True)        # "HelloWorld"
```

### `camel_to_snake(text)`

Convert `camelCase` or `PascalCase` to `snake_case`.

```python
camel_to_snake("helloWorld")       # "hello_world"
camel_to_snake("HTTPResponse")     # "h_t_t_p_response"
```

### `keys_to_camel(data, upper_first=False)`

Transform all dictionary keys from `snake_case` to `camelCase` (shallow).

```python
keys_to_camel({"user_name": "alice", "created_at": "now"})
# {"userName": "alice", "createdAt": "now"}
```

### `keys_to_snake(data)`

Transform all dictionary keys from `camelCase` to `snake_case` (shallow).

```python
keys_to_snake({"userName": "alice", "createdAt": "now"})
# {"user_name": "alice", "created_at": "now"}
```

### `pad_left(text, width, pad_char=" ")`

Left-pad a string so it reaches `width` characters.

```python
pad_left("42", 5, "0")            # "00042"
```

### `pad_right(text, width, pad_char=" ")`

Right-pad a string so it reaches `width` characters.

```python
pad_right("42", 5, "0")           # "42000"
```

### `word_count(text)`

Count whitespace-delimited words.

```python
word_count("the quick brown fox") # 4
```

### `is_url_safe(text)`

Check whether `text` contains only URL-safe ASCII characters
(`A-Z`, `a-z`, `0-9`, `-`, `_`, `.`, `~`).

```python
is_url_safe("hello-world_123")    # True
is_url_safe("hello world!")       # False
```

---

## Pagination

### `paginate(total, page=1, per_page=20)` → `PageInfo`

Compute pagination metadata entirely in Rust. Returns a `PageInfo` object.

```python
info = paginate(total=95, page=2, per_page=10)
info.total_pages  # 10
info.offset       # 10
info.has_next     # True
info.has_prev     # True
info.from_item    # 11
info.to_item      # 20
info.to_dict()    # ready to embed in a JSON response
```

#### `PageInfo` fields

| Field         | Type   | Description                          |
|---------------|--------|--------------------------------------|
| `total`       | `int`  | Total number of items                |
| `page`        | `int`  | Current page (1-based)               |
| `per_page`    | `int`  | Items per page                       |
| `total_pages` | `int`  | Total pages                          |
| `has_next`    | `bool` | Whether a next page exists           |
| `has_prev`    | `bool` | Whether a previous page exists       |
| `offset`      | `int`  | SQL `OFFSET` value                   |
| `from_item`   | `int`  | First item number on this page (1-based) |
| `to_item`     | `int`  | Last item number on this page        |

### `encode_cursor(offset)` / `decode_cursor(cursor)`

Convert between integer offsets and opaque cursor strings for cursor-based
pagination.

```python
cursor = encode_cursor(42)       # e.g. "NDI="
offset = decode_cursor(cursor)   # 42
```

---

## Crypto, Encoding & IDs

### `random_token(length=32)`

Generate a cryptographically-secure URL-safe token string.

```python
random_token()     # 32-char token
random_token(16)   # 16-char token
```

### `random_bytes(n)`

Generate *n* cryptographically-secure random bytes.

```python
random_bytes(16)   # b'\x8a\x3f...'
```

### `sha256_hex(data)`

SHA-256 hex digest of a UTF-8 string.

```python
sha256_hex("hello")
# "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
```

### `hmac_sha256_hex(key, data)` / `hmac_sha256_bytes(key, data)`

HMAC-SHA-256. The `_hex` variant works with strings and returns a hex digest;
the `_bytes` variant works with raw bytes.

```python
hmac_sha256_hex("secret", "message")   # hex string
hmac_sha256_bytes(b"key", b"data")     # raw bytes
```

### `secure_compare(a, b)`

Constant-time comparison to prevent timing attacks.

```python
secure_compare(b"expected", b"actual")  # True / False
```

### `b64_encode(data)` / `b64_decode(data)`

Standard Base64 encoding/decoding.

```python
b64_encode(b"hello")        # "aGVsbG8="
b64_decode("aGVsbG8=")      # b"hello"
```

### `b64url_encode(data)` / `b64url_decode(data)`

URL-safe Base64 (no padding).

```python
b64url_encode(b"hello")     # "aGVsbG8"
b64url_decode("aGVsbG8")    # b"hello"
```

### `uuid_v4()` / `uuid_v7()`

Generate UUIDs. **v4** is fully random; **v7** is time-sortable (ideal for
database primary keys).

```python
uuid_v4()   # "f2b144d7-eaf0-4b04-a4c6-3afd9a1cce83"
uuid_v7()   # "019c8b61-bbcb-79e3-a734-1eb95503e3eb"
```

### `fast_hash(data)` / `fast_hash_bytes(data)`

xxHash3-64 non-cryptographic hash — extremely fast, suitable for cache keys,
sharding, deduplication.

```python
fast_hash("hello")           # 10760762337991515389
fast_hash_bytes(b"hello")    # same result
```

---

## Time Helpers

### `now_ms()` / `now_sec()`

Current UTC Unix timestamp in milliseconds or seconds.

```python
now_ms()   # 1771864964043
now_sec()  # 1771864964
```

### `now_iso()`

Current UTC time as an ISO 8601 string.

```python
now_iso()  # "2026-02-23T16:42:44.043Z"
```

### `format_timestamp(ts_secs)`

Format a Unix timestamp (seconds) to ISO 8601 UTC.

```python
format_timestamp(1700000000)  # "2023-11-14T22:13:20.000Z"
```

### `parse_iso(s)`

Parse an ISO 8601 datetime string to Unix seconds. Returns `None` on failure.

```python
parse_iso("2024-01-01T00:00:00Z")  # 1704067200
parse_iso("not-a-date")            # None
```

### `relative_time(ts_secs)`

Human-readable relative time from ``ts_secs`` to now.

```python
from hypern.utils import now_sec, relative_time

relative_time(now_sec() - 3600)   # "1 hour ago"
relative_time(now_sec() - 90)     # "1 minute ago"
relative_time(now_sec() + 600)    # "in 10 minutes"
```

### `elapsed_ms(start_ms)`

Milliseconds elapsed from `start_ms` to now. Useful for request timing.

```python
start = now_ms()
# ... work ...
print(f"Took {elapsed_ms(start)} ms")
```

### `ms_to_sec(ms)` / `sec_to_ms(sec)`

Simple unit conversions with integer arithmetic.

```python
ms_to_sec(1500)   # 1
sec_to_ms(2)      # 2000
```

---

## Performance Notes

All functions are implemented in compiled Rust and called through zero-copy PyO3
bindings. Key performance characteristics:

- **No GIL contention** — most functions release the Python GIL, allowing true
  parallelism in multi-threaded applications.
- **Zero-copy where possible** — byte-oriented functions like `fast_hash_bytes`
  avoid copying data across the Python/Rust boundary.
- **SIMD-optimized hashing** — `fast_hash` / `fast_hash_bytes` use xxHash3
  which leverages SSE2/AVX2 on x86-64.
- **Constant-time crypto** — `secure_compare` uses the `subtle` crate's
  constant-time primitives to prevent timing side-channels.
