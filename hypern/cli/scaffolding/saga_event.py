"""Combined SAGA + Event-Driven / Event Sourcing pattern."""

from __future__ import annotations

from typing import Dict

from ._base import base_files, health_controller

LABEL = "SAGA + Event-Driven / Event Sourcing"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    # Pull in modules from the individual patterns
    from . import event_driven as _ed
    from . import saga as _sg

    ed_files = _ed.generate(name)
    sg_files = _sg.generate(name)

    # ── Entry point ──────────────────────────────────────────────
    files["app.py"] = '''\
"""Application entry point – SAGA + Event-Driven architecture."""

from hypern import Hypern
from config import get_config
from api.controllers.health_controller import health_router
from api.controllers.order_controller import order_router
from api.controllers.example_controller import example_router
from bootstrap import wire_dependencies

config = get_config()

app = Hypern(debug=config.DEBUG)
wire_dependencies(app)

app.use("/", health_router)
app.use("/api", order_router)
app.use("/api", example_router)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    files["bootstrap.py"] = '''\
"""Composition root – wires both saga and event-sourcing infrastructure."""

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
from infrastructure.persistence.in_memory_order_repository import InMemoryOrderRepository
from infrastructure.persistence.in_memory_payment_repository import InMemoryPaymentRepository
from infrastructure.persistence.saga_log_store import InMemorySagaLogStore
from infrastructure.external.payment_client import StubPaymentClient
from infrastructure.external.inventory_client import StubInventoryClient
from infrastructure.external.notification_client import StubNotificationClient
from services.example_service import ExampleService
from services.order_service import OrderService


def wire_dependencies(app) -> None:
    # ── Event sourcing ───────────────────────────────────────
    event_store = InMemoryEventStore()
    snapshot_store = InMemorySnapshotStore()
    projection = ExampleProjection()

    event_bus.subscribe(ExampleCreated, projection.handle_created)
    event_bus.subscribe(ExampleUpdated, projection.handle_updated)
    event_bus.subscribe(ExampleDeleted, projection.handle_deleted)

    event_bus.subscribe(ExampleCreated, on_example_created)
    event_bus.subscribe(ExampleUpdated, on_example_updated)
    event_bus.subscribe(ExampleDeleted, on_example_deleted)

    example_service = ExampleService(
        event_store=event_store,
        event_bus=event_bus,
        snapshot_store=snapshot_store,
        projection=projection,
    )

    # ── Saga infrastructure ──────────────────────────────────
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    saga_log = InMemorySagaLogStore()

    order_service = OrderService(
        order_repo=order_repo,
        payment_repo=payment_repo,
        saga_log=saga_log,
        payment_client=StubPaymentClient(),
        inventory_client=StubInventoryClient(),
        notification_client=StubNotificationClient(),
    )

    app.singleton("example_service", example_service)
    app.singleton("order_service", order_service)
    app.singleton("example_projection", projection)
'''

    # ── Domain (merge both) ──────────────────────────────────────
    # Event-sourced aggregates
    for key in (
        "domain/__init__.py",
        "domain/aggregates/__init__.py",
        "domain/aggregates/base.py",
        "domain/aggregates/example.py",
    ):
        files[key] = ed_files[key]

    # Saga domain models
    for key in (
        "domain/models/__init__.py",
        "domain/models/order.py",
        "domain/models/payment.py",
        "domain/events/__init__.py",
        "domain/events/order_events.py",
        "domain/interfaces/__init__.py",
        "domain/interfaces/order_repository.py",
        "domain/interfaces/payment_repository.py",
    ):
        files[key] = sg_files[key]

    # ── Events (from event-driven) ───────────────────────────────
    for key in (
        "events/__init__.py",
        "events/bus.py",
        "events/definitions/__init__.py",
        "events/definitions/example_events.py",
        "events/handlers/__init__.py",
        "events/handlers/example_handler.py",
        "events/store/__init__.py",
        "events/store/event_store.py",
    ):
        files[key] = ed_files[key]

    # ── Projections ──────────────────────────────────────────────
    files["projections/__init__.py"] = ed_files["projections/__init__.py"]
    files["projections/example_projection.py"] = ed_files["projections/example_projection.py"]

    # ── Sagas (from saga) ────────────────────────────────────────
    for key in (
        "sagas/__init__.py",
        "sagas/base.py",
        "sagas/order_saga.py",
        "sagas/steps/__init__.py",
        "sagas/steps/payment_step.py",
        "sagas/steps/inventory_step.py",
        "sagas/steps/notification_step.py",
    ):
        files[key] = sg_files[key]

    # ── Services (both) ──────────────────────────────────────────
    files["services/__init__.py"] = ""
    files["services/example_service.py"] = ed_files["services/example_service.py"]
    files["services/order_service.py"] = sg_files["services/order_service.py"]

    # ── Infrastructure (merge) ───────────────────────────────────
    files["infrastructure/__init__.py"] = ""
    files["infrastructure/snapshot/__init__.py"] = ed_files["infrastructure/snapshot/__init__.py"]
    files["infrastructure/snapshot/snapshot_store.py"] = ed_files["infrastructure/snapshot/snapshot_store.py"]
    files["infrastructure/persistence/__init__.py"] = ""
    files["infrastructure/persistence/in_memory_order_repository.py"] = sg_files[
        "infrastructure/persistence/in_memory_order_repository.py"
    ]
    files["infrastructure/persistence/in_memory_payment_repository.py"] = sg_files[
        "infrastructure/persistence/in_memory_payment_repository.py"
    ]
    files["infrastructure/persistence/saga_log_store.py"] = sg_files[
        "infrastructure/persistence/saga_log_store.py"
    ]
    files["infrastructure/external/__init__.py"] = ""
    files["infrastructure/external/payment_client.py"] = sg_files["infrastructure/external/payment_client.py"]
    files["infrastructure/external/inventory_client.py"] = sg_files["infrastructure/external/inventory_client.py"]
    files["infrastructure/external/notification_client.py"] = sg_files["infrastructure/external/notification_client.py"]
    files["infrastructure/config/__init__.py"] = ""
    files["infrastructure/config/database.py"] = ed_files.get(
        "infrastructure/config/database.py",
        sg_files.get("infrastructure/config/database.py", ""),
    )

    # ── API ──────────────────────────────────────────────────────
    files["api/__init__.py"] = ""
    files["api/controllers/__init__.py"] = ""
    files["api/controllers/health_controller.py"] = health_controller()
    files["api/controllers/order_controller.py"] = sg_files["api/controllers/order_controller.py"]
    files["api/controllers/example_controller.py"] = ed_files["api/controllers/example_controller.py"]

    # ── Tests (merge) ────────────────────────────────────────────
    files["tests/test_saga_orchestrator.py"] = sg_files["tests/test_saga_orchestrator.py"]
    files["tests/test_event_sourcing.py"] = ed_files["tests/test_event_sourcing.py"]

    return files
