use pyo3::prelude::*;
use pyo3::types::PyDict;

// ────────────────────────── slug / text helpers ──────────────────────────── //

/// Convert a string to a URL-safe slug.
///
/// Strips accented characters, lowercases, replaces whitespace / symbols with
/// `separator`, and collapses consecutive separators.
///
/// Example (Python):
///     slugify("  Hello World!  2026 ") == "hello-world-2026"
///     slugify("café & résumé", "_")    == "cafe_resume"
#[pyfunction]
#[pyo3(signature = (text, separator="-"))]
pub fn slugify(text: &str, separator: &str) -> String {
    let mut result = String::with_capacity(text.len());
    let mut last_was_sep = true; // suppress leading separator

    for ch in text.chars() {
        if ch.is_ascii_alphanumeric() {
            result.push(ch.to_ascii_lowercase());
            last_was_sep = false;
        } else if ch.is_alphabetic() {
            // Transliterate common accented latin characters to ASCII
            let ascii = transliterate_char(ch);
            if !ascii.is_empty() {
                result.push_str(ascii);
                last_was_sep = false;
            }
        } else if !last_was_sep && !result.is_empty() {
            result.push_str(separator);
            last_was_sep = true;
        }
    }

    // Strip trailing separator
    if result.ends_with(separator) {
        result.truncate(result.len() - separator.len());
    }
    result
}

/// Truncate a string to `max_len` characters, appending `suffix` if truncated.
///
/// Example (Python):
///     truncate("Hello World", 7)        == "Hell..."
///     truncate("Hi", 10)                == "Hi"
///     truncate("abcdef", 5, "…")        == "abcd…"
#[pyfunction]
#[pyo3(signature = (text, max_len, suffix="..."))]
pub fn truncate(text: &str, max_len: usize, suffix: &str) -> String {
    let char_count = text.chars().count();
    if char_count <= max_len {
        return text.to_string();
    }
    let suffix_len = suffix.chars().count();
    let keep = max_len.saturating_sub(suffix_len);
    let truncated: String = text.chars().take(keep).collect();
    format!("{}{}", truncated, suffix)
}

// ───────────────────────────── PII masking ───────────────────────────────── //

/// Mask an email address for display.
///
/// Example (Python):
///     mask_email("user@example.com")  == "u**r@example.com"
///     mask_email("ab@x.com")          == "**@x.com"
#[pyfunction]
pub fn mask_email(email: &str) -> String {
    match email.split_once('@') {
        None => "*".repeat(email.len()),
        Some((local, domain)) => {
            let masked = mask_inner(local, 1, 1);
            format!("{}@{}", masked, domain)
        }
    }
}

/// Mask a phone number, keeping only the last N digits visible.
///
/// Example (Python):
///     mask_phone("+1-800-555-1234")     == "**********1234"
///     mask_phone("0123456789", 4)       == "******6789"
#[pyfunction]
#[pyo3(signature = (phone, keep_last=4))]
pub fn mask_phone(phone: &str, keep_last: usize) -> String {
    let digits: String = phone.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() <= keep_last {
        return digits;
    }
    let n = digits.len() - keep_last;
    format!("{}{}", "*".repeat(n), &digits[n..])
}

/// Mask a generic string, keeping `keep_start` chars at the beginning and
/// `keep_end` chars at the end, replacing the middle with '*'.
///
/// Example (Python):
///     mask_string("secret-value", 2, 2) == "se**********ue"
#[pyfunction]
#[pyo3(signature = (text, keep_start=1, keep_end=1))]
pub fn mask_string(text: &str, keep_start: usize, keep_end: usize) -> String {
    mask_inner(text, keep_start, keep_end)
}

// ─────────────────────── case conversion helpers ─────────────────────────── //

/// Convert a ``snake_case`` string to ``camelCase``.
///
/// Example (Python):
///     snake_to_camel("user_first_name")         == "userFirstName"
///     snake_to_camel("get_by_id", True)          == "GetById"
#[pyfunction]
#[pyo3(signature = (text, upper_first=false))]
pub fn snake_to_camel(text: &str, upper_first: bool) -> String {
    let mut result = String::with_capacity(text.len());
    let mut cap_next = upper_first;

    for ch in text.chars() {
        if ch == '_' {
            cap_next = true;
        } else if cap_next {
            for u in ch.to_uppercase() {
                result.push(u);
            }
            cap_next = false;
        } else {
            result.push(ch);
        }
    }
    result
}

/// Convert a ``camelCase`` or ``PascalCase`` string to ``snake_case``.
///
/// Example (Python):
///     camel_to_snake("userFirstName") == "user_first_name"
///     camel_to_snake("HTTPSRequest")  == "https_request"
#[pyfunction]
pub fn camel_to_snake(text: &str) -> String {
    let mut result = String::with_capacity(text.len() + 4);
    let chars: Vec<char> = text.chars().collect();

    for (i, &ch) in chars.iter().enumerate() {
        if ch.is_uppercase() {
            let prev_lower = i > 0 && chars[i - 1].is_lowercase();
            let next_lower = i + 1 < chars.len() && chars[i + 1].is_lowercase();
            if i > 0 && (prev_lower || next_lower) {
                result.push('_');
            }
            for lower in ch.to_lowercase() {
                result.push(lower);
            }
        } else {
            result.push(ch);
        }
    }
    result
}

// ───────────────────────────── batch helpers ─────────────────────────────── //

