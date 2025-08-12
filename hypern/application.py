# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, TypeVar

import psutil
from typing_extensions import Annotated, Doc

from hypern.hypern import Router, Server
from hypern.hypern import Route
from hypern.processpool import run_processes

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

        self.router.extend_route(routes)
    
    def start(
        self,
        host='0.0.0.0',
        port=5000,
        workers=1,
        processes=1,
        max_blocking_threads=1,
        reload=False,
    ):
        """
        Starts the server with the specified configuration.
        Raises:
            ValueError: If an invalid port number is entered when prompted.

        """
        server = Server()
        server.set_router(router=self.router)


        run_processes(
            server=server,
            host=host,
            port=port,
            workers=workers,
            processes=processes,
            max_blocking_threads=max_blocking_threads,
            reload=reload,
        )

    def add_route(self, method: str, endpoint: str, handler: Callable[..., Any]):
        """
        Adds a route to the router.

        Args:
            method (HTTPMethod): The HTTP method for the route (e.g., GET, POST).
            endpoint (str): The endpoint path for the route.
            handler (Callable[..., Any]): The function that handles requests to the route.

        """
        route = Route(path=endpoint, function=handler, method=method.name)
        self.router.add_route(route=route)
