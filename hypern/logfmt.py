import datetime
import logging
import sys
from copy import copy
from typing import Literal

import click

TRACE_LOG_LEVEL = 5


class ColourizedFormatter(logging.Formatter):
    level_name_colors = {  # noqa: RUF012
        TRACE_LOG_LEVEL: lambda level_name: click.style(str(level_name), fg="blue"),
        logging.DEBUG: lambda level_name: click.style(str(level_name), fg="cyan"),
        logging.INFO: lambda level_name: click.style(str(level_name), fg="green"),
        logging.WARNING: lambda level_name: click.style(str(level_name), fg="yellow"),
        logging.ERROR: lambda level_name: click.style(str(level_name), fg="red"),
        logging.CRITICAL: lambda level_name: click.style(
            str(level_name), fg="bright_red"
        ),
    }

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        use_colors: bool | None = None,
    ):
        if use_colors in (True, False):
            self.use_colors = use_colors
        else:
            self.use_colors = sys.stdout.isatty()
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)

    def color_level_name(self, level_name: str, level_no: int) -> str:
        def default(level_name: str) -> str:
            return str(level_name)

        func = self.level_name_colors.get(level_no, default)
        return func(level_name)

    def should_use_colors(self) -> bool:
        return True

    def formatTime(self, record, datefmt = None):
        dt = datetime.datetime.fromtimestamp(record.created)  # noqa: DTZ006
        return dt.isoformat(timespec='milliseconds') + 'Z'

    def formatMessage(self, record: logging.LogRecord) -> str:
        recordcopy = copy(record)
        levelname = recordcopy.levelname
        process = recordcopy.process
        seperator = " " * (8 - len(recordcopy.levelname))
        
        if self.use_colors:
            levelname = self.color_level_name(levelname, recordcopy.levelno)
            if "color_message" in recordcopy.__dict__:
                recordcopy.msg = recordcopy.__dict__["color_message"]
                recordcopy.__dict__["message"] = recordcopy.getMessage()
        recordcopy.levelname = levelname
        recordcopy.__dict__["levelprefix"] = levelname + ":" + seperator
        recordcopy.__dict__["process"] = click.style(str(process), fg="blue")
        return super().formatMessage(recordcopy)


class DefaultFormatter(ColourizedFormatter):
    def should_use_colors(self) -> bool:
        return self.use_colors

def config_basic_logging(level: int = logging.INFO, *, use_colors: bool = True) -> None:
    """
    Configures basic logging with a default formatter.
    """
    formatter = DefaultFormatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        use_colors=use_colors,
        datefmt="%d-%m-%Y %H:%M:%S",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=[handler])
