import hashlib
import hmac
import secrets
import time
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt

from hypern.exceptions import ForbiddenException, UnauthorizedException
from hypern.hypern import Request, Response
from .base import Middleware, MiddlewareConfig


@dataclass
class CORSConfig:
    allowed_origins: List[str]
    allowed_methods: List[str]
    max_age: int


@dataclass
class SecurityConfig:
    rate_limiting: bool = False
    jwt_auth: bool = False
    cors_configuration: Optional[CORSConfig] = None
    csrf_protection: bool = False
    security_headers: Optional[Dict[str, str]] = None
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expires_in: int = 3600  # 1 hour in seconds

    def __post_init__(self):
        if self.cors_configuration:
            self.cors_configuration = CORSConfig(**self.cors_configuration)

        if self.security_headers is None:
            self.security_headers = {
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            }


class SecurityMiddleware(Middleware):
    def __init__(self, secur_config: SecurityConfig, config: Optional[MiddlewareConfig] = None):
        super().__init__(config)
        self.secur_config = secur_config
        self._secret_key = secrets.token_bytes(32)
        self._token_lifetime = 3600
        self._rate_limit_storage = {}

    def _rate_limit_check(self, request: Request) -> Optional[Response]:
        """Check if the request exceeds rate limits"""
        if not self.secur_config.rate_limiting:
            return None

        client_ip = request.client.host
        current_time = time.time()
        window_start = int(current_time - 60)  # 1-minute window

        # Clean up old entries
        self._rate_limit_storage = {ip: hits for ip, hits in self._rate_limit_storage.items() if hits["timestamp"] > window_start}

        if client_ip not in self._rate_limit_storage:
            self._rate_limit_storage[client_ip] = {"count": 1, "timestamp": current_time}
        else:
            self._rate_limit_storage[client_ip]["count"] += 1

        if self._rate_limit_storage[client_ip]["count"] > 60:  # 60 requests per minute
            return Response(status_code=429, description=b"Too Many Requests", headers={"Retry-After": "60"})
        return None

    def _generate_jwt_token(self, user_data: Dict[str, Any]) -> str:
        """Generate a JWT token"""
        if not self.secur_config.jwt_secret:
            raise ValueError("JWT secret key is not configured")

        payload = {
            "user": user_data,
            "exp": datetime.now(tz=timezone.utc) + timedelta(seconds=self.secur_config.jwt_expires_in),
            "iat": datetime.now(tz=timezone.utc),
        }
        return jwt.encode(payload, self.secur_config.jwt_secret, algorithm=self.secur_config.jwt_algorithm)

    def _verify_jwt_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token and return payload"""
        try:
            payload = jwt.decode(token, self.secur_config.jwt_secret, algorithms=[self.secur_config.jwt_algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise UnauthorizedException(details={"message": "Token has expired"})
        except jwt.InvalidTokenError:
            raise UnauthorizedException(details={"message": "Invalid token"})

    def _generate_csrf_token(self, session_id: str) -> str:
        """Generate a new CSRF token"""
        timestamp = str(int(time.time()))
        token_data = f"{session_id}:{timestamp}"
        signature = hmac.new(self._secret_key, token_data.encode(), hashlib.sha256).digest()
        return b64encode(f"{token_data}:{b64encode(signature).decode()}".encode()).decode()

    def _validate_csrf_token(self, token: str) -> bool:
        """Validate CSRF token"""
        try:
            decoded_token = b64decode(token.encode()).decode()
            session_id, timestamp, signature = decoded_token.rsplit(":", 2)

            # Verify timestamp
            token_time = int(timestamp)
            current_time = int(time.time())
            if current_time - token_time > self._token_lifetime:
                return False

            # Verify signature
            expected_data = f"{session_id}:{timestamp}"
            expected_signature = hmac.new(self._secret_key, expected_data.encode(), hashlib.sha256).digest()

            actual_signature = b64decode(signature)
            return hmac.compare_digest(expected_signature, actual_signature)

        except (ValueError, AttributeError, TypeError):
            return False

    def _apply_cors_headers(self, response: Response) -> None:
        """Apply CORS headers to response"""
        if not self.secur_config.cors_configuration:
            return

        cors = self.secur_config.cors_configuration
        response.headers.update(
            {
                "Access-Control-Allow-Origin": ", ".join(cors.allowed_origins),
                "Access-Control-Allow-Methods": ", ".join(cors.allowed_methods),
                "Access-Control-Max-Age": str(cors.max_age),
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-CSRF-Token",
                "Access-Control-Allow-Credentials": "true",
            }
        )

    def _apply_security_headers(self, response: Response) -> None:
        """Apply security headers to response"""
        if self.secur_config.security_headers:
            response.headers.update(self.secur_config.security_headers)

    async def before_request(self, request: Request) -> Request | Response:
        """Process request before handling"""
        # Rate limiting check
        if rate_limit_response := self._rate_limit_check(request):
            return rate_limit_response

        # JWT authentication check
        if self.secur_config.jwt_auth:
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise UnauthorizedException(details={"message": "Authorization header missing or invalid"})
            token = auth_header.split(" ")[1]
            try:
                request.user = self._verify_jwt_token(token)
            except UnauthorizedException as e:
                return Response(status_code=401, description=str(e))

        # CSRF protection check
        if self.secur_config.csrf_protection and request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            csrf_token = request.headers.get("X-CSRF-Token")
            if not csrf_token or not self._validate_csrf_token(csrf_token):
                raise ForbiddenException(details={"message": "Invalid CSRF token"})

        return request

    async def after_request(self, response: Response) -> Response:
        """Process response after handling"""
        self._apply_security_headers(response)
        self._apply_cors_headers(response)
        return response

    def generate_csrf_token(self, request: Request) -> str:
        """Generate and set CSRF token for the request"""
        if not hasattr(request, "session_id"):
            request.session_id = secrets.token_urlsafe(32)
        token = self._generate_csrf_token(request.session_id)
        return token
