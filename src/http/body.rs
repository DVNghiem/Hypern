use bytes::Bytes;
use http_body_util::{BodyExt, Full};

pub type HTTPResponseBody = http_body_util::combinators::BoxBody<Bytes, anyhow::Error>;

pub fn full_http<T: Into<Bytes>>(chunk: T) -> HTTPResponseBody {
    Full::new(chunk.into())
        .map_err(|never| match never {})
        .boxed()
}
