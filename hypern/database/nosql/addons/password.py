from mongoengine.base import BaseField
import weakref
from passlib.context import CryptContext
import re
from typing import Optional, Any


class PasswordField(BaseField):
    """
    A custom password field using passlib for hashing and weakref for reference management.
    Supports multiple hashing schemes and automatic upgrade of hash algorithms.
    """

    # Class-level password context - shared across all instances
    pwd_context = CryptContext(
        # List of hashing schemes in order of preference
        schemes=["argon2", "pbkdf2_sha256", "bcrypt_sha256"],
        # Mark argon2 as default
        default="argon2",
        # Argon2 parameters
        argon2__rounds=4,
        argon2__memory_cost=65536,
        argon2__parallelism=2,
        # PBKDF2 parameters
        pbkdf2_sha256__rounds=29000,
    )

    def __init__(
        self,
        min_length: int = 8,
        require_number: bool = False,
        require_special: bool = False,
        require_uppercase: bool = False,
        require_lowercase: bool = False,
        **kwargs,
    ):
        """
        Initialize the password field with validation rules.

        Args:
            min_length: Minimum password length
            require_number: Require at least one number
            require_special: Require at least one special character
            require_uppercase: Require at least one uppercase letter
            require_lowercase: Require at least one lowercase letter
        """
        self.min_length = min_length
        self.require_number = require_number
        self.require_special = require_special
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase

        # Use weakref to store references to parent documents
        self.instances = weakref.WeakKeyDictionary()

        kwargs["required"] = True
        super(PasswordField, self).__init__(**kwargs)

    def validate_password(self, password: str) -> tuple[bool, str]:
        """Validate password strength."""

        if len(password) < self.min_length:
            return False, f"Password must be at least {self.min_length} characters long"

        if self.require_number and not re.search(r"\d", password):
            return False, "Password must contain at least one number"

        if self.require_special and not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return False, "Password must contain at least one special character"

        if self.require_uppercase and not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter"

        if self.require_lowercase and not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter"

        return True, ""

    def hash_password(self, password: str) -> str:
        """Hash password using the configured passlib context."""
        return self.pwd_context.hash(password)

    def verify_password(self, password: str, hash: str) -> tuple[bool, Optional[str]]:
        """
        Verify password and return tuple of (is_valid, new_hash).
        new_hash is provided if the hash needs to be upgraded.
        """
        try:
            is_valid = self.pwd_context.verify(password, hash)
            # Check if the hash needs to be upgraded
            if is_valid and self.pwd_context.needs_update(hash):
                return True, self.hash_password(password)
            return is_valid, None
        except Exception:
            return False, None

    def __get__(self, instance, owner):
        """Custom getter using weakref."""
        if instance is None:
            return self
        return self.instances.get(instance)

    def __set__(self, instance, value):
        """Custom setter using weakref."""
        if value and isinstance(value, str):
            # Validate and hash new password
            is_valid, error = self.validate_password(value)
            if not is_valid:
                raise ValueError(error)
            hashed = self.hash_password(value)
            self.instances[instance] = hashed
            instance._data[self.name] = hashed
        else:
            # If it's already hashed or None
            self.instances[instance] = value
            instance._data[self.name] = value

    def to_mongo(self, value: str) -> Optional[str]:
        """Convert to MongoDB-compatible value."""
        if value is None:
            return None
        return self.hash_password(value)

    def to_python(self, value: str) -> str:
        """Convert from MongoDB to Python."""
        return value

    def prepare_query_value(self, op, value: Any) -> Optional[str]:
        """Prepare value for database operations."""
        if value is None:
            return None
        if op == "exact":
            return self.hash_password(value)
        return value
