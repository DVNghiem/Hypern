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
