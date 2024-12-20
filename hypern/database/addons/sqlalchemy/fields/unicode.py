from sqlalchemy.types import TypeDecorator, Unicode


class UnicodeField(TypeDecorator):
    impl = Unicode

    def process_bind_param(self, value, dialect):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Value must be valid Unicode")
        return value

    def process_result_value(self, value, dialect):
        return value
