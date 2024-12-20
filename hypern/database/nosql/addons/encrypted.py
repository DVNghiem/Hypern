import os
from typing import Any, Optional
from mongoengine.base import BaseField

from cryptography.hazmat.primitives import padding

from hypern.security import EDEngine, AESEngine


class EncryptedField(BaseField):
    """
    A custom MongoEngine field that encrypts data using AES-256-CBC.

    The field automatically handles encryption when saving to MongoDB and
    decryption when retrieving data.

    Attributes:
        engine: Encryption engine to use. If not provided, will use AES-256-CBC
    """

    def __init__(self, engine: Optional[EDEngine] = None, **kwargs):
        if not engine:
            key = os.urandom(32)
            iv = os.urandom(16)
            padding_class = padding.PKCS7
            self.engine = AESEngine(secret_key=key, iv=iv, padding_class=padding_class)
        else:
            self.engine = engine  # type: ignore
        super(EncryptedField, self).__init__(**kwargs)

    def to_mongo(self, value: Any) -> Optional[str]:
        """Convert a Python object to a MongoDB-compatible format."""
        if value is None:
            return None
        return self.engine.encrypt(value)

    def to_python(self, value: Optional[str]) -> Optional[str]:
        """Convert a MongoDB-compatible format to a Python object."""
        if value is None:
            return None
        if isinstance(value, bytes):
            return self.engine.decrypt(value)
        return value

    def prepare_query_value(self, op, value: Any) -> Optional[str]:
        """Prepare a value used in a query."""
        if value is None:
            return None

        if op in ("set", "upsert"):
            return self.to_mongo(value)

        return value
