"""Domain-Driven Design (DDD) + Layered architecture pattern."""

from __future__ import annotations

from typing import Dict

from ._base import base_files, health_controller

LABEL = "Domain-Driven Design (DDD) + Layered"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    files["app.py"] = '''\
"""Application entry point – DDD + Layered architecture."""

from hypern import Hypern
from config import get_config
from interfaces.api.example_controller import example_router
from interfaces.api.health_controller import health_router

config = get_config()

app = Hypern(debug=config.DEBUG)

# Mount API routers
app.use("/api", example_router)
app.use("/", health_router)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    # ── Domain layer ─────────────────────────────────────────────
    files["domain/__init__.py"] = ""

    files["domain/entities/__init__.py"] = ""
    files["domain/entities/example.py"] = '''\
"""Domain entity – the core business object."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Example:
    id: Optional[str] = None
    name: str = ""
    description: str = ""

    def validate(self) -> bool:
        return bool(self.name)
'''

    files["domain/value_objects/__init__.py"] = ""
    files["domain/value_objects/example_id.py"] = '''\
"""Value object – immutable identifier."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExampleId:
    value: str

    def __post_init__(self):
        if not self.value:
            raise ValueError("ExampleId cannot be empty")
'''

    files["domain/repositories/__init__.py"] = ""
    files["domain/repositories/example_repository.py"] = '''\
"""Repository interface (port) – defined in the domain layer."""

from abc import ABC, abstractmethod
from typing import List, Optional

from domain.entities.example import Example


class ExampleRepository(ABC):
    @abstractmethod
    async def find_all(self) -> List[Example]:
        ...

    @abstractmethod
    async def find_by_id(self, item_id: str) -> Optional[Example]:
        ...

    @abstractmethod
    async def save(self, entity: Example) -> Example:
        ...
'''

    files["domain/services/__init__.py"] = ""
    files["domain/services/example_domain_service.py"] = '''\
"""Domain service – logic that doesn\'t belong to a single entity."""

from domain.entities.example import Example


class ExampleDomainService:
    @staticmethod
    def is_valid_example(entity: Example) -> bool:
        return entity.validate()
'''

    # ── Application layer ────────────────────────────────────────
    files["application/__init__.py"] = ""

    files["application/use_cases/__init__.py"] = ""
    files["application/use_cases/create_example.py"] = '''\
"""Use case – create an Example."""

from domain.entities.example import Example
from domain.repositories.example_repository import ExampleRepository


class CreateExampleUseCase:
    def __init__(self, repository: ExampleRepository):
        self.repository = repository

    async def execute(self, name: str, description: str = "") -> Example:
        entity = Example(name=name, description=description)
        if not entity.validate():
            raise ValueError("Invalid example data")
        return await self.repository.save(entity)
'''

    files["application/use_cases/get_example.py"] = '''\
"""Use case – retrieve Examples."""

from typing import List, Optional

from domain.entities.example import Example
from domain.repositories.example_repository import ExampleRepository


class GetExampleUseCase:
    def __init__(self, repository: ExampleRepository):
        self.repository = repository

    async def get_all(self) -> List[Example]:
        return await self.repository.find_all()

    async def get_by_id(self, item_id: str) -> Optional[Example]:
        return await self.repository.find_by_id(item_id)
'''

    files["application/dto/__init__.py"] = ""
    files["application/dto/example_dto.py"] = '''\
"""Data Transfer Objects."""

from dataclasses import dataclass


@dataclass
class CreateExampleDTO:
    name: str
    description: str = ""


@dataclass
class ExampleResponseDTO:
    id: str
    name: str
    description: str
'''

    # ── Infrastructure layer ─────────────────────────────────────
    files["infrastructure/__init__.py"] = ""

    files["infrastructure/persistence/__init__.py"] = ""
    files["infrastructure/persistence/in_memory_example_repository.py"] = '''\
"""In-memory implementation of ExampleRepository."""

from typing import List, Optional
import uuid

from domain.entities.example import Example
from domain.repositories.example_repository import ExampleRepository


class InMemoryExampleRepository(ExampleRepository):
    def __init__(self):
        self._store: dict[str, Example] = {}

    async def find_all(self) -> List[Example]:
        return list(self._store.values())

    async def find_by_id(self, item_id: str) -> Optional[Example]:
        return self._store.get(item_id)

    async def save(self, entity: Example) -> Example:
        if entity.id is None:
            entity.id = str(uuid.uuid4())
        self._store[entity.id] = entity
        return entity
'''

    files["infrastructure/config/__init__.py"] = ""
    files["infrastructure/config/database.py"] = '''\
"""Database configuration – replace with real DB setup."""


class DatabaseConfig:
    URI: str = "sqlite:///db.sqlite3"
'''

    # ── Interface layer ──────────────────────────────────────────
    files["interfaces/__init__.py"] = ""
    files["interfaces/api/__init__.py"] = ""
    files["interfaces/api/health_controller.py"] = health_controller()
    files["interfaces/api/example_controller.py"] = '''\
"""Example API controller."""

from hypern import Router, Request, Response

example_router = Router(prefix="/examples")


@example_router.get("/")
async def list_examples(request: Request) -> Response:
    # TODO: inject use case via DI
    return Response(status_code=200, description=[])


@example_router.post("/")
async def create_example(request: Request) -> Response:
    # TODO: inject use case via DI
    return Response(status_code=201, description={"created": True})
'''

    return files
