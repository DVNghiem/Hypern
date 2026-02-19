"""Onion Architecture pattern – expanded scaffolding.

Rings (inside → out):
  1. core/          – entities, value objects, domain services, repository interfaces
  2. application/   – use cases (application services), DTOs, mappers
  3. infrastructure/– persistence, external services, configuration
  4. presentation/  – controllers, middleware, serializers
"""

from __future__ import annotations

from typing import Dict

from ._base import base_files, health_controller

LABEL = "Onion Architecture"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    # ── Entry point ──────────────────────────────────────────────
    files["app.py"] = '''\
"""Application entry point – Onion Architecture."""

from hypern import Hypern
from config import get_config

# Presentation layer
from presentation.controllers.health_controller import health_router
from presentation.controllers.example_controller import example_router
from presentation.middleware.logging import LoggingMiddleware
from presentation.middleware.error_handler import ErrorHandlerMiddleware

# Dependency wiring
from bootstrap import wire_dependencies

config = get_config()

app = Hypern(debug=config.DEBUG)

# Wire DI
wire_dependencies(app)

# Middleware (outermost ring)
app.use(ErrorHandlerMiddleware())
app.use(LoggingMiddleware())

# Mount routers
app.use("/", health_router)
app.use("/api", example_router)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    files["bootstrap.py"] = '''\
"""Dependency wiring – connects infrastructure to application layer."""

from core.interfaces.repositories.example_repository import IExampleRepository
from infrastructure.persistence.in_memory_example_repository import InMemoryExampleRepository
from application.services.example_service import ExampleAppService


def wire_dependencies(app) -> None:
    """Register singletons / factories in the DI container."""
    repo: IExampleRepository = InMemoryExampleRepository()
    service = ExampleAppService(repository=repo)

    app.singleton("example_repository", repo)
    app.singleton("example_service", service)
'''

    # ══════════════════════════════════════════════════════════════
    # RING 1 – Core (innermost – zero external dependencies)
    # ══════════════════════════════════════════════════════════════
    files["core/__init__.py"] = ""

    # ── Entities ─────────────────────────────────────────────────
    files["core/entities/__init__.py"] = ""
    files["core/entities/base.py"] = '''\
"""Base entity with identity semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BaseEntity:
    """All domain entities derive from this base."""
    id: Optional[str] = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseEntity):
            return NotImplemented
        return self.id is not None and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id) if self.id else id(self)
'''

    files["core/entities/example.py"] = '''\
"""Example domain entity."""

from dataclasses import dataclass

from core.entities.base import BaseEntity


@dataclass
class Example(BaseEntity):
    name: str = ""
    description: str = ""
    is_active: bool = True

    # ── Domain rules ─────────────────────────────────────────
    def validate(self) -> bool:
        return bool(self.name)

    def deactivate(self) -> None:
        self.is_active = False

    def activate(self) -> None:
        self.is_active = True
'''

    # ── Value Objects ────────────────────────────────────────────
    files["core/value_objects/__init__.py"] = ""
    files["core/value_objects/example_id.py"] = '''\
"""Value object – immutable identifier."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExampleId:
    value: str

    def __post_init__(self):
        if not self.value:
            raise ValueError("ExampleId cannot be empty")

    def __str__(self) -> str:
        return self.value
'''

    # ── Domain Services ──────────────────────────────────────────
    files["core/services/__init__.py"] = ""
    files["core/services/example_domain_service.py"] = '''\
"""Domain service – cross-entity or complex domain logic."""

from core.entities.example import Example


class ExampleDomainService:
    @staticmethod
    def is_publishable(entity: Example) -> bool:
        """Business rule: only active, valid examples can be published."""
        return entity.is_active and entity.validate()
'''

    # ── Repository interfaces (ports) ────────────────────────────
    files["core/interfaces/__init__.py"] = ""
    files["core/interfaces/repositories/__init__.py"] = ""
    files["core/interfaces/repositories/example_repository.py"] = '''\
"""Repository interface – defined in the core ring (no infra deps)."""

from abc import ABC, abstractmethod
from typing import List, Optional

from core.entities.example import Example


class IExampleRepository(ABC):
    @abstractmethod
    async def find_all(self, *, active_only: bool = False) -> List[Example]: ...

    @abstractmethod
    async def find_by_id(self, item_id: str) -> Optional[Example]: ...

    @abstractmethod
    async def save(self, entity: Example) -> Example: ...

    @abstractmethod
    async def delete(self, item_id: str) -> bool: ...
'''

    # ── Domain exceptions ────────────────────────────────────────
    files["core/exceptions.py"] = '''\
"""Domain-level exceptions – used by core and application rings."""


class DomainException(Exception):
    """Base exception for domain errors."""


