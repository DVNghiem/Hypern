# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, List, TypeVar

import orjson
import psutil
from typing_extensions import Annotated, Doc

from hypern.args_parser import ArgsConfig
from hypern.datastructures import SwaggerConfig
from hypern.enum import HTTPMethod
from hypern.hypern import DatabaseConfig, FunctionInfo, Scheduler, Server
from hypern.logging import logger
from hypern.manager import (
    ConfigManager,
    DependencyManager,
    MiddlewareManager,
    RouterManager,
    WebsocketManager,
)
from hypern.middleware import Middleware
from hypern.openapi import SchemaGenerator, SwaggerUI
from hypern.processpool import run_processes
from hypern.response import HTMLResponse, JSONResponse
from hypern.routing import Route
from hypern.ws import WebsocketRoute

AppType = TypeVar("AppType", bound="Hypern")


@dataclass
class ThreadConfig:
    workers: int
    max_blocking_threads: int


class ThreadConfigurator:
    def __init__(self):
        self._cpu_count = psutil.cpu_count(logical=True)
        self._memory_gb = psutil.virtual_memory().total / (1024**3)

    def get_config(self, concurrent_requests: int | None = None) -> ThreadConfig:
        """Calculate optimal thread configuration based on system resources."""
        workers = max(2, self._cpu_count or 2)

        if concurrent_requests:
            max_blocking = min(
                max(32, concurrent_requests * 2), workers * 4, int(self._memory_gb * 8)
            )
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
        websockets: Annotated[
            List[WebsocketRoute] | None,
            Doc(
                """
                A list of routes to serve incoming WebSocket requests.
                You can define routes using the `WebsocketRoute` class from `Hypern
                """
            ),
        ] = None,
        dependencies: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                A dictionary of global dependencies that can be accessed by all routes.
                """
            ),
        ] = None,
        swagger_config: Annotated[
            SwaggerConfig | None,
            Doc(
                """
                A dictionary with the configuration for the Swagger UI documentation.
                """
            ),
        ] = None,
        scheduler: Annotated[
            Scheduler | None,
            Doc(
                """
                A scheduler to run background tasks.
                """
            ),
        ] = None,
        database_config: Annotated[
            DatabaseConfig | None,
            Doc(
                """
                The database configuration for the application.
                """
            ),
        ] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.router_manager = RouterManager()
        self.websocket_manager = WebsocketManager()
        self.middleware_manager = MiddlewareManager()
        self.dependency_manager = DependencyManager()
        self.config_manager = ConfigManager()
        self.scheduler = scheduler
        self.response_headers = {}
        self.args = ArgsConfig()
        self.start_up_handler = None
        self.shutdown_handler = None
        self.thread_config = ThreadConfigurator().get_config()

        for caller_route in routes or []:
            self.router_manager.extend_route(caller_route())

        for websocket_route in websockets or []:
            for route in websocket_route.routes:
                self.websocket_manager.add_websocket(route)

        if database_config:
            self.config_manager.set_database_config(database_config)

        for key, value in (dependencies or {}).items():
            self.dependency_manager.inject(key, value)

        if swagger_config:
            self.config_manager.set_swagger_config(swagger_config)
            self.__add_openapi(swagger_config)

    def __add_openapi(
        self,
        config: SwaggerConfig,
    ):
        """
        Adds OpenAPI schema and documentation routes to the application.

        Args:
            info (Info): An instance of the Info class containing metadata about the API.
            openapi_url (str): The URL path where the OpenAPI schema will be served.
            docs_url (str): The URL path where the Swagger UI documentation will be served.

        The method defines two internal functions:
            - schema: Generates and returns the OpenAPI schema as a JSON response.
            - template_render: Renders and returns the Swagger UI documentation as an HTML response.

        The method then adds routes to the application for serving the OpenAPI schema and the Swagger UI documentation.
        """

        def schema(*args, **kwargs):
            schemas = SchemaGenerator(config=config)
            return JSONResponse(content=orjson.dumps(schemas.get_schema(self)))

        def template_render(*args, **kwargs):
            swagger = SwaggerUI(
                title="Swagger",
                openapi_url=config.openapi_url,
            )
            template = swagger.get_html_content()
            return HTMLResponse(template)

        self.add_route(HTTPMethod.GET, config.openapi_url, schema)
        self.add_route(HTTPMethod.GET, config.docs_url, template_render)

    def inject(self, key: str, value: Any):
        """
        Injects a key-value pair into the injectables dictionary.

        Args:
            key (str): The key to be added to the injectables dictionary.
            value (Any): The value to be associated with the key.

        Returns:
            self: Returns the instance of the class to allow method chaining.
        """
        self.dependency_manager.inject(key, value)
        return self

    def add_response_header(self, key: str, value: str):
        """
        Adds a response header to the response headers dictionary.

        Args:
            key (str): The header field name.
            value (str): The header field value.
        """
        self.response_headers[key] = value

    def add_middleware(self, middleware: Middleware):
        """
        Adds middleware to the application.

        This method attaches the middleware to the application instance and registers
        its `before_request` and `after_request` hooks if they are defined.

        Args:
            middleware (Middleware): The middleware instance to be added.

        Returns:
            self: The application instance with the middleware added.
        """
        self.middleware_manager.add_middleware(middleware)

    def start(
        self,
    ):
        """
        Starts the server with the specified configuration.
        Raises:
            ValueError: If an invalid port number is entered when prompted.

        """
        if self.scheduler:
            self.scheduler.start()

        server = Server()
        server.set_router(router=self.router_manager.router)
        server.set_websocket_router(
            websocket_router=self.websocket_manager.websocket_router
        )
        server.set_dependencies(dependencies=self.dependency_manager.dependencies)
        server.set_before_hooks(hooks=self.middleware_manager.before_request)
        server.set_after_hooks(hooks=self.middleware_manager.after_request)
        server.set_response_headers(headers=self.response_headers)

        if self.config_manager.database_config:
            server.set_database_config(config=self.config_manager.database_config)
        if self.start_up_handler:
            server.set_startup_handler(self.start_up_handler)
        if self.shutdown_handler:
            server.set_shutdown_handler(self.shutdown_handler)

        if self.args.auto_workers:
            self.args.workers = self.thread_config.workers
            self.args.max_blocking_threads = self.thread_config.max_blocking_threads

        if self.args.http2:
            logger.info("HTTP/2 enabled")
            server.enable_http2()

        run_processes(
            server=server,
            host=self.args.host,
            port=self.args.port,
            workers=self.args.workers,
            processes=self.args.processes,
            max_blocking_threads=self.args.max_blocking_threads,
            reload=self.args.reload,
        )

    def add_route(self, method: HTTPMethod, endpoint: str, handler: Callable[..., Any]):
        """
        Adds a route to the router.

        Args:
            method (HTTPMethod): The HTTP method for the route (e.g., GET, POST).
            endpoint (str): The endpoint path for the route.
            handler (Callable[..., Any]): The function that handles requests to the route.

        """
        self.router_manager.add_route(method, endpoint, handler)

    def add_websocket(self, ws_route: WebsocketRoute):
        """
        Adds a WebSocket route to the WebSocket router.

        Args:
            ws_route (WebsocketRoute): The WebSocket route to be added to the router.
        """
        for route in ws_route.routes:
            self.websocket_manager.add_websocket(route)

    def on_startup(self, handler: Callable[..., Any]):
        """
        Registers a function to be executed on application startup.

        Args:
            handler (Callable[..., Any]): The function to be executed on application startup.
        """
        # decorator
        self.start_up_handler = FunctionInfo(
            handler=handler, is_async=asyncio.iscoroutinefunction(handler)
        )

    def on_shutdown(self, handler: Callable[..., Any]):
        """
        Registers a function to be executed on application shutdown.

        Args:
            handler (Callable[..., Any]): The function to be executed on application shutdown.
        """
        self.shutdown_handler = FunctionInfo(
            handler=handler, is_async=asyncio.iscoroutinefunction(handler)
        )

    def route(self, method: HTTPMethod, endpoint: str):
        def decorator(handler):
            self.router_manager.add_route(method, endpoint, handler)
            return handler

        return decorator
