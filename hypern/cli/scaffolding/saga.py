"""SAGA pattern – expanded scaffolding.

Structure:
  domain/         – models, repository interfaces, domain events
  sagas/          – orchestrator, step definitions, saga registry
  services/       – application services that compose sagas
  infrastructure/ – persistence (saga log, repositories), external adapters
  api/            – HTTP controllers
"""

from __future__ import annotations

from typing import Dict

from ._base import base_files, health_controller

LABEL = "SAGA Pattern"


def generate(name: str) -> Dict[str, str]:
    files = base_files(name, LABEL)

    # ── Entry point ──────────────────────────────────────────────
    files["app.py"] = '''\
"""Application entry point – SAGA pattern."""

from hypern import Hypern
from config import get_config
from api.controllers.health_controller import health_router
from api.controllers.order_controller import order_router
from bootstrap import wire_dependencies

config = get_config()

app = Hypern(debug=config.DEBUG)
wire_dependencies(app)

app.use("/", health_router)
app.use("/api", order_router)


if __name__ == "__main__":
    app.start(host=config.HOST, port=config.PORT, num_processes=config.WORKERS)
'''

    files["bootstrap.py"] = '''\
"""Composition root – wires saga infrastructure."""

from infrastructure.persistence.in_memory_order_repository import InMemoryOrderRepository
from infrastructure.persistence.in_memory_payment_repository import InMemoryPaymentRepository
from infrastructure.persistence.saga_log_store import InMemorySagaLogStore
from infrastructure.external.payment_client import StubPaymentClient
from infrastructure.external.inventory_client import StubInventoryClient
from infrastructure.external.notification_client import StubNotificationClient
from services.order_service import OrderService


def wire_dependencies(app) -> None:
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    saga_log = InMemorySagaLogStore()

    payment_client = StubPaymentClient()
    inventory_client = StubInventoryClient()
    notification_client = StubNotificationClient()

    service = OrderService(
        order_repo=order_repo,
        payment_repo=payment_repo,
        saga_log=saga_log,
        payment_client=payment_client,
        inventory_client=inventory_client,
        notification_client=notification_client,
    )
    app.singleton("order_service", service)
'''

    # ══════════════════════════════════════════════════════════════
    # Domain
    # ══════════════════════════════════════════════════════════════
    files["domain/__init__.py"] = ""
    files["domain/models/__init__.py"] = ""
    files["domain/models/order.py"] = '''\
"""Order aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class OrderStatus(Enum):
    PENDING = "pending"
    PAYMENT_PROCESSING = "payment_processing"
    PAYMENT_CONFIRMED = "payment_confirmed"
    INVENTORY_RESERVED = "inventory_reserved"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    COMPENSATION_IN_PROGRESS = "compensation_in_progress"


@dataclass
class OrderItem:
    product_id: str
    quantity: int
    unit_price: float


@dataclass
class Order:
    id: Optional[str] = None
    customer_id: str = ""
    items: List[OrderItem] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    total: float = 0.0
    payment_id: Optional[str] = None
    failure_reason: Optional[str] = None

    def calculate_total(self) -> float:
        self.total = sum(i.quantity * i.unit_price for i in self.items)
        return self.total

    def transition(self, new_status: OrderStatus) -> None:
        self.status = new_status
'''

    files["domain/models/payment.py"] = '''\
"""Payment model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PaymentStatus(Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    FAILED = "failed"


@dataclass
class Payment:
    id: Optional[str] = None
    order_id: str = ""
    amount: float = 0.0
    status: PaymentStatus = PaymentStatus.PENDING
'''

    files["domain/events/__init__.py"] = ""
    files["domain/events/order_events.py"] = '''\
"""Domain events emitted during order saga."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OrderCreated:
    order_id: str
    customer_id: str
    total: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PaymentAuthorized:
    order_id: str
    payment_id: str
    amount: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class InventoryReserved:
    order_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OrderCompleted:
    order_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OrderCancelled:
    order_id: str
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
'''

    files["domain/interfaces/__init__.py"] = ""
    files["domain/interfaces/order_repository.py"] = '''\
"""Repository interface for orders."""

from abc import ABC, abstractmethod
from typing import List, Optional

from domain.models.order import Order


class IOrderRepository(ABC):
    @abstractmethod
    async def save(self, order: Order) -> Order: ...

    @abstractmethod
    async def find_by_id(self, order_id: str) -> Optional[Order]: ...

    @abstractmethod
    async def find_all(self) -> List[Order]: ...
'''

    files["domain/interfaces/payment_repository.py"] = '''\
"""Repository interface for payments."""

from abc import ABC, abstractmethod
from typing import Optional

from domain.models.payment import Payment


class IPaymentRepository(ABC):
    @abstractmethod
    async def save(self, payment: Payment) -> Payment: ...

    @abstractmethod
    async def find_by_order_id(self, order_id: str) -> Optional[Payment]: ...
'''

    # ══════════════════════════════════════════════════════════════
    # Sagas
    # ══════════════════════════════════════════════════════════════
    files["sagas/__init__.py"] = ""

    files["sagas/base.py"] = '''\
"""Generic SAGA orchestrator with step-by-step execution and compensation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional
import uuid


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    name: str
    action: Callable[..., Coroutine]
    compensation: Callable[..., Coroutine]
    status: StepStatus = StepStatus.PENDING
    error: Optional[str] = None


@dataclass
class SagaResult:
    saga_id: str
    success: bool
    context: Dict[str, Any]
    failed_step: Optional[str] = None
    error: Optional[str] = None


class SagaOrchestrator:
    """Execute a sequence of steps; automatically compensate on failure."""

    def __init__(self, saga_id: Optional[str] = None):
        self.saga_id = saga_id or str(uuid.uuid4())
        self.steps: List[SagaStep] = []
        self._log_callback: Optional[Callable] = None

    def add_step(
        self,
        name: str,
        action: Callable[..., Coroutine],
        compensation: Callable[..., Coroutine],
    ) -> "SagaOrchestrator":
        self.steps.append(SagaStep(name=name, action=action, compensation=compensation))
        return self

    def on_log(self, callback: Callable) -> "SagaOrchestrator":
        """Register a logging callback: callback(saga_id, step_name, status)."""
        self._log_callback = callback
        return self

    async def _log(self, step_name: str, status: str) -> None:
        if self._log_callback:
            await self._log_callback(self.saga_id, step_name, status)

    async def execute(self, context: Dict[str, Any] | None = None) -> SagaResult:
        context = context or {}
        completed: List[SagaStep] = []

        for step in self.steps:
            try:
                step.status = StepStatus.RUNNING
                await self._log(step.name, "running")
                result = await step.action(context)
                context[step.name] = result
                step.status = StepStatus.COMPLETED
                await self._log(step.name, "completed")
                completed.append(step)
            except Exception as exc:
                step.status = StepStatus.FAILED
                step.error = str(exc)
                await self._log(step.name, f"failed: {exc}")

                # Compensate in reverse order
                for comp_step in reversed(completed):
                    try:
                        comp_step.status = StepStatus.COMPENSATING
                        await self._log(comp_step.name, "compensating")
                        await comp_step.compensation(context)
                        comp_step.status = StepStatus.COMPENSATED
                        await self._log(comp_step.name, "compensated")
                    except Exception as comp_exc:
                        await self._log(comp_step.name, f"compensation_failed: {comp_exc}")

                return SagaResult(
                    saga_id=self.saga_id,
                    success=False,
                    context=context,
                    failed_step=step.name,
                    error=str(exc),
                )

        return SagaResult(saga_id=self.saga_id, success=True, context=context)
'''

    files["sagas/order_saga.py"] = '''\
"""Create-order saga – orchestrates payment, inventory, notification."""

from sagas.base import SagaOrchestrator
from sagas.steps.payment_step import authorize_payment, refund_payment
from sagas.steps.inventory_step import reserve_inventory, release_inventory
from sagas.steps.notification_step import send_confirmation, noop_compensation


def build_create_order_saga(
    saga_id: str,
    payment_client,
    inventory_client,
    notification_client,
    log_callback=None,
) -> SagaOrchestrator:
    """Build and return a fully-configured create-order saga."""
    saga = SagaOrchestrator(saga_id=saga_id)

    saga.add_step(
        "authorize_payment",
        lambda ctx: authorize_payment(ctx, payment_client),
        lambda ctx: refund_payment(ctx, payment_client),
    )
    saga.add_step(
        "reserve_inventory",
        lambda ctx: reserve_inventory(ctx, inventory_client),
        lambda ctx: release_inventory(ctx, inventory_client),
    )
    saga.add_step(
        "send_confirmation",
        lambda ctx: send_confirmation(ctx, notification_client),
        noop_compensation,
    )

    if log_callback:
        saga.on_log(log_callback)

    return saga
'''

    files["sagas/steps/__init__.py"] = ""
    files["sagas/steps/payment_step.py"] = '''\
"""Saga step – payment authorization / refund."""


async def authorize_payment(context: dict, payment_client) -> dict:
    order = context["order"]
    result = await payment_client.authorize(order_id=order.id, amount=order.total)
    return result


async def refund_payment(context: dict, payment_client) -> None:
    payment_info = context.get("authorize_payment")
    if payment_info and payment_info.get("payment_id"):
        await payment_client.refund(payment_id=payment_info["payment_id"])
'''

    files["sagas/steps/inventory_step.py"] = '''\
"""Saga step – inventory reservation / release."""


async def reserve_inventory(context: dict, inventory_client) -> dict:
    order = context["order"]
    items = [{"product_id": i.product_id, "quantity": i.quantity} for i in order.items]
    result = await inventory_client.reserve(order_id=order.id, items=items)
    return result


async def release_inventory(context: dict, inventory_client) -> None:
    reservation = context.get("reserve_inventory")
    if reservation and reservation.get("reservation_id"):
        await inventory_client.release(reservation_id=reservation["reservation_id"])
'''

    files["sagas/steps/notification_step.py"] = '''\
"""Saga step – send order confirmation."""


async def send_confirmation(context: dict, notification_client) -> dict:
    order = context["order"]
    await notification_client.send(
        recipient=order.customer_id,
        message=f"Order {order.id} confirmed!",
    )
    return {"notified": True}


async def noop_compensation(context: dict) -> None:
    """Notifications are fire-and-forget – nothing to compensate."""
    pass
'''

    # ══════════════════════════════════════════════════════════════
    # Services
    # ══════════════════════════════════════════════════════════════
    files["services/__init__.py"] = ""
    files["services/order_service.py"] = '''\
"""Order application service – composes saga for order creation."""

from __future__ import annotations

import uuid
from typing import List, Optional

from domain.models.order import Order, OrderItem, OrderStatus
from domain.models.payment import Payment, PaymentStatus
from domain.interfaces.order_repository import IOrderRepository
from domain.interfaces.payment_repository import IPaymentRepository
from sagas.order_saga import build_create_order_saga


class OrderService:
    def __init__(
        self,
        order_repo: IOrderRepository,
        payment_repo: IPaymentRepository,
        saga_log,
        payment_client,
        inventory_client,
        notification_client,
    ):
        self._order_repo = order_repo
        self._payment_repo = payment_repo
        self._saga_log = saga_log
        self._payment = payment_client
        self._inventory = inventory_client
        self._notification = notification_client

    async def create_order(self, customer_id: str, items: List[dict]) -> Order:
        order = Order(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            items=[OrderItem(**i) for i in items],
        )
        order.calculate_total()
        order = await self._order_repo.save(order)

        saga = build_create_order_saga(
            saga_id=f"order-{order.id}",
            payment_client=self._payment,
            inventory_client=self._inventory,
            notification_client=self._notification,
            log_callback=self._saga_log.log,
        )

        result = await saga.execute({"order": order})

        if result.success:
            pay_info = result.context.get("authorize_payment", {})
            payment = Payment(
                id=pay_info.get("payment_id", str(uuid.uuid4())),
                order_id=order.id,
                amount=order.total,
                status=PaymentStatus.AUTHORIZED,
            )
            await self._payment_repo.save(payment)
            order.payment_id = payment.id
            order.transition(OrderStatus.COMPLETED)
        else:
            order.transition(OrderStatus.CANCELLED)
            order.failure_reason = result.error

        await self._order_repo.save(order)
        return order

    async def get_order(self, order_id: str) -> Optional[Order]:
        return await self._order_repo.find_by_id(order_id)

    async def list_orders(self) -> List[Order]:
        return await self._order_repo.find_all()
'''

    # ══════════════════════════════════════════════════════════════
    # Infrastructure
    # ══════════════════════════════════════════════════════════════
    files["infrastructure/__init__.py"] = ""

    files["infrastructure/persistence/__init__.py"] = ""
    files["infrastructure/persistence/in_memory_order_repository.py"] = '''\
"""In-memory order repository."""

from typing import List, Optional

from domain.models.order import Order
from domain.interfaces.order_repository import IOrderRepository


class InMemoryOrderRepository(IOrderRepository):
    def __init__(self):
        self._store: dict[str, Order] = {}

    async def save(self, order: Order) -> Order:
        self._store[order.id] = order
        return order

    async def find_by_id(self, order_id: str) -> Optional[Order]:
        return self._store.get(order_id)

    async def find_all(self) -> List[Order]:
        return list(self._store.values())
'''

    files["infrastructure/persistence/in_memory_payment_repository.py"] = '''\
"""In-memory payment repository."""

from typing import Optional

from domain.models.payment import Payment
from domain.interfaces.payment_repository import IPaymentRepository


class InMemoryPaymentRepository(IPaymentRepository):
    def __init__(self):
        self._store: dict[str, Payment] = {}

    async def save(self, payment: Payment) -> Payment:
        self._store[payment.id] = payment
        return payment

    async def find_by_order_id(self, order_id: str) -> Optional[Payment]:
        for p in self._store.values():
            if p.order_id == order_id:
                return p
        return None
'''

    files["infrastructure/persistence/saga_log_store.py"] = '''\
"""Persist saga execution logs for recovery / observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class SagaLogEntry:
    saga_id: str
    step_name: str
    status: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class InMemorySagaLogStore:
    def __init__(self):
        self._logs: List[SagaLogEntry] = []

    async def log(self, saga_id: str, step_name: str, status: str) -> None:
        self._logs.append(SagaLogEntry(saga_id=saga_id, step_name=step_name, status=status))

    async def get_logs(self, saga_id: str) -> List[SagaLogEntry]:
        return [e for e in self._logs if e.saga_id == saga_id]

    async def get_all_logs(self) -> List[SagaLogEntry]:
        return list(self._logs)
'''

    files["infrastructure/external/__init__.py"] = ""
    files["infrastructure/external/payment_client.py"] = '''\
"""Stub payment gateway – replace with real integration."""

import uuid


class StubPaymentClient:
    async def authorize(self, order_id: str, amount: float) -> dict:
        return {"payment_id": str(uuid.uuid4()), "status": "authorized", "amount": amount}

    async def refund(self, payment_id: str) -> dict:
        return {"payment_id": payment_id, "status": "refunded"}
'''

    files["infrastructure/external/inventory_client.py"] = '''\
"""Stub inventory service – replace with real integration."""

import uuid


class StubInventoryClient:
    async def reserve(self, order_id: str, items: list) -> dict:
        return {"reservation_id": str(uuid.uuid4()), "status": "reserved"}

    async def release(self, reservation_id: str) -> dict:
        return {"reservation_id": reservation_id, "status": "released"}
'''

    files["infrastructure/external/notification_client.py"] = '''\
"""Stub notification service – replace with real integration."""


class StubNotificationClient:
    async def send(self, recipient: str, message: str) -> bool:
        print(f"[Notification] To {recipient}: {message}")
        return True
'''

    # ══════════════════════════════════════════════════════════════
    # API
    # ══════════════════════════════════════════════════════════════
    files["api/__init__.py"] = ""
    files["api/controllers/__init__.py"] = ""
    files["api/controllers/health_controller.py"] = health_controller()
    files["api/controllers/order_controller.py"] = '''\
"""Order controller – REST endpoints backed by saga-orchestrated service."""

from hypern import Router, Request, Response

order_router = Router(prefix="/orders")


@order_router.get("/")
async def list_orders(request: Request) -> Response:
    # service = request.app.resolve("order_service")
    # orders = await service.list_orders()
    return Response(status_code=200, description=[])


@order_router.get("/:id")
async def get_order(request: Request) -> Response:
    # service = request.app.resolve("order_service")
    # order = await service.get_order(request.params["id"])
    return Response(status_code=200, description={})


@order_router.post("/")
async def create_order(request: Request) -> Response:
    """
    Expected body:
    {
        "customer_id": "cust-1",
        "items": [
            {"product_id": "prod-1", "quantity": 2, "unit_price": 29.99}
        ]
    }
    """
    # service = request.app.resolve("order_service")
    # body = request.json()
    # order = await service.create_order(body["customer_id"], body["items"])
    return Response(status_code=201, description={"created": True})
'''

    # ── Tests ────────────────────────────────────────────────────
    files["tests/test_saga_orchestrator.py"] = '''\
"""Unit tests for the generic SagaOrchestrator."""

import asyncio
from sagas.base import SagaOrchestrator


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _ok_step(ctx):
    return {"done": True}


async def _noop(ctx):
    pass


async def _failing_step(ctx):
    raise RuntimeError("boom")


def test_saga_success():
    saga = SagaOrchestrator()
    saga.add_step("step1", _ok_step, _noop)
    saga.add_step("step2", _ok_step, _noop)
    result = _run(saga.execute())
    assert result.success is True
    assert "step1" in result.context


def test_saga_compensation_on_failure():
    compensated = []

    async def track_comp(ctx):
        compensated.append("step1")

    saga = SagaOrchestrator()
    saga.add_step("step1", _ok_step, track_comp)
    saga.add_step("step2", _failing_step, _noop)
    result = _run(saga.execute())
    assert result.success is False
    assert result.failed_step == "step2"
    assert "step1" in compensated
'''

    return files
