# -*- coding: utf-8 -*-
from sqlalchemy import types


class DatetimeType(types.TypeDecorator):
    impl = types.DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(types.TEXT)
        return dialect.type_descriptor(self.impl)

    def process_bind_param(self, value, dialect):
        if dialect.name == "sqlite":
            return value.isoformat()
        return value

    def process_result_value(self, value, dialect):
        if dialect.name != "sqlite":
            return value.timestamp()
        return value
