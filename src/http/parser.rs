pub struct RequestParser;

impl RequestParser {
    /// Parse method from raw bytes with minimal allocation
    #[inline]
    pub fn parse_method(data: &[u8]) -> Option<&[u8]> {
        let space_idx = data.iter().position(|&b| b == b' ')?;
        Some(&data[..space_idx])
    }

    /// Parse path from raw bytes
    #[inline]
    pub fn parse_path(data: &[u8]) -> Option<&[u8]> {
        let first_space = data.iter().position(|&b| b == b' ')?;
        let rest = &data[first_space + 1..];
        let second_space = rest.iter().position(|&b| b == b' ')?;
        Some(&rest[..second_space])
    }

    /// Extract query string from path
    #[inline]
    pub fn extract_query(path: &[u8]) -> Option<&[u8]> {
        let query_start = path.iter().position(|&b| b == b'?')?;
        Some(&path[query_start + 1..])
    }
}