class EntityNotFound(DomainException):
    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(f"{entity_type} with id '{entity_id}' not found")
        self.entity_type = entity_type
        self.entity_id = entity_id


class ValidationError(DomainException):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message)
'''

    # ══════════════════════════════════════════════════════════════
    # RING 2 – Application (use cases / app services / DTOs)
    # ══════════════════════════════════════════════════════════════
    files["application/__init__.py"] = ""

    # ── DTOs ─────────────────────────────────────────────────────
    files["application/dto/__init__.py"] = ""
    files["application/dto/example_dto.py"] = '''\
"""Data Transfer Objects – decouple core from presentation."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CreateExampleDTO:
    name: str
    description: str = ""


@dataclass
class UpdateExampleDTO:
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


@dataclass
class ExampleResponseDTO:
    id: str
    name: str
    description: str
    is_active: bool
'''

    # ── Mappers ──────────────────────────────────────────────────
    files["application/mappers/__init__.py"] = ""
    files["application/mappers/example_mapper.py"] = '''\
"""Mapper – convert between DTOs and domain entities."""

from core.entities.example import Example
from application.dto.example_dto import ExampleResponseDTO


class ExampleMapper:
    @staticmethod
    def to_response(entity: Example) -> ExampleResponseDTO:
        return ExampleResponseDTO(
            id=entity.id or "",
            name=entity.name,
            description=entity.description,
            is_active=entity.is_active,
        )

    @staticmethod
    def to_response_list(entities: list[Example]) -> list[ExampleResponseDTO]:
        return [ExampleMapper.to_response(e) for e in entities]
'''

    # ── Application services (use cases) ─────────────────────────
    files["application/services/__init__.py"] = ""
    files["application/services/example_service.py"] = '''\
"""Application service – orchestrates use cases via repository interface."""

from typing import List, Optional
import uuid

from core.entities.example import Example
from core.exceptions import EntityNotFound, ValidationError
from core.interfaces.repositories.example_repository import IExampleRepository
from application.dto.example_dto import (
    CreateExampleDTO,
    UpdateExampleDTO,
    ExampleResponseDTO,
)
from application.mappers.example_mapper import ExampleMapper


class ExampleAppService:
    def __init__(self, repository: IExampleRepository):
        self._repo = repository

    async def get_all(self, active_only: bool = False) -> List[ExampleResponseDTO]:
        entities = await self._repo.find_all(active_only=active_only)
        return ExampleMapper.to_response_list(entities)

    async def get_by_id(self, item_id: str) -> ExampleResponseDTO:
        entity = await self._repo.find_by_id(item_id)
        if entity is None:
            raise EntityNotFound("Example", item_id)
        return ExampleMapper.to_response(entity)

    async def create(self, dto: CreateExampleDTO) -> ExampleResponseDTO:
        entity = Example(
            id=str(uuid.uuid4()),
            name=dto.name,
            description=dto.description,
        )
        if not entity.validate():
            raise ValidationError("Name is required")
        saved = await self._repo.save(entity)
        return ExampleMapper.to_response(saved)

    async def update(self, item_id: str, dto: UpdateExampleDTO) -> ExampleResponseDTO:
        entity = await self._repo.find_by_id(item_id)
        if entity is None:
            raise EntityNotFound("Example", item_id)
        if dto.name is not None:
            entity.name = dto.name
        if dto.description is not None:
            entity.description = dto.description
        if dto.is_active is not None:
            entity.is_active = dto.is_active
        saved = await self._repo.save(entity)
        return ExampleMapper.to_response(saved)

    async def delete(self, item_id: str) -> bool:
        return await self._repo.delete(item_id)
'''

    # ══════════════════════════════════════════════════════════════
    # RING 3 – Infrastructure (persistence, external integrations)
    # ══════════════════════════════════════════════════════════════
    files["infrastructure/__init__.py"] = ""

    files["infrastructure/persistence/__init__.py"] = ""
    files["infrastructure/persistence/in_memory_example_repository.py"] = '''\
"""In-memory implementation of IExampleRepository.

