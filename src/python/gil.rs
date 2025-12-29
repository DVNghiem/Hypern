use pyo3::prelude::*;

pub fn release_gil<F, R>(py: Python<'_>, f: F) -> R
where
    F: FnOnce() -> R + Send,
    R: Send,
{
    // Fix deprecation: Python::allow_threads -> Python::detach (or similar behavior)
    // However, allow_threads expects the closure to execute and return R.
    // detach returns a wrapper.
    // Pyo3 0.23: allow_threads is deprecated.
    // Note: The warning suggested `Python::detach`.
    // Let's rely on the fact that for simple blocking operations, allow_threads is still the semantic we want.
    // But to make the warning go away, we can use the suggestion if it matches.
    // Actually, `py.allow_threads(f)` is correct for < 0.23. 
    // If newer, we might need adjustments.
    // I will try to use the raw `pyo3::Python::allow_threads` if available or just ignore for now if I can't check docs.
    // BUT the warning explicitly said `use Python::detach instead`.
    // Let's try it.
    py.detach(f)
}
