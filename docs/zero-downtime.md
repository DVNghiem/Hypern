# Zero-Downtime Reloads & Health Probes

Hypern ships with built-in zero-downtime reload support and Kubernetes-ready health probes. It works in both development (hot reload) and production (graceful reload) modes.

## Quick Start

```python
from hypern import Hypern

app = Hypern()

# Configure reload + health probes (defaults shown)
app.setup_reload(
    drain_timeout_secs=30,     # wait for in-flight requests before restart
    startup_grace_secs=2,      # delay before marking new workers healthy
    health_probes=True,        # enable probe endpoints
    health_path="/_health",    # probe prefix (avoid clashing with user routes)
)

@app.get("/")
def home(req, res, ctx):
    res.json({"message": "ok"})

if __name__ == "__main__":
    app.start(port=8000)
```

## Health Probe Endpoints

When `health_probes=True`, Hypern exposes lightweight JSON probes (no GIL):

- `GET /_health` – Full status (status, readiness, liveness, in-flight, uptime)
- `GET /_health/live` – Liveness probe (process alive?)
- `GET /_health/ready` – Readiness probe (accepting traffic?)
- `GET /_health/startup` – Startup probe (finished initializing?)

> Tip: Change the prefix with `health_path` to avoid clashing with your own `/health` route.

Example response:

```json
{
  "status": "healthy",
  "live": true,
  "ready": true,
  "in_flight": 0,
  "uptime_secs": 3.12
}
```

## Signals & Modes (Unix)

- `SIGUSR1` → **Graceful reload**: stop accepting new requests, wait for in-flight to drain (up to `drain_timeout_secs`), then restart workers
- `SIGUSR2` → **Hot reload**: immediate restart (best for dev)
- `SIGINT` / `SIGTERM` → **Shutdown**: brief drain then exit

Programmatic triggers (Python):

```python
app.graceful_reload()      # same as kill -USR1 <pid>
app.hot_reload_signal()    # same as kill -USR2 <pid>
```

## Production Graceful Reload

1. Send `SIGUSR1` to the parent process.
2. Existing workers enter **draining**: new requests receive HTTP 503 with `Retry-After` and keep-alive close; in-flight requests are awaited up to `drain_timeout_secs`.
3. New workers start; after `startup_grace_secs` they mark themselves **healthy** and pass readiness.
4. Old workers terminate once drained or after timeout.

## Development Hot Reload

Use `SIGUSR2` (or `app.hot_reload_signal()`) to restart immediately. In-flight requests are not drained—best suited to local development.

## HealthCheck & ReloadManager (Python API)

```python
from hypern import ReloadManager, ReloadConfig

rm = ReloadManager(ReloadConfig(health_path_prefix="/_health"))
rm.graceful_reload()
print(rm.health().to_json())
```

- `HealthCheck` exposes status, readiness/liveness checks, in-flight counts, uptime, and JSON serialization.
- `ReloadManager` signals hot/graceful reloads and tracks draining state.

## Kubernetes Probes (example)

```yaml
livenessProbe:
  httpGet:
    path: /_health/live
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
readinessProbe:
  httpGet:
    path: /_health/ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
startupProbe:
  httpGet:
    path: /_health/startup
    port: 8000
  failureThreshold: 30
  periodSeconds: 2
```

## Defaults

- Path prefix: `/_health`
- Graceful drain timeout: 30s
- Startup grace: 2s
- Probes enabled by default

## Notes

- Non-Unix platforms fall back to thread-based workers; signals may differ. You can still trigger reload programmatically via `ReloadManager`.
- If you already expose `/health`, set `health_path` to avoid conflicts (e.g., `/_health`).
