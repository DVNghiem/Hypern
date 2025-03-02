import logging
from datetime import datetime

from hypern.hypern import RustLogger


class RustLoggerHandler(logging.Handler):
    def __init__(
        self,
        level="INFO",
        format="text",
        text_format="%{timestamp} %{level} %{client_ip} %{method} %{path} %{status_code} %{response_time}ms %{message}",
    ):
        super().__init__()
        self.rust_logger = RustLogger(
            level=level, format=format, text_format=text_format
        )

    def formatTime(self, record, datefmt=None):
        if datefmt:
            return datetime.fromtimestamp(record.created).strftime(datefmt)
        else:
            # ISO8601 milliseconds
            return (
                datetime.fromtimestamp(record.created).isoformat(
                    timespec="milliseconds"
                )
                + "Z"
            )

    def emit(self, record):
        try:
            attributes = {
                "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ")[:-4]
                + "Z",  # ISO8601
                "level": record.levelname,
                "message": record.getMessage(),
                "client_ip": getattr(record, "client_ip", "-"),
                "method": getattr(record, "method", "-"),
                "path": getattr(record, "path", "-"),
                "status_code": getattr(record, "status_code", "-"),
                "response_time": getattr(record, "response_time", "-"),
            }
            self.rust_logger.log(record.levelname, record.getMessage(), attributes)
        except Exception:
            self.handleError(record)
