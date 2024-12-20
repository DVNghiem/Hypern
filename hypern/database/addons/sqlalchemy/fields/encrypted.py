# -*- coding: utf-8 -*-
import os
import typing

from cryptography.hazmat.primitives import padding
from sqlalchemy.types import LargeBinary, String, TypeDecorator

from hypern.security import AESEngine, EDEngine


class StringEncryptType(TypeDecorator):
    impl = String
    cache_ok = True

    def __init__(self, engine: typing.Optional[EDEngine] = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        if not engine:
            key = os.urandom(32)
            iv = os.urandom(16)
            padding_class = padding.PKCS7
            self.engine = AESEngine(secret_key=key, iv=iv, padding_class=padding_class)
        else:
            self.engine = engine  # type: ignore

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("Value String Encrypt Type must be a string")
        return self.engine.encrypt(value).decode(encoding="utf-8")

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return self.engine.decrypt(value)


class LargeBinaryEncryptType(StringEncryptType):
    impl = LargeBinary
    cache_ok = True

    def __init__(self, engine: typing.Optional[EDEngine] = None, *args, **kwargs) -> None:
        super().__init__(engine=engine, *args, **kwargs)  # type: ignore

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        value = super().process_bind_param(value, dialect)
        if isinstance(value, str):
            return value.encode("utf-8")
        return value

    def process_result_value(self, value, dialect):
        if isinstance(value, bytes):
            value = value.decode("utf-8")
            return super().process_result_value(value, dialect)
        return value
