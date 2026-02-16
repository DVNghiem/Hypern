use crossbeam_channel as channel;
use pyo3::prelude::*;
use std::{
    sync::{atomic, Arc},
    thread, time,
};

pub(crate) struct BlockingTask {
    inner: Box<dyn FnOnce(Python) + Send + 'static>,
}

impl BlockingTask {
    #[inline]
    pub fn new<T>(inner: T) -> BlockingTask
    where
        T: FnOnce(Python) + Send + 'static,
    {
        Self {
            inner: Box::new(inner),
        }
    }

    #[inline(always)]
    pub fn run(self, py: Python) {
        (self.inner)(py);
    }
}

#[derive(Debug)]
pub(crate) struct BlockingRunner {
    birth: time::Instant,
    queue: channel::Sender<BlockingTask>,
    tq: channel::Receiver<BlockingTask>,
    threads: Arc<atomic::AtomicUsize>,
    tmax: usize,
    idle_timeout: time::Duration,
    spawning: atomic::AtomicBool,
    spawn_tick: atomic::AtomicU64,
}

impl BlockingRunner {
    pub fn new(max_threads: usize, idle_timeout: u64) -> Self {
        let (qtx, qrx) = channel::unbounded();
        let threads = Arc::new(atomic::AtomicUsize::new(0));

        // Pre-spawn all threads up to max for immediate availability
        // This avoids thread spawn overhead during request handling
        let initial_threads = max_threads;
        for _ in 0..initial_threads {
            let queue = qrx.clone();
            let tcount = threads.clone();
            tcount.fetch_add(1, atomic::Ordering::Release);
            thread::spawn(move || {
                blocking_worker(queue);
                tcount.fetch_sub(1, atomic::Ordering::Release);
            });
        }

        Self {
            queue: qtx,
            tq: qrx,
            threads,
            tmax: max_threads,
            birth: time::Instant::now(),
            spawning: false.into(),
            spawn_tick: 0.into(),
            idle_timeout: time::Duration::from_secs(idle_timeout),
        }
    }

    #[inline(always)]
    fn spawn_thread(&self) {
        // Reduced throttle: 100μs instead of 350μs for faster scaling
        let tick = self.birth.elapsed().as_micros() as u64;
        if tick - self.spawn_tick.load(atomic::Ordering::Relaxed) < 100 {
            return;
        }
        if self
            .spawning
            .compare_exchange(
                false,
                true,
                atomic::Ordering::Relaxed,
                atomic::Ordering::Relaxed,
            )
            .is_err()
        {
            return;
        }

        let queue = self.tq.clone();
        let tcount = self.threads.clone();
        let timeout = self.idle_timeout;
        thread::spawn(move || {
            tcount.fetch_add(1, atomic::Ordering::Release);
            blocking_worker_idle(queue, timeout);
            tcount.fetch_sub(1, atomic::Ordering::Release);
        });

        self.spawn_tick.store(
            self.birth.elapsed().as_micros() as u64,
            atomic::Ordering::Relaxed,
        );
        self.spawning.store(false, atomic::Ordering::Relaxed);
    }

    #[inline(always)]
    pub fn run<T>(&self, task: T) -> Result<(), channel::SendError<BlockingTask>>
    where
        T: FnOnce(Python) + Send + 'static,
    {
        self.queue.send(BlockingTask::new(task))?;
        // Spawn additional threads if queue is building up
        if self.queue.len() > 2 && self.threads.load(atomic::Ordering::Acquire) < self.tmax {
            self.spawn_thread();
        }
        Ok(())
    }
}

fn blocking_worker(queue: channel::Receiver<BlockingTask>) {
    Python::attach(|py| {
        while let Ok(task) = py.detach(|| queue.recv()) {
            task.run(py);
        }
    });
}

fn blocking_worker_idle(queue: channel::Receiver<BlockingTask>, timeout: time::Duration) {
    Python::attach(|py| {
        while let Ok(task) = py.detach(|| queue.recv_timeout(timeout)) {
            task.run(py);
        }
    });
}
