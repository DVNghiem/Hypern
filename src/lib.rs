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
mod body;
mod header;
mod request;
mod response;
mod response_builder;
mod socket;
mod errors;
mod runtime;
mod execute;
mod application;
mod lifecycle;
pub mod radix;
pub mod route;
pub mod middleware;

#[pymodule(gil_used = false)]
fn hypern(_py: Python, module: &Bound<PyModule>) -> PyResult<()>  {

    module.add_class::<server::Server>()?;
    module.add_class::<route::Route>()?;
    module.add_class::<router::Router>()?;
    module.add_class::<middleware::Middleware>()?;
    module.add_class::<application::Application>()?;
    module.add_class::<response::Response>()?;
    module.add_class::<response_builder::ResponseBuilder>()?;
    module.add_class::<request::Request>()?;
    module.add_class::<header::HypernHeaders>()?;
    module.add_class::<socket::SocketHeld>()?;
    module.add_class::<errors::HypernError>()?;
    module.add_class::<errors::DefaultErrorHandler>()?;
    module.add_class::<errors::ErrorContext>()?;
    module.add_class::<lifecycle::LifecycleManager>()?;

    pyo3::prepare_freethreaded_python();
    Ok(())
}
