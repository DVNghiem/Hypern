"""Clean Architecture pattern – expanded scaffolding.

Layers (inside → out):
  1. entities/            – Enterprise business rules
  2. use_cases/           – Application business rules (interactors)
  3. interface_adapters/  – Controllers, presenters, gateways
  4. frameworks/          – Web framework, database drivers, external services
"""

from __future__ import annotations

from typing import Dict

from ._base import base_files

LABEL = "Clean Architecture"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    # ── Entry point ──────────────────────────────────────────────
    files["app.py"] = '''\
"""Application entry point – Clean Architecture."""

from hypern import Hypern
from config import get_config
from frameworks.web.routes import register_routes
from bootstrap import wire_dependencies

config = get_config()

app = Hypern(debug=config.DEBUG)
wire_dependencies(app)
register_routes(app)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    files["bootstrap.py"] = '''\
"""Composition root – wires concrete implementations to use-case boundaries."""

from frameworks.database.in_memory_repository import InMemoryExampleRepository
from use_cases.create_example import CreateExampleInteractor
from use_cases.list_examples import ListExamplesInteractor
from use_cases.get_example import GetExampleInteractor
from use_cases.update_example import UpdateExampleInteractor
from use_cases.delete_example import DeleteExampleInteractor


def wire_dependencies(app) -> None:
    repo = InMemoryExampleRepository()

    app.singleton("example_repository", repo)
    app.singleton("create_example", CreateExampleInteractor(gateway=repo))
    app.singleton("list_examples", ListExamplesInteractor(gateway=repo))
    app.singleton("get_example", GetExampleInteractor(gateway=repo))
    app.singleton("update_example", UpdateExampleInteractor(gateway=repo))
    app.singleton("delete_example", DeleteExampleInteractor(gateway=repo))
'''

    # ══════════════════════════════════════════════════════════════
    # LAYER 1 – Entities (enterprise business rules)
    # ══════════════════════════════════════════════════════════════
    files["entities/__init__.py"] = ""

    files["entities/base.py"] = '''\
"""Base entity with identity semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BaseEntity:
    id: Optional[str] = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseEntity):
            return NotImplemented
        return self.id is not None and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id) if self.id else id(self)
'''

    files["entities/example.py"] = '''\
"""Enterprise business rule / entity."""

from dataclasses import dataclass

from entities.base import BaseEntity


@dataclass
class Example(BaseEntity):
    name: str = ""
    description: str = ""
    is_active: bool = True

    def is_valid(self) -> bool:
        return bool(self.name)

    def deactivate(self) -> None:
        self.is_active = False
'''

    files["entities/exceptions.py"] = '''\
"""Domain-level exceptions."""


class DomainError(Exception):
    """Base class for domain errors."""


class EntityNotFound(DomainError):
    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(f"{entity_type} '{entity_id}' not found")
        self.entity_type = entity_type
        self.entity_id = entity_id


class ValidationError(DomainError):
    pass
'''

    # ══════════════════════════════════════════════════════════════
    # LAYER 2 – Use Cases (application business rules / interactors)
    # ══════════════════════════════════════════════════════════════
    files["use_cases/__init__.py"] = ""

    files["use_cases/ports.py"] = '''\
"""Output ports (gateway interfaces) that use cases depend on.

Concrete implementations live in the frameworks layer.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from entities.example import Example


class ExampleGateway(ABC):
    @abstractmethod
    async def find_all(self, *, active_only: bool = False) -> List[Example]: ...

    @abstractmethod
    async def find_by_id(self, item_id: str) -> Optional[Example]: ...

    @abstractmethod
    async def save(self, entity: Example) -> Example: ...

    @abstractmethod
    async def delete(self, item_id: str) -> bool: ...
'''

    files["use_cases/dto.py"] = '''\
