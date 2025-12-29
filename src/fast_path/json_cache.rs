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
    cache: RwLock<AHashMap<u64, CachedJson>>,
    max_size: usize,
    default_ttl: Duration,
}

impl JsonResponseCache {
    pub fn new(max_size: usize, default_ttl: Duration) -> Self {
        Self {
            cache: RwLock::new(AHashMap::with_capacity(max_size)),
            max_size,
            default_ttl,
        }
    }

    /// Get a cached response by key hash
    pub fn get(&self, key_hash: u64) -> Option<Arc<Bytes>> {
        let mut cache = self.cache.write();

        if let Some(entry) = cache.get_mut(&key_hash) {
            if entry.is_expired() {
                cache.remove(&key_hash);
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
        let mut cache = self.cache.write();

        // Evict expired entries if at capacity
        if cache.len() >= self.max_size {
            self.evict_expired(&mut cache);
        }

        // Still at capacity? Evict least hit entry
        if cache.len() >= self.max_size {
            self.evict_lru(&mut cache);
        }

        cache.insert(key_hash, CachedJson::new(data, ttl));
    }

    /// Evict expired entries
    fn evict_expired(&self, cache: &mut AHashMap<u64, CachedJson>) {
        cache.retain(|_, v| !v.is_expired());
    }

    /// Evict least recently used entry
    fn evict_lru(&self, cache: &mut AHashMap<u64, CachedJson>) {
        let mut min_hits = u64::MAX;
        let mut min_key = None;

        for (key, entry) in cache.iter() {
            if entry.hits < min_hits {
                min_hits = entry.hits;
                min_key = Some(*key);
            }
        }

        if let Some(key) = min_key {
            cache.remove(&key);
        }
    }

    /// Remove a specific entry
    pub fn invalidate(&self, key_hash: u64) {
        self.cache.write().remove(&key_hash);
    }

    /// Clear all cached entries
    pub fn clear(&self) {
        self.cache.write().clear();
    }

    /// Get cache statistics
    pub fn stats(&self) -> JsonCacheStats {
        let cache = self.cache.read();
        let entries = cache.len();
        let total_size: usize = cache.values().map(|v| v.data.len()).sum();
        let total_hits: u64 = cache.values().map(|v| v.hits).sum();

        JsonCacheStats {
            entries,
            total_size,
            total_hits,
        }
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

/// Cache statistics
#[derive(Debug, Clone, Default)]
pub struct JsonCacheStats {
    pub entries: usize,
    pub total_size: usize,
    pub total_hits: u64,
}
