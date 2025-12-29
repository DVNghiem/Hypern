//! Static file serving with memory-mapped files for zero-copy performance.

use ahash::AHashMap;
use memmap2::Mmap;
use parking_lot::RwLock;
use std::fs::File;
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// Cached static file
pub struct CachedFile {
    pub data: Arc<Mmap>,
    pub content_type: String,
    pub size: usize,
    pub etag: String,
}

impl CachedFile {
    pub fn as_bytes(&self) -> &[u8] {
        &self.data[..]
    }
}

/// Static file handler with memory-mapped caching
pub struct StaticFileHandler {
    root_path: PathBuf,
    cache: RwLock<AHashMap<String, Arc<CachedFile>>>,
    max_cache_size: usize,
    max_file_size: usize,
}

impl StaticFileHandler {
    pub fn new(root_path: impl AsRef<Path>) -> Self {
        Self {
            root_path: root_path.as_ref().to_path_buf(),
            cache: RwLock::new(AHashMap::new()),
            max_cache_size: 1000,
            max_file_size: 50 * 1024 * 1024, // 50MB max
        }
    }

    pub fn with_limits(mut self, max_cache_size: usize, max_file_size: usize) -> Self {
        self.max_cache_size = max_cache_size;
        self.max_file_size = max_file_size;
        self
    }

    /// Serve a static file, using cache if available
    pub fn serve(&self, path: &str) -> Result<Arc<CachedFile>, StaticFileError> {
        // Normalize and validate path
        let clean_path = self.normalize_path(path)?;

        // Check cache
        if let Some(cached) = self.cache.read().get(&clean_path) {
            return Ok(cached.clone());
        }

        // Load from disk
        let file = self.load_file(&clean_path)?;

        // Cache if within limits
        if self.cache.read().len() < self.max_cache_size {
            self.cache.write().insert(clean_path, file.clone());
        }

        Ok(file)
    }

    /// Normalize path and prevent directory traversal
    fn normalize_path(&self, path: &str) -> Result<String, StaticFileError> {
        let path = path.trim_start_matches('/');

        // Prevent directory traversal
        if path.contains("..") {
            return Err(StaticFileError::InvalidPath);
        }

        Ok(path.to_string())
    }

    /// Load a file from disk with memory mapping
    fn load_file(&self, path: &str) -> Result<Arc<CachedFile>, StaticFileError> {
        let full_path = self.root_path.join(path);

        // Check if file exists
        if !full_path.exists() || !full_path.is_file() {
            return Err(StaticFileError::NotFound);
        }

        // Open file
        let file = File::open(&full_path).map_err(|_| StaticFileError::IoError)?;
        let metadata = file.metadata().map_err(|_| StaticFileError::IoError)?;
        let size = metadata.len() as usize;

        // Check size limit
        if size > self.max_file_size {
            return Err(StaticFileError::TooLarge);
        }

        // Memory-map the file for zero-copy access
        let mmap = unsafe { Mmap::map(&file).map_err(|_| StaticFileError::IoError)? };

        // Determine content type
        let content_type = self.guess_content_type(&full_path);

        // Generate ETag
        let etag = format!(
            "\"{:x}-{:x}\"",
            size,
            metadata
                .modified()
                .map(|t| t
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs())
                .unwrap_or(0)
        );

        Ok(Arc::new(CachedFile {
            data: Arc::new(mmap),
            content_type,
            size,
            etag,
        }))
    }

    /// Guess content type from file extension
    fn guess_content_type(&self, path: &Path) -> String {
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");

        match ext.to_lowercase().as_str() {
            "html" | "htm" => "text/html; charset=utf-8",
            "css" => "text/css; charset=utf-8",
            "js" | "mjs" => "application/javascript; charset=utf-8",
            "json" => "application/json; charset=utf-8",
            "png" => "image/png",
            "jpg" | "jpeg" => "image/jpeg",
            "gif" => "image/gif",
            "svg" => "image/svg+xml",
            "ico" => "image/x-icon",
            "woff" => "font/woff",
            "woff2" => "font/woff2",
            "ttf" => "font/ttf",
            "eot" => "application/vnd.ms-fontobject",
            "pdf" => "application/pdf",
            "txt" => "text/plain; charset=utf-8",
            "xml" => "application/xml; charset=utf-8",
            "mp4" => "video/mp4",
            "webm" => "video/webm",
            "mp3" => "audio/mpeg",
            "wav" => "audio/wav",
            "zip" => "application/zip",
            _ => "application/octet-stream",
        }
        .to_string()
    }

    /// Clear the cache
    pub fn clear_cache(&self) {
        self.cache.write().clear();
    }

    /// Get cache statistics
    pub fn cache_stats(&self) -> (usize, usize) {
        let cache = self.cache.read();
        let count = cache.len();
        let bytes: usize = cache.values().map(|f| f.size).sum();
        (count, bytes)
    }
}

/// Static file errors
#[derive(Debug, Clone)]
pub enum StaticFileError {
    NotFound,
    InvalidPath,
    IoError,
    TooLarge,
}

impl std::fmt::Display for StaticFileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StaticFileError::NotFound => write!(f, "File not found"),
            StaticFileError::InvalidPath => write!(f, "Invalid path"),
            StaticFileError::IoError => write!(f, "I/O error"),
            StaticFileError::TooLarge => write!(f, "File too large"),
        }
    }
}

impl std::error::Error for StaticFileError {}
