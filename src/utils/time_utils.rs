use pyo3::prelude::*;
use std::time::{SystemTime, UNIX_EPOCH};

// ──────────────────────────── timestamps ─────────────────────────────────── //

/// Current UTC Unix timestamp in **milliseconds**.
///
/// Example (Python):
///     ts = now_ms()  # 1740355200000
#[pyfunction]
pub fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

/// Current UTC Unix timestamp in **seconds**.
#[pyfunction]
pub fn now_sec() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Current UTC time as an ISO 8601 string (``2026-02-23T14:30:00.000Z``).
#[pyfunction]
pub fn now_iso() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string()
}

// ────────────────────────── formatting / parsing ─────────────────────────── //

/// Format a Unix timestamp (seconds) to ISO 8601 UTC.
///
/// Example (Python):
///     format_timestamp(1740355200)  # "2026-02-23T..."
#[pyfunction]
pub fn format_timestamp(ts_secs: i64) -> String {
    use chrono::{DateTime, Utc};
    match DateTime::<Utc>::from_timestamp(ts_secs, 0) {
        Some(dt) => dt.format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string(),
        None => "invalid timestamp".to_string(),
    }
}

/// Parse an ISO 8601 / RFC 3339 datetime string to Unix seconds.
///
/// Returns ``None`` on unparseable input.
///
/// Accepts:
/// - ``2026-02-23T14:30:00Z``
/// - ``2026-02-23T14:30:00.123Z``
/// - ``2026-02-23T14:30:00``  (assumes UTC)
/// - ``2026-02-23``           (start of day UTC)
#[pyfunction]
pub fn parse_iso(s: &str) -> Option<i64> {
    use chrono::{DateTime, NaiveDate, NaiveDateTime, TimeZone, Utc};

    // RFC 3339 / ISO 8601
    if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
        return Some(dt.timestamp());
    }
    // Naive datetime — assume UTC
    for fmt in &[
        "%Y-%m-%dT%H:%M:%S%.f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ] {
        if let Ok(ndt) = NaiveDateTime::parse_from_str(s, fmt) {
            return Some(Utc.from_utc_datetime(&ndt).timestamp());
        }
    }
    // Date only
    if let Ok(nd) = NaiveDate::parse_from_str(s, "%Y-%m-%d") {
        return Some(
            Utc.from_utc_datetime(&nd.and_hms_opt(0, 0, 0).unwrap())
                .timestamp(),
        );
    }
    None
}

// ───────────────────────── human-readable elapsed ────────────────────────── //

/// Human-readable *relative* time from a past (or future) Unix timestamp in
/// **seconds**.
///
/// Example (Python):
///     relative_time(now_sec() - 3700)  # "1 hour ago"
///     relative_time(now_sec() + 120)   # "in 2 minutes"
///     relative_time(now_sec() - 3)     # "just now"
#[pyfunction]
pub fn relative_time(ts_secs: i64) -> String {
    let diff = now_sec() - ts_secs;
    format_relative(diff)
}

/// Elapsed milliseconds from `start_ms` to now.
///
/// Example (Python):
///     start = now_ms()
///     # ... work ...
///     ms = elapsed_ms(start)   # 142
#[pyfunction]
pub fn elapsed_ms(start_ms: i64) -> i64 {
    now_ms() - start_ms
}

// ─────────────────────── conversion helpers ──────────────────────────────── //

/// Milliseconds → seconds.
#[pyfunction]
pub fn ms_to_sec(ms: i64) -> i64 {
    ms / 1000
}

/// Seconds → milliseconds.
#[pyfunction]
pub fn sec_to_ms(sec: i64) -> i64 {
    sec * 1000
}

// ───────────────────────── internal helpers ──────────────────────────────── //

fn format_relative(diff_secs: i64) -> String {
    let abs = diff_secs.unsigned_abs();

    if abs < 10 {
        return "just now".to_string();
    }

    let (prefix, suffix) = if diff_secs > 0 {
        ("", " ago")
    } else {
        ("in ", "")
    };

    let label = if abs < 60 {
        format!("{} seconds", abs)
    } else if abs < 3600 {
        let m = abs / 60;
        if m == 1 {
            "1 minute".to_string()
        } else {
            format!("{} minutes", m)
        }
    } else if abs < 86400 {
        let h = abs / 3600;
        if h == 1 {
            "1 hour".to_string()
        } else {
            format!("{} hours", h)
        }
    } else if abs < 86400 * 30 {
        let d = abs / 86400;
        if d == 1 {
            "1 day".to_string()
        } else {
            format!("{} days", d)
        }
    } else if abs < 86400 * 365 {
        let mo = abs / (86400 * 30);
        if mo == 1 {
            "1 month".to_string()
        } else {
            format!("{} months", mo)
        }
    } else {
        let y = abs / (86400 * 365);
        if y == 1 {
            "1 year".to_string()
        } else {
            format!("{} years", y)
        }
    };

    format!("{}{}{}", prefix, label, suffix)
}

// ──────────────────── module registration ────────────────────────────────── //

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(now_ms, m)?)?;
    m.add_function(wrap_pyfunction!(now_sec, m)?)?;
    m.add_function(wrap_pyfunction!(now_iso, m)?)?;
    m.add_function(wrap_pyfunction!(format_timestamp, m)?)?;
    m.add_function(wrap_pyfunction!(parse_iso, m)?)?;
    m.add_function(wrap_pyfunction!(relative_time, m)?)?;
    m.add_function(wrap_pyfunction!(elapsed_ms, m)?)?;
    m.add_function(wrap_pyfunction!(ms_to_sec, m)?)?;
    m.add_function(wrap_pyfunction!(sec_to_ms, m)?)?;
    Ok(())
}