Replace with a real database adapter (e.g. PostgreSQL via Hypern\'s Database).
"""

from typing import List, Optional
import uuid

from core.entities.example import Example
from core.interfaces.repositories.example_repository import IExampleRepository


class InMemoryExampleRepository(IExampleRepository):
    def __init__(self):
        self._store: dict[str, Example] = {}

    async def find_all(self, *, active_only: bool = False) -> List[Example]:
        items = list(self._store.values())
        if active_only:
            items = [e for e in items if e.is_active]
        return items

    async def find_by_id(self, item_id: str) -> Optional[Example]:
        return self._store.get(item_id)

    async def save(self, entity: Example) -> Example:
        if entity.id is None:
            entity.id = str(uuid.uuid4())
        self._store[entity.id] = entity
        return entity

    async def delete(self, item_id: str) -> bool:
        return self._store.pop(item_id, None) is not None
'''

    files["infrastructure/config/__init__.py"] = ""
    files["infrastructure/config/database.py"] = '''\
"""Database configuration – replace with real DB setup."""

import os


class DatabaseConfig:
    URI: str = os.getenv("DATABASE_URL", "sqlite:///db.sqlite3")
    POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
'''

    # ══════════════════════════════════════════════════════════════
    # RING 4 – Presentation (HTTP controllers, middleware, serializers)
    # ══════════════════════════════════════════════════════════════
    files["presentation/__init__.py"] = ""

    # ── Controllers ──────────────────────────────────────────────
    files["presentation/controllers/__init__.py"] = ""
    files["presentation/controllers/health_controller.py"] = health_controller()
    files["presentation/controllers/example_controller.py"] = '''\
"""Example controller – outermost ring, depends on application services."""

from hypern import Router, Request, Response

example_router = Router(prefix="/examples")


@example_router.get("/")
async def list_examples(request: Request) -> Response:
    """List all examples (optionally filter active only via ?active=true)."""
    # service: ExampleAppService = request.app.resolve("example_service")
    # active_only = request.query.get("active") == "true"
    # items = await service.get_all(active_only=active_only)
    return Response(status_code=200, description=[])


@example_router.get("/:id")
async def get_example(request: Request) -> Response:
    """Get a single example by ID."""
    # service = request.app.resolve("example_service")
    # item = await service.get_by_id(request.params["id"])
    return Response(status_code=200, description={})


@example_router.post("/")
async def create_example(request: Request) -> Response:
    """Create a new example."""
    # service = request.app.resolve("example_service")
    # dto = CreateExampleDTO(**request.json())
    # result = await service.create(dto)
    return Response(status_code=201, description={"created": True})


@example_router.put("/:id")
async def update_example(request: Request) -> Response:
    """Update an existing example."""
    # service = request.app.resolve("example_service")
    # dto = UpdateExampleDTO(**request.json())
    # result = await service.update(request.params["id"], dto)
    return Response(status_code=200, description={"updated": True})


@example_router.delete("/:id")
async def delete_example(request: Request) -> Response:
    """Delete an example by ID."""
    # service = request.app.resolve("example_service")
    # await service.delete(request.params["id"])
    return Response(status_code=204, description="")
'''

    # ── Middleware ────────────────────────────────────────────────
    files["presentation/middleware/__init__.py"] = ""
    files["presentation/middleware/logging.py"] = '''\
"""Request-logging middleware."""

from hypern import Request


class LoggingMiddleware:
    async def __call__(self, request: Request) -> Request:
        print(f"[{request.method}] {request.url.path}")
        return request
'''

    files["presentation/middleware/error_handler.py"] = '''\
"""Global error-handling middleware – maps domain exceptions to HTTP responses."""

from hypern import Request, Response


class ErrorHandlerMiddleware:
    async def __call__(self, request: Request) -> Request:
        # In a real app you would wrap this in try/except around
        # the downstream handler and catch domain exceptions.
        return request
'''

    # ── Serializers ──────────────────────────────────────────────
    files["presentation/serializers/__init__.py"] = ""
    files["presentation/serializers/example_serializer.py"] = '''\
"""Serializer – convert DTOs to JSON-ready dicts."""

from application.dto.example_dto import ExampleResponseDTO


def serialize_example(dto: ExampleResponseDTO) -> dict:
    return {
        "id": dto.id,
        "name": dto.name,
        "description": dto.description,
        "is_active": dto.is_active,
    }


def serialize_example_list(dtos: list[ExampleResponseDTO]) -> list[dict]:
    return [serialize_example(d) for d in dtos]
'''

    # ── Tests ────────────────────────────────────────────────────
    files["tests/test_example_service.py"] = '''\
"""Unit tests for ExampleAppService."""

import asyncio
from application.dto.example_dto import CreateExampleDTO
from application.services.example_service import ExampleAppService
from infrastructure.persistence.in_memory_example_repository import InMemoryExampleRepository


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_create_and_retrieve():
    repo = InMemoryExampleRepository()
    service = ExampleAppService(repository=repo)

    dto = CreateExampleDTO(name="Test", description="A test example")
    result = _run(service.create(dto))
    assert result.name == "Test"
    assert result.id

    fetched = _run(service.get_by_id(result.id))
    assert fetched.name == "Test"


def test_list_all():
    repo = InMemoryExampleRepository()
    service = ExampleAppService(repository=repo)

    _run(service.create(CreateExampleDTO(name="A")))
    _run(service.create(CreateExampleDTO(name="B")))

    items = _run(service.get_all())
    assert len(items) == 2
'''

    return files
