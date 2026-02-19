"""Event-Driven / Event Sourcing architecture pattern – expanded scaffolding.

Structure:
  domain/       – aggregates with event-sourcing support
  events/       – event bus, definitions, handlers, store
  projections/  – read-model projections rebuilt from events
  services/     – application services that produce/consume events
  infrastructure/ – persistence, snapshot store
  api/          – HTTP controllers
"""

from __future__ import annotations

from typing import Dict

from ._base import base_files, health_controller

LABEL = "Event-Driven / Event Sourcing"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    # ── Entry point ──────────────────────────────────────────────
    files["app.py"] = '''\
"""Application entry point – Event-Driven / Event Sourcing architecture."""

from hypern import Hypern
from config import get_config

from api.controllers.health_controller import health_router
from api.controllers.example_controller import example_router
from bootstrap import wire_dependencies

config = get_config()

app = Hypern(debug=config.DEBUG)
wire_dependencies(app)

app.use("/", health_router)
app.use("/api", example_router)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    files["bootstrap.py"] = '''\
"""Wire event subscriptions and dependencies."""

from events.bus import event_bus
from events.definitions.example_events import ExampleCreated, ExampleUpdated, ExampleDeleted
from events.handlers.example_handler import (
    on_example_created,
    on_example_updated,
    on_example_deleted,
)
from projections.example_projection import ExampleProjection
from events.store.event_store import InMemoryEventStore
from infrastructure.snapshot.snapshot_store import InMemorySnapshotStore
from services.example_service import ExampleService


def wire_dependencies(app) -> None:
    event_store = InMemoryEventStore()
    snapshot_store = InMemorySnapshotStore()
    projection = ExampleProjection()

    # Subscribe projection handlers
    event_bus.subscribe(ExampleCreated, projection.handle_created)
    event_bus.subscribe(ExampleUpdated, projection.handle_updated)
    event_bus.subscribe(ExampleDeleted, projection.handle_deleted)

    # Subscribe logging / side-effect handlers
    event_bus.subscribe(ExampleCreated, on_example_created)
    event_bus.subscribe(ExampleUpdated, on_example_updated)
    event_bus.subscribe(ExampleDeleted, on_example_deleted)

    service = ExampleService(
        event_store=event_store,
        event_bus=event_bus,
        snapshot_store=snapshot_store,
        projection=projection,
    )

    app.singleton("example_service", service)
    app.singleton("example_projection", projection)
'''

    # ══════════════════════════════════════════════════════════════
    # Domain – aggregates with event sourcing
    # ══════════════════════════════════════════════════════════════
    files["domain/__init__.py"] = ""
    files["domain/aggregates/__init__.py"] = ""
    files["domain/aggregates/base.py"] = '''\
"""Base aggregate root with event-sourcing support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class AggregateRoot:
    id: Optional[str] = None
    version: int = 0
    _pending_events: List[Any] = field(default_factory=list, repr=False)

    def _apply(self, event: Any) -> None:
        """Override in subclass to mutate state from an event."""
        raise NotImplementedError

    def apply_event(self, event: Any, *, is_new: bool = True) -> None:
        """Apply event and optionally mark it as pending (new)."""
        self._apply(event)
        self.version += 1
        if is_new:
            self._pending_events.append(event)

    def collect_events(self) -> List[Any]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def load_from_history(self, events: list) -> None:
        """Replay events to rebuild state."""
        for event in events:
            self.apply_event(event, is_new=False)
'''

    files["domain/aggregates/example.py"] = '''\
"""Example aggregate – event-sourced."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.aggregates.base import AggregateRoot
from events.definitions.example_events import (
    ExampleCreated,
    ExampleUpdated,
    ExampleDeleted,
)


