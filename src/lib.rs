#[cfg(not(any(
    target_env = "musl",
    target_os = "freebsd",
    target_os = "openbsd",
    target_os = "windows",
    feature = "mimalloc"
)))]
#[global_allocator]
static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

#[cfg(feature = "mimalloc")]
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

use pyo3::prelude::*;

mod server;
mod router;
mod types;
mod socket;
mod errors;
mod runtime;
mod execute;

#[pymodule(gil_used = false)]
fn hypern(_py: Python, module: &Bound<PyModule>) -> PyResult<()>  {

    module.add_class::<server::Server>()?;
    module.add_class::<router::route::Route>()?;
    module.add_class::<router::router::Router>()?;
    module.add_class::<types::response::Response>()?;
    module.add_class::<types::request::Request>()?;
    module.add_class::<types::header::HypernHeaders>()?;
    module.add_class::<socket::SocketHeld>()?;

    pyo3::prepare_freethreaded_python();
    Ok(())
}