"""Input / output DTOs for use cases."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CreateExampleInput:
    name: str
    description: str = ""


@dataclass
class UpdateExampleInput:
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


@dataclass
class ExampleOutput:
    id: str
    name: str
    description: str
    is_active: bool
'''

    files["use_cases/create_example.py"] = '''\
"""Interactor – create an Example."""

import uuid

from entities.example import Example
from entities.exceptions import ValidationError
from use_cases.ports import ExampleGateway
from use_cases.dto import CreateExampleInput, ExampleOutput


class CreateExampleInteractor:
    def __init__(self, gateway: ExampleGateway):
        self._gw = gateway

    async def execute(self, inp: CreateExampleInput) -> ExampleOutput:
        entity = Example(id=str(uuid.uuid4()), name=inp.name, description=inp.description)
        if not entity.is_valid():
            raise ValidationError("Name is required")
        saved = await self._gw.save(entity)
        return ExampleOutput(
            id=saved.id, name=saved.name,
            description=saved.description, is_active=saved.is_active,
        )
'''

    files["use_cases/list_examples.py"] = '''\
"""Interactor – list examples."""

from typing import List

from use_cases.ports import ExampleGateway
from use_cases.dto import ExampleOutput


class ListExamplesInteractor:
    def __init__(self, gateway: ExampleGateway):
        self._gw = gateway

    async def execute(self, active_only: bool = False) -> List[ExampleOutput]:
        entities = await self._gw.find_all(active_only=active_only)
        return [
            ExampleOutput(id=e.id, name=e.name, description=e.description, is_active=e.is_active)
            for e in entities
        ]
'''

    files["use_cases/get_example.py"] = '''\
"""Interactor – get a single example by ID."""

from entities.exceptions import EntityNotFound
from use_cases.ports import ExampleGateway
from use_cases.dto import ExampleOutput


class GetExampleInteractor:
    def __init__(self, gateway: ExampleGateway):
        self._gw = gateway

    async def execute(self, item_id: str) -> ExampleOutput:
        entity = await self._gw.find_by_id(item_id)
        if entity is None:
            raise EntityNotFound("Example", item_id)
        return ExampleOutput(
            id=entity.id, name=entity.name,
            description=entity.description, is_active=entity.is_active,
        )
'''

    files["use_cases/update_example.py"] = '''\
"""Interactor – update an existing example."""

from entities.exceptions import EntityNotFound
from use_cases.ports import ExampleGateway
from use_cases.dto import UpdateExampleInput, ExampleOutput


class UpdateExampleInteractor:
    def __init__(self, gateway: ExampleGateway):
        self._gw = gateway

    async def execute(self, item_id: str, inp: UpdateExampleInput) -> ExampleOutput:
        entity = await self._gw.find_by_id(item_id)
        if entity is None:
            raise EntityNotFound("Example", item_id)
        if inp.name is not None:
            entity.name = inp.name
        if inp.description is not None:
            entity.description = inp.description
        if inp.is_active is not None:
            entity.is_active = inp.is_active
        saved = await self._gw.save(entity)
        return ExampleOutput(
            id=saved.id, name=saved.name,
            description=saved.description, is_active=saved.is_active,
        )
'''

    files["use_cases/delete_example.py"] = '''\
"""Interactor – delete an example."""

from use_cases.ports import ExampleGateway


class DeleteExampleInteractor:
    def __init__(self, gateway: ExampleGateway):
        self._gw = gateway

    async def execute(self, item_id: str) -> bool:
        return await self._gw.delete(item_id)
'''

    # ══════════════════════════════════════════════════════════════
    # LAYER 3 – Interface Adapters (controllers, presenters, gateways)
    # ══════════════════════════════════════════════════════════════
    files["interface_adapters/__init__.py"] = ""

    files["interface_adapters/controllers/__init__.py"] = ""
    files["interface_adapters/controllers/example_controller.py"] = '''\
"""Controller – converts HTTP requests into use-case calls."""

from hypern import Router, Request, Response

example_router = Router(prefix="/api/examples")


@example_router.get("/")
async def list_examples(request: Request) -> Response:
    # interactor = request.app.resolve("list_examples")
    # items = await interactor.execute()
    return Response(status_code=200, description=[])


@example_router.get("/:id")
async def get_example(request: Request) -> Response:
    # interactor = request.app.resolve("get_example")
    # item = await interactor.execute(request.params["id"])
    return Response(status_code=200, description={})


@example_router.post("/")
async def create_example(request: Request) -> Response:
    # interactor = request.app.resolve("create_example")
    # inp = CreateExampleInput(**request.json())
    # result = await interactor.execute(inp)
    return Response(status_code=201, description={"created": True})


@example_router.put("/:id")
async def update_example(request: Request) -> Response:
    # interactor = request.app.resolve("update_example")
    # inp = UpdateExampleInput(**request.json())
    # result = await interactor.execute(request.params["id"], inp)
    return Response(status_code=200, description={"updated": True})


@example_router.delete("/:id")
async def delete_example(request: Request) -> Response:
    # interactor = request.app.resolve("delete_example")
    # await interactor.execute(request.params["id"])
    return Response(status_code=204, description="")
'''

    files["interface_adapters/presenters/__init__.py"] = ""
    files["interface_adapters/presenters/example_presenter.py"] = '''\
"""Presenter – formats use-case output for the delivery mechanism."""

from use_cases.dto import ExampleOutput


def present_example(output: ExampleOutput) -> dict:
    return {
        "id": output.id,
        "name": output.name,
        "description": output.description,
        "is_active": output.is_active,
    }


def present_example_list(outputs: list[ExampleOutput]) -> list[dict]:
    return [present_example(o) for o in outputs]
'''

    files["interface_adapters/gateways/__init__.py"] = ""
    files["interface_adapters/gateways/notification_gateway.py"] = '''\
"""Example outbound gateway interface – for external service calls."""

from abc import ABC, abstractmethod


class NotificationGateway(ABC):
    @abstractmethod
    async def send(self, recipient: str, message: str) -> bool: ...
'''

    # ══════════════════════════════════════════════════════════════
    # LAYER 4 – Frameworks & Drivers (outermost)
    # ══════════════════════════════════════════════════════════════
    files["frameworks/__init__.py"] = ""

    # ── Database ─────────────────────────────────────────────────
    files["frameworks/database/__init__.py"] = ""
    files["frameworks/database/in_memory_repository.py"] = '''\
"""Concrete repository implementation (in-memory)."""

from typing import List, Optional
import uuid

from entities.example import Example
from use_cases.ports import ExampleGateway


class InMemoryExampleRepository(ExampleGateway):
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

    files["frameworks/database/config.py"] = '''\
"""Database configuration."""

import os


class DatabaseConfig:
    URI: str = os.getenv("DATABASE_URL", "sqlite:///db.sqlite3")
    POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
'''

    # ── Web ──────────────────────────────────────────────────────
    files["frameworks/web/__init__.py"] = ""
    files["frameworks/web/routes.py"] = '''\
"""Route registration – wires controllers to the Hypern app."""

from hypern import Router, Request, Response
from interface_adapters.controllers.example_controller import example_router

health_router = Router(prefix="")


@health_router.get("/health")
async def health(request: Request) -> Response:
    return Response(status_code=200, description={"status": "ok"})


def register_routes(app):
    app.use("/", health_router)
    app.use("/", example_router)
'''

    files["frameworks/web/middleware.py"] = '''\
"""Framework-level middleware."""

from hypern import Request


class RequestLoggingMiddleware:
    async def __call__(self, request: Request) -> Request:
        print(f"[{request.method}] {request.url.path}")
        return request
'''

    # ── External services ────────────────────────────────────────
    files["frameworks/external/__init__.py"] = ""
    files["frameworks/external/console_notification.py"] = '''\
"""Concrete notification gateway – prints to console (replace with real impl)."""

from interface_adapters.gateways.notification_gateway import NotificationGateway


class ConsoleNotificationGateway(NotificationGateway):
    async def send(self, recipient: str, message: str) -> bool:
        print(f"[Notification] To {recipient}: {message}")
        return True
'''

    # ── Tests ────────────────────────────────────────────────────
    files["tests/test_create_example.py"] = '''\
"""Unit tests for CreateExampleInteractor."""

import asyncio
from use_cases.create_example import CreateExampleInteractor
from use_cases.dto import CreateExampleInput
from frameworks.database.in_memory_repository import InMemoryExampleRepository


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_create_example():
    repo = InMemoryExampleRepository()
    interactor = CreateExampleInteractor(gateway=repo)
    result = _run(interactor.execute(CreateExampleInput(name="Test", description="Desc")))
    assert result.name == "Test"
    assert result.id


def test_list_after_create():
    from use_cases.list_examples import ListExamplesInteractor
    repo = InMemoryExampleRepository()
    create = CreateExampleInteractor(gateway=repo)
    _run(create.execute(CreateExampleInput(name="A")))
    _run(create.execute(CreateExampleInput(name="B")))

    lister = ListExamplesInteractor(gateway=repo)
    items = _run(lister.execute())
    assert len(items) == 2
'''

    return files
