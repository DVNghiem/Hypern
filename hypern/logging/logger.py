import logging

from hypern.logging.handler import RustLoggerHandler


def setup_logger(config):
    logger = logging.getLogger("hypern")
    logger.setLevel(config.get("level", "INFO"))
    handler = RustLoggerHandler(
        level=config["level"],
        format=config.get("format", "text"),
        text_format=config.get(
            "text_format",
            "%{timestamp} %{level} %{client_ip} %{method} %{path} %{status_code} %{response_time}ms %{message}",
        ),
    )
    logger.handlers = []  # Reset handler
    logger.addHandler(handler)
    return logger


LOGGER_CONFIG = {
    "level": "INFO",
    "format": "text",
    "text_format": "%{timestamp} %{level} %{client_ip} %{method} %{path} %{status_code} %{response_time} %{message}",
}

logger = setup_logger(LOGGER_CONFIG)
