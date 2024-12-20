from mongoengine import BaseField
from datetime import datetime


class DateRangeField(BaseField):
    def __init__(self, **kwargs):
        super(DateRangeField, self).__init__(**kwargs)

    def validate(self, value):
        if not isinstance(value, dict) or "start" not in value or "end" not in value:
            self.error('DateRangeField must be a dictionary with "start" and "end" keys')
        # Use get to safely access keys
        start = value.get("start")
        end = value.get("end")
        # Check if both "start" and "end" are present
        if start is None or end is None:
            self.error('DateRangeField must contain both "start" and "end" keys')

        # Check if "start" and "end" are datetime objects
        if not isinstance(value["start"], datetime) or not isinstance(value["end"], datetime):
            self.error('DateRangeField "start" and "end" must be datetime objects')
        if value["start"] > value["end"]:
            self.error('DateRangeField "start" must be earlier than "end"')
        return True

    def to_mongo(self, value):
        return value

    def to_python(self, value):
        return value
