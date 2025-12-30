# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, TypeVar

import psutil
from typing_extensions import Annotated, Doc

from hypern.hypern import Router, Server, SocketHeld
from hypern.hypern import Route

AppType = TypeVar("AppType", bound="Hypern")


@dataclass
class ThreadConfig:
    workers: int
    max_blocking_threads: int


class ThreadConfigurator:
    def __init__(self):
        self._cpu_count = psutil.cpu_count(logical=True)
        self._memory_gb = psutil.virtual_memory().total / (1024**3)

    def get_config(self, concurrent_requests: int = None) -> ThreadConfig:
        """Calculate optimal thread configuration based on system resources."""
        workers = max(2, self._cpu_count)

        if concurrent_requests:
            max_blocking = min(max(32, concurrent_requests * 2), workers * 4, int(self._memory_gb * 8))
        else:
            max_blocking = min(workers * 4, int(self._memory_gb * 8), 256)

        return ThreadConfig(workers=workers, max_blocking_threads=max_blocking)


class Hypern:
    def __init__(
        self: AppType,
        routes: Annotated[
            List[Route] | None,
            Doc(
                """
                A list of routes to serve incoming HTTP and WebSocket requests.
                You can define routes using the `Route` class from `Hypern.routing`.
                **Example**
                ---
                ```python
                class DefaultRoute(HTTPEndpoint):
                    async def get(self, global_dependencies):
                        return PlainTextResponse("/hello")
                Route("/test", DefaultRoute)

                # Or you can define routes using the decorator
                route = Route("/test)
                @route.get("/route")
                def def_get():
                    return PlainTextResponse("Hello")
                ```
                """
            ),
        ] = None,
        
    ) -> None:
        self.router = Router(path="/")
        self.response_headers = {}
        self.start_up_handler = None
        self.shutdown_handler = None
        self.thread_config = ThreadConfigurator().get_config()

        if routes is not None:
            self.router.extend_route(routes)
    
    def start(
        self,
        host='0.0.0.0',
        port=5000,
        workers=1,
        max_blocking_threads=1,
        max_connections=10000,
    ):
        """
        Starts the server with the specified configuration.
        Raises:
            ValueError: If an invalid port number is entered when prompted.

        """
        server = Server()
        server.set_router(router=self.router)
        socket = SocketHeld(host, port)
        server.start(socket=socket, workers=workers, max_blocking_threads=max_blocking_threads, max_connections=max_connections)

    def add_route(self, method: str, endpoint: str, handler: Callable[..., Any]):
        """
        Adds a route to the router.

        Args:
            method (str): The HTTP method for the route (e.g., GET, POST).
            endpoint (str): The endpoint path for the route.
            handler (Callable[..., Any]): The function that handles requests to the route.

        """
        route = Route(path=endpoint, function=handler, method=method.upper())
        self.router.add_route(route=route)

    def get(self, path: str):
        def decorator(handler: Callable[..., Any]):
            self.add_route("GET", path, handler)
            return handler
        return decorator

    def post(self, path: str):
        def decorator(handler: Callable[..., Any]):
            self.add_route("POST", path, handler)
            return handler
        return decorator

    def put(self, path: str):
        def decorator(handler: Callable[..., Any]):
            self.add_route("PUT", path, handler)
            return handler
        return decorator

    def delete(self, path: str):
        def decorator(handler: Callable[..., Any]):
            self.add_route("DELETE", path, handler)
            return handler
        return decorator
