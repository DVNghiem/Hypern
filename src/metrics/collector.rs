//! Zero-cost metrics collection using atomic operations.

use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::time::Instant;

/// Server-wide metrics using lock-free atomics
pub struct ServerMetrics {
    requests_total: AtomicU64,
    requests_in_flight: AtomicU32,
    requests_successful: AtomicU64,
    requests_failed: AtomicU64,
    latency_sum_us: AtomicU64,
    latency_min_us: AtomicU64,
    latency_max_us: AtomicU64,
    bytes_sent: AtomicU64,
    bytes_received: AtomicU64,
    start_time: Instant,
}

impl ServerMetrics {
    pub fn new() -> Self {
        Self {
            requests_total: AtomicU64::new(0),
            requests_in_flight: AtomicU32::new(0),
            requests_successful: AtomicU64::new(0),
            requests_failed: AtomicU64::new(0),
            latency_sum_us: AtomicU64::new(0),
            latency_min_us: AtomicU64::new(u64::MAX),
            latency_max_us: AtomicU64::new(0),
            bytes_sent: AtomicU64::new(0),
            bytes_received: AtomicU64::new(0),
            start_time: Instant::now(),
        }
    }

    /// Record the start of a request
    #[inline]
    pub fn request_start(&self) {
        self.requests_in_flight.fetch_add(1, Ordering::Relaxed);
    }

    /// Record the completion of a request
    #[inline]
    pub fn request_complete(&self, latency_us: u64, success: bool) {
        self.requests_total.fetch_add(1, Ordering::Relaxed);
        self.requests_in_flight.fetch_sub(1, Ordering::Relaxed);
        self.latency_sum_us.fetch_add(latency_us, Ordering::Relaxed);

        if success {
            self.requests_successful.fetch_add(1, Ordering::Relaxed);
        } else {
            self.requests_failed.fetch_add(1, Ordering::Relaxed);
        }

        // Update min/max latency (lock-free)
        self.update_min_latency(latency_us);
        self.update_max_latency(latency_us);
    }

    #[inline]
    fn update_min_latency(&self, latency_us: u64) {
        let mut current = self.latency_min_us.load(Ordering::Relaxed);
        while latency_us < current {
            match self.latency_min_us.compare_exchange_weak(
                current,
                latency_us,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(c) => current = c,
            }
        }
    }

    #[inline]
    fn update_max_latency(&self, latency_us: u64) {
        let mut current = self.latency_max_us.load(Ordering::Relaxed);
        while latency_us > current {
            match self.latency_max_us.compare_exchange_weak(
                current,
                latency_us,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(c) => current = c,
            }
        }
    }

    /// Record bytes sent
    #[inline]
    pub fn record_bytes_sent(&self, bytes: u64) {
        self.bytes_sent.fetch_add(bytes, Ordering::Relaxed);
    }

    /// Record bytes received
    #[inline]
    pub fn record_bytes_received(&self, bytes: u64) {
        self.bytes_received.fetch_add(bytes, Ordering::Relaxed);
    }

    /// Get a snapshot of current metrics
    pub fn snapshot(&self) -> MetricsSnapshot {
        let total = self.requests_total.load(Ordering::Relaxed);
        let latency_sum = self.latency_sum_us.load(Ordering::Relaxed);
        let uptime = self.start_time.elapsed();

        MetricsSnapshot {
            requests_total: total,
            requests_in_flight: self.requests_in_flight.load(Ordering::Relaxed),
            requests_successful: self.requests_successful.load(Ordering::Relaxed),
            requests_failed: self.requests_failed.load(Ordering::Relaxed),
            avg_latency_us: if total > 0 { latency_sum / total } else { 0 },
            min_latency_us: {
                let min = self.latency_min_us.load(Ordering::Relaxed);
                if min == u64::MAX {
                    0
                } else {
                    min
                }
            },
            max_latency_us: self.latency_max_us.load(Ordering::Relaxed),
            bytes_sent: self.bytes_sent.load(Ordering::Relaxed),
            bytes_received: self.bytes_received.load(Ordering::Relaxed),
            requests_per_second: if uptime.as_secs() > 0 {
                total as f64 / uptime.as_secs_f64()
            } else {
                0.0
            },
            uptime_seconds: uptime.as_secs(),
        }
    }

    /// Reset all metrics
    pub fn reset(&self) {
        self.requests_total.store(0, Ordering::Relaxed);
        self.requests_in_flight.store(0, Ordering::Relaxed);
        self.requests_successful.store(0, Ordering::Relaxed);
        self.requests_failed.store(0, Ordering::Relaxed);
        self.latency_sum_us.store(0, Ordering::Relaxed);
        self.latency_min_us.store(u64::MAX, Ordering::Relaxed);
        self.latency_max_us.store(0, Ordering::Relaxed);
        self.bytes_sent.store(0, Ordering::Relaxed);
        self.bytes_received.store(0, Ordering::Relaxed);
    }
}

impl Default for ServerMetrics {
    fn default() -> Self {
        Self::new()
    }
}

/// Snapshot of server metrics at a point in time
#[derive(Debug, Clone, Default)]
pub struct MetricsSnapshot {
    pub requests_total: u64,
    pub requests_in_flight: u32,
    pub requests_successful: u64,
    pub requests_failed: u64,
    pub avg_latency_us: u64,
    pub min_latency_us: u64,
    pub max_latency_us: u64,
    pub bytes_sent: u64,
    pub bytes_received: u64,
    pub requests_per_second: f64,
    pub uptime_seconds: u64,
}

impl MetricsSnapshot {
    /// Format as human-readable string
    pub fn to_string_pretty(&self) -> String {
        format!(
            "Requests: {} total ({} in-flight)\n\
             Success/Fail: {}/{}\n\
             Latency: {} avg, {} min, {} max (μs)\n\
             Throughput: {:.2} req/s\n\
             Bytes: {} sent, {} received\n\
             Uptime: {}s",
            self.requests_total,
            self.requests_in_flight,
            self.requests_successful,
            self.requests_failed,
            self.avg_latency_us,
            self.min_latency_us,
            self.max_latency_us,
            self.requests_per_second,
            self.bytes_sent,
            self.bytes_received,
            self.uptime_seconds,
        )
    }
}

/// Request timer for automatic latency tracking
pub struct RequestTimer<'a> {
    metrics: &'a ServerMetrics,
    start: Instant,
    success: bool,
}

impl<'a> RequestTimer<'a> {
    pub fn new(metrics: &'a ServerMetrics) -> Self {
        metrics.request_start();
        Self {
            metrics,
            start: Instant::now(),
            success: true,
        }
    }

    pub fn mark_failed(&mut self) {
        self.success = false;
    }
}

impl<'a> Drop for RequestTimer<'a> {
    fn drop(&mut self) {
        let elapsed = self.start.elapsed().as_micros() as u64;
        self.metrics.request_complete(elapsed, self.success);
    }
}
