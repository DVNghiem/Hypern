import asyncio
import logging
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from typing import Callable, Dict, List

from celery import Celery
from celery.result import AsyncResult
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    task_failure,
    task_postrun,
    task_prerun,
    worker_ready,
    worker_shutdown,
)
from kombu import Exchange, Queue


class Worker(Celery):
    def __init__(
        self,
        main: str = None,
        broker_url: str = None,
        result_backend: str = "rpc://",
        queues: Dict[str, Dict] = None,
        task_routes: Dict[str, str] = None,
        imports: List[str] = None,
        **kwargs,
    ):
        super().__init__(main, **kwargs)

        self._executor = ThreadPoolExecutor()
        self._task_timings = {}

        self.default_exchange = Exchange("default", type="direct")
        self.priority_exchange = Exchange("priority", type="direct")

        default_queues = {
            "default": {"exchange": self.default_exchange, "routing_key": "default"},
            "high_priority": {"exchange": self.priority_exchange, "routing_key": "high"},
            "low_priority": {"exchange": self.priority_exchange, "routing_key": "low"},
        }
        if queues:
            default_queues.update(queues)

        self._queues = {
            name: Queue(
                name,
                exchange=config.get("exchange", self.default_exchange),
                routing_key=config.get("routing_key", name),
                queue_arguments=config.get("arguments", {}),
            )
            for name, config in default_queues.items()
        }

        self.conf.update(
            broker_url=broker_url,
            result_backend=result_backend,
            # Worker Pool Configuration
            worker_pool="solo",
            worker_pool_restarts=True,
            broker_connection_retry_on_startup=True,
            # Worker Configuration
            worker_prefetch_multiplier=1,
            worker_max_tasks_per_child=1000,
            worker_concurrency=os.cpu_count(),
            # Task Settings
            task_acks_late=True,
            task_reject_on_worker_lost=True,
            task_time_limit=3600,
            task_soft_time_limit=3000,
            task_default_retry_delay=300,
            task_max_retries=3,
            # Memory Management
            worker_max_memory_per_child=200000,  # 200MB
            # Task Routing
            task_routes=task_routes,
            task_queues=list(self._queues.values()),
            # Performance Settings
            task_compression="gzip",
            result_compression="gzip",
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            imports=imports,
            task_default_exchange=self.default_exchange.name,
            task_default_routing_key="default",
        )

        self._setup_signals()

    def _setup_signals(self):
        @worker_ready.connect
        def on_worker_ready(sender, **kwargs):
            self.logger.info(f"Worker {sender.hostname} is ready")

        @worker_shutdown.connect
        def on_worker_shutdown(sender, **kwargs):
            self.logger.info(f"Worker {sender.hostname} is shutting down")
            self._executor.shutdown(wait=True)

        @task_prerun.connect
        def task_prerun_handler(task_id, task, *args, **kwargs):
            self._task_timings[task_id] = {"start": time.time()}
            self.logger.info(f"Task {task.name}[{task_id}] started")

        @task_postrun.connect
        def task_postrun_handler(task_id, task, *args, retval=None, **kwargs):
            if task_id in self._task_timings:
                start_time = self._task_timings[task_id]["start"]
                duration = time.time() - start_time
                self.logger.info(f"Task {task.name}[{task_id}] completed in {duration:.2f}s")
                del self._task_timings[task_id]

        @task_failure.connect
        def task_failure_handler(task_id, exc, task, *args, **kwargs):
            self.logger.error(f"Task {task.name}[{task_id}] failed: {exc}\n{traceback.format_exc()}")

        @after_setup_logger.connect
        def setup_celery_logger(logger, *args, **kwargs):
            existing_logger = logging.getLogger("hypern")
            logger.handlers = existing_logger.handlers
            logger.filters = existing_logger.filters
            logger.level = existing_logger.level

        @after_setup_task_logger.connect
        def setup_task_logger(logger, *args, **kwargs):
            existing_logger = logging.getLogger("hypern")
            logger.handlers = existing_logger.handlers
            logger.filters = existing_logger.filters
            logger.level = existing_logger.level

    def add_task_routes(self, routes: Dict[str, str]) -> None:
        """
        Example:
            app.add_task_routes({
                'tasks.email.*': 'email_queue',
                'tasks.payment.process': 'payment_queue',
                'tasks.high_priority.*': 'high_priority'
            })
        """
        for task_pattern, queue in routes.items():
            self.add_task_route(task_pattern, queue)

    def add_task_route(self, task_pattern: str, queue: str) -> None:
        """
        Add a task route to the Celery app

        Example:
            app.add_task_route('tasks.email.send', 'email_queue')
            app.add_task_route('tasks.payment.*', 'payment_queue')
        """
        if queue not in self._queues:
            raise ValueError(f"Queue '{queue}' does not exist. Create it first using create_queue()")

        self._task_route_mapping[task_pattern] = queue

        # Update Celery task routes
        routes = self.conf.task_routes or {}
        routes[task_pattern] = {"queue": queue}
        self.conf.task_routes = routes

        self.logger.info(f"Added route: {task_pattern} -> {queue}")

    def task(self, *args, **opts):
        """
        Decorator modified to support sync and async functions
        """
        base_task = Celery.task.__get__(self)

        def decorator(func):
            is_async = asyncio.iscoroutinefunction(func)

            if is_async:

                @wraps(func)
                async def async_wrapper(*fargs, **fkwargs):
                    return await func(*fargs, **fkwargs)

                @base_task(*args, **opts)
                def wrapped(*fargs, **fkwargs):
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        return loop.run_until_complete(async_wrapper(*fargs, **fkwargs))
                    finally:
                        loop.close()

                return wrapped
            else:
                return base_task(*args, **opts)(func)

        return decorator

    async def async_send_task(self, task_name: str, *args, **kwargs) -> AsyncResult:
        """
        Version of send_task() that is async
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, partial(self.send_task, task_name, args=args, kwargs=kwargs))

    async def async_result(self, task_id: str) -> Dict:
        """
        Get the result of a task asynchronously
        """
        async_result = self.AsyncResult(task_id)
        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            self._executor,
            lambda: {
                "task_id": task_id,
                "status": async_result.status,
                "result": async_result.result,
                "traceback": async_result.traceback,
                "date_done": async_result.date_done,
            },
        )
        return result

    def get_queue_length(self, queue_name: str) -> int:
        """
        Get the number of messages in a queue
        """
        with self.connection_or_acquire() as conn:
            channel = conn.channel()
            queue = Queue(queue_name, channel=channel)
            return queue.queue_declare(passive=True).message_count

    async def chain_tasks(self, tasks: list) -> AsyncResult:
        """
        Function to chain multiple tasks together
        """
        chain = tasks[0]
        for task in tasks[1:]:
            chain = chain | task
        return await self.adelay_task(chain)

    def register_task_middleware(self, middleware: Callable):
        """
        Register a middleware function to be called before each task
        """

        def task_middleware(task):
            @wraps(task)
            def _wrapped(*args, **kwargs):
                return middleware(task, *args, **kwargs)

            return _wrapped

        self.task = task_middleware(self.task)

    def monitor_task(self, task_id: str) -> dict:
        """
        Get monitoring data for a task
        """
        result = self.AsyncResult(task_id)
        timing_info = self._task_timings.get(task_id, {})

        monitoring_data = {
            "task_id": task_id,
            "status": result.status,
            "start_time": timing_info.get("start"),
            "duration": time.time() - timing_info["start"] if timing_info.get("start") else None,
            "result": result.result if result.ready() else None,
            "traceback": result.traceback,
        }

        return monitoring_data
