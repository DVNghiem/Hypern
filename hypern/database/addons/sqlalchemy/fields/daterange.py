from datetime import datetime

from sqlalchemy.dialects.postgresql import DATERANGE
from sqlalchemy.types import TypeDecorator


class DateRangeField(TypeDecorator):
    impl = DATERANGE

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        elif "start" in value and "end" in value:
            return f"['{value['start']}', '{value['end']}']"
        else:
            raise ValueError('DateRangeField must be a dictionary with "start" and "end" keys')

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        else:
            start, end = value[1:-1].split(",")
            return {"start": datetime.strptime(start.strip("'"), "%Y-%m-%d %H:%M:%S.%f"), "end": datetime.strptime(end.strip("'"), "%Y-%m-%d %H:%M:%S.%f")}
