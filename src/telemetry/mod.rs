use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use dashmap::DashMap;
use parking_lot::RwLock;
use pyo3::prelude::*;

/// A single counter metric
struct Counter {
    value: AtomicU64,
}

impl Counter {
    fn new() -> Self {
        Self {
            value: AtomicU64::new(0),
        }
    }

    fn inc_by(&self, n: u64) {
        self.value.fetch_add(n, Ordering::Relaxed);
    }

    fn get(&self) -> u64 {
        self.value.load(Ordering::Relaxed)
    }
}

/// A single gauge metric
struct Gauge {
    value: AtomicU64,
}

impl Gauge {
    fn new() -> Self {
        Self {
            value: AtomicU64::new(0),
        }
    }

    fn set(&self, v: f64) {
        self.value
            .store(v.to_bits(), Ordering::Relaxed);
    }

    fn inc(&self) {
        loop {
            let current = self.value.load(Ordering::Relaxed);
            let new = f64::from_bits(current) + 1.0;
            if self
                .value
                .compare_exchange_weak(current, new.to_bits(), Ordering::Relaxed, Ordering::Relaxed)
                .is_ok()
            {
                break;
            }
        }
    }

    fn dec(&self) {
        loop {
            let current = self.value.load(Ordering::Relaxed);
            let new = f64::from_bits(current) - 1.0;
            if self
                .value
                .compare_exchange_weak(current, new.to_bits(), Ordering::Relaxed, Ordering::Relaxed)
                .is_ok()
            {
                break;
            }
        }
    }

    fn get(&self) -> f64 {
        f64::from_bits(self.value.load(Ordering::Relaxed))
    }
}

/// Simple histogram using fixed buckets
struct Histogram {
    buckets: Vec<(f64, AtomicU64)>,
    sum: AtomicU64, // stored as f64 bits
    count: AtomicU64,
}

impl Histogram {
    fn new(bucket_bounds: &[f64]) -> Self {
        let mut buckets: Vec<(f64, AtomicU64)> = bucket_bounds
            .iter()
            .map(|&b| (b, AtomicU64::new(0)))
            .collect();
        buckets.push((f64::INFINITY, AtomicU64::new(0)));
        Self {
            buckets,
            sum: AtomicU64::new(0f64.to_bits()),
            count: AtomicU64::new(0),
        }
    }

    fn observe(&self, value: f64) {
        for (bound, count) in &self.buckets {
            if value <= *bound {
                count.fetch_add(1, Ordering::Relaxed);
            }
        }
        self.count.fetch_add(1, Ordering::Relaxed);
        // Atomic float add
        loop {
            let current = self.sum.load(Ordering::Relaxed);
            let new = f64::from_bits(current) + value;
            if self
                .sum
                .compare_exchange_weak(current, new.to_bits(), Ordering::Relaxed, Ordering::Relaxed)
                .is_ok()
            {
                break;
            }
        }
    }
}

/// Label key used for keyed metrics (e.g., method+path+status)
type LabelKey = String;

/// Prometheus-compatible metrics registry
#[pyclass(name = "MetricsRegistry")]
pub struct MetricsRegistry {
    counters: DashMap<String, DashMap<LabelKey, Arc<Counter>>>,
    gauges: DashMap<String, DashMap<LabelKey, Arc<Gauge>>>,
    histograms: DashMap<String, DashMap<LabelKey, Arc<Histogram>>>,
    help_texts: DashMap<String, String>,
    histogram_buckets: RwLock<Vec<f64>>,
}

impl Default for MetricsRegistry {
    fn default() -> Self {
        Self::new()
    }
}

#[pymethods]
impl MetricsRegistry {
    #[new]
    pub fn new() -> Self {
        Self {
            counters: DashMap::new(),
            gauges: DashMap::new(),
            histograms: DashMap::new(),
            help_texts: DashMap::new(),
            histogram_buckets: RwLock::new(vec![
                0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
            ]),
        }
    }

    /// Increment a counter
    #[pyo3(signature = (name, labels = None, value = 1))]
    pub fn counter_inc(&self, name: &str, labels: Option<&str>, value: u64) {
        let label_key = labels.unwrap_or("").to_string();
        let metric_map = self.counters.entry(name.to_string()).or_default();
        let counter = metric_map
            .entry(label_key)
            .or_insert_with(|| Arc::new(Counter::new()))
            .clone();
        counter.inc_by(value);
    }

    /// Set a gauge value
    #[pyo3(signature = (name, value, labels = None))]
    pub fn gauge_set(&self, name: &str, value: f64, labels: Option<&str>) {
        let label_key = labels.unwrap_or("").to_string();
        let metric_map = self.gauges.entry(name.to_string()).or_default();
        let gauge = metric_map
            .entry(label_key)
            .or_insert_with(|| Arc::new(Gauge::new()))
            .clone();
        gauge.set(value);
    }

