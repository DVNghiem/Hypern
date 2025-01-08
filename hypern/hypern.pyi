from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple
from enum import Enum

@dataclass
class BaseSchemaGenerator:
    remove_converter: Callable[[str], str]
    parse_docstring: Callable[..., str]

@dataclass
class SwaggerUI:
    title: str
    openapi_url: str

    def get_html_content(self) -> str: ...

@dataclass
class BackgroundTask:
    """
    A task to be executed in the background
    id: str: The task ID
    function: Callable[..., Any]: The function to be executed
    args: List | Tuple: The arguments to be passed to the function
    kwargs: Dict[str, Any]: The keyword arguments to be passed to the function
    timeout_secs: int: The maximum time in seconds the task is allowed to run
    cancelled: bool: Whether the task is cancelled

    **Note**: function is currently running with sync mode, so it should be a sync function
    """

    id: str
    function: Callable[..., Any]
    args: List | Tuple
    kwargs: Dict[str, Any]
    timeout_secs: int
    cancelled: bool

    def get_id(self) -> str:
        """
        Get the task ID
        """
        pass

    def cancel(self) -> None:
        """
        Cancel the task
        """
        pass

    def is_cancelled(self) -> bool:
        """
        Check if the task is cancelled
        """
        pass

    def execute(self) -> Any:
        """
        Execute the task
        """
        pass

