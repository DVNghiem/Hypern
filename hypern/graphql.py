"""GraphQL endpoint integration for Hypern using Strawberry.

``strawberry-graphql`` is an **optional** dependency.  Install it with::

    pip install strawberry-graphql

Example::

    import strawberry
    from hypern import Hypern
    from hypern.graphql import GraphQLRoute

    @strawberry.type
    class Query:
        @strawberry.field
        def hello(self) -> str:
            return "world"

    schema = strawberry.Schema(Query)
    app = Hypern()
    app.mount("/graphql", GraphQLRoute(schema))
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

try:
    from strawberry import Schema

    HAS_STRAWBERRY = True
except ImportError:
    HAS_STRAWBERRY = False

_GRAPHIQL_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>GraphiQL</title>
  <link rel="stylesheet" href="https://unpkg.com/graphiql/graphiql.min.css" />
</head>
<body style="margin:0">
  <div id="graphiql" style="height:100vh"></div>
  <script crossorigin src="https://unpkg.com/react/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/graphiql/graphiql.min.js"></script>
  <script>
    const fetcher = GraphiQL.createFetcher({ url: window.location.pathname });
    ReactDOM.render(
      React.createElement(GraphiQL, { fetcher }),
      document.getElementById('graphiql'),
    );
  </script>
</body>
</html>"""


class GraphQLRoute:
    """Mount a Strawberry GraphQL schema as a Hypern route handler.

    Supports:
    * ``POST /graphql`` with JSON body ``{"query": "...", "variables": {...}}``
    * ``GET /graphql?query=...`` for simple queries
    * ``GET /graphql`` with ``Accept: text/html`` serves the GraphiQL IDE

    Args:
        schema: A ``strawberry.Schema`` instance.
        graphiql: Whether to serve the GraphiQL IDE on GET with ``text/html``
            accept header (default ``True``).
    """

    def __init__(self, schema: Any, graphiql: bool = True) -> None:
        if not HAS_STRAWBERRY:
            raise ImportError(
                "strawberry-graphql is required for GraphQL support. "
                "Install it with: pip install strawberry-graphql"
            )
        self._schema: Schema = schema
        self._graphiql = graphiql

    # Hypern calls the handler with (request, response, context).
    async def __call__(self, request: Any, response: Any, context: Any = None) -> None:
        method: str = getattr(request, "method", "GET")

        if method == "GET":
            return await self._handle_get(request, response)
        if method == "POST":
            return await self._handle_post(request, response)

        response.status_code = 405
        response.json({"errors": [{"message": "Method not allowed"}]})

    async def _handle_get(self, request: Any, response: Any) -> None:
        accept = _get_header(request, "accept") or ""

        if "text/html" in accept and self._graphiql:
            response.status_code = 200
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            response.body = _GRAPHIQL_HTML
            return

        query = _get_query_param(request, "query")
        if not query:
            response.status_code = 400
            response.json({"errors": [{"message": "Missing query parameter"}]})
            return

        variables_raw = _get_query_param(request, "variables")
        variables: Optional[Dict[str, Any]] = None
        if variables_raw:
            try:
                variables = json.loads(variables_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        result = await self._schema.execute(query, variable_values=variables)
        _send_result(response, result)

    async def _handle_post(self, request: Any, response: Any) -> None:
        try:
            body = _get_body_json(request)
        except Exception:
            response.status_code = 400
            response.json({"errors": [{"message": "Invalid JSON body"}]})
            return

        query = body.get("query")
        if not query:
            response.status_code = 400
            response.json({"errors": [{"message": "Missing 'query' in body"}]})
            return

        variables = body.get("variables")
        operation_name = body.get("operationName")

        result = await self._schema.execute(
            query,
            variable_values=variables,
            operation_name=operation_name,
        )
        _send_result(response, result)


def _get_header(request: Any, name: str) -> Optional[str]:
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    if isinstance(headers, dict):
        return headers.get(name) or headers.get(name.title())
    if hasattr(headers, "get"):
        return headers.get(name)
    return None


def _get_query_param(request: Any, name: str) -> Optional[str]:
    if hasattr(request, "query_params"):
        qp = request.query_params
        if isinstance(qp, dict):
            return qp.get(name)
        if hasattr(qp, "get"):
            return qp.get(name)
    return None


def _get_body_json(request: Any) -> Dict[str, Any]:
    if hasattr(request, "json"):
        body = request.json
        if callable(body):
            body = body()
        return body
    if hasattr(request, "body"):
        raw = request.body
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    return {}


def _send_result(response: Any, result: Any) -> None:
    payload: Dict[str, Any] = {"data": result.data}
    if result.errors:
        payload["errors"] = [
            {"message": str(e), "path": getattr(e, "path", None)}
            for e in result.errors
        ]
    response.status_code = 200
    response.json(payload)


__all__ = ["GraphQLRoute"]
