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
    # ── Pagination ─────────────────────────────────────────────────────────
    PageInfo,
    b64_decode,
    b64_encode,
    b64url_decode,
    b64url_encode,
    camel_to_snake,
    decode_cursor,
    elapsed_ms,
    encode_cursor,
    fast_hash,
    fast_hash_bytes,
    format_timestamp,
    hmac_sha256_bytes,
    hmac_sha256_hex,
    is_url_safe,
    keys_to_camel,
    keys_to_snake,
    mask_email,
    mask_phone,
    mask_string,
    ms_to_sec,
    now_iso,
    # ── Time helpers ───────────────────────────────────────────────────────
    now_ms,
    now_sec,
    pad_left,
    pad_right,
    paginate,
    parse_iso,
    random_bytes,
    # ── Crypto / encoding / IDs ────────────────────────────────────────────
    random_token,
    relative_time,
    sec_to_ms,
    secure_compare,
    sha256_hex,
    # ── String helpers ─────────────────────────────────────────────────────
    slugify,
    snake_to_camel,
    truncate,
    uuid_v4,
    uuid_v7,
    word_count,
)

__all__ = [
    # Pagination
    "PageInfo",
    "b64_decode",
    "b64_encode",
    "b64url_decode",
    "b64url_encode",
    "camel_to_snake",
    "decode_cursor",
    "elapsed_ms",
    "encode_cursor",
    "fast_hash",
    "fast_hash_bytes",
    "format_timestamp",
    "hmac_sha256_bytes",
    "hmac_sha256_hex",
    "is_url_safe",
    "keys_to_camel",
    "keys_to_snake",
    "mask_email",
    "mask_phone",
    "mask_string",
    "ms_to_sec",
    "now_iso",
    # Time
    "now_ms",
    "now_sec",
    "pad_left",
    "pad_right",
    "paginate",
    "parse_iso",
    "random_bytes",
    # Crypto / encoding / IDs
    "random_token",
    "relative_time",
    "sec_to_ms",
    "secure_compare",
    "sha256_hex",
    # String
    "slugify",
    "snake_to_camel",
    "truncate",
    "uuid_v4",
    "uuid_v7",
    "word_count",
]
