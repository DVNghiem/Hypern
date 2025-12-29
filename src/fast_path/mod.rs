// Fast path handlers for pure Rust request processing
pub mod json_cache;
pub mod static_files;

pub use static_files::StaticFileHandler;
