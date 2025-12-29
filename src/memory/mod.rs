// Memory management with object pooling and arena allocation
pub mod arena;
pub mod pool;

pub use pool::{ObjectPool, RequestPool, ResponsePool};
