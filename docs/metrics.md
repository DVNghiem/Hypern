# Metrics (Prometheus)

Hypern includes a built-in metrics registry for collecting application metrics in Prometheus text exposition format. The registry is implemented in Rust for high performance using lock-free atomics.

## Quick Start

```python
from hypern._hypern import MetricsRegistry

metrics = MetricsRegistry()

# Counter
metrics.counter_inc("http_requests_total", {"method": "GET", "path": "/api"})

# Gauge
metrics.gauge_set("active_connections", {}, 42.0)

# Histogram
metrics.histogram_observe("request_duration_seconds", {}, 0.123)

# Expose metrics endpoint
@app.get("/metrics")
def prometheus_metrics(req, res, ctx):
    res.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8"
    res.body = metrics.render()
```

## Metric Types

### Counter

A monotonically increasing value (e.g. total requests, errors).

```python
metrics.counter_inc("http_requests_total", {"method": "GET", "status": "200"})
metrics.counter_inc("http_requests_total", {"method": "POST", "status": "201"})
```

### Gauge

A value that can go up or down (e.g. active connections, queue size).

```python
metrics.gauge_set("active_connections", {}, 10.0)
metrics.gauge_inc("active_connections", {})    # 11.0
metrics.gauge_dec("active_connections", {})    # 10.0
```

### Histogram

Observes values and tracks count/sum (e.g. request latency).

```python
metrics.histogram_observe("request_duration_seconds", {"path": "/api"}, 0.042)
metrics.histogram_observe("request_duration_seconds", {"path": "/api"}, 0.158)
```

## Help Text

Add descriptive help text to metrics:

```python
metrics.set_help("http_requests_total", "Total number of HTTP requests")
metrics.set_help("request_duration_seconds", "Request duration in seconds")
```

## Prometheus Output

Call `metrics.render()` to get Prometheus text exposition format:

```
# HELP http_requests_total Total number of HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="GET",status="200"} 42

# HELP request_duration_seconds Request duration in seconds
# TYPE request_duration_seconds histogram
request_duration_seconds_count{path="/api"} 2
request_duration_seconds_sum{path="/api"} 0.2
```

## API Reference

### MetricsRegistry

| Method | Description |
|--------|-------------|
| `counter_inc(name, labels)` | Increment a counter by 1 |
| `gauge_set(name, labels, value)` | Set a gauge to a specific value |
| `gauge_inc(name, labels)` | Increment a gauge by 1 |
| `gauge_dec(name, labels)` | Decrement a gauge by 1 |
| `histogram_observe(name, labels, value)` | Record a histogram observation |
| `set_help(name, help_text)` | Set help text for a metric |
| `render()` | Render all metrics in Prometheus text format |

**Parameters:**

- `name` (`str`): Metric name (e.g. `"http_requests_total"`)
- `labels` (`dict`): Label key-value pairs (e.g. `{"method": "GET"}`)
- `value` (`float`): Metric value (for gauge_set and histogram_observe)
- `help_text` (`str`): Descriptive help text
