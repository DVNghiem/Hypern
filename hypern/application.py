# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Callable, List, TypeVar
from typing_extensions import Annotated, Doc

from hypern.hypern import Router, Server
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
        num_processes=1,
        workers_threads=1,
        max_blocking_threads=16,
        max_connections=10000,
    ):
        server = Server()
        server.set_router(router=self.router)
        server.start(
            host=host,
            port=port,
            num_processes=num_processes,
            workers_threads=workers_threads,
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
