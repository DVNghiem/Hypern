//! Optimized route matching with caching integration.

use super::cache::RouteMatcher;
use super::radix::RadixNode;
use super::route::Route;
use std::collections::HashMap;

/// High-performance route matcher combining radix tree with caching
pub struct OptimizedMatcher {
    radix: RadixNode,
    cache: RouteMatcher,
    use_cache: bool,
}

impl OptimizedMatcher {
    pub fn new(cache_size: usize) -> Self {
        Self {
            radix: RadixNode::new(),
            cache: RouteMatcher::new(cache_size),
            use_cache: true,
        }
    }

    /// Insert a route into the radix tree
    pub fn insert(&mut self, path: &str, route: Route) {
        self.radix.insert(path, route);
    }

    /// Find a matching route with caching
    pub fn find(&self, path: &str, method: &str) -> Option<(Route, HashMap<String, String>)> {
        // Try cache first
        if self.use_cache {
            if let Some(cached) = self.cache.get_cached(path, method) {
                return Some((cached.route, cached.path_params));
            }
        }

        // Fallback to radix tree
        if let Some((route, params)) = self.radix.find(path, method) {
            let route_clone = route.clone();
            let params_clone = params.clone();

            // Cache the result
            if self.use_cache {
                self.cache
                    .cache_route(path, method, route_clone.clone(), params_clone.clone());
            }

            Some((route_clone, params_clone))
        } else {
            None
        }
    }

    /// Get cache hit rate
    pub fn cache_hit_rate(&self) -> f64 {
        self.cache.hit_rate()
    }

    /// Enable/disable caching
    pub fn set_cache_enabled(&mut self, enabled: bool) {
        self.use_cache = enabled;
    }
}

impl Default for OptimizedMatcher {
    fn default() -> Self {
        Self::new(10000)
    }
}