@dataclass
class BackgroundTasks:
    """
    A collection of tasks to be executed in the background

    **Note**: Only set tasks. pool, sender, receiver are set by the framework
    """

    def add_task(self, task: BackgroundTask) -> str:
        """
        Add a task to the collection
        """
        pass

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task in the collection
        """
        pass

    def execute_all(self) -> None:
        """
        Execute all tasks in the collection
        """
        pass

    def execute_task(self, task_id: str) -> None:
        """
        Execute a task in the collection
        """
        pass

class Scheduler:
    def add_job(
        self,
        job_type: str,
        schedule_param: str,
        task: Callable[..., Any],
        timezone: str,
        dependencies: List[str],
        retry_policy: Tuple[int, int, bool] | None = None,
    ) -> str:
        """
        Add a job to the scheduler
        params:
        job_type: str: The type of the job (e.g. "cron", "interval")

        schedule_param: str: The schedule parameter of the job. interval in seconds for interval jobs, cron expression for cron jobs

        Exmaple:
        //           sec  min   hour   day of month   month   day of week   year
        expression = "0   30   9,12,15     1,15       May-Aug  Mon,Wed,Fri  2018/2";

        task: Callable[..., Any]: The task to be executed

        timezone: str: The timezone of the job

        dependencies: List[str]: The IDs of the jobs this job depends on

        retry_policy: Tuple[int, int, bool] | None: The retry policy of the job. (max_retries, retry_delay_secs, exponential_backoff)

        return:
        str: The ID of the job
        """
        pass

    def remove_job(self, job_id: str) -> None:
        """
        Remove a job from the scheduler
        """
        pass

    def start(self) -> None:
        """
        Start the scheduler
        """
        pass

    def stop(self) -> None:
        """
        Stop the scheduler
        """
        pass

    def get_job_status(self, job_id: str) -> Tuple[float, float, List[str], int]:
        """
        Get the status of a job
        """
        pass

    def get_next_run(self, job_id: str) -> float:
        """
        Get the next run time of a job
        """
        pass

@dataclass
class FunctionInfo:
    """
    The function info object passed to the route handler.

    Attributes:
        handler (Callable): The function to be called
        is_async (bool): Whether the function is async or not
    """

    handler: Callable
    is_async: bool

@dataclass
class Server:
    router: Router
    websocket_router: Any
    startup_handler: Any
    shutdown_handler: Any

    def add_route(self, route: Route) -> None: ...
    def set_router(self, router: Router) -> None: ...
    def set_websocket_router(self, websocket_router: WebsocketRouter) -> None: ...
    def start(self, socket: SocketHeld, worker: int, max_blocking_threads: int) -> None: ...
    def set_before_hooks(self, hooks: List[FunctionInfo]) -> None: ...
    def set_after_hooks(self, hooks: List[FunctionInfo]) -> None: ...
    def set_response_headers(self, headers: Dict[str, str]) -> None: ...
    def set_startup_handler(self, on_startup: FunctionInfo) -> None: ...
    def set_shutdown_handler(self, on_shutdown: FunctionInfo) -> None: ...
    def set_database_config(self, config: DatabaseConfig) -> None: ...
    def set_dependencies(self, dependencies: Dict[str, Any]) -> None: ...
    def enable_http2(self) -> None: ...

class Route:
    path: str
    function: FunctionInfo
    method: str
    doc: str | None = None

    def matches(self, path: str, method: str) -> str: ...
    def clone_route(self) -> Route: ...
    def update_path(self, new_path: str) -> None: ...
    def update_method(self, new_method: str) -> None: ...
    def is_valid(self) -> bool: ...
    def get_path_parans(self) -> List[str]: ...
    def has_parameters(self) -> bool: ...
    def normalized_path(self) -> str: ...
    def same_handler(self, other: Route) -> bool: ...

class Router:
    routes: List[Route]

    def add_route(self, route: Route) -> None: ...
    def remove_route(self, path: str, method: str) -> bool: ...
    def get_route(self, path: str, method) -> Route | None: ...
    def get_routes_by_path(self, path: str) -> List[Route]: ...
    def get_routes_by_method(self, method: str) -> List[Route]: ...
    def extend_route(self, routes: List[Route]) -> None: ...

@dataclass
class SocketHeld:
    socket: Any

@dataclass
class WebSocketSession:
    sender: Callable[[str], None]
    receiver: Callable[[], str]
    is_closed: bool

    def send(self, message: str) -> None: ...

@dataclass
class WebsocketRoute:
    path: str
    handler: Callable[[WebSocketSession], None]

@dataclass
class WebsocketRouter:
    path: str
    routes: List[WebsocketRoute]

    def add_route(self, route: WebsocketRoute) -> None: ...
    def remove_route(self, path: str) -> None: ...
    def extend_route(self, route: WebsocketRoute) -> None: ...
    def clear_routes(self) -> None: ...
    def route_count(self) -> int: ...

@dataclass
class Header:
    headers: Dict[str, str]

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def append(self, key: str, value: str) -> None: ...
    def update(self, headers: Dict[str, str]) -> None: ...
    def get_headers(self) -> Dict[str, str]: ...

@dataclass
class Response:
    status_code: int
    response_type: str
    headers: Header
    description: str
    file_path: str | None
    context_id: str

@dataclass
class QueryParams:
    queries: Dict[str, List[str]]

    def to_dict(self) -> Dict[str, str]: ...

@dataclass
class UploadedFile:
    name: str
    content_type: str
    path: str
    size: int
    content: bytes
    file_name: str

@dataclass
class BodyData:
    json: bytes
    files: List[UploadedFile]

@dataclass
class Request:
    path: str
    query_params: QueryParams
    headers: Header
    path_params: Dict[str, str]
    body: BodyData
    method: str
    remote_addr: str
    timestamp: float
    context_id: str

    def json(self) -> Dict[str, Any]: ...
    def set_body(self, body: BodyData) -> None: ...

@dataclass
class MiddlewareConfig:
    priority: int = 0
    is_conditional: bool = True

    @staticmethod
    def default(self) -> MiddlewareConfig: ...

class DatabaseType(Enum):
    Postgres: str
    MySQL: str
    SQLite: str

@dataclass
class DatabaseConfig:
    driver: DatabaseType
    url: str
    max_connections: int = 10
    min_connections: int = 1
    idle_timeout: int = 30

    options: Dict[str, Any] = {}

@dataclass
class DatabaseTransaction:
    def execute(self, query: str, params: List[Any]) -> int: ...
    def fetch_all(self, query: str, params: List[Any]) -> List[Dict[str, Any]]: ...
    def stream_data(self, query: str, params: List[Any], chunk_size: int) -> Dict[str, Any]: ...
    def bulk_change(self, query: str, params: List[List[Any]], batch_size: int) -> int | None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...

def get_session_database(context_id: str) -> DatabaseTransaction: ...
