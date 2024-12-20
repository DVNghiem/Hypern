import re
from datetime import date, datetime

from hypern.config import context_store
from hypern.exceptions import OutOfScopeApplicationException
from hypern.hypern import get_session_database

from .field import Field, ForeignKey
from .query import QuerySet


class MetaModel(type):
    def __new__(mcs, name, bases, attrs):
        # Skip initialization for base Model class
        if name == "Model" and not bases:
            return super().__new__(mcs, name, bases, attrs)

        fields = {}
        table_name = attrs.get("__tablename__")

        # If table name not specified, convert CamelCase to snake_case
        if not table_name:
            table_name = re.sub("(?!^)([A-Z])", r"_\1", name).lower()

        # Collect all fields
        for key, value in list(attrs.items()):
            if isinstance(value, Field):
                fields[key] = value
                value.name = key

        # Store metadata in class
        attrs["_fields"] = fields
        attrs["_table_name"] = table_name

        return super().__new__(mcs, name, bases, attrs)


class Model(metaclass=MetaModel):
    def __init__(self, **kwargs):
        self._data = {}
        # Set default values
        for name, field in self._fields.items():
            if field.default is not None:
                self._data[name] = field.default

        # Set provided values
        for key, value in kwargs.items():
            if key in self._fields:
                self._fields[key].validate(value)
                self._data[key] = value
            else:
                raise ValueError(f"Unknown field {key}")

    @classmethod
    def get_session(cls):
        try:
            context_id = context_store.get_context()
        except Exception:
            raise OutOfScopeApplicationException("Context not set")
        return get_session_database(context_id)

    @classmethod
    def objects(cls) -> QuerySet:
        return QuerySet(cls)

    @classmethod
    def table_name(cls) -> str:
        return cls._table_name

    @classmethod
    def create_table_sql(cls) -> str:
        fields_sql = []
        indexes_sql = []
        foreign_keys = []

        for name, field in cls._fields.items():
            fields_sql.append(cls._get_field_sql(name, field))
            if field.index:
                indexes_sql.append(cls._get_index_sql(name))
            if isinstance(field, ForeignKey):
                foreign_keys.append(cls._get_foreign_key_sql(name, field))

        fields_sql.extend(foreign_keys)
        joined_fields_sql = ", \n ".join(fields_sql)

        create_table = f"CREATE TABLE {cls.table_name()} (\n  {joined_fields_sql} \n"

        return f"{create_table};\n" + ";\n".join(indexes_sql)

    @classmethod
    def _get_field_sql(cls, name, field) -> str:
        field_def = [f"{name} {field.sql_type()}"]
        if field.primary_key:
            field_def.append("PRIMARY KEY")
        if not field.null:
            field_def.append("NOT NULL")
        if field.unique:
            field_def.append("UNIQUE")
        if field.default is not None:
            if isinstance(field.default, (str, datetime, date)):
                field_def.append(f"DEFAULT '{field.default}'")
            else:
                field_def.append(f"DEFAULT {field.default}")
        return " ".join(field_def)

    @classmethod
    def _get_index_sql(cls, name) -> str:
        return f"CREATE INDEX idx_{cls.table_name()}_{name} ON {cls.table_name()} ({name})"

    @classmethod
    def _get_foreign_key_sql(cls, name, field) -> str:
        return f"FOREIGN KEY ({name}) REFERENCES {field.to_model}({field.related_field}) ON DELETE {field.on_delete} ON UPDATE {field.on_update}"

    def save(self):
        query_object = QuerySet(self)
        query_object.bulk_create([self])
