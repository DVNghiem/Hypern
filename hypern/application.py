# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, List, TypeVar

import orjson
import psutil
from typing_extensions import Annotated, Doc

from hypern.args_parser import ArgsConfig
from hypern.datastructures import Contact, Info, License
from hypern.enum import HTTPMethod
from hypern.hypern import DatabaseConfig, FunctionInfo, MiddlewareConfig, Router, Server, WebsocketRouter, Scheduler
from hypern.hypern import Route as InternalRoute
from hypern.logging import logger
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
        title: Annotated[
            str,
            Doc(
                """
                The title of the API.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more in the
                """
            ),
        ] = "Hypern",
        summary: Annotated[
            str | None,
            Doc(
                """"
                A short summary of the API.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        description: Annotated[
            str,
            Doc(
                """
                A description of the API. Supports Markdown (using
                [CommonMark syntax](https://commonmark.org/)).

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "",
        version: Annotated[
            str,
            Doc(
                """
                The version of the API.

                **Note** This is the version of your application, not the version of
                the OpenAPI specification nor the version of Application being used.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "0.0.1",
        contact: Annotated[
            Contact | None,
            Doc(
                """
                A dictionary with the contact information for the exposed API.

                It can contain several fields.

                * `name`: (`str`) The name of the contact person/organization.
                * `url`: (`str`) A URL pointing to the contact information. MUST be in
                    the format of a URL.
                * `email`: (`str`) The email address of the contact person/organization.
                    MUST be in the format of an email address.            
                """
            ),
        ] = None,
        openapi_url: Annotated[
            str | None,
            Doc(
                """
                The URL where the OpenAPI schema will be served from.

                If you set it to `None`, no OpenAPI schema will be served publicly, and
                the default automatic endpoints `/docs` and `/redoc` will also be
                disabled.
            """
            ),
        ] = "/openapi.json",
        docs_url: Annotated[
            str | None,
            Doc(
                """
                The path to the automatic interactive API documentation.
                It is handled in the browser by Swagger UI.

                The default URL is `/docs`. You can disable it by setting it to `None`.

                If `openapi_url` is set to `None`, this will be automatically disabled.
            """
            ),
        ] = "/docs",
        license_info: Annotated[
            License | None,
            Doc(
                """
                A dictionary with the license information for the exposed API.

                It can contain several fields.

                * `name`: (`str`) **REQUIRED** (if a `license_info` is set). The
                    license name used for the API.
                * `identifier`: (`str`) An [SPDX](https://spdx.dev/) license expression
                    for the API. The `identifier` field is mutually exclusive of the `url`
                    field. Available since OpenAPI 3.1.0
                * `url`: (`str`) A URL to the license used for the API. This MUST be
                    the format of a URL.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                **Example**

                ```python
                app = Hypern(
                    license_info={
                        "name": "Apache 2.0",
                        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
                    }
                )
                ```
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
        self.router = Router(path="/")
        self.websocket_router = WebsocketRouter(path="/")
        self.dependencies = dependencies or {}
        self.scheduler = scheduler
        self.middleware_before_request = []
        self.middleware_after_request = []
        self.response_headers = {}
        self.args = ArgsConfig()
        self.start_up_handler = None
        self.shutdown_handler = None
        self.database_config = database_config
        self.thread_config = ThreadConfigurator().get_config()

        for route in routes or []:
            self.router.extend_route(route(app=self).routes)

        for websocket_route in websockets or []:
            for route in websocket_route.routes:
                self.websocket_router.add_route(route)

        if openapi_url and docs_url:
            self.__add_openapi(
                info=Info(
                    title=title,
                    summary=summary,
                    description=description,
                    version=version,
                    contact=contact,
                    license=license_info,
                ),
                openapi_url=openapi_url,
                docs_url=docs_url,
            )

    def __add_openapi(
        self,
        info: Info,
        openapi_url: str,
        docs_url: str,
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
            schemas = SchemaGenerator(
                {
                    "openapi": "3.0.0",
                    "info": info.model_dump(),
                    "components": {"securitySchemes": {}},
                }
            )
            return JSONResponse(content=orjson.dumps(schemas.get_schema(self)))

        def template_render(*args, **kwargs):
            swagger = SwaggerUI(
                title="Swagger",
                openapi_url=openapi_url,
            )
            template = swagger.get_html_content()
            return HTMLResponse(template)

        self.add_route(HTTPMethod.GET, openapi_url, schema)
        self.add_route(HTTPMethod.GET, docs_url, template_render)

    def inject(self, key: str, value: Any):
        """
        Injects a key-value pair into the injectables dictionary.

        Args:
            key (str): The key to be added to the injectables dictionary.
            value (Any): The value to be associated with the key.

        Returns:
            self: Returns the instance of the class to allow method chaining.
        """
        self.dependencies[key] = value
        return self

    def add_response_header(self, key: str, value: str):
        """
        Adds a response header to the response headers dictionary.

        Args:
            key (str): The header field name.
            value (str): The header field value.
        """
        self.response_headers[key] = value

    def before_request(self):
        """
        A decorator to register a function to be executed before each request.

        This decorator can be used to add middleware functions that will be
        executed before the main request handler. The function can be either
        synchronous or asynchronous.

        Returns:
            function: The decorator function that registers the middleware.
        """

        logger.warning("This functin will be deprecated in version 0.4.0. Please use the middleware class instead.")

        def decorator(func):
            is_async = asyncio.iscoroutinefunction(func)
            func_info = FunctionInfo(handler=func, is_async=is_async)
            self.middleware_before_request.append((func_info, MiddlewareConfig.default()))
            return func

        return decorator

    def after_request(self):
        """
        Decorator to register a function to be called after each request.

        This decorator can be used to register both synchronous and asynchronous functions.
        The registered function will be wrapped in a FunctionInfo object and appended to the
        middleware_after_request list.

        Returns:
            function: The decorator function that registers the given function.
        """
        logger.warning("This functin will be deprecated in version 0.4.0. Please use the middleware class instead.")

        def decorator(func):
            is_async = asyncio.iscoroutinefunction(func)
            func_info = FunctionInfo(handler=func, is_async=is_async)
            self.middleware_after_request.append((func_info, MiddlewareConfig.default()))
            return func

        return decorator

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
        setattr(middleware, "app", self)
        before_request = getattr(middleware, "before_request", None)
        after_request = getattr(middleware, "after_request", None)

        is_async = asyncio.iscoroutinefunction(before_request)
        before_request = FunctionInfo(handler=before_request, is_async=is_async)
        self.middleware_before_request.append((before_request, middleware.config))

        is_async = asyncio.iscoroutinefunction(after_request)
        after_request = FunctionInfo(handler=after_request, is_async=is_async)
        self.middleware_after_request.append((after_request, middleware.config))

    def set_database_config(self, config: DatabaseConfig):
        """
        Sets the database configuration for the application.

        Args:
            config (DatabaseConfig): The database configuration to be set.
        """
        self.database_config = config

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
        server.set_router(router=self.router)
        server.set_websocket_router(websocket_router=self.websocket_router)
        server.set_dependencies(dependencies=self.dependencies)
        server.set_before_hooks(hooks=self.middleware_before_request)
        server.set_after_hooks(hooks=self.middleware_after_request)
        server.set_response_headers(headers=self.response_headers)

        if self.database_config:
            server.set_database_config(config=self.database_config)
        if self.start_up_handler:
            server.set_startup_handler(self.start_up_handler)
        if self.shutdown_handler:
            server.set_shutdown_handler(self.shutdown_handler)

        if self.args.auto_workers:
            self.args.workers = self.thread_config.workers
            self.args.max_blocking_threads = self.thread_config.max_blocking_threads

        if self.args.http2:
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
        is_async = asyncio.iscoroutinefunction(handler)
        func_info = FunctionInfo(handler=handler, is_async=is_async)
        route = InternalRoute(path=endpoint, function=func_info, method=method.name)
        self.router.add_route(route=route)

    def add_websocket(self, ws_route: WebsocketRoute):
        """
        Adds a WebSocket route to the WebSocket router.

        Args:
            ws_route (WebsocketRoute): The WebSocket route to be added to the router.
        """
        for route in ws_route.routes:
            self.websocket_router.add_route(route=route)

    def on_startup(self, handler: Callable[..., Any]):
        """
        Registers a function to be executed on application startup.

        Args:
            handler (Callable[..., Any]): The function to be executed on application startup.
        """
        # decorator
        self.start_up_handler = FunctionInfo(handler=handler, is_async=asyncio.iscoroutinefunction(handler))

    def on_shutdown(self, handler: Callable[..., Any]):
        """
        Registers a function to be executed on application shutdown.

        Args:
            handler (Callable[..., Any]): The function to be executed on application shutdown.
        """
        self.shutdown_handler = FunctionInfo(handler=handler, is_async=asyncio.iscoroutinefunction(handler))
