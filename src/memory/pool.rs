use parking_lot::Mutex;

/// Generic object pool for reusable objects
pub struct ObjectPool<T> {
    pool: Mutex<Vec<T>>,
    max_size: usize,
    create_fn: Box<dyn Fn() -> T + Send + Sync>,
}

impl<T> ObjectPool<T> {
    pub fn new<F>(max_size: usize, create_fn: F) -> Self
    where
        F: Fn() -> T + Send + Sync + 'static,
    {
        Self {
            pool: Mutex::new(Vec::with_capacity(max_size)),
            max_size,
            create_fn: Box::new(create_fn),
        }
    }

    /// Get an object from the pool or create a new one
    pub fn get(&self) -> T {
        self.pool.lock().pop().unwrap_or_else(|| (self.create_fn)())
    }

    /// Return an object to the pool
    pub fn put(&self, obj: T) {
        let mut pool = self.pool.lock();
        if pool.len() < self.max_size {
            pool.push(obj);
        }
        // Drop if pool is full
    }

    /// Get current pool size
    pub fn size(&self) -> usize {
        self.pool.lock().len()
    }

    /// Pre-populate the pool
    pub fn warm(&self, count: usize) {
        let mut pool = self.pool.lock();
        for _ in 0..count.min(self.max_size - pool.len()) {
            pool.push((self.create_fn)());
        }
    }
}

/// Request buffer pool for zero-allocation request parsing
pub struct RequestPool {
    buffers: ObjectPool<Vec<u8>>,
}

impl RequestPool {
    pub fn new(max_size: usize, buffer_capacity: usize) -> Self {
        Self {
            buffers: ObjectPool::new(max_size, move || Vec::with_capacity(buffer_capacity)),
        }
    }

    pub fn get_buffer(&self) -> Vec<u8> {
        let mut buf = self.buffers.get();
        buf.clear();
        buf
    }

    pub fn return_buffer(&self, buf: Vec<u8>) {
        self.buffers.put(buf);
    }
}

impl Default for RequestPool {
    fn default() -> Self {
        Self::new(1024, 8192) // 1K buffers, 8KB each
    }
}

/// Response buffer pool for zero-allocation response building
pub struct ResponsePool {
    buffers: ObjectPool<Vec<u8>>,
    header_buffers: ObjectPool<Vec<(String, String)>>,
}

impl ResponsePool {
    pub fn new(max_size: usize, buffer_capacity: usize) -> Self {
        Self {
            buffers: ObjectPool::new(max_size, move || Vec::with_capacity(buffer_capacity)),
            header_buffers: ObjectPool::new(max_size, || Vec::with_capacity(16)),
        }
    }

    pub fn get_body_buffer(&self) -> Vec<u8> {
        let mut buf = self.buffers.get();
        buf.clear();
        buf
    }

    pub fn return_body_buffer(&self, buf: Vec<u8>) {
        self.buffers.put(buf);
    }

    pub fn get_header_buffer(&self) -> Vec<(String, String)> {
        let mut buf = self.header_buffers.get();
        buf.clear();
        buf
    }

    pub fn return_header_buffer(&self, buf: Vec<(String, String)>) {
        self.header_buffers.put(buf);
    }
}

impl Default for ResponsePool {
    fn default() -> Self {
        Self::new(1024, 4096) // 1K buffers, 4KB each
    }
}
