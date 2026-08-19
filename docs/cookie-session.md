# Cookies and Sessions

Hypern exposes Express-style cookie helpers on `res.cookie()` and
`res.clear_cookie()`, plus signed-cookie primitives from the Rust utility
layer (`hmac_sha256_hex`, `secure_compare`). This page shows how to wire them
into a small, dependency-free signed session store.

## Setting Cookies

```python
from hypern import Hypern

app = Hypern()

@app.post("/login")
def login(req, res, ctx):
    # Validate credentials...
    user_id = "user-123"

    res.cookie(
        "session_id",
        "abc123",
        max_age=60 * 60 * 24 * 7,   # 7 days, in seconds
        path="/",
        domain="example.com",       # omit for host-only cookies
        secure=True,                # HTTPS-only
        http_only=True,             # not visible to JavaScript
        same_site="Lax",            # "Strict" | "Lax" | "None"
    )
    res.json({"user_id": user_id})
```

`res.cookie()` always sets `Path=/` and `HttpOnly` unless you override them.
Pick `SameSite=Lax` for typical web apps, `Strict` for admin surfaces, and
`None` only when you genuinely need cross-site requests (and only with
`Secure=True`).

## Reading Cookies

```python
@app.get("/me")
def me(req, res, ctx):
    session_id = req.cookie("session_id")
    if session_id is None:
        res.status(401).json({"error": "not authenticated"})
        return

    user = sessions.find(session_id)
    if user is None:
        res.status(401).json({"error": "session expired"})
        return

    res.json({"user_id": user.id, "email": user.email})
```

`req.cookie(name)` returns `None` when the cookie is missing. `req.cookies()`
returns all cookies as a `dict[str, str]`.

## Clearing Cookies

Use `clear_cookie()` to send a `Set-Cookie` header with an expired date and
`Max-Age=0`. Mirror the `path` and `domain` of the original cookie or the
browser will not remove it:

```python
@app.post("/logout")
def logout(req, res, ctx):
    res.clear_cookie("session_id", path="/", domain="example.com")
    res.json({"ok": True})
```

## Signed Cookies

Plain cookies are tamper-evident on the wire but anyone with write access
can edit them. Sign them with an HMAC if you want integrity. The example
below uses `hmac_sha256_hex` and `secure_compare` from `hypern.utils` to
produce an Express-style `<payload>.<signature>` cookie.

```python
import json
from hypern import Hypern
from hypern.utils import hmac_sha256_hex, secure_compare

SECRET = "change-me-in-production"  # load from env in real apps

def sign(payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":")).encode()
    encoded = body.hex()  # safe for cookie values
    sig = hmac_sha256_hex(SECRET, encoded)
    return f"{encoded}.{sig}"

def verify(token: str) -> dict | None:
    if "." not in token:
        return None
    encoded, sig = token.rsplit(".", 1)
    expected = hmac_sha256_hex(SECRET, encoded)
    if not secure_compare(sig.encode(), expected.encode()):
        return None
    try:
        return json.loads(bytes.fromhex(encoded))
    except (ValueError, json.JSONDecodeError):
        return None

app = Hypern()

@app.post("/login")
def login(req, res, ctx):
    user_id = "user-123"  # look up from your auth backend
    token = sign({"user_id": user_id, "iat": 1700000000})
    res.cookie(
        "session",
        token,
        max_age=60 * 60 * 24 * 7,
        http_only=True,
        secure=True,
        same_site="Lax",
    )
    res.json({"user_id": user_id})

@app.get("/me")
def me(req, res, ctx):
    raw = req.cookie("session")
    if raw is None:
        res.status(401).json({"error": "not authenticated"})
        return

    payload = verify(raw)
    if payload is None:
        res.status(401).json({"error": "invalid session"})
        return

    res.json(payload)
```

Notes:

- `secure_compare` runs in constant time so signature verification does not
  leak timing information.
- Always pair `http_only` with `secure` for session cookies.
- Rotate `SECRET` to invalidate all outstanding sessions; combine with a
  short `max_age` to bound the damage.

## Server-Side Session Store

For revocable sessions (logout-everywhere, ban a user), keep session state
on the server and store only the opaque ID in the cookie:

```python
import time
import secrets
from dataclasses import dataclass, asdict
from hypern import Hypern

@dataclass
class Session:
    user_id: str
    issued_at: float

class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, user_id: str) -> str:
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = Session(user_id=user_id, issued_at=time.time())
        return sid

    def lookup(self, sid: str) -> Session | None:
        return self._sessions.get(sid)

    def revoke(self, sid: str) -> None:
        self._sessions.pop(sid, None)

store = SessionStore()
app = Hypern()

@app.post("/login")
def login(req, res, ctx):
    user_id = "user-123"
    sid = store.create(user_id)
    res.cookie("sid", sid, max_age=60 * 60 * 8, http_only=True, secure=True, same_site="Lax")
    res.json({"user_id": user_id})

@app.post("/logout")
def logout(req, res, ctx):
    sid = req.cookie("sid")
    if sid:
        store.revoke(sid)
    res.clear_cookie("sid", path="/")
    res.json({"ok": True})
```

Replace the in-memory dict with Redis, a database row, or any KV store that
survives process restarts. The cookie format stays the same — an opaque ID.

## Cookie Best Practices

1. **`HttpOnly` on session cookies** — keeps them out of `document.cookie`.
2. **`Secure` in production** — never send session cookies over plain HTTP.
3. **`SameSite=Lax` or `Strict`** — drop `SameSite=None` unless cross-site is
   required, and never combine it with `Secure=False`.
4. **Bound the lifetime** — short `max_age` reduces the value of a stolen
   cookie.
5. **Mirror attributes on logout** — `path` and `domain` must match for
   `clear_cookie` to remove the cookie.
6. **Rotate secrets carefully** — changing `SECRET` invalidates every
   signed cookie; use key versioning if you need zero-downtime rotation.
7. **Don't put PII in cookies** — even signed cookies can be read by anyone
   with the secret; keep payloads to identifiers, not data.