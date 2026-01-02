# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Callable, List, TypeVar
from typing_extensions import Annotated, Doc

from hypern.hypern import Router, Server, SocketHeld
from hypern.hypern import Route

AppType = TypeVar("AppType", bound="Hypern")


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

    def start_with_fd(
        self,
        fd: int,
        host='0.0.0.0',
        port=5000,
        workers=1,
        max_blocking_threads=1,
        max_connections=10000,
    ):
        """
        Starts the server using an existing socket file descriptor.
        This is used for multiprocess worker mode where the parent
        creates a shared socket and passes the fd to child processes.
        """
        server = Server()
        server.set_router(router=self.router)
        socket = SocketHeld.from_fd(fd, host, port)
        server.start(socket=socket, workers=workers, max_blocking_threads=max_blocking_threads, max_connections=max_connections)

    def start_multiprocess(
        self,
        host='0.0.0.0',
        port=5000,
        num_processes=8,
        tokio_workers_per_process=1,
        max_blocking_threads=16,
        max_connections=10000,
    ):
        """
        Starts the server in multiprocess mode using pure Rust fork().
        Each worker process has its own Python interpreter and GIL,
        allowing true parallel execution without GIL contention.
        
        Args:
            host: Host address to bind to
            port: Port to listen on  
            num_processes: Number of worker processes (typically = CPU cores)
            tokio_workers_per_process: Tokio async workers per process
            max_blocking_threads: Max blocking threads for Python execution per process
            max_connections: Maximum concurrent connections per process
        """
        server = Server()
        server.set_router(router=self.router)
        server.start_multiprocess(
            host=host,
            port=port,
            num_processes=num_processes,
            tokio_workers_per_process=tokio_workers_per_process,
            max_blocking_threads=max_blocking_threads,
            max_connections=max_connections,
        )

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
