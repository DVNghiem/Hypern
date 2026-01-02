use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};

use super::route::Route;

/// Cached route entry with hit count
#[derive(Clone)]
pub struct CachedRoute {
    pub route: Route,
    pub path_params: HashMap<String, String>,
    pub hits: u64,
    pub last_access: u64,
}

impl CachedRoute {
    pub fn new(route: Route, path_params: HashMap<String, String>) -> Self {
        Self {
            route,
            path_params,
            hits: 1,
            last_access: 0,
        }
    }
}

/// High-performance route cache using DashMap for concurrent access
pub struct RouteCache {
    cache: dashmap::DashMap<u64, CachedRoute>,
    max_size: usize,
    access_counter: AtomicU64,
}

impl RouteCache {
    pub fn new(max_size: usize) -> Self {
        Self {
            cache: dashmap::DashMap::with_capacity(max_size),
            max_size,
            access_counter: AtomicU64::new(0),
        }
    }

    /// Get a cached route by path hash
    #[inline]
    pub fn get(&self, path_hash: u64) -> Option<CachedRoute> {
        if let Some(mut entry) = self.cache.get_mut(&path_hash) {
            let access_time = self.access_counter.fetch_add(1, Ordering::Relaxed);
            entry.hits += 1;
            entry.last_access = access_time;
            Some(entry.clone())
        } else {
            None
        }
    }

    /// Insert a route into the cache
    pub fn insert(&self, path_hash: u64, route: Route, path_params: HashMap<String, String>) {
        // Evict if at capacity
        if self.cache.len() >= self.max_size {
            self.evict_lru();
        }

        let cached = CachedRoute::new(route, path_params);
        self.cache.insert(path_hash, cached);
    }

    /// Evict least recently used entry
    fn evict_lru(&self) {
        let mut oldest_key = None;
        let mut oldest_time = u64::MAX;

        for entry in self.cache.iter() {
            if entry.last_access < oldest_time {
                oldest_time = entry.last_access;
                oldest_key = Some(*entry.key());
            }
        }

        if let Some(key) = oldest_key {
            self.cache.remove(&key);
        }
    }

    /// Clear the cache
    pub fn clear(&self) {
        self.cache.clear();
    }

    /// Get current cache size
    pub fn len(&self) -> usize {
        self.cache.len()
    }

    /// Check if cache is empty
    pub fn is_empty(&self) -> bool {
        self.cache.is_empty()
    }
}

impl Default for RouteCache {
    fn default() -> Self {
        Self::new(10000) // Default 10K entries
    }
}

/// Fast route matcher using xxhash for path hashing
pub struct RouteMatcher {
    cache: RouteCache,
}

impl RouteMatcher {
    pub fn new(cache_size: usize) -> Self {
        Self {
            cache: RouteCache::new(cache_size),
        }
    }

    /// Compute hash for a path + method combination
    #[inline]
    pub fn compute_hash(path: &str, method: &str) -> u64 {
        use xxhash_rust::xxh3::xxh3_64;
        let combined = format!("{}:{}", method, path);
        xxh3_64(combined.as_bytes())
    }

    /// Try to get a cached route
    #[inline]
    pub fn get_cached(&self, path: &str, method: &str) -> Option<CachedRoute> {
        let hash = Self::compute_hash(path, method);
        self.cache.get(hash)
    }

    /// Cache a route match result
    pub fn cache_route(
        &self,
        path: &str,
        method: &str,
        route: Route,
        params: HashMap<String, String>,
    ) {
        let hash = Self::compute_hash(path, method);
        self.cache.insert(hash, route, params);
    }
}

impl Default for RouteMatcher {
    fn default() -> Self {
        Self::new(10000)
    }
}
