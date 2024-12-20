import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, List, Optional, Union

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
        validators: Optional[list[Callable]] = None,
        auto_increment: bool = False,
    ):
        """
        Initialize a field with various constraints and validation options.

        :param field_type: Type of the field
        :param primary_key: Whether the field is a primary key
        :param null: Whether the field can be null
        :param default: Default value for the field
        :param unique: Whether the field value must be unique
        :param index: Whether to create an index for this field
        :param validators: List of custom validator functions
        """
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

    def to_py_type(self, value: Any) -> Any:
        """
        Convert input value to the field's Python type.

        :param value: Input value to convert
        :return: Converted value
        """
        if value is None:
            return None
        return value

    def to_sql_type(self) -> str:
        """
        Get the SQL type representation of the field.

        :return: SQL type string
        """
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

    def validate(self, value: Any) -> None:
        """
        Validate the input value against field constraints.

        :param value: Value to validate
        :raises DBFieldValidationError: If validation fails
        """
        # Null check
        if value is None:
            if not self.null:
                raise DBFieldValidationError(f"Field {self.name} cannot be null")
            return

        # Run custom validators
        for validator in self.validators:
            try:
                validator(value)
            except Exception as e:
                raise DBFieldValidationError(f"Validation failed for {self.name}: {str(e)}")


class CharField(Field):
    """Character field with max length constraint."""

    def __init__(self, max_length: int = 255, min_length: int = 0, regex: Optional[str] = None, **kwargs):
        """
        Initialize a character field.

        :param max_length: Maximum allowed length
        :param min_length: Minimum allowed length
        :param regex: Optional regex pattern for validation
        """
        super().__init__("str", **kwargs)
        self.max_length = max_length
        self.min_length = min_length
        self.regex = regex

    def to_py_type(self, value: Any) -> Optional[str]:
        """Convert input to string."""
        if value is None:
            return None
        return str(value)

    def to_sql_type(self) -> str:
        """Get SQL type with defined max length."""
        return f"VARCHAR({self.max_length})"

    def validate(self, value: Any) -> None:
        """
        Validate character field constraints.

        :param value: Value to validate
        """
        super().validate(value)

        if value is None:
            return

        # Convert to string for validation
        str_value = str(value)

        # Length validation
        if len(str_value) > self.max_length:
            raise DBFieldValidationError(f"Value exceeds max length of {self.max_length}")

        if len(str_value) < self.min_length:
            raise DBFieldValidationError(f"Value is shorter than min length of {self.min_length}")

        # Regex validation
        if self.regex and not re.match(self.regex, str_value):
            raise DBFieldValidationError(f"Value does not match required pattern: {self.regex}")


