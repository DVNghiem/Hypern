use bytes::Bytes;
use http_body_util::Full;

pub type HTTPResponseBody = Full<Bytes>;

pub fn full_http<T: Into<Bytes>>(chunk: T) -> HTTPResponseBody {
    Full::new(chunk.into())
}
