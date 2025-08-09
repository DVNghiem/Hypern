use pyo3::prelude::*;

mod instants;
mod server;
mod router;
mod types;
mod executor;
mod socket;

#[pymodule]
fn hypern(_py: Python<'_>, m: &PyModule) -> PyResult<()>  {

    m.add_class::<server::Server>()?;
    m.add_class::<router::route::Route>()?;
    m.add_class::<router::router::Router>()?;
    m.add_class::<types::function_info::FunctionInfo>()?;
    m.add_class::<types::response::Response>()?;
    m.add_class::<types::header::HypernHeaders>()?;
    m.add_class::<types::request::Request>()?;
    m.add_class::<socket::SocketHeld>()?;

    pyo3::prepare_freethreaded_python();
    Ok(())
}
