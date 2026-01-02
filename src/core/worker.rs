use crate::{core::global::get_runtime, utils::cpu::num_cpus};

/// Work item to be processed by a worker
pub struct WorkItem<T> {
    pub id: u64,
    pub data: T,
}

/// Configuration for the worker pool
#[derive(Clone)]
pub struct WorkerPoolConfig {
    pub num_workers: usize,
    pub queue_size: usize,
    pub pin_to_cores: bool,
}

impl Default for WorkerPoolConfig {
    fn default() -> Self {
        Self {
            num_workers: num_cpus(1),
            queue_size: 1024,
            pin_to_cores: true,
        }
    }
}

impl WorkerPoolConfig {
    pub fn new(num_workers: usize) -> Self {
        Self {
            num_workers,
            ..Default::default()
        }
    }
}

/// A single worker in the pool
pub struct Worker<T: Send + 'static> {
    pub core_id: usize,
    pub sender: tokio::sync::mpsc::Sender<WorkItem<T>>,
    handle: Option<tokio::task::JoinHandle<()>>,
}

impl<T: Send + 'static> Worker<T> {
    pub fn new<F, Fut>(core_id: usize, queue_size: usize, pin_to_core: bool, handler: F) -> Self
    where
        F: Fn(WorkItem<T>) -> Fut + Send + 'static,
        Fut: std::future::Future<Output = ()> + Send,
    {
        // let (tx, rx) = bounded(queue_size);
        let (tx, rx) = tokio::sync::mpsc::channel(queue_size);

        // Initialize Tokio Runtime for this thread
        let rt = get_runtime();
        let handle = rt.spawn(async move {
            // Pin to core if enabled
            if pin_to_core {
                if let Some(core_ids) = core_affinity::get_core_ids() {
                    if core_id < core_ids.len() {
                        core_affinity::set_for_current(core_ids[core_id]);
                    }
                }
            }
            // Worker loop
            Self::worker_loop_async(rx, handler).await;
        });

        Self {
            core_id,
            sender: tx,
            handle: Some(handle),
        }
    }

    async fn worker_loop_async<F, Fut>(mut rx: tokio::sync::mpsc::Receiver<WorkItem<T>>, handler: F)
    where
        F: Fn(WorkItem<T>) -> Fut,
        Fut: std::future::Future<Output = ()>,
    {
        let mut batch = Vec::with_capacity(32);

        loop {
            // Batch receive
            batch.clear();

            // Wait for first item
            if let Some(item) = rx.recv().await {
                batch.push(item);

                // Try to fill batch without waiting
                while batch.len() < 32 {
                    match rx.try_recv() {
                        Ok(item) => batch.push(item),
                        Err(_) => break,
                    }
                }

                // Process batch concurrently
                futures::future::join_all(batch.drain(..).map(|item| handler(item))).await;
            } else {
                break; // Channel closed
            }
        }
    }

    pub async fn submit(
        &self,
        item: WorkItem<T>,
    ) -> Result<(), tokio::sync::mpsc::error::SendError<WorkItem<T>>> {
        self.sender.send(item).await
    }
}

impl<T: Send + 'static> Drop for Worker<T> {
    fn drop(&mut self) {
        if let Some(handle) = self.handle.take() {
            handle.abort();
        }
    }
}

/// Worker pool for distributing work across CPU cores
pub struct WorkerPool<T: Send + 'static> {
    workers: Vec<Worker<T>>,
    next_worker: std::sync::atomic::AtomicUsize,
}

impl<T: Send + 'static> WorkerPool<T> {
    pub fn new<F, Fut>(config: WorkerPoolConfig, handler: F) -> Self
    where
        F: Fn(WorkItem<T>) -> Fut + Send + Clone + 'static,
        Fut: std::future::Future<Output = ()> + Send,
    {
        let mut workers = Vec::with_capacity(config.num_workers);

        for core_id in 0..config.num_workers {
            let worker = Worker::new(
                core_id,
                config.queue_size,
                config.pin_to_cores,
                handler.clone(),
            );
            workers.push(worker);
        }

        Self {
            workers,
            next_worker: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    /// Submit work using round-robin distribution
    pub async fn submit_round_robin(
        &self,
        item: WorkItem<T>,
    ) -> Result<(), tokio::sync::mpsc::error::SendError<WorkItem<T>>> {
        let idx = self
            .next_worker
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            % self.workers.len();
        self.workers[idx].submit(item).await
    }

    /// Submit work to a specific worker based on hash (affinity routing)
    pub async fn submit_affinity(
        &self,
        item: WorkItem<T>,
        hash: u64,
    ) -> Result<(), tokio::sync::mpsc::error::SendError<WorkItem<T>>> {
        let idx = (hash as usize) % self.workers.len();
        self.workers[idx].submit(item).await
    }
    /// Get number of workers
    pub fn num_workers(&self) -> usize {
        self.workers.len()
    }
}
