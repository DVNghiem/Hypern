use ahash::AHasher;
use std::hash::{Hash, Hasher};
use xxhash_rust::xxh3::xxh3_64;

/// Fast path-specific hashing using XXH3
#[inline]
pub fn hash_path(path: &str) -> u64 {
    xxh3_64(path.as_bytes())
}

/// Generic fast hashing for strings
#[inline]
pub fn hash_str(s: &str) -> u64 {
    let mut hasher = AHasher::default();
    s.hash(&mut hasher);
    hasher.finish()
}

/// Combined hash for method and path
#[inline]
pub fn hash_route(method: &str, path: &str) -> u64 {
    let mut hasher = AHasher::default();
    method.hash(&mut hasher);
    path.hash(&mut hasher);
    hasher.finish()
}