@dataclass
class ExampleAggregate(AggregateRoot):
    name: str = ""
    description: str = ""
    is_active: bool = True

    # ── Commands (produce events) ────────────────────────────
    def create(self, aggregate_id: str, name: str, description: str = "") -> None:
        event = ExampleCreated(example_id=aggregate_id, name=name, description=description)
        self.apply_event(event)

    def update(self, name: str | None = None, description: str | None = None) -> None:
        event = ExampleUpdated(
            example_id=self.id or "",
            name=name if name is not None else self.name,
            description=description if description is not None else self.description,
        )
        self.apply_event(event)

    def delete(self) -> None:
        event = ExampleDeleted(example_id=self.id or "")
        self.apply_event(event)

    # ── Event applicators ────────────────────────────────────
    def _apply(self, event) -> None:
        if isinstance(event, ExampleCreated):
            self.id = event.example_id
            self.name = event.name
            self.description = event.description
            self.is_active = True
        elif isinstance(event, ExampleUpdated):
            self.name = event.name
            self.description = event.description
        elif isinstance(event, ExampleDeleted):
            self.is_active = False
'''

    # ══════════════════════════════════════════════════════════════
    # Events
    # ══════════════════════════════════════════════════════════════
    files["events/__init__.py"] = ""

    files["events/bus.py"] = '''\
"""In-process async event bus with subscribe / publish semantics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Coroutine, Dict, List, Type


class EventBus:
    def __init__(self):
        self._handlers: Dict[Type, List[Callable[..., Coroutine]]] = defaultdict(list)

    def subscribe(self, event_type: Type, handler: Callable[..., Coroutine]) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: Type, handler: Callable[..., Coroutine]) -> None:
        self._handlers[event_type] = [h for h in self._handlers[event_type] if h is not handler]

    async def publish(self, event: Any) -> None:
        for handler in self._handlers.get(type(event), []):
            await handler(event)

    async def publish_all(self, events: list) -> None:
        for event in events:
            await self.publish(event)


# Global singleton
event_bus = EventBus()
'''

    files["events/definitions/__init__.py"] = ""
    files["events/definitions/example_events.py"] = '''\
"""Event definitions for the Example aggregate."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ExampleCreated:
    example_id: str
    name: str
    description: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExampleUpdated:
    example_id: str
    name: str
    description: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExampleDeleted:
    example_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
'''

    files["events/handlers/__init__.py"] = ""
    files["events/handlers/example_handler.py"] = '''\
"""Side-effect handlers – react to domain events (logging, notifications, …)."""

from events.definitions.example_events import ExampleCreated, ExampleUpdated, ExampleDeleted


async def on_example_created(event: ExampleCreated) -> None:
    print(f"[Event] Example created: {event.example_id} – {event.name}")


async def on_example_updated(event: ExampleUpdated) -> None:
    print(f"[Event] Example updated: {event.example_id}")


async def on_example_deleted(event: ExampleDeleted) -> None:
    print(f"[Event] Example deleted: {event.example_id}")
'''

    files["events/store/__init__.py"] = ""
    files["events/store/event_store.py"] = '''\
