use crossbeam_channel as channel;
use pyo3::prelude::*;
use std::{
    sync::{atomic, Arc, Mutex},
    thread, time,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BlockingRunnerError {
    ShuttingDown,
    Closed,
    QueueFull,
}

pub(crate) enum BlockingTask {
    Run {
        inner: Box<dyn FnOnce(Python, &WorkerEventLoop) + Send + 'static>,
        completion: Box<dyn FnOnce(Result<(), BlockingRunnerError>) + Send + 'static>,
    },
    Shutdown(channel::Sender<()>),
}

impl BlockingTask {
    #[inline]
    pub fn new<T, C>(inner: T, completion: C) -> BlockingTask
    where
        T: FnOnce(Python, &WorkerEventLoop) + Send + 'static,
        C: FnOnce(Result<(), BlockingRunnerError>) + Send + 'static,
    {
        Self::Run {
            inner: Box::new(inner),
            completion: Box::new(completion),
        }
    }

    #[inline(always)]
    fn run(self, py: Python<'_>, event_loop: &WorkerEventLoop) {
        if let Self::Run { inner, completion } = self {
            inner(py, event_loop);
            completion(Ok(()));
        }
    }

    fn reject(self, error: BlockingRunnerError) {
        if let Self::Run { completion, .. } = self {
            completion(Err(error));
        }
    }
}

pub(crate) struct WorkerEventLoop {
    event_loop: Py<PyAny>,
    pub(crate) run_until_complete: Py<PyAny>,
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
    admission: Mutex<()>,
    shutting_down: Arc<atomic::AtomicBool>,
    force_shutdown: Arc<atomic::AtomicBool>,
    event_loops: Arc<Mutex<Vec<Py<PyAny>>>>,
    spawn_tick: atomic::AtomicU64,
}

impl BlockingRunner {
    pub fn new(max_threads: usize, idle_timeout: u64, queue_capacity: usize) -> Self {
        // Do not let slow Python handlers turn into an unbounded latency and
        // memory queue.  Admission is non-blocking; callers get QueueFull and
        // can return an overload response immediately.
        let (qtx, qrx) = channel::bounded(queue_capacity.max(1));
        let threads = Arc::new(atomic::AtomicUsize::new(0));
        let event_loops = Arc::new(Mutex::new(Vec::with_capacity(max_threads)));
        let force_shutdown = Arc::new(atomic::AtomicBool::new(false));
        let shutting_down = Arc::new(atomic::AtomicBool::new(false));

        // Pre-spawn all threads up to max for immediate availability
        // This avoids thread spawn overhead during request handling
        let initial_threads = max_threads;
        for _ in 0..initial_threads {
            let queue = qrx.clone();
            let tcount = threads.clone();
            let loops = event_loops.clone();
            let forced = force_shutdown.clone();
            let worker_shutdown = shutting_down.clone();
            tcount.fetch_add(1, atomic::Ordering::Release);
            thread::spawn(move || {
                blocking_worker(queue, loops, forced, worker_shutdown);
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
            admission: Mutex::new(()),
            shutting_down,
            force_shutdown,
            event_loops,
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
        let loops = self.event_loops.clone();
        let forced = self.force_shutdown.clone();
        let shutting_down = self.shutting_down.clone();
        let timeout = self.idle_timeout;
        tcount.fetch_add(1, atomic::Ordering::Release);
        thread::spawn(move || {
            blocking_worker_idle(queue, timeout, loops, forced, shutting_down);
            tcount.fetch_sub(1, atomic::Ordering::Release);
        });

        self.spawn_tick.store(
            self.birth.elapsed().as_micros() as u64,
            atomic::Ordering::Relaxed,
        );
        self.spawning.store(false, atomic::Ordering::Relaxed);
    }

    #[inline(always)]
    pub fn run<T, C>(&self, task: T, completion: C) -> Result<(), BlockingRunnerError>
    where
        T: FnOnce(Python) + Send + 'static,
        C: FnOnce(Result<(), BlockingRunnerError>) + Send + 'static,
    {
        self.run_with_event_loop(move |py, _| task(py), completion)
    }

    #[inline(always)]
    pub fn run_with_event_loop<T, C>(
        &self,
        task: T,
        completion: C,
    ) -> Result<(), BlockingRunnerError>
    where
        T: FnOnce(Python, &WorkerEventLoop) + Send + 'static,
        C: FnOnce(Result<(), BlockingRunnerError>) + Send + 'static,
    {
        let task = BlockingTask::new(task, completion);
        // Admission and shutdown markers share this lock, so an accepted task
        // is always queued before every worker exit marker.
        let admission = self.admission.lock().unwrap();
        if self.shutting_down.load(atomic::Ordering::Acquire) {
            drop(admission);
            task.reject(BlockingRunnerError::ShuttingDown);
            return Err(BlockingRunnerError::ShuttingDown);
        }
        match self.queue.try_send(task) {
            Ok(()) => {}
            Err(channel::TrySendError::Full(task)) => {
                drop(admission);
                task.reject(BlockingRunnerError::QueueFull);
                return Err(BlockingRunnerError::QueueFull);
            }
            Err(channel::TrySendError::Disconnected(task)) => {
                drop(admission);
                task.reject(BlockingRunnerError::Closed);
                return Err(BlockingRunnerError::Closed);
            }
        }
        // Spawn additional threads if queue is building up
        if self.queue.len() > 2 && self.threads.load(atomic::Ordering::Acquire) < self.tmax {
            self.spawn_thread();
        }
        drop(admission);
        Ok(())
    }

    pub fn shutdown(&self) {
        let admission = self.admission.lock().unwrap();
        if self.shutting_down.swap(true, atomic::Ordering::AcqRel) {
            return;
        }

        let mut rejected_tasks = Vec::new();
        while let Ok(task) = self.tq.try_recv() {
            match task {
                task @ BlockingTask::Run { .. } => rejected_tasks.push(task),
                BlockingTask::Shutdown(completion) => {
                    let _ = completion.send(());
                }
            }
        }

        let worker_count = self.threads.load(atomic::Ordering::Acquire);
        let (completion_tx, completion_rx) = channel::bounded(worker_count);
        let mut shutdown_count = 0;
        for _ in 0..worker_count {
            if self
                .queue
                .send(BlockingTask::Shutdown(completion_tx.clone()))
                .is_err()
            {
                break;
            }
            shutdown_count += 1;
        }
        drop(completion_tx);
        drop(admission);
        for task in rejected_tasks {
            task.reject(BlockingRunnerError::ShuttingDown);
        }

        let graceful_deadline = time::Instant::now() + time::Duration::from_secs(1);
        let completed =
            self.wait_for_workers(&completion_rx, shutdown_count, graceful_deadline, false);
        if completed == shutdown_count {
            return;
        }

        self.force_shutdown.store(true, atomic::Ordering::Release);
        let forced_deadline = time::Instant::now() + time::Duration::from_secs(1);
        self.wait_for_workers(
            &completion_rx,
            shutdown_count - completed,
            forced_deadline,
            true,
        );
    }

    fn wait_for_workers(
        &self,
        completion_rx: &channel::Receiver<()>,
        worker_count: usize,
        deadline: time::Instant,
        force: bool,
    ) -> usize {
        let mut completed = 0;
        while completed < worker_count {
            if force {
                self.stop_worker_loops();
            } else {
                self.cancel_worker_tasks();
            }
            let Some(remaining) = deadline.checked_duration_since(time::Instant::now()) else {
                break;
            };
            let wait = remaining.min(time::Duration::from_millis(50));
            match completion_rx.recv_timeout(wait) {
                Ok(()) => completed += 1,
                Err(channel::RecvTimeoutError::Timeout) => continue,
                Err(channel::RecvTimeoutError::Disconnected) => break,
            }
        }
        completed
    }

    fn cancel_worker_tasks(&self) {
        Python::attach(|py| {
            let Ok(asyncio) = py.import("asyncio") else {
                return;
            };
            let loops = self.event_loops.lock().unwrap();
            for event_loop in loops.iter() {
                let loop_ref = event_loop.bind(py);
                let Ok(tasks) = asyncio.call_method1("all_tasks", (loop_ref,)) else {
                    continue;
                };
                let Ok(tasks) = tasks.try_iter() else {
                    continue;
                };
                for task in tasks.flatten() {
                    if let Ok(cancel) = task.getattr("cancel") {
                        let _ = loop_ref.call_method1("call_soon_threadsafe", (cancel,));
                    }
                }
            }
        });
    }

    fn stop_worker_loops(&self) {
        Python::attach(|py| {
            let loops = self.event_loops.lock().unwrap();
            for event_loop in loops.iter() {
                let loop_ref = event_loop.bind(py);
                if let Ok(stop) = loop_ref.getattr("stop") {
                    let _ = loop_ref.call_method1("call_soon_threadsafe", (stop,));
                }
            }
        });
    }
}

fn blocking_worker(
    queue: channel::Receiver<BlockingTask>,
    event_loops: Arc<Mutex<Vec<Py<PyAny>>>>,
    force_shutdown: Arc<atomic::AtomicBool>,
    shutting_down: Arc<atomic::AtomicBool>,
) {
    Python::attach(|py| {
        let event_loop = create_worker_event_loop(py);
        event_loops
            .lock()
            .unwrap()
            .push(event_loop.event_loop.clone_ref(py));
        let completion = loop {
            match py.detach(|| queue.recv()) {
                Ok(task @ BlockingTask::Run { .. }) => {
                    if shutting_down.load(atomic::Ordering::Acquire) {
                        task.reject(BlockingRunnerError::ShuttingDown);
                    } else {
                        task.run(py, &event_loop);
                    }
                }
                Ok(BlockingTask::Shutdown(completion)) => break Some(completion),
                Err(_) => break None,
            }
        };
        close_worker_event_loop(
            py,
            &event_loop.event_loop,
            force_shutdown.load(atomic::Ordering::Acquire),
        );
        if let Some(completion) = completion {
            let _ = completion.send(());
        }
    });
}

fn blocking_worker_idle(
    queue: channel::Receiver<BlockingTask>,
    timeout: time::Duration,
    event_loops: Arc<Mutex<Vec<Py<PyAny>>>>,
    force_shutdown: Arc<atomic::AtomicBool>,
    shutting_down: Arc<atomic::AtomicBool>,
) {
    Python::attach(|py| {
        let event_loop = create_worker_event_loop(py);
        event_loops
            .lock()
            .unwrap()
            .push(event_loop.event_loop.clone_ref(py));
        let completion = loop {
            match py.detach(|| queue.recv_timeout(timeout)) {
                Ok(task @ BlockingTask::Run { .. }) => {
                    if shutting_down.load(atomic::Ordering::Acquire) {
                        task.reject(BlockingRunnerError::ShuttingDown);
                    } else {
                        task.run(py, &event_loop);
                    }
                }
                Ok(BlockingTask::Shutdown(completion)) => break Some(completion),
                Err(_) => break None,
            }
        };
        close_worker_event_loop(
            py,
            &event_loop.event_loop,
            force_shutdown.load(atomic::Ordering::Acquire),
        );
        if let Some(completion) = completion {
            let _ = completion.send(());
        }
    });
}

fn create_worker_event_loop(py: Python<'_>) -> WorkerEventLoop {
    let asyncio = py.import("asyncio").expect("Failed to import asyncio");
    let event_loop = asyncio
        .call_method0("new_event_loop")
        .expect("Failed to create worker event loop");
    asyncio
        .call_method1("set_event_loop", (&event_loop,))
        .expect("Failed to set worker event loop");
    let run_until_complete = event_loop
        .getattr("run_until_complete")
        .expect("Failed to cache worker event loop runner")
        .unbind();
    WorkerEventLoop {
        event_loop: event_loop.unbind(),
        run_until_complete,
    }
}

fn close_worker_event_loop(py: Python<'_>, event_loop: &Py<PyAny>, forced: bool) {
    let loop_ref = event_loop.bind(py);
    let asyncio = match py.import("asyncio") {
        Ok(asyncio) => asyncio,
        Err(error) => {
            error.print(py);
            return;
        }
    };

    if !forced {
        if let Ok(runners) = py.import("asyncio.runners") {
            if let Err(error) = runners.call_method1("_cancel_all_tasks", (loop_ref,)) {
                error.print(py);
            }
        }
        for shutdown_method in ["shutdown_asyncgens", "shutdown_default_executor"] {
            match loop_ref.call_method0(shutdown_method) {
                Ok(shutdown) => {
                    if let Err(error) = loop_ref.call_method1("run_until_complete", (shutdown,)) {
                        error.print(py);
                    }
                }
                Err(error) => error.print(py),
            }
        }
    }
    if let Err(error) = loop_ref.call_method0("close") {
        error.print(py);
    }
    if let Err(error) = asyncio.call_method1("set_event_loop", (py.None(),)) {
        error.print(py);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_work_when_the_bounded_queue_is_full() {
        // No workers are needed: the first item occupies the sole queue slot,
        // allowing the admission path to be tested deterministically.
        let runner = BlockingRunner::new(0, 1, 1);
        runner.run(|_| {}, |_| {}).unwrap();

        let (tx, rx) = std::sync::mpsc::channel();
        let result = runner.run(|_| {}, move |outcome| tx.send(outcome).unwrap());

        assert_eq!(result, Err(BlockingRunnerError::QueueFull));
        assert_eq!(rx.recv().unwrap(), Err(BlockingRunnerError::QueueFull));
    }
}
