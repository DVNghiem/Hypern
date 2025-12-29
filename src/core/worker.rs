use crossbeam::channel::{bounded, Receiver, Sender};
use std::thread::{self, JoinHandle};

use crate::utils::cpu::num_cpus;

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
    pub sender: Sender<WorkItem<T>>,
    handle: Option<JoinHandle<()>>,
}

impl<T: Send + 'static> Worker<T> {
    pub fn new<F>(core_id: usize, queue_size: usize, pin_to_core: bool, handler: F) -> Self
    where
        F: Fn(WorkItem<T>) + Send + 'static,
    {
        let (tx, rx) = bounded(queue_size);

        let handle = thread::Builder::new()
            .name(format!("hypern-worker-{}", core_id))
            .spawn(move || {
                // Pin to core if enabled
                if pin_to_core {
                    if let Some(core_ids) = core_affinity::get_core_ids() {
                        if core_id < core_ids.len() {
                            core_affinity::set_for_current(core_ids[core_id]);
                        }
                    }
                }
                // Worker loop
                Self::worker_loop(rx, handler);
            })
            .expect("Failed to spawn worker thread");

        Self {
            core_id,
            sender: tx,
            handle: Some(handle),
        }
    }

    fn worker_loop<F>(rx: Receiver<WorkItem<T>>, handler: F)
    where
        F: Fn(WorkItem<T>),
    {
        loop {
            match rx.recv() {
                Ok(work_item) => {
                    handler(work_item);
                }
                Err(_) => {
                    // Channel closed, exit loop
                    break;
                }
            }
        }
    }

    pub fn submit(
        &self,
        item: WorkItem<T>,
    ) -> Result<(), crossbeam::channel::SendError<WorkItem<T>>> {
        self.sender.send(item)
    }

}

impl<T: Send + 'static> Drop for Worker<T> {
    fn drop(&mut self) {
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

/// Worker pool for distributing work across CPU cores
pub struct WorkerPool<T: Send + 'static> {
    workers: Vec<Worker<T>>,
    next_worker: std::sync::atomic::AtomicUsize,
}

impl<T: Send + 'static> WorkerPool<T> {
    pub fn new<F>(config: WorkerPoolConfig, handler: F) -> Self
    where
        F: Fn(WorkItem<T>) + Send + Clone + 'static,
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
    pub fn submit_round_robin(
        &self,
        item: WorkItem<T>,
    ) -> Result<(), crossbeam::channel::SendError<WorkItem<T>>> {
        let idx = self
            .next_worker
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            % self.workers.len();
        self.workers[idx].submit(item)
    }

    /// Submit work to a specific worker based on hash (affinity routing)
    pub fn submit_affinity(
        &self,
        item: WorkItem<T>,
        hash: u64,
    ) -> Result<(), crossbeam::channel::SendError<WorkItem<T>>> {
        let idx = (hash as usize) % self.workers.len();
        self.workers[idx].submit(item)
    }
    /// Get number of workers
    pub fn num_workers(&self) -> usize {
        self.workers.len()
    }
}