class IntegerField(Field):
    """Integer field with range constraints."""

    def __init__(self, min_value: Optional[int] = None, max_value: Optional[int] = None, **kwargs):
        """
        Initialize an integer field.

        :param min_value: Minimum allowed value
        :param max_value: Maximum allowed value
        """
        super().__init__("int", **kwargs)
        self.min_value = min_value
        self.max_value = max_value

    def to_py_type(self, value: Any) -> Optional[int]:
        """Convert input to integer."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise DBFieldValidationError(f"Cannot convert {value} to integer")

    def validate(self, value: Any) -> None:
        """
        Validate integer field constraints.

        :param value: Value to validate
        """
        super().validate(value)

        if value is None:
            return

        int_value = self.to_py_type(value)

        # Range validation
        if self.min_value is not None and int_value < self.min_value:
            raise DBFieldValidationError(f"Value must be >= {self.min_value}")

        if self.max_value is not None and int_value > self.max_value:
            raise DBFieldValidationError(f"Value must be <= {self.max_value}")


class DecimalField(Field):
    """Decimal field with precision and scale constraints."""

    def __init__(
        self,
        max_digits: int = 10,
        decimal_places: int = 2,
        min_value: Optional[Union[int, float, Decimal]] = None,
        max_value: Optional[Union[int, float, Decimal]] = None,
        **kwargs,
    ):
        """
        Initialize a decimal field.

        :param max_digits: Total number of digits
        :param decimal_places: Number of decimal places
        :param min_value: Minimum allowed value
        :param max_value: Maximum allowed value
        """
        super().__init__("decimal", **kwargs)
        self.max_digits = max_digits
        self.decimal_places = decimal_places
        self.min_value = min_value
        self.max_value = max_value

    def to_py_type(self, value: Any) -> Optional[Decimal]:
        """Convert input to Decimal."""
        if value is None:
            return None
        try:
            decimal_value = Decimal(str(value))

            # Check precision
            parts = str(decimal_value).split(".")
            total_digits = len(parts[0].lstrip("-")) + (len(parts[1]) if len(parts) > 1 else 0)
            decimal_digits = len(parts[1]) if len(parts) > 1 else 0

            if total_digits > self.max_digits or decimal_digits > self.decimal_places:
                raise DBFieldValidationError(f"Decimal exceeds precision: {self.max_digits} digits, {self.decimal_places} decimal places")

            return decimal_value
        except (TypeError, ValueError, InvalidOperation):
            raise DBFieldValidationError(f"Cannot convert {value} to Decimal")

    def to_sql_type(self) -> str:
        """Get SQL type with defined precision."""
        return f"DECIMAL({self.max_digits},{self.decimal_places})"

    def validate(self, value: Any) -> None:
        """
        Validate decimal field constraints.

        :param value: Value to validate
        """
        super().validate(value)

        if value is None:
            return

        decimal_value = self.to_py_type(value)

        # Range validation
        if self.min_value is not None and decimal_value < Decimal(str(self.min_value)):
            raise DBFieldValidationError(f"Value must be >= {self.min_value}")

        if self.max_value is not None and decimal_value > Decimal(str(self.max_value)):
            raise DBFieldValidationError(f"Value must be <= {self.max_value}")


class DateField(Field):
    """Date field with range constraints."""

    def __init__(self, auto_now: bool = False, auto_now_add: bool = False, min_date: Optional[date] = None, max_date: Optional[date] = None, **kwargs):
        """
        Initialize a date field.

        :param auto_now: Update to current date on every save
        :param auto_now_add: Set to current date when first created
        :param min_date: Minimum allowed date
        :param max_date: Maximum allowed date
        """
        super().__init__("date", **kwargs)
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add
        self.min_date = min_date
        self.max_date = max_date

    def to_py_type(self, value: Any) -> Optional[date]:
        """Convert input to date."""
        if value is None:
            return None

        if isinstance(value, date):
            return value

        try:
            return date.fromisoformat(str(value))
        except ValueError:
            raise DBFieldValidationError(f"Cannot convert {value} to date")

    def validate(self, value: Any) -> None:
        """
        Validate date field constraints.

        :param value: Value to validate
        """
        super().validate(value)

        if value is None:
            return

        date_value = self.to_py_type(value)

        # Range validation
        if self.min_date is not None and date_value < self.min_date:
            raise DBFieldValidationError(f"Date must be >= {self.min_date}")

        if self.max_date is not None and date_value > self.max_date:
            raise DBFieldValidationError(f"Date must be <= {self.max_date}")


class JSONField(Field):
    """JSON field with optional schema validation."""

    def __init__(self, schema: Optional[dict] = None, **kwargs):
        """
        Initialize a JSON field.

        :param schema: Optional JSON schema for validation
        """
        super().__init__("json", **kwargs)
        self.schema = schema

    def to_py_type(self, value: Any) -> Optional[dict]:
        """Convert input to JSON."""
        if value is None:
            return None

        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                raise DBFieldValidationError(f"Invalid JSON string: {value}")

        if isinstance(value, dict):
            return value

        raise DBFieldValidationError(f"Cannot convert {value} to JSON")

    def validate(self, value: Any) -> None:
        """
        Validate JSON field constraints.

        :param value: Value to validate
        """
        super().validate(value)

        if value is None:
            return

        json_value = self.to_py_type(value)

        # Schema validation
        if self.schema:
            from jsonschema import DBFieldValidationError as JsonSchemaError
            from jsonschema import validate

            try:
                validate(instance=json_value, schema=self.schema)
            except JsonSchemaError as e:
                raise DBFieldValidationError(f"JSON schema validation failed: {str(e)}")


class ArrayField(Field):
    """Array field with base field type validation."""

    def __init__(self, base_field: Field, min_length: Optional[int] = None, max_length: Optional[int] = None, **kwargs):
        """
        Initialize an array field.

        :param base_field: Field type for array elements
        :param min_length: Minimum number of elements
        :param max_length: Maximum number of elements
        """
        super().__init__("array", **kwargs)
        self.base_field = base_field
        self.min_length = min_length
        self.max_length = max_length

    def to_py_type(self, value: Any) -> Optional[List[Any]]:
        """
        Convert input to a list with base field type conversion.

        :param value: Input value to convert
        :return: Converted list
        """
        if value is None:
            return None

        # Ensure input is a list
        if not isinstance(value, list):
            try:
                value = list(value)
            except TypeError:
                raise DBFieldValidationError(f"Cannot convert {value} to list")

        # Convert each element using base field's to_py_type
        return [self.base_field.to_py_type(item) for item in value]

    def to_sql_type(self) -> str:
        """
        Get SQL type representation of the array.

        :return: SQL array type string
        """
        return f"{self.base_field.to_sql_type()}[]"

    def validate(self, value: Any) -> None:
        """
        Validate array field constraints.

        :param value: Value to validate
        """
        super().validate(value)

        if value is None:
            return

        # Ensure we have a list
        list_value = self.to_py_type(value)

        # Length validation
        if self.min_length is not None and len(list_value) < self.min_length:
            raise DBFieldValidationError(f"Array must have at least {self.min_length} elements")

        if self.max_length is not None and len(list_value) > self.max_length:
            raise DBFieldValidationError(f"Array must have no more than {self.max_length} elements")

        # Validate each element using base field's validate method
        for item in list_value:
            self.base_field.validate(item)


class ForeignKey(Field):
    """Foreign key field representing a relationship to another model."""

    def __init__(self, to_model: str, related_field: str, on_delete: str = "CASCADE", on_update: str = "CASCADE", **kwargs):
        """
        Initialize a foreign key field.

        :param to_model: Name of the related model
        :param on_delete: Action to take on related record deletion
        :param on_update: Action to take on related record update
        """
        # Allow overriding primary key and null status if not specified
        if "primary_key" not in kwargs:
            kwargs["primary_key"] = False
        if "null" not in kwargs:
            kwargs["null"] = False

        super().__init__("int", **kwargs)
        self.to_model = to_model
        self.on_delete = on_delete
        self.on_update = on_update
        self.related_field = related_field

    def to_py_type(self, value: Any) -> Optional[int]:
        """
        Convert input to integer representing foreign key.

        :param value: Value to convert
        :return: Converted integer
        """
        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            raise DBFieldValidationError(f"Cannot convert {value} to integer foreign key")

    def to_sql_type(self) -> str:
        """
        Get SQL type for foreign key.

        :return: SQL integer type string
        """
        return "INTEGER"

    def validate(self, value: Any) -> None:
        """
        Validate foreign key constraints.

        :param value: Value to validate
        """
        super().validate(value)


class DateTimeField(Field):
    """DateTime field with advanced validation and auto-update capabilities."""

    def __init__(
        self,
        auto_now: bool = False,
        auto_now_add: bool = False,
        min_datetime: Optional[datetime] = None,
        max_datetime: Optional[datetime] = None,
        timezone_aware: bool = True,
        **kwargs,
    ):
        """
        Initialize a datetime field.

        :param auto_now: Update to current datetime on every save
        :param auto_now_add: Set to current datetime when first created
        :param min_datetime: Minimum allowed datetime
        :param max_datetime: Maximum allowed datetime
        :param timezone_aware: Enforce timezone awareness
        """
        super().__init__("datetime", **kwargs)
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add
        self.min_datetime = min_datetime
        self.max_datetime = max_datetime
        self.timezone_aware = timezone_aware

    def to_py_type(self, value: Any) -> Optional[datetime]:
        """
        Convert input to datetime with robust parsing.

        :param value: Value to convert
        :return: Converted datetime
        """
        if value is None:
            return None

        # If already a datetime, handle timezone
        if isinstance(value, datetime):
            return self._handle_timezone(value)

        # String parsing with multiple formats
        if isinstance(value, str):
            try:
                # ISO format parsing
                parsed_datetime = datetime.fromisoformat(value)
                return self._handle_timezone(parsed_datetime)
            except ValueError:
                # Additional parsing formats can be added
                try:
                    # Alternative parsing (e.g., common formats)
                    parsed_datetime = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                    return self._handle_timezone(parsed_datetime)
                except ValueError:
                    raise DBFieldValidationError(f"Cannot parse datetime from: {value}")

        # Attempt generic conversion
        try:
            converted_datetime = datetime.fromtimestamp(float(value))
            return self._handle_timezone(converted_datetime)
        except (TypeError, ValueError):
            raise DBFieldValidationError(f"Cannot convert {value} to datetime")

    def _handle_timezone(self, dt: datetime) -> datetime:
        """
        Handle timezone requirements.

        :param dt: Input datetime
        :return: Timezone-adjusted datetime
        """
        if self.timezone_aware:
            # If no timezone, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            # Remove timezone if not required
            dt = dt.replace(tzinfo=None)

        return dt

    def to_sql_type(self) -> str:
        """
        Get SQL type for datetime.

        :return: SQL timestamp type string
        """
        return "TIMESTAMP"

    def validate(self, value: Any) -> None:
        """
        Validate datetime field constraints.

        :param value: Value to validate
        """
        super().validate(value)

        if value is None:
            return

        datetime_value = self.to_py_type(value)

        # Range validation
        if self.min_datetime is not None:
            min_dt = self._handle_timezone(self.min_datetime)
            if datetime_value < min_dt:
                raise DBFieldValidationError(f"Datetime must be >= {min_dt}")

        if self.max_datetime is not None:
            max_dt = self._handle_timezone(self.max_datetime)
            if datetime_value > max_dt:
                raise DBFieldValidationError(f"Datetime must be <= {max_dt}")

        # Timezone awareness check
        if self.timezone_aware and datetime_value.tzinfo is None:
            raise DBFieldValidationError("Datetime must be timezone-aware")
