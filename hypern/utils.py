"""
Hypern Utilities — Rust-accelerated helper functions for common business tasks.

All functions are implemented in Rust and exposed via PyO3.  They are 5–50×
faster than equivalent pure-Python implementations and release the GIL where
possible, making them safe for concurrent use.

Categories
----------
**String helpers** — slugify, truncate, case conversion, PII masking.
**Pagination**     — offset / cursor pagination metadata.
**Crypto / IDs**   — SHA-256, HMAC-SHA-256, Base64, UUIDs, random tokens.
**Time helpers**   — timestamps, ISO formatting, relative time.
**Hashing**        — xxHash3-64 fast non-cryptographic hashing.

Example::

    from hypern.utils import (
        slugify, mask_email, paginate, uuid_v7, now_iso, sha256_hex,
        keys_to_camel,
    )

    slug = slugify("Hello World 🚀")          # "hello-world"
    safe = mask_email("user@example.com")      # "u**r@example.com"
    pg   = paginate(total=250, page=3)         # PageInfo(page=3/13, ...)
    pk   = uuid_v7()                           # time-sortable primary key
    ts   = now_iso()                           # "2026-02-23T14:30:00.000Z"
    sig  = sha256_hex("payload")               # hex digest
    body = keys_to_camel({"user_name": "Jo"})  # {"userName": "Jo"}
"""

from __future__ import annotations

from hypern._hypern import (
    # ── String helpers ─────────────────────────────────────────────────────
    slugify,
    truncate,
    mask_email,
    mask_phone,
    mask_string,
    snake_to_camel,
    camel_to_snake,
    keys_to_camel,
    keys_to_snake,
    pad_left,
    pad_right,
    word_count,
    is_url_safe,
    # ── Pagination ─────────────────────────────────────────────────────────
    PageInfo,
    paginate,
    encode_cursor,
    decode_cursor,
    # ── Crypto / encoding / IDs ────────────────────────────────────────────
    random_token,
    random_bytes,
    hmac_sha256_hex,
    hmac_sha256_bytes,
    sha256_hex,
    secure_compare,
    b64_encode,
    b64_decode,
    b64url_encode,
    b64url_decode,
    uuid_v4,
    uuid_v7,
    fast_hash,
    fast_hash_bytes,
    # ── Time helpers ───────────────────────────────────────────────────────
    now_ms,
    now_sec,
    now_iso,
    format_timestamp,
    parse_iso,
    relative_time,
    elapsed_ms,
    ms_to_sec,
    sec_to_ms,
)

__all__ = [
    # String
    "slugify",
    "truncate",
    "mask_email",
    "mask_phone",
    "mask_string",
    "snake_to_camel",
    "camel_to_snake",
    "keys_to_camel",
    "keys_to_snake",
    "pad_left",
    "pad_right",
    "word_count",
    "is_url_safe",
    # Pagination
    "PageInfo",
    "paginate",
    "encode_cursor",
    "decode_cursor",
    # Crypto / encoding / IDs
    "random_token",
    "random_bytes",
    "hmac_sha256_hex",
    "hmac_sha256_bytes",
    "sha256_hex",
    "secure_compare",
    "b64_encode",
    "b64_decode",
    "b64url_encode",
    "b64url_decode",
    "uuid_v4",
    "uuid_v7",
    "fast_hash",
    "fast_hash_bytes",
    # Time
    "now_ms",
    "now_sec",
    "now_iso",
    "format_timestamp",
    "parse_iso",
    "relative_time",
    "elapsed_ms",
    "ms_to_sec",
    "sec_to_ms",
]