"""Event store – append-only log of domain events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


@dataclass
class StoredEvent:
    aggregate_id: str
    event_type: str
    data: Any
    version: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


class InMemoryEventStore:
    def __init__(self):
        self._events: List[StoredEvent] = []

    async def append(self, aggregate_id: str, event: Any, version: int) -> None:
        self._events.append(
            StoredEvent(
                aggregate_id=aggregate_id,
                event_type=type(event).__name__,
                data=event,
                version=version,
            )
        )

    async def append_all(self, aggregate_id: str, events: list, start_version: int) -> None:
        for i, event in enumerate(events):
            await self.append(aggregate_id, event, start_version + i)

    async def get_events(
        self, aggregate_id: str, *, after_version: int = 0
    ) -> List[StoredEvent]:
        return [
            e
            for e in self._events
            if e.aggregate_id == aggregate_id and e.version > after_version
        ]

    async def get_all_events(self) -> List[StoredEvent]:
        return list(self._events)
'''

    # ══════════════════════════════════════════════════════════════
    # Projections (read models)
    # ══════════════════════════════════════════════════════════════
    files["projections/__init__.py"] = ""
    files["projections/example_projection.py"] = '''\
"""Read-model projection – rebuilt from events, serves queries."""

from __future__ import annotations

from typing import Dict, List, Optional

from events.definitions.example_events import ExampleCreated, ExampleUpdated, ExampleDeleted


class ExampleProjection:
    """Maintains an in-memory read model updated by event handlers."""

    def __init__(self):
        self._read_model: Dict[str, dict] = {}

    # ── Event handlers (subscribed via EventBus) ─────────────
    async def handle_created(self, event: ExampleCreated) -> None:
        self._read_model[event.example_id] = {
            "id": event.example_id,
            "name": event.name,
            "description": event.description,
            "is_active": True,
        }

    async def handle_updated(self, event: ExampleUpdated) -> None:
        if event.example_id in self._read_model:
            self._read_model[event.example_id].update(
                {"name": event.name, "description": event.description}
            )

    async def handle_deleted(self, event: ExampleDeleted) -> None:
        if event.example_id in self._read_model:
            self._read_model[event.example_id]["is_active"] = False

    # ── Query methods ────────────────────────────────────────
    def get(self, item_id: str) -> Optional[dict]:
        return self._read_model.get(item_id)

    def get_all(self, *, active_only: bool = False) -> List[dict]:
        items = list(self._read_model.values())
        if active_only:
            items = [i for i in items if i.get("is_active", True)]
        return items

    def rebuild(self, events: list) -> None:
        """Replay all events to rebuild the projection from scratch."""
        import asyncio
        for stored in events:
            evt = stored.data
            if isinstance(evt, ExampleCreated):
                asyncio.get_event_loop().run_until_complete(self.handle_created(evt))
            elif isinstance(evt, ExampleUpdated):
                asyncio.get_event_loop().run_until_complete(self.handle_updated(evt))
            elif isinstance(evt, ExampleDeleted):
                asyncio.get_event_loop().run_until_complete(self.handle_deleted(evt))
'''

    # ══════════════════════════════════════════════════════════════
    # Services
    # ══════════════════════════════════════════════════════════════
    files["services/__init__.py"] = ""
    files["services/example_service.py"] = '''\
"""Application service – coordinates aggregates, event store, and bus."""

from __future__ import annotations

import uuid
from typing import List, Optional

from domain.aggregates.example import ExampleAggregate


class ExampleService:
    def __init__(self, event_store, event_bus, snapshot_store, projection):
        self._store = event_store
        self._bus = event_bus
        self._snapshots = snapshot_store
        self._projection = projection

    async def _load_aggregate(self, aggregate_id: str) -> ExampleAggregate:
        """Load aggregate from snapshot + subsequent events."""
        agg = ExampleAggregate()
        snapshot = await self._snapshots.load(aggregate_id)
        after_version = 0

        if snapshot:
            agg = snapshot["aggregate"]
            after_version = snapshot["version"]

        events = await self._store.get_events(aggregate_id, after_version=after_version)
        for stored in events:
            agg.apply_event(stored.data, is_new=False)

        return agg

    async def create(self, name: str, description: str = "") -> dict:
        agg = ExampleAggregate()
        agg_id = str(uuid.uuid4())
        agg.create(agg_id, name, description)

        pending = agg.collect_events()
        await self._store.append_all(agg_id, pending, start_version=1)
        await self._bus.publish_all(pending)

        return self._projection.get(agg_id) or {"id": agg_id}

    async def update(self, aggregate_id: str, name: str = None, description: str = None) -> dict:
        agg = await self._load_aggregate(aggregate_id)
        agg.update(name=name, description=description)

        pending = agg.collect_events()
        await self._store.append_all(aggregate_id, pending, start_version=agg.version - len(pending) + 1)
        await self._bus.publish_all(pending)

        # Optionally snapshot
        if agg.version % 10 == 0:
            await self._snapshots.save(aggregate_id, agg, agg.version)

        return self._projection.get(aggregate_id) or {}

    async def delete(self, aggregate_id: str) -> bool:
        agg = await self._load_aggregate(aggregate_id)
        agg.delete()

        pending = agg.collect_events()
        await self._store.append_all(aggregate_id, pending, start_version=agg.version - len(pending) + 1)
        await self._bus.publish_all(pending)
        return True

    async def get(self, aggregate_id: str) -> Optional[dict]:
        return self._projection.get(aggregate_id)

    async def list_all(self, active_only: bool = False) -> List[dict]:
        return self._projection.get_all(active_only=active_only)
'''

    # ══════════════════════════════════════════════════════════════
    # Infrastructure
    # ══════════════════════════════════════════════════════════════
    files["infrastructure/__init__.py"] = ""

    files["infrastructure/snapshot/__init__.py"] = ""
    files["infrastructure/snapshot/snapshot_store.py"] = '''\
"""Snapshot store – periodically persist aggregate state to speed up loading."""

from __future__ import annotations

from typing import Any, Dict, Optional


class InMemorySnapshotStore:
    def __init__(self):
        self._snapshots: Dict[str, dict] = {}

    async def save(self, aggregate_id: str, aggregate: Any, version: int) -> None:
        self._snapshots[aggregate_id] = {"aggregate": aggregate, "version": version}

    async def load(self, aggregate_id: str) -> Optional[dict]:
        return self._snapshots.get(aggregate_id)
'''

    files["infrastructure/config/__init__.py"] = ""
    files["infrastructure/config/database.py"] = '''\
"""Database / event-store configuration."""

import os


class EventStoreConfig:
    URI: str = os.getenv("EVENT_STORE_URL", "sqlite:///events.sqlite3")
    SNAPSHOT_FREQUENCY: int = int(os.getenv("SNAPSHOT_FREQUENCY", "10"))
'''

    # ══════════════════════════════════════════════════════════════
    # API
    # ══════════════════════════════════════════════════════════════
    files["api/__init__.py"] = ""
    files["api/controllers/__init__.py"] = ""
    files["api/controllers/health_controller.py"] = health_controller()
    files["api/controllers/example_controller.py"] = '''\
"""Example controller – event-sourced CRUD endpoints."""

from hypern import Router, Request, Response

example_router = Router(prefix="/examples")


@example_router.get("/")
async def list_examples(request: Request) -> Response:
    # service = request.app.resolve("example_service")
    # items = await service.list_all()
    return Response(status_code=200, description=[])


@example_router.get("/:id")
async def get_example(request: Request) -> Response:
    # service = request.app.resolve("example_service")
    # item = await service.get(request.params["id"])
    return Response(status_code=200, description={})


@example_router.post("/")
async def create_example(request: Request) -> Response:
    # service = request.app.resolve("example_service")
    # body = request.json()
    # result = await service.create(body["name"], body.get("description", ""))
    return Response(status_code=201, description={"created": True})


@example_router.put("/:id")
async def update_example(request: Request) -> Response:
    # service = request.app.resolve("example_service")
    # body = request.json()
    # result = await service.update(request.params["id"], **body)
    return Response(status_code=200, description={"updated": True})


@example_router.delete("/:id")
async def delete_example(request: Request) -> Response:
    # service = request.app.resolve("example_service")
    # await service.delete(request.params["id"])
    return Response(status_code=204, description="")
'''

    # ── Tests ────────────────────────────────────────────────────
    files["tests/test_event_sourcing.py"] = '''\
"""Unit tests for event-sourced aggregate and service."""

import asyncio
from domain.aggregates.example import ExampleAggregate
from events.definitions.example_events import ExampleCreated


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_aggregate_create_produces_event():
    agg = ExampleAggregate()
    agg.create("ex-1", "Test", "A test")
    events = agg.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], ExampleCreated)
    assert agg.name == "Test"
    assert agg.version == 1


def test_aggregate_replay():
    agg = ExampleAggregate()
    agg.create("ex-1", "Test", "Desc")
    agg.update(name="Updated")
    events = agg.collect_events()

    # Replay on a new aggregate
    replayed = ExampleAggregate()
    replayed.load_from_history(events)
    assert replayed.name == "Updated"
    assert replayed.version == 2


def test_service_create_and_read():
    from events.bus import EventBus
    from events.store.event_store import InMemoryEventStore
    from infrastructure.snapshot.snapshot_store import InMemorySnapshotStore
    from projections.example_projection import ExampleProjection
    from services.example_service import ExampleService

    bus = EventBus()
    store = InMemoryEventStore()
    snapshots = InMemorySnapshotStore()
    projection = ExampleProjection()

    bus.subscribe(ExampleCreated, projection.handle_created)

    svc = ExampleService(event_store=store, event_bus=bus, snapshot_store=snapshots, projection=projection)
    result = _run(svc.create("MyExample", "Desc"))
    assert result["name"] == "MyExample"

    items = _run(svc.list_all())
    assert len(items) == 1
'''

    return files