    /// Increment a gauge
    #[pyo3(signature = (name, labels = None))]
    pub fn gauge_inc(&self, name: &str, labels: Option<&str>) {
        let label_key = labels.unwrap_or("").to_string();
        let metric_map = self.gauges.entry(name.to_string()).or_default();
        let gauge = metric_map
            .entry(label_key)
            .or_insert_with(|| Arc::new(Gauge::new()))
            .clone();
        gauge.inc();
    }

    /// Decrement a gauge
    #[pyo3(signature = (name, labels = None))]
    pub fn gauge_dec(&self, name: &str, labels: Option<&str>) {
        let label_key = labels.unwrap_or("").to_string();
        let metric_map = self.gauges.entry(name.to_string()).or_default();
        let gauge = metric_map
            .entry(label_key)
            .or_insert_with(|| Arc::new(Gauge::new()))
            .clone();
        gauge.dec();
    }

    /// Observe a value in a histogram
    #[pyo3(signature = (name, value, labels = None))]
    pub fn histogram_observe(&self, name: &str, value: f64, labels: Option<&str>) {
        let label_key = labels.unwrap_or("").to_string();
        let buckets = self.histogram_buckets.read().clone();
        let metric_map = self.histograms.entry(name.to_string()).or_default();
        let histogram = metric_map
            .entry(label_key)
            .or_insert_with(|| Arc::new(Histogram::new(&buckets)))
            .clone();
        histogram.observe(value);
    }

    /// Set help text for a metric
    pub fn set_help(&self, name: &str, help: &str) {
        self.help_texts
            .insert(name.to_string(), help.to_string());
    }

    /// Render all metrics in Prometheus text exposition format
    pub fn render(&self) -> String {
        let mut out = String::with_capacity(4096);

        // Counters
        for entry in self.counters.iter() {
            let name = entry.key();
            if let Some(help) = self.help_texts.get(name.as_str()) {
                out.push_str(&format!("# HELP {} {}\n", name, help.value()));
            }
            out.push_str(&format!("# TYPE {} counter\n", name));
            for label_entry in entry.value().iter() {
                let labels = label_entry.key();
                let value = label_entry.value().get();
                if labels.is_empty() {
                    out.push_str(&format!("{} {}\n", name, value));
                } else {
                    out.push_str(&format!("{}{{{}}} {}\n", name, labels, value));
                }
            }
        }

        // Gauges
        for entry in self.gauges.iter() {
            let name = entry.key();
            if let Some(help) = self.help_texts.get(name.as_str()) {
                out.push_str(&format!("# HELP {} {}\n", name, help.value()));
            }
            out.push_str(&format!("# TYPE {} gauge\n", name));
            for label_entry in entry.value().iter() {
                let labels = label_entry.key();
                let value = label_entry.value().get();
                if labels.is_empty() {
                    out.push_str(&format!("{} {}\n", name, value));
                } else {
                    out.push_str(&format!("{}{{{}}} {}\n", name, labels, value));
                }
            }
        }

        // Histograms
        for entry in self.histograms.iter() {
            let name = entry.key();
            if let Some(help) = self.help_texts.get(name.as_str()) {
                out.push_str(&format!("# HELP {} {}\n", name, help.value()));
            }
            out.push_str(&format!("# TYPE {} histogram\n", name));
            for label_entry in entry.value().iter() {
                let labels = label_entry.key();
                let histogram = label_entry.value();
                let label_prefix = if labels.is_empty() {
                    String::new()
                } else {
                    format!("{},", labels)
                };

                for (bound, count) in &histogram.buckets {
                    let le = if bound.is_infinite() {
                        "+Inf".to_string()
                    } else {
                        format!("{}", bound)
                    };
                    out.push_str(&format!(
                        "{}_bucket{{{}le=\"{}\"}} {}\n",
                        name,
                        label_prefix,
                        le,
                        count.load(Ordering::Relaxed)
                    ));
                }
                out.push_str(&format!(
                    "{}_sum{} {}\n",
                    name,
                    if labels.is_empty() {
                        String::new()
                    } else {
                        format!("{{{}}}", labels)
                    },
                    f64::from_bits(histogram.sum.load(Ordering::Relaxed))
                ));
                out.push_str(&format!(
                    "{}_count{} {}\n",
                    name,
                    if labels.is_empty() {
                        String::new()
                    } else {
                        format!("{{{}}}", labels)
                    },
                    histogram.count.load(Ordering::Relaxed)
                ));
            }
        }

        out
    }

    fn __repr__(&self) -> String {
        format!(
            "MetricsRegistry(counters={}, gauges={}, histograms={})",
            self.counters.len(),
            self.gauges.len(),
            self.histograms.len()
        )
    }
}
