import re

from sqlalchemy.types import String, TypeDecorator


class ColorField(TypeDecorator):
    impl = String

    def process_bind_param(self, value, dialect):
        color_regex = r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$"
        if not re.match(color_regex, value):
            raise ValueError("Invalid color format. Use hexadecimal color codes (e.g., #FF0000)")
        return value

    def process_result_value(self, value, dialect):
        return value
