# hypern/auth/middleware.py
from typing import List, Optional

from hypern.hypern import Request
from hypern.response import JSONResponse
from hypern.middleware.base import Middleware

from .jwt import JWTAuth


class AuthMiddleware(Middleware):
    def __init__(self, jwt_auth: JWTAuth, exclude_paths: Optional[List[str]] = None):
        self.jwt_auth = jwt_auth
        self.exclude_paths = exclude_paths or []

    async def before_request(self, request: Request):
        if request.path in self.exclude_paths:
            return None

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse({"error": "Invalid authentication"}, status_code=401)

        token = auth_header.split(" ")[1]
        payload = self.jwt_auth.verify_token(token)

        if not payload:
            return JSONResponse({"error": "Invalid token"}, status_code=401)

        request.auth = payload
        return None