/// Convert **all** keys in a flat dict from ``snake_case`` to ``camelCase``.
///
/// Extremely common when serialising Python models to JSON API responses.
///
/// Example (Python):
///     keys_to_camel({"user_name": "Jo", "first_login": True})
///     # {"userName": "Jo", "firstLogin": True}
#[pyfunction]
#[pyo3(signature = (data, upper_first=false))]
pub fn keys_to_camel<'py>(
    py: Python<'py>,
    data: &Bound<'py, PyDict>,
    upper_first: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let out = PyDict::new(py);
    for (key, value) in data.iter() {
        let key_str: String = key.extract()?;
        let new_key = snake_to_camel(&key_str, upper_first);
        out.set_item(new_key, value)?;
    }
    Ok(out)
}

/// Convert **all** keys in a flat dict from ``camelCase`` to ``snake_case``.
///
/// Common when ingesting external JSON payloads into Python models.
#[pyfunction]
pub fn keys_to_snake<'py>(
    py: Python<'py>,
    data: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let out = PyDict::new(py);
    for (key, value) in data.iter() {
        let key_str: String = key.extract()?;
        let new_key = camel_to_snake(&key_str);
        out.set_item(new_key, value)?;
    }
    Ok(out)
}

// ────────────────────────── padding / counting ───────────────────────────── //

/// Left-pad a string to reach `width` characters.
///
/// Example (Python):
///     pad_left("42", 5, "0") == "00042"
#[pyfunction]
#[pyo3(signature = (text, width, pad_char=" "))]
pub fn pad_left(text: &str, width: usize, pad_char: &str) -> String {
    let len = text.chars().count();
    if len >= width {
        return text.to_string();
    }
    let ch = pad_char.chars().next().unwrap_or(' ');
    let padding: String = std::iter::repeat(ch).take(width - len).collect();
    format!("{}{}", padding, text)
}

/// Right-pad a string to reach `width` characters.
///
/// Example (Python):
///     pad_right("hi", 5, ".") == "hi..."
#[pyfunction]
#[pyo3(signature = (text, width, pad_char=" "))]
pub fn pad_right(text: &str, width: usize, pad_char: &str) -> String {
    let len = text.chars().count();
    if len >= width {
        return text.to_string();
    }
    let ch = pad_char.chars().next().unwrap_or(' ');
    let padding: String = std::iter::repeat(ch).take(width - len).collect();
    format!("{}{}", text, padding)
}

/// Count the number of whitespace-delimited words.
///
/// Example (Python):
///     word_count("Hello   World foo") == 3
#[pyfunction]
pub fn word_count(text: &str) -> usize {
    text.split_whitespace().count()
}

/// Check whether `text` contains only ASCII-safe URL characters.
///
/// Useful for quickly validating user-provided slug / path segments.
#[pyfunction]
pub fn is_url_safe(text: &str) -> bool {
    text.chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.' || c == '~')
}

// ───────────────────────── internal helpers ──────────────────────────────── //

fn mask_inner(s: &str, keep_start: usize, keep_end: usize) -> String {
    let chars: Vec<char> = s.chars().collect();
    let n = chars.len();
    if n <= keep_start + keep_end {
        return "*".repeat(n);
    }
    let mut out = String::with_capacity(n);
    for (i, &c) in chars.iter().enumerate() {
        if i < keep_start || i >= n - keep_end {
            out.push(c);
        } else {
            out.push('*');
        }
    }
    out
}

fn transliterate_char(ch: char) -> &'static str {
    match ch {
        'à' | 'á' | 'â' | 'ã' | 'ä' | 'å' | 'À' | 'Á' | 'Â' | 'Ã' | 'Ä' | 'Å' => "a",
        'æ' | 'Æ' => "ae",
        'ç' | 'Ç' => "c",
        'è' | 'é' | 'ê' | 'ë' | 'È' | 'É' | 'Ê' | 'Ë' => "e",
        'ì' | 'í' | 'î' | 'ï' | 'Ì' | 'Í' | 'Î' | 'Ï' => "i",
        'ð' | 'Ð' => "d",
        'ñ' | 'Ñ' => "n",
        'ò' | 'ó' | 'ô' | 'õ' | 'ö' | 'ø' | 'Ò' | 'Ó' | 'Ô' | 'Õ' | 'Ö' | 'Ø' => "o",
        'ù' | 'ú' | 'û' | 'ü' | 'Ù' | 'Ú' | 'Û' | 'Ü' => "u",
        'ý' | 'ÿ' | 'Ý' | 'Ÿ' => "y",
        'þ' | 'Þ' => "th",
        'ß' => "ss",
        'đ' | 'Đ' => "d",
        _ => "",
    }
}

// ──────────────────── module registration ────────────────────────────────── //

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(slugify, m)?)?;
    m.add_function(wrap_pyfunction!(truncate, m)?)?;
    m.add_function(wrap_pyfunction!(mask_email, m)?)?;
    m.add_function(wrap_pyfunction!(mask_phone, m)?)?;
    m.add_function(wrap_pyfunction!(mask_string, m)?)?;
    m.add_function(wrap_pyfunction!(snake_to_camel, m)?)?;
    m.add_function(wrap_pyfunction!(camel_to_snake, m)?)?;
    m.add_function(wrap_pyfunction!(keys_to_camel, m)?)?;
    m.add_function(wrap_pyfunction!(keys_to_snake, m)?)?;
    m.add_function(wrap_pyfunction!(pad_left, m)?)?;
    m.add_function(wrap_pyfunction!(pad_right, m)?)?;
    m.add_function(wrap_pyfunction!(word_count, m)?)?;
    m.add_function(wrap_pyfunction!(is_url_safe, m)?)?;
    Ok(())
}
