//! JSON response caching for fast API responses.

use ahash::AHashMap;
use bytes::Bytes;
use parking_lot::RwLock;
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Cached JSON response
#[derive(Clone)]
pub struct CachedJson {
    pub data: Arc<Bytes>,
    pub content_type: String,
    pub created_at: Instant,
    pub ttl: Duration,
    pub hits: u64,
}

impl CachedJson {
    pub fn new(data: Vec<u8>, ttl: Duration) -> Self {
        Self {
            data: Arc::new(Bytes::from(data)),
            content_type: "application/json; charset=utf-8".to_string(),
            created_at: Instant::now(),
            ttl,
            hits: 0,
        }
    }

    pub fn is_expired(&self) -> bool {
        self.created_at.elapsed() > self.ttl
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.data
    }
}

/// JSON response cache with TTL support
pub struct JsonResponseCache {
    cache: RwLock<JsonCacheState>,
    max_size: usize,
    max_bytes: usize,
    default_ttl: Duration,
}

struct JsonCacheState {
    entries: AHashMap<u64, CachedJson>,
    bytes: usize,
}

const DEFAULT_MAX_CACHE_BYTES: usize = 64 * 1024 * 1024;

impl JsonResponseCache {
    pub fn new(max_size: usize, default_ttl: Duration) -> Self {
        Self::with_memory_limit(max_size, DEFAULT_MAX_CACHE_BYTES, default_ttl)
    }

    /// Create a cache constrained by both entry count and retained payload bytes.
    pub fn with_memory_limit(max_size: usize, max_bytes: usize, default_ttl: Duration) -> Self {
        let max_size = max_size.max(1);
        Self {
            cache: RwLock::new(JsonCacheState {
                entries: AHashMap::with_capacity(max_size),
                bytes: 0,
            }),
            max_size,
            max_bytes,
            default_ttl,
        }
    }

    /// Get a cached response by key hash
    pub fn get(&self, key_hash: u64) -> Option<Arc<Bytes>> {
        let mut cache = self.cache.write();

        if let Some(entry) = cache.entries.get_mut(&key_hash) {
            if entry.is_expired() {
                let expired = cache.entries.remove(&key_hash).expect("entry must exist");
                cache.bytes = cache.bytes.saturating_sub(expired.data.len());
                return None;
            }
            entry.hits += 1;
            return Some(entry.data.clone());
        }

        None
    }

    /// Cache a JSON response
    pub fn insert(&self, key_hash: u64, data: Vec<u8>) {
        self.insert_with_ttl(key_hash, data, self.default_ttl);
    }

    /// Cache a JSON response with custom TTL
    pub fn insert_with_ttl(&self, key_hash: u64, data: Vec<u8>, ttl: Duration) {
        // Avoid retaining a single response that could consume the whole
        // process cache budget. The caller can still return it normally.
        if data.len() > self.max_bytes {
            return;
        }

        let mut cache = self.cache.write();
        let data_len = data.len();

        if let Some(previous) = cache.entries.remove(&key_hash) {
            cache.bytes = cache.bytes.saturating_sub(previous.data.len());
        }

        // Clear expired entries before evicting live data.
        if cache.entries.len() >= self.max_size
            || cache.bytes.saturating_add(data_len) > self.max_bytes
        {
            self.evict_expired(&mut cache);
        }

        // Enforce both bounds. Responses can have very different sizes, so an
        // entry-count bound alone is insufficient to cap process RSS.
        while cache.entries.len() >= self.max_size
            || cache.bytes.saturating_add(data_len) > self.max_bytes
        {
            self.evict_lru(&mut cache);
        }

        cache.bytes += data_len;
        cache.entries.insert(key_hash, CachedJson::new(data, ttl));
    }

    /// Evict expired entries
    fn evict_expired(&self, cache: &mut JsonCacheState) {
        cache.entries.retain(|_, v| !v.is_expired());
        cache.bytes = cache.entries.values().map(|entry| entry.data.len()).sum();
    }

    /// Evict least recently used entry
    fn evict_lru(&self, cache: &mut JsonCacheState) {
        let mut min_hits = u64::MAX;
        let mut min_key = None;

        for (key, entry) in &cache.entries {
            if entry.hits < min_hits {
                min_hits = entry.hits;
                min_key = Some(*key);
            }
        }

        if let Some(key) = min_key {
            if let Some(removed) = cache.entries.remove(&key) {
                cache.bytes = cache.bytes.saturating_sub(removed.data.len());
            }
        }
    }

    /// Remove a specific entry
    pub fn invalidate(&self, key_hash: u64) {
        let mut cache = self.cache.write();
        if let Some(removed) = cache.entries.remove(&key_hash) {
            cache.bytes = cache.bytes.saturating_sub(removed.data.len());
        }
    }

    /// Clear all cached entries
    pub fn clear(&self) {
        let mut cache = self.cache.write();
        cache.entries.clear();
        cache.bytes = 0;
    }

    /// Bytes currently retained by cached response payloads.
    pub fn allocated_bytes(&self) -> usize {
        self.cache.read().bytes
    }

    /// Compute hash for a cache key
    pub fn compute_key_hash(route: &str, params: &str) -> u64 {
        use xxhash_rust::xxh3::xxh3_64;
        let combined = format!("{}:{}", route, params);
        xxh3_64(combined.as_bytes())
    }
}

impl Default for JsonResponseCache {
    fn default() -> Self {
        Self::new(10000, Duration::from_secs(60))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn enforces_payload_byte_limit() {
        let cache = JsonResponseCache::with_memory_limit(10, 5, Duration::from_secs(60));

        cache.insert(1, vec![1, 2, 3]);
        cache.insert(2, vec![4, 5, 6]);

        assert!(cache.allocated_bytes() <= 5);
        assert!(cache.get(2).is_some());
    }

    #[test]
    fn skips_entries_larger_than_the_entire_budget() {
        let cache = JsonResponseCache::with_memory_limit(10, 4, Duration::from_secs(60));

        cache.insert(1, vec![0; 5]);

        assert_eq!(cache.allocated_bytes(), 0);
        assert!(cache.get(1).is_none());
    }
}
