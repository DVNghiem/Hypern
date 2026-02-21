"""Layered / N-tier architecture pattern."""

from __future__ import annotations

from typing import Dict

from ._base import base_files, health_controller

LABEL = "Layered / N-tier"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    files["app.py"] = '''\
"""Application entry point – Layered / N-tier architecture."""

from hypern import Hypern
from config import get_config
from controllers.health import health_router
from controllers.example import example_router
from middleware.logging import LoggingMiddleware

config = get_config()

app = Hypern(debug=config.DEBUG)

# Register middleware
app.use(LoggingMiddleware())

# Mount routers
app.use("/", health_router)
app.use("/api", example_router)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    # ── Controllers ──────────────────────────────────────────────
    files["controllers/__init__.py"] = ""
    files["controllers/health.py"] = health_controller()
    files["controllers/example.py"] = '''\
"""Example controller – thin HTTP layer."""

from hypern import Router, Request, Response

example_router = Router(prefix="/examples")


@example_router.get("/")
async def list_examples(request: Request) -> Response:
    # TODO: inject service via DI
    return Response(status_code=200, description=[])


@example_router.get("/:id")
async def get_example(request: Request) -> Response:
    return Response(status_code=200, description={"id": request.params.get("id")})


@example_router.post("/")
async def create_example(request: Request) -> Response:
    # TODO: inject service via DI
    return Response(status_code=201, description={"created": True})
'''

    # ── Services ─────────────────────────────────────────────────
    files["services/__init__.py"] = ""
    files["services/example_service.py"] = '''\
"""Example service layer – business logic lives here."""

from repositories.example_repository import ExampleRepository


class ExampleService:
    def __init__(self):
        self.repository = ExampleRepository()

    async def get_all(self):
        return await self.repository.find_all()

    async def get_by_id(self, item_id: str):
        return await self.repository.find_by_id(item_id)

    async def create(self, data: dict):
        return await self.repository.save(data)
'''

    # ── Repositories ─────────────────────────────────────────────
    files["repositories/__init__.py"] = ""
    files["repositories/example_repository.py"] = '''\
"""Example repository – data access layer."""


class ExampleRepository:
    """Replace with real database logic."""

    def __init__(self):
        self._store: dict = {}

    async def find_all(self):
        return list(self._store.values())

    async def find_by_id(self, item_id: str):
        return self._store.get(item_id)

    async def save(self, data: dict):
        item_id = data.get("id", str(len(self._store) + 1))
        self._store[item_id] = data
        return data
'''

    # ── Models ───────────────────────────────────────────────────
    files["models/__init__.py"] = ""
    files["models/example.py"] = '''\
"""Example domain model."""

from dataclasses import dataclass


@dataclass
class Example:
    id: str
    name: str
    description: str = ""
'''

    # ── Schemas ──────────────────────────────────────────────────
    files["schemas/__init__.py"] = ""
    files["schemas/example.py"] = '''\
"""Request/response schemas (validation)."""

from dataclasses import dataclass


@dataclass
class CreateExampleRequest:
    name: str
    description: str = ""


@dataclass
class ExampleResponse:
    id: str
    name: str
    description: str
'''

    # ── Middleware ────────────────────────────────────────────────
    files["middleware/__init__.py"] = ""
    files["middleware/logging.py"] = '''\
"""Simple request-logging middleware."""

from hypern import Request, Response


class LoggingMiddleware:
    async def __call__(self, request: Request) -> Request:
        print(f"[{request.method}] {request.url.path}")
        return request
'''

    return files
