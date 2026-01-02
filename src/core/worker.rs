use std::time::Duration;

use crate::{runtime::get_runtime, utils::cpu::num_cpus};

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
    pub batch_size: usize,
    pub batch_timeout_us: u64
}

impl Default for WorkerPoolConfig {
    fn default() -> Self {
        Self {
            num_workers: num_cpus(1),
            queue_size: 2048,
            pin_to_cores: true,
            batch_size: 128,
            batch_timeout_us: 100,
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

pub struct Worker<T: Send + Sync + Clone + 'static> {
    pub core_id: usize,
    pub sender: tokio::sync::mpsc::Sender<WorkItem<T>>,
    handle: Option<tokio::task::JoinHandle<()>>,
}

impl<T: Send + Sync + Clone + 'static> Worker<T> {
    pub fn new<F, Fut>(core_id: usize, config: &WorkerPoolConfig, handler: F) -> Self
    where
        F: Fn(WorkItem<T>) -> Fut + Send + Sync + 'static,
        Fut: std::future::Future<Output = ()> + Send + 'static,
    {
        let (tx, rx) = tokio::sync::mpsc::channel(config.queue_size);
        let batch_size = config.batch_size;
        let batch_timeout = Duration::from_micros(config.batch_timeout_us);
        let pin_to_core = config.pin_to_cores;
        let rt = get_runtime();
        let handle = rt.spawn(async move {
            if pin_to_core {
                if let Some(core_ids) = core_affinity::get_core_ids() {
                    if core_id < core_ids.len() {
                        core_affinity::set_for_current(core_ids[core_id]);
                    }
                }
            }
            worker_loop_optimized(rx, handler, batch_size, batch_timeout).await;
        });

        Self {
            core_id,
            sender: tx,
            handle: Some(handle),
        }
    }

    pub async fn submit(
        &self,
        item: WorkItem<T>,
    ) -> Result<(), tokio::sync::mpsc::error::SendError<WorkItem<T>>> {
        self.sender.send(item).await
    }
}

async fn worker_loop_optimized<T, F, Fut>(
    mut rx: tokio::sync::mpsc::Receiver<WorkItem<T>>,
    handler: F,
    batch_size: usize,
    batch_timeout: Duration,
) where
    T: Send + Sync + Clone + 'static,
    F: Fn(WorkItem<T>) -> Fut + Send + Sync + 'static,
    Fut: std::future::Future<Output = ()> + Send + 'static,
{
    let mut batch = Vec::with_capacity(batch_size);
    
    loop {
        batch.clear();
        
        while batch.len() < batch_size {
            match rx.try_recv() {
                Ok(item) => batch.push(item),
                Err(tokio::sync::mpsc::error::TryRecvError::Empty) => break,
                Err(tokio::sync::mpsc::error::TryRecvError::Disconnected) => {
                    if !batch.is_empty() {
                        process_batch_parallel(&batch, &handler).await;
                    }
                    return;
                }
            }
        }
        
        if batch.is_empty() {
            match tokio::time::timeout(batch_timeout, rx.recv()).await {
                Ok(Some(item)) => {
                    batch.push(item);
                    while batch.len() < batch_size {
                        match rx.try_recv() {
                            Ok(item) => batch.push(item),
                            Err(_) => break,
                        }
                    }
                }
                Ok(None) => return,
                Err(_) => continue,
            }
        }
        
        if !batch.is_empty() {
            process_batch_parallel(&batch, &handler).await;
        }
    }
}

#[inline]
async fn process_batch_parallel<T, F, Fut>(batch: &[WorkItem<T>], handler: &F)
where
    T: Send + Sync + Clone + 'static,
    F: Fn(WorkItem<T>) -> Fut + Send + Sync + 'static,
    Fut: std::future::Future<Output = ()> + Send + 'static,
{
    for item in batch {
        let fut = handler(WorkItem {
            id: item.id,
            data: item.data.clone(),
        });
        tokio::spawn(fut);
    }
    
    tokio::task::yield_now().await;
}

impl<T: Send + Sync + Clone + 'static> Drop for Worker<T> {
    fn drop(&mut self) {
        if let Some(handle) = self.handle.take() {
            handle.abort();
        }
    }
}

pub struct WorkerPool<T: Send + Sync + Clone + 'static> {
    workers: Vec<Worker<T>>,
    next_worker: std::sync::atomic::AtomicUsize,
}

impl<T: Send + Sync + Clone + 'static> WorkerPool<T> {
    pub fn new<F, Fut>(config: WorkerPoolConfig, handler: F) -> Self
    where
        F: Fn(WorkItem<T>) -> Fut + Send + Sync + Clone + 'static,
        Fut: std::future::Future<Output = ()> + Send + 'static,
    {
        let mut workers = Vec::with_capacity(config.num_workers);

        for core_id in 0..config.num_workers {
            let worker = Worker::new(
                core_id,
                &config,
                handler.clone(),
            );
            workers.push(worker);
        }

        Self {
            workers,
            next_worker: std::sync::atomic::AtomicUsize::new(0),
        }
    }

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

    pub async fn submit_affinity(
        &self,
        item: WorkItem<T>,
        hash: u64,
    ) -> Result<(), tokio::sync::mpsc::error::SendError<WorkItem<T>>> {
        let idx = (hash as usize) % self.workers.len();
        self.workers[idx].submit(item).await
    }

    pub fn num_workers(&self) -> usize {
        self.workers.len()
    }
}
