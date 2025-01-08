import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Union

from hypern.exceptions import DBFieldValidationError


class Field:
    """Base field class for ORM-like field definitions."""

    def __init__(
        self,
        field_type: str,
        primary_key: bool = False,
        null: bool = True,
        default: Any = None,
        unique: bool = False,
        index: bool = False,
        validators: Optional[list] = None,
        auto_increment: bool = False,
    ):
        self.field_type = field_type
        self.primary_key = primary_key
        self.null = null
        self.default = default
        self.unique = unique
        self.index = index
        self.validators = validators or []
        self.name = None
        self.model = None
        self.auto_increment = auto_increment

    def validate(self, value: Any) -> None:
        if value is None:
            if not self.null:
                raise DBFieldValidationError(f"Field {self.name} cannot be null")
            return

        for validator in self.validators:
            try:
                validator(value)
            except Exception as e:
                raise DBFieldValidationError(f"Validation failed for {self.name}: {str(e)}")

    def sql_type(self) -> str:
        """Return SQL type definition for the field."""
        type_mapping = {
            "int": "INTEGER",
            "str": "VARCHAR(255)",
            "float": "FLOAT",
            "bool": "BOOLEAN",
            "datetime": "TIMESTAMP",
            "date": "DATE",
            "text": "TEXT",
            "json": "JSONB",
            "array": "ARRAY",
            "decimal": "DECIMAL",
        }
        return type_mapping.get(self.field_type, "VARCHAR(255)")


class CharField(Field):
    def __init__(self, max_length: int = 255, **kwargs):
        super().__init__(field_type="str", **kwargs)
        self.max_length = max_length

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            if not isinstance(value, str):
                raise DBFieldValidationError(f"Field {self.name} must be a string")
            if len(value) > self.max_length:
                raise DBFieldValidationError(f"Field {self.name} cannot exceed {self.max_length} characters")

    def sql_type(self) -> str:
        return f"VARCHAR({self.max_length})"


class TextField(Field):
    def __init__(self, **kwargs):
        super().__init__(field_type="text", **kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, str):
            raise DBFieldValidationError(f"Field {self.name} must be a string")


class IntegerField(Field):
    def __init__(self, **kwargs):
        super().__init__(field_type="int", **kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            try:
                int(value)
            except (TypeError, ValueError):
                raise DBFieldValidationError(f"Field {self.name} must be an integer")


class FloatField(Field):
    def __init__(self, **kwargs):
        super().__init__(field_type="float", **kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            try:
                float(value)
            except (TypeError, ValueError):
                raise DBFieldValidationError(f"Field {self.name} must be a float")


class BooleanField(Field):
    def __init__(self, **kwargs):
        super().__init__(field_type="bool", **kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, bool):
            raise DBFieldValidationError(f"Field {self.name} must be a boolean")


class DateTimeField(Field):
    def __init__(self, auto_now: bool = False, auto_now_add: bool = False, **kwargs):
        super().__init__(field_type="datetime", **kwargs)
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, datetime):
            raise DBFieldValidationError(f"Field {self.name} must be a datetime object")


class DateField(Field):
    def __init__(self, auto_now: bool = False, auto_now_add: bool = False, **kwargs):
        super().__init__(field_type="date", **kwargs)
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, date):
            raise DBFieldValidationError(f"Field {self.name} must be a date object")


class JSONField(Field):
    def __init__(self, **kwargs):
        super().__init__(field_type="json", **kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                raise DBFieldValidationError(f"Field {self.name} must be JSON serializable")


class ArrayField(Field):
    def __init__(self, base_field: Field, **kwargs):
        super().__init__(field_type="array", **kwargs)
        self.base_field = base_field

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            if not isinstance(value, (list, tuple)):
                raise DBFieldValidationError(f"Field {self.name} must be a list or tuple")
            for item in value:
                self.base_field.validate(item)

    def sql_type(self) -> str:
        return f"{self.base_field.sql_type()}[]"


class DecimalField(Field):
    def __init__(self, max_digits: int = 10, decimal_places: int = 2, **kwargs):
        super().__init__(field_type="decimal", **kwargs)
        self.max_digits = max_digits
        self.decimal_places = decimal_places

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            try:
                decimal_value = Decimal(str(value))
                decimal_tuple = decimal_value.as_tuple()
                if len(decimal_tuple.digits) - (-decimal_tuple.exponent) > self.max_digits:
                    raise DBFieldValidationError(f"Field {self.name} exceeds maximum digits {self.max_digits}")
                if -decimal_tuple.exponent > self.decimal_places:
                    raise DBFieldValidationError(f"Field {self.name} exceeds maximum decimal places {self.decimal_places}")
            except InvalidOperation:
                raise DBFieldValidationError(f"Field {self.name} must be a valid decimal number")

    def sql_type(self) -> str:
        return f"DECIMAL({self.max_digits},{self.decimal_places})"


class ForeignKeyField(Field):
    """Field for foreign key relationships."""

    def __init__(
        self,
        to_model: Union[str, Any],
        related_field: str = "id",
        on_delete: str = "CASCADE",
        on_update: str = "CASCADE",
        related_name: Optional[str] = None,
        **kwargs,
    ):
        if isinstance(to_model, str):
            field_type = "int"
        else:
            related_field_obj = getattr(to_model, related_field, None)
            if related_field_obj is None:
                raise ValueError(f"Field {related_field} not found in model {to_model.__name__}")
            field_type = related_field_obj.field_type

        super().__init__(field_type=field_type, **kwargs)
        self.to_model = to_model
        self.related_field = related_field
        self.on_delete = on_delete.upper()
        self.on_update = on_update.upper()
        self.related_name = related_name

        valid_actions = {"CASCADE", "SET NULL", "RESTRICT", "NO ACTION"}
        if self.on_delete not in valid_actions:
            raise ValueError(f"Invalid on_delete action. Must be one of: {valid_actions}")
        if self.on_update not in valid_actions:
            raise ValueError(f"Invalid on_update action. Must be one of: {valid_actions}")

        if (self.on_delete == "SET NULL" or self.on_update == "SET NULL") and not kwargs.get("null", True):
            raise ValueError("Field must be nullable to use SET NULL referential action")

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(self.to_model, str):
            related_field_obj = getattr(self.to_model, self.related_field)
            try:
                related_field_obj.validate(value)
            except DBFieldValidationError as e:
                raise DBFieldValidationError(f"Foreign key {self.name} validation failed: {str(e)}")
