use std::{future::Future, pin::Pin, sync::Arc, task::Poll};

use crate::{Router, body::HTTPResponseBody, core::interpreter_pool::InterpreterPool};



pub struct HypernService {
    pub pool: Arc<InterpreterPool>,
    pub router: Arc<Router>,
}

impl tower::Service<hyper::Request<hyper::body::Incoming>> for HypernService {
    type Response = HTTPResponseBody;
    type Error = hyper::Error;
    type Future = Pin<Box<dyn Future<Output=Result<Self::Response, Self::Error>> + Send>>;
    
    fn call(&mut self, req: hyper::Request<hyper::body::Incoming>) -> Self::Future {
        let pool = self.pool.clone(); // Only clone once per call
        let router = self.router.clone();
        
        Box::pin(async move {
            // Handle the request using the interpreter pool and router
            // (Implementation details would go here)
            Ok(HTTPResponseBody::new()) // Placeholder response
        })
    }
    
    fn poll_ready(&mut self, cx: &mut std::task::Context<'_>) -> std::task::Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }
}
