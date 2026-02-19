"""Hexagonal (Ports & Adapters) architecture pattern."""

from __future__ import annotations

from typing import Dict

from ._base import base_files, health_controller

LABEL = "Hexagonal (Ports & Adapters)"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    files["app.py"] = '''\
"""Application entry point – Hexagonal (Ports & Adapters) architecture."""

from hypern import Hypern
from config import get_config
from adapters.inbound.api.health_controller import health_router
from adapters.inbound.api.example_controller import example_router

config = get_config()

app = Hypern(debug=config.DEBUG)

# Mount adapters
app.use("/", health_router)
app.use("/api", example_router)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    # ── Core – Domain ────────────────────────────────────────────
    files["core/__init__.py"] = ""
    files["core/domain/__init__.py"] = ""
    files["core/domain/example.py"] = '''\
"""Domain entity."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Example:
    id: Optional[str] = None
    name: str = ""
    description: str = ""
'''

    # ── Core – Ports ─────────────────────────────────────────────
    files["core/ports/__init__.py"] = ""

    files["core/ports/inbound/__init__.py"] = ""
    files["core/ports/inbound/example_use_case.py"] = '''\
"""Inbound port – defines how external actors interact with the core."""

from abc import ABC, abstractmethod
from typing import List, Optional

from core.domain.example import Example


class ExampleUseCase(ABC):
    @abstractmethod
    async def get_all(self) -> List[Example]: ...

    @abstractmethod
    async def get_by_id(self, item_id: str) -> Optional[Example]: ...

    @abstractmethod
    async def create(self, name: str, description: str = "") -> Example: ...
'''

    files["core/ports/outbound/__init__.py"] = ""
    files["core/ports/outbound/example_repository_port.py"] = '''\
"""Outbound port – defines how the core accesses external resources."""

from abc import ABC, abstractmethod
from typing import List, Optional

from core.domain.example import Example


class ExampleRepositoryPort(ABC):
    @abstractmethod
    async def find_all(self) -> List[Example]: ...

    @abstractmethod
    async def find_by_id(self, item_id: str) -> Optional[Example]: ...

    @abstractmethod
    async def save(self, entity: Example) -> Example: ...
'''

    # ── Core – Services ──────────────────────────────────────────
    files["core/services/__init__.py"] = ""
    files["core/services/example_service.py"] = '''\
"""Application service – implements inbound port, orchestrates domain logic."""

from typing import List, Optional
import uuid

from core.domain.example import Example
from core.ports.inbound.example_use_case import ExampleUseCase
from core.ports.outbound.example_repository_port import ExampleRepositoryPort


class ExampleService(ExampleUseCase):
    def __init__(self, repository: ExampleRepositoryPort):
        self.repository = repository

    async def get_all(self) -> List[Example]:
        return await self.repository.find_all()

    async def get_by_id(self, item_id: str) -> Optional[Example]:
        return await self.repository.find_by_id(item_id)

    async def create(self, name: str, description: str = "") -> Example:
        entity = Example(id=str(uuid.uuid4()), name=name, description=description)
        return await self.repository.save(entity)
'''

    # ── Adapters – Inbound ───────────────────────────────────────
    files["adapters/__init__.py"] = ""
    files["adapters/inbound/__init__.py"] = ""
    files["adapters/inbound/api/__init__.py"] = ""
    files["adapters/inbound/api/health_controller.py"] = health_controller()
    files["adapters/inbound/api/example_controller.py"] = '''\
"""Example API adapter – drives the application via inbound port."""

from hypern import Router, Request, Response

example_router = Router(prefix="/examples")


@example_router.get("/")
async def list_examples(request: Request) -> Response:
    # TODO: inject ExampleUseCase via DI
    return Response(status_code=200, description=[])


@example_router.post("/")
async def create_example(request: Request) -> Response:
    # TODO: inject ExampleUseCase via DI
    return Response(status_code=201, description={"created": True})
'''

    # ── Adapters – Outbound ──────────────────────────────────────
    files["adapters/outbound/__init__.py"] = ""
    files["adapters/outbound/persistence/__init__.py"] = ""
    files["adapters/outbound/persistence/in_memory_example_repository.py"] = '''\
"""In-memory adapter for the outbound ExampleRepositoryPort."""

from typing import List, Optional
import uuid

from core.domain.example import Example
from core.ports.outbound.example_repository_port import ExampleRepositoryPort


class InMemoryExampleRepository(ExampleRepositoryPort):
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

    return files
