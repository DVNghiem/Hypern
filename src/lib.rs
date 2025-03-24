use pyo3::prelude::*;

mod instants;
mod openapi;
mod background;
mod scheduler;
mod server;
mod router;
mod types;
mod ws;
mod executor;
mod middlewares;
mod database;
mod di;
mod runtime;
mod http;

#[pymodule]
fn hypern(_py: Python<'_>, m: &PyModule) -> PyResult<()>  {

    m.add_class::<openapi::schemas::BaseSchemaGenerator>()?;
    m.add_class::<openapi::swagger::SwaggerUI>()?;    

    m.add_class::<background::background_task::BackgroundTask>()?;
    m.add_class::<background::background_tasks::BackgroundTasks>()?;

    m.add_class::<scheduler::scheduler::Scheduler>()?;
    
    m.add_class::<server::Server>()?;
    m.add_class::<router::route::Route>()?;
    m.add_class::<router::router::Router>()?;
    m.add_class::<types::function_info::FunctionInfo>()?;
    m.add_class::<types::response::PyResponse>()?;
    m.add_class::<types::header::Header>()?;
    m.add_class::<types::request::PyRequest>()?;
    m.add_class::<types::request::PyBodyData>()?;
    m.add_class::<types::request::PyUploadedFile>()?;
    m.add_class::<types::query::QueryParams>()?;
    m.add_class::<middlewares::base::MiddlewareConfig>()?;
    
    m.add_class::<ws::socket::SocketHeld>()?;
    m.add_class::<ws::websocket::WebSocketSession>()?;
    m.add_class::<ws::route::WebsocketRoute>()?;
    m.add_class::<ws::router::PyWebsocketRouter>()?;

    m.add_class::<database::sql::config::DatabaseConfig>()?;
    m.add_class::<database::sql::config::DatabaseType>()?;
    m.add_class::<database::sql::transaction::DatabaseTransaction>()?;

    m.add_function(wrap_pyfunction!(database::context::get_session_database, m)?)?;

    pyo3::prepare_freethreaded_python();
    Ok(())
}
