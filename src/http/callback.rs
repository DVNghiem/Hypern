use pyo3::prelude::*;
use tokio::sync::oneshot;

#[pyclass]
pub struct PyResponseCallback {
    tx: Option<oneshot::Sender<()>>,
}

impl PyResponseCallback {
    pub fn new(tx: oneshot::Sender<()>) -> Self {
        Self { tx: Some(tx) }
    }
}

#[pymethods]
impl PyResponseCallback {
    /// Called by Python's task.add_done_callback
    pub fn done(&mut self, _task: Bound<'_, PyAny>) {
        if let Some(tx) = self.tx.take() {
            let _ = tx.send(());
        }
    }
}
