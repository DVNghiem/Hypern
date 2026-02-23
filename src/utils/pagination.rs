use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Pagination metadata computed entirely in Rust — zero Python overhead.
///
/// Example (Python):
///     info = paginate(total=95, page=2, per_page=10)
///     info.total_pages  # 10
///     info.offset       # 10
///     info.has_next     # True
///     info.to_dict()    # ready to embed in a JSON response
#[pyclass(frozen, from_py_object)]
#[derive(Clone, Debug)]
pub struct PageInfo {
    #[pyo3(get)]
    pub total: u64,
    #[pyo3(get)]
    pub page: u64,
    #[pyo3(get)]
    pub per_page: u64,
    #[pyo3(get)]
    pub total_pages: u64,
    #[pyo3(get)]
    pub has_next: bool,
    #[pyo3(get)]
    pub has_prev: bool,
    /// SQL ``OFFSET`` value
    #[pyo3(get)]
    pub offset: u64,
    /// First item number on this page (1-based, 0 if empty)
    #[pyo3(get)]
    pub from_item: u64,
    /// Last item number on this page (1-based, 0 if empty)
    #[pyo3(get)]
    pub to_item: u64,
}

#[pymethods]
impl PageInfo {
    /// Return all fields as a plain ``dict`` ready for JSON serialisation.
    pub fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        d.set_item("total", self.total)?;
        d.set_item("page", self.page)?;
        d.set_item("per_page", self.per_page)?;
        d.set_item("total_pages", self.total_pages)?;
        d.set_item("has_next", self.has_next)?;
        d.set_item("has_prev", self.has_prev)?;
        d.set_item("offset", self.offset)?;
        d.set_item("from", self.from_item)?;
        d.set_item("to", self.to_item)?;
        Ok(d)
    }

    fn __repr__(&self) -> String {
        format!(
            "PageInfo(page={}/{}, per_page={}, total={}, offset={})",
            self.page, self.total_pages, self.per_page, self.total, self.offset
        )
    }
}

/// Compute pagination metadata.
///
/// Args:
///     total:    Total item count.
///     page:     Current page (1-based). Clamped to ``[1, total_pages]``.
///     per_page: Items per page. Clamped to ``[1, 10 000]``.
///
/// Returns:
///     :class:`PageInfo` with all derived fields.
///
/// Example (Python)::
///
///     from hypern._hypern import paginate
///     pg = paginate(total=250, page=3, per_page=25)
///     # SELECT * FROM t ORDER BY id LIMIT {pg.per_page} OFFSET {pg.offset}
#[pyfunction]
#[pyo3(signature = (total, page=1, per_page=20))]
pub fn paginate(total: u64, page: u64, per_page: u64) -> PageInfo {
    let per_page = per_page.clamp(1, 10_000);
    let total_pages = if total == 0 {
        1
    } else {
        (total + per_page - 1) / per_page
    };
    let page = page.clamp(1, total_pages);
    let offset = (page - 1) * per_page;

    let (from_item, to_item) = if total == 0 {
        (0, 0)
    } else {
        (offset + 1, (offset + per_page).min(total))
    };

    PageInfo {
        total,
        page,
        per_page,
        total_pages,
        has_next: page < total_pages,
        has_prev: page > 1,
        offset,
        from_item,
        to_item,
    }
}

/// Encode an integer offset into an opaque URL-safe cursor string.
///
/// Example (Python):
///     cursor = encode_cursor(40)       # "AAAAAAAAAKQ"
///     offset = decode_cursor(cursor)   # 40
#[pyfunction]
pub fn encode_cursor(offset: u64) -> String {
    use base64::Engine;
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(offset.to_be_bytes())
}

/// Decode an opaque cursor string back to an integer offset.
///
/// Returns ``0`` on invalid input (safe default).
#[pyfunction]
pub fn decode_cursor(cursor: &str) -> u64 {
    use base64::Engine;
    base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(cursor)
        .ok()
        .and_then(|b| <[u8; 8]>::try_from(b).ok())
        .map(u64::from_be_bytes)
        .unwrap_or(0)
}

// ──────────────────── module registration ────────────────────────────────── //

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PageInfo>()?;
    m.add_function(wrap_pyfunction!(paginate, m)?)?;
    m.add_function(wrap_pyfunction!(encode_cursor, m)?)?;
    m.add_function(wrap_pyfunction!(decode_cursor, m)?)?;
    Ok(())
}
