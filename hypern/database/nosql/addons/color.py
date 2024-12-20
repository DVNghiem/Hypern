from mongoengine import BaseField
import re


class ColorField(BaseField):
    def validate(self, value):
        color_regex = r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$"
        if not re.match(color_regex, value):
            self.error("Invalid color format. Use hexadecimal color codes (e.g., #FF0000)")
        return True

    def to_mongo(self, value):
        return value

    def to_python(self, value):
        return value
