"""CQRS (Command-Query Responsibility Segregation) architecture pattern."""

from __future__ import annotations

from typing import Dict

from ._base import base_files, health_controller

LABEL = "CQRS (Command-Query Responsibility Segregation)"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    files["app.py"] = '''\
"""Application entry point – CQRS architecture."""

from hypern import Hypern
from config import get_config
from api.controllers.example_controller import example_router
from api.controllers.health_controller import health_router

config = get_config()

app = Hypern(debug=config.DEBUG)

app.use("/", health_router)
app.use("/api", example_router)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    # ── Domain ───────────────────────────────────────────────────
    files["domain/__init__.py"] = ""
    files["domain/models/__init__.py"] = ""
    files["domain/models/example.py"] = '''\
"""Domain model."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Example:
    id: Optional[str] = None
    name: str = ""
    description: str = ""
'''

    files["domain/events/__init__.py"] = ""
    files["domain/events/example_event.py"] = '''\
"""Domain events emitted by commands."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ExampleCreated:
    example_id: str
    name: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExampleUpdated:
    example_id: str
    changes: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
'''

    # ── Commands ─────────────────────────────────────────────────
    files["commands/__init__.py"] = ""
    files["commands/models/__init__.py"] = ""
    files["commands/models/example_command.py"] = '''\
"""Command definitions."""

from dataclasses import dataclass


@dataclass
class CreateExampleCommand:
    name: str
    description: str = ""


@dataclass
class UpdateExampleCommand:
    id: str
    name: str
    description: str = ""
'''

    files["commands/handlers/__init__.py"] = ""
    files["commands/handlers/example_handler.py"] = '''\
"""Command handler – write side."""

import uuid

from commands.models.example_command import CreateExampleCommand
from domain.models.example import Example
from domain.events.example_event import ExampleCreated


class CreateExampleHandler:
    def __init__(self, write_store):
        self.write_store = write_store

    async def handle(self, command: CreateExampleCommand) -> Example:
        entity = Example(
            id=str(uuid.uuid4()),
            name=command.name,
            description=command.description,
        )
        await self.write_store.save(entity)
        # Emit event
        event = ExampleCreated(example_id=entity.id, name=entity.name)
        await self.write_store.publish_event(event)
        return entity
'''

    # ── Queries ──────────────────────────────────────────────────
    files["queries/__init__.py"] = ""
    files["queries/models/__init__.py"] = ""
    files["queries/models/example_query.py"] = '''\
"""Query definitions."""

from dataclasses import dataclass


@dataclass
class GetExampleQuery:
    id: str


@dataclass
class ListExamplesQuery:
    limit: int = 100
    offset: int = 0
'''

    files["queries/handlers/__init__.py"] = ""
    files["queries/handlers/example_handler.py"] = '''\
"""Query handler – read side."""

from typing import List, Optional

from domain.models.example import Example
from queries.models.example_query import GetExampleQuery, ListExamplesQuery


class ExampleQueryHandler:
    def __init__(self, read_store):
        self.read_store = read_store

    async def get_by_id(self, query: GetExampleQuery) -> Optional[Example]:
        return await self.read_store.find_by_id(query.id)

    async def list_all(self, query: ListExamplesQuery) -> List[Example]:
        return await self.read_store.find_all(limit=query.limit, offset=query.offset)
'''

    # ── Infrastructure ───────────────────────────────────────────
    files["infrastructure/__init__.py"] = ""

    files["infrastructure/write_store/__init__.py"] = ""
    files["infrastructure/write_store/in_memory_write_store.py"] = '''\
"""In-memory write store."""

from domain.models.example import Example


class InMemoryWriteStore:
    def __init__(self):
        self._store: dict[str, Example] = {}
        self._events: list = []

    async def save(self, entity: Example):
        self._store[entity.id] = entity

    async def publish_event(self, event):
        self._events.append(event)
'''

    files["infrastructure/read_store/__init__.py"] = ""
    files["infrastructure/read_store/in_memory_read_store.py"] = '''\
"""In-memory read store (projection)."""

from typing import List, Optional

from domain.models.example import Example


class InMemoryReadStore:
    def __init__(self):
        self._store: dict[str, Example] = {}

    async def find_all(self, limit: int = 100, offset: int = 0) -> List[Example]:
        items = list(self._store.values())
        return items[offset:offset + limit]

    async def find_by_id(self, item_id: str) -> Optional[Example]:
        return self._store.get(item_id)

    async def project(self, event):
        """Update read model from event."""
        if hasattr(event, "example_id") and hasattr(event, "name"):
            self._store[event.example_id] = Example(
                id=event.example_id, name=event.name
            )
'''

    # ── API ──────────────────────────────────────────────────────
    files["api/__init__.py"] = ""
    files["api/controllers/__init__.py"] = ""
    files["api/controllers/health_controller.py"] = health_controller()
    files["api/controllers/example_controller.py"] = '''\
"""Example CQRS controller – separate read/write endpoints."""

from hypern import Router, Request, Response

example_router = Router(prefix="/examples")


@example_router.get("/")
async def query_examples(request: Request) -> Response:
    """Read side – uses query handler."""
    # TODO: inject query handler via DI
    return Response(status_code=200, description=[])


@example_router.post("/")
async def command_create_example(request: Request) -> Response:
    """Write side – uses command handler."""
    # TODO: inject command handler via DI
    return Response(status_code=201, description={"created": True})
'''

    return files
