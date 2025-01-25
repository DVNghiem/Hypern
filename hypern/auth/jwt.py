# hypern/auth/jwt.py
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from pydantic import BaseModel


class JWTConfig(BaseModel):
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7


class JWTAuth:
    def __init__(self, config: JWTConfig):
        self.config = config

    def create_access_token(self, data: Dict[str, Any]) -> str:
        expire = datetime.now(tz=timezone.utc) + timedelta(minutes=self.config.access_token_expire_minutes)
        to_encode = data.copy()
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, self.config.secret_key, algorithm=self.config.algorithm)

    def create_refresh_token(self, data: Dict[str, Any]) -> str:
        expire = datetime.now(tz=timezone.utc) + timedelta(days=self.config.refresh_token_expire_days)
        to_encode = data.copy()
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, self.config.secret_key, algorithm=self.config.algorithm)

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = jwt.decode(token, self.config.secret_key, algorithms=[self.config.algorithm])
            return payload
        except jwt.PyJWTError:
            return None
