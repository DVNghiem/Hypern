import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from queue import PriorityQueue
from typing import Any, Dict

from hypern.hypern import Request, Response
from hypern.response import JSONResponse
from hypern.routing import HTTPEndpoint
from hypern.logging import logger


@dataclass(order=True)
class PrioritizedRequest:
    priority: int
    timestamp: float = field(default_factory=time.time)
    request: Request | None = field(default=None, compare=False)
    future: asyncio.Future = field(compare=False, default_factory=asyncio.Future)


class QueuedHTTPEndpoint(HTTPEndpoint):
    """
    HTTPEndpoint with request queuing capabilities for high-load scenarios.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Queue configuration
        self._max_concurrent = kwargs.get("max_concurrent", 100)
        self._queue_size = kwargs.get("queue_size", 1000)
        self._request_timeout = kwargs.get("request_timeout", 30)

        # Initialize queuing system
        self._request_queue: PriorityQueue = PriorityQueue(maxsize=self._queue_size)
        self._active_requests = 0
        self._lock = None  # Will be initialized when needed
        self._request_semaphore = None  # Will be initialized when needed
        self._shutdown = False
        self._queue_task = None
        self._initialized = False

        # Metrics
        self._metrics = {"processed_requests": 0, "queued_requests": 0, "rejected_requests": 0, "avg_wait_time": 0.0}

        self._fully_message = "Request queue is full"

    async def _initialize(self):
        """Initialize async components when first request arrives"""
        if not self._initialized:
            self._lock = asyncio.Lock()
            self._request_semaphore = asyncio.Semaphore(self._max_concurrent)
            self._queue_task = asyncio.create_task(self._process_queue())
            self._initialized = True

    @asynccontextmanager
    async def _queue_context(self, request: Request, priority: int = 10):
        """Context manager for handling request queuing."""
        if self._shutdown:
            raise RuntimeError("Endpoint is shutting down")

        await self._initialize()  # Ensure async components are initialized

        request_future = asyncio.Future()
        prioritized_request = PrioritizedRequest(priority=priority, timestamp=time.time(), request=request, future=request_future)

        try:
            if self._request_queue.qsize() >= self._queue_size:
                self._metrics["rejected_requests"] += 1
                raise asyncio.QueueFull(self._fully_message)

            await self._enqueue_request(prioritized_request)
            yield await asyncio.wait_for(request_future, timeout=self._request_timeout)

        except asyncio.TimeoutError:
            self._metrics["rejected_requests"] += 1
            raise asyncio.TimeoutError("Request timed out while waiting in queue")
        finally:
            if not request_future.done():
                request_future.cancel()

    async def _enqueue_request(self, request: PrioritizedRequest):
        """Add request to the queue."""
        try:
            self._request_queue.put_nowait(request)
            self._metrics["queued_requests"] += 1
        except asyncio.QueueFull:
            self._metrics["rejected_requests"] += 1
            raise asyncio.QueueFull(self._fully_message)

    async def _process_queue(self):
        """Background task to process queued requests."""
        while not self._shutdown:
            try:
                if not self._request_queue.empty():
                    async with self._lock:
                        if self._active_requests >= self._max_concurrent:
                            await asyncio.sleep(0.1)
                            continue

                        request = self._request_queue.get_nowait()
                        wait_time = time.time() - request.timestamp
                        self._metrics["avg_wait_time"] = (self._metrics["avg_wait_time"] * self._metrics["processed_requests"] + wait_time) / (
                            self._metrics["processed_requests"] + 1
                        )

                        if not request.future.cancelled():
                            self._active_requests += 1
                            asyncio.create_task(self._handle_request(request))

                await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"Error processing queue: {e}")
                await asyncio.sleep(1)

    async def _handle_request(self, request: PrioritizedRequest):
        """Handle individual request."""
        try:
            async with self._request_semaphore:
                response = await super().dispatch(request.request, {})
                if not request.future.done():
                    request.future.set_result(response)
        except Exception as e:
            if not request.future.done():
                request.future.set_exception(e)
        finally:
            self._active_requests -= 1
            self._metrics["processed_requests"] += 1
            self._metrics["queued_requests"] -= 1

    async def dispatch(self, request: Request) -> Response:
        """
        Enhanced dispatch method with request queuing.
        """
        try:
            priority = self._get_request_priority(request)

            async with self._queue_context(request, priority) as response:
                return response

        except asyncio.QueueFull:
            return JSONResponse(description={"error": "Server too busy", "message": self._fully_message, "retry_after": 5}, status_code=503)
        except asyncio.TimeoutError:
            return JSONResponse(
                description={
                    "error": "Request timeout",
                    "message": "Request timed out while waiting in queue",
                },
                status_code=504,
            )
        except Exception as e:
            return JSONResponse(description={"error": "Internal server error", "message": str(e)}, status_code=500)

    def _get_request_priority(self, request: Request) -> int:
        """
        Determine request priority. Override this method to implement
        custom priority logic.
        """
        if request.method == "GET":
            return 5
        return 10

    async def shutdown(self):
        """Gracefully shutdown the endpoint."""
        self._shutdown = True
        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass

    def get_metrics(self) -> Dict[str, Any]:
        """Get current queue metrics."""
        return {**self._metrics, "current_queue_size": self._request_queue.qsize(), "active_requests": self._active_requests}
