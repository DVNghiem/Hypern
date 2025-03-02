use chrono::DateTime;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

// define log level
#[derive(Debug, PartialEq, PartialOrd, Clone)]
enum LogLevel {
    Debug,
    Info,
    Warning,
    Error,
}

impl LogLevel {
    fn from_str(level: &str) -> Self {
        match level.to_uppercase().as_str() {
            "DEBUG" => LogLevel::Debug,
            "INFO" => LogLevel::Info,
            "WARNING" => LogLevel::Warning,
            "ERROR" => LogLevel::Error,
            _ => LogLevel::Info, // Default level is INFO
        }
    }

    fn to_str(&self) -> &'static str {
        match self {
            LogLevel::Debug => "DEBUG",
            LogLevel::Info => "INFO",
            LogLevel::Warning => "WARNING",
            LogLevel::Error => "ERROR",
        }
    }
}

// Format log
enum LogFormat {
    Text(String),
    Json,
}

// Struct main of Logger
struct Logger {
    level: LogLevel,
    format: LogFormat,
}

impl Logger {
    // Initial logger with level and format for log
    fn new(level: &str, format: &str, text_format: Option<&str>) -> Self {
        let level = LogLevel::from_str(level);
        let format = match format.to_lowercase().as_str() {
            "json" => LogFormat::Json,
            _ => LogFormat::Text(
                text_format.unwrap_or("%{timestamp} %{level} %{request_id} %{client_ip} %{user_id} %{method} %{path} %{status_code} %{response_time}ms %{message}").to_string()
            ),
        };
        Logger { level, format }
    }

    // Get timestamp follow pattern ISO8601 (Grok-compatible)
    fn get_timestamp() -> String {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
        let secs = now.as_secs();
        let nanos = now.subsec_nanos();
        let naive = DateTime::from_timestamp(secs as i64, nanos);
        naive
            .expect("Expect format %Y-%m-%dT%H:%M:%S%.3fZ")
            .format("%Y-%m-%dT%H:%M:%S%.3fZ")
            .to_string()
    }

    fn log(&self, level: LogLevel, message: &str, attributes: HashMap<String, String>) {
        if level < self.level {
            return; // by pass log if level is lower than current level
        }

        let output = match &self.format {
            LogFormat::Text(fmt) => {
                let mut result = fmt.clone();
                let timestamp = attributes
                    .get("timestamp")
                    .cloned()
                    .unwrap_or_else(|| Logger::get_timestamp());
                result = result.replace("%{timestamp}", &timestamp);
                result = result.replace("%{level}", level.to_str());
                result = result.replace("%{message}", message);
                for (key, value) in attributes.iter() {
                    result = result.replace(&format!("%{{{}}}", key), value);
                }
                result
            }
            LogFormat::Json => {
                let mut json_map = attributes;
                json_map.insert("level".to_string(), level.to_str().to_string());
                json_map.insert("message".to_string(), message.to_string());
                json_map.insert("timestamp".to_string(), Logger::get_timestamp());
                serde_json::to_string(&json_map).unwrap_or_else(|_| "{}".to_string())
            }
        };

        println!("{}", output); // Print stdout, may be replace with saved file or others handler 
    }
}

#[pyclass]
pub struct RustLogger {
    inner: Logger,
}

#[pymethods]
impl RustLogger {
    #[new]
    fn new(level: String, format: String, text_format: Option<String>) -> Self {
        let logger = Logger::new(&level, &format, text_format.as_deref());
        RustLogger { inner: logger }
    }

    fn log(&self, level: String, message: String, attributes: &PyDict) -> PyResult<()> {
        let level = LogLevel::from_str(&level);
        let mut attrs = HashMap::new();
        for (k, v) in attributes.iter() {
            attrs.insert(k.to_string(), v.to_string());
        }
        self.inner.log(level, &message, attrs);
        Ok(())
    }
}
