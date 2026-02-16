from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type, Union, get_type_hints
import orjson


@dataclass
class APIParameter:
    """Represents an API parameter (path, query, header, cookie)."""
    name: str
    location: str  # "path", "query", "header", "cookie"
    required: bool = True
    description: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)
    example: Any = None


@dataclass
class APIRequestBody:
    """Represents a request body schema."""
    content_type: str = "application/json"
    schema: Dict[str, Any] = field(default_factory=dict)
    required: bool = True
    description: str = ""
    example: Any = None


@dataclass
class APIResponse:
    """Represents an API response."""
    status_code: int
    description: str
    content_type: str = "application/json"
    schema: Dict[str, Any] = field(default_factory=dict)
    example: Any = None
    headers: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class APIEndpoint:
    """Represents an API endpoint with full documentation."""
    path: str
    method: str
    summary: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    parameters: List[APIParameter] = field(default_factory=list)
    request_body: Optional[APIRequestBody] = None
    responses: Dict[int, APIResponse] = field(default_factory=dict)
    deprecated: bool = False
    security: List[Dict[str, List[str]]] = field(default_factory=list)
    operation_id: Optional[str] = None


class OpenAPIGenerator:
    """
    Generates OpenAPI 3.0 specification from route definitions.
    
    Example:
        ```python
        app = Hypern()
        openapi = OpenAPIGenerator(
            title="My API",
            version="1.0.0",
            description="A sample API",
        )
        
        # Routes are automatically collected from app
        spec = openapi.generate(app)
        
        # Serve the spec
        @app.get("/openapi.json")
        async def openapi_spec(req, res):
            res.json(spec)
        ```
    """
    
    def __init__(
        self,
        title: str = "API",
        version: str = "1.0.0",
        description: str = "",
        terms_of_service: Optional[str] = None,
        contact: Optional[Dict[str, str]] = None,
        license_info: Optional[Dict[str, str]] = None,
        servers: Optional[List[Dict[str, str]]] = None,
        external_docs: Optional[Dict[str, str]] = None,
    ):
        self.title = title
        self.version = version
        self.description = description
        self.terms_of_service = terms_of_service
        self.contact = contact
        self.license_info = license_info
        self.servers = servers or [{"url": "/", "description": "Default server"}]
        self.external_docs = external_docs
        
        self.endpoints: List[APIEndpoint] = []
        self.schemas: Dict[str, Dict[str, Any]] = {}
        self.security_schemes: Dict[str, Dict[str, Any]] = {}
        self.tags: List[Dict[str, Any]] = []
    
    def add_security_scheme(
        self,
        name: str,
        scheme_type: str,
        **kwargs,
    ) -> "OpenAPIGenerator":
        """
        Add a security scheme.
        
        Args:
            name: Security scheme name
            scheme_type: Type (apiKey, http, oauth2, openIdConnect)
            **kwargs: Additional scheme properties
        """
        scheme = {"type": scheme_type, **kwargs}
        self.security_schemes[name] = scheme
        return self
    
    def add_bearer_auth(self, name: str = "bearerAuth") -> "OpenAPIGenerator":
        """Add Bearer token authentication scheme."""
        return self.add_security_scheme(
            name,
            "http",
            scheme="bearer",
            bearerFormat="JWT",
        )
    
    def add_api_key_auth(
        self,
        scheme_name: str = "apiKeyAuth",
        location: str = "header",
        key_name: str = "X-API-Key",
    ) -> "OpenAPIGenerator":
        """Add API Key authentication scheme."""
        scheme = {
            "type": "apiKey",
            "in": location,
            "name": key_name,
        }
        self.security_schemes[scheme_name] = scheme
        return self
    
    def add_tag(
        self,
        name: str,
        description: str = "",
        external_docs: Optional[Dict[str, str]] = None,
    ) -> "OpenAPIGenerator":
        """Add a tag for grouping endpoints."""
        tag = {"name": name}
        if description:
            tag["description"] = description
        if external_docs:
            tag["externalDocs"] = external_docs
        self.tags.append(tag)
        return self
    
    def add_endpoint(self, endpoint: APIEndpoint) -> "OpenAPIGenerator":
        """Add an endpoint to the documentation."""
        self.endpoints.append(endpoint)
        return self
    
    def add_schema(self, name: str, schema: Dict[str, Any]) -> "OpenAPIGenerator":
        """Add a reusable schema."""
        self.schemas[name] = schema
        return self
    
    def schema_from_type(self, type_hint: Type) -> Dict[str, Any]:
        """Generate JSON Schema from a Python type hint."""
        if type_hint is None or type_hint is type(None):
            return {"type": "null"}
        
        # Handle basic types
        if type_hint is str:
            return {"type": "string"}
        if type_hint is int:
            return {"type": "integer"}
        if type_hint is float:
            return {"type": "number"}
        if type_hint is bool:
            return {"type": "boolean"}
        if type_hint is bytes:
            return {"type": "string", "format": "binary"}
        
        # Handle generic types
        origin = getattr(type_hint, "__origin__", None)
        args = getattr(type_hint, "__args__", ())
        
        if origin is list:
            item_type = args[0] if args else Any
            return {
                "type": "array",
                "items": self.schema_from_type(item_type),
            }
        
        if origin is dict:
            value_type = args[1] if len(args) > 1 else Any
            return {
                "type": "object",
                "additionalProperties": self.schema_from_type(value_type),
            }
        
        if origin is Union:
            # Handle Optional (Union with None)
            non_none_types = [t for t in args if t is not type(None)]
            if len(non_none_types) == 1:
                schema = self.schema_from_type(non_none_types[0])
                schema["nullable"] = True
                return schema
            return {
                "oneOf": [self.schema_from_type(t) for t in args if t is not type(None)]
            }
        
        # Handle msgspec Struct
        if hasattr(type_hint, "__struct_fields__"):
            return self._schema_from_msgspec_struct(type_hint)
        
        # Handle dataclass
        if hasattr(type_hint, "__dataclass_fields__"):
            return self._schema_from_dataclass(type_hint)
        
        # Default to object
        return {"type": "object"}
    
    def _schema_from_msgspec_struct(self, struct_type: Type) -> Dict[str, Any]:
        """Generate schema from msgspec Struct."""
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        
        fields = struct_type.__struct_fields__
        defaults = getattr(struct_type, "__struct_defaults__", {})
        
        for field_name in fields:
            field_type = struct_type.__annotations__.get(field_name, Any)
            schema["properties"][field_name] = self.schema_from_type(field_type)
            
            # Check if required (no default value)
            if field_name not in defaults:
                schema["required"].append(field_name)
        
        # Add to schemas for reference
        schema_name = struct_type.__name__
        self.schemas[schema_name] = schema
        
        return {"$ref": f"#/components/schemas/{schema_name}"}
    
    def _schema_from_dataclass(self, dc_type: Type) -> Dict[str, Any]:
        """Generate schema from dataclass."""
        from dataclasses import fields as dc_fields, MISSING
        
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        
        for f in dc_fields(dc_type):
            schema["properties"][f.name] = self.schema_from_type(f.type)
            
            if f.default is MISSING and f.default_factory is MISSING:
                schema["required"].append(f.name)
        
        schema_name = dc_type.__name__
        self.schemas[schema_name] = schema
        
        return {"$ref": f"#/components/schemas/{schema_name}"}
    
    def endpoint_from_route(
        self,
        path: str,
        method: str,
        handler: Callable,
        tags: Optional[List[str]] = None,
    ) -> APIEndpoint:
        """
        Generate an APIEndpoint from a route handler.
        
        Extracts documentation from:
        - Docstring (summary and description)
        - Type hints (parameters and response)
        - Decorator metadata
        """
        endpoint = APIEndpoint(path=path, method=method.lower())
        
        # Extract docstring
        if handler.__doc__:
            lines = handler.__doc__.strip().split("\n")
            endpoint.summary = lines[0]
            if len(lines) > 1:
                endpoint.description = "\n".join(lines[1:]).strip()
        
        # Extract tags
        endpoint.tags = tags or getattr(handler, "_tags", [])
        
        # Extract parameters from path
        path_params = re.findall(r":(\w+)", path)
        for param in path_params:
            endpoint.parameters.append(APIParameter(
                name=param,
                location="path",
                required=True,
                schema={"type": "string"},
            ))
        
        # Extract type hints
        try:
            hints = get_type_hints(handler)
        except Exception:
            hints = {}
        
        # Look for body parameter
        sig = inspect.signature(handler)
        for param_name, param in sig.parameters.items():
            if param_name in ("req", "res", "ctx", "request", "response", "context"):
                continue
            
            if param_name == "body" and param_name in hints:
                body_type = hints[param_name]
                endpoint.request_body = APIRequestBody(
                    schema=self.schema_from_type(body_type),
                )
            elif param_name == "query" and param_name in hints:
                query_type = hints[param_name]
                # Add query parameters from schema
                if hasattr(query_type, "__annotations__"):
                    for qname, qtype in query_type.__annotations__.items():
                        endpoint.parameters.append(APIParameter(
                            name=qname,
                            location="query",
                            required=False,  # Query params usually optional
                            schema=self.schema_from_type(qtype),
                        ))
        
        # Extract return type for response
        if "return" in hints:
            return_type = hints["return"]
            endpoint.responses[200] = APIResponse(
                status_code=200,
                description="Successful response",
                schema=self.schema_from_type(return_type),
            )
        
        # Add default responses if not specified
        if 200 not in endpoint.responses:
            endpoint.responses[200] = APIResponse(
                status_code=200,
                description="Successful response",
            )
        
        # Add common error responses
        endpoint.responses[400] = APIResponse(
            status_code=400,
            description="Bad request",
            schema={"type": "object", "properties": {"error": {"type": "string"}}},
        )
        endpoint.responses[500] = APIResponse(
            status_code=500,
            description="Internal server error",
            schema={"type": "object", "properties": {"error": {"type": "string"}}},
        )
        
        # Extract security requirements
        if hasattr(handler, "_requires_auth"):
            endpoint.security = [{"bearerAuth": []}]
        
        # Extract RBAC metadata for description
        required_roles = getattr(handler, "_required_roles", None)
        required_permissions = getattr(handler, "_required_permissions", None)
        rbac_notes = []
        if required_roles:
            rbac_notes.append(f"**Required roles**: {', '.join(required_roles)}")
        if required_permissions:
            rbac_notes.append(f"**Required permissions**: {', '.join(required_permissions)}")
        if rbac_notes:
            extra = "\n\n" + "\n\n".join(rbac_notes)
            endpoint.description = (endpoint.description or "") + extra
        
        # Extract deprecation
        endpoint.deprecated = getattr(handler, "_deprecated", False)
        
        # Generate operation ID
        endpoint.operation_id = getattr(
            handler,
            "_operation_id",
            f"{method.lower()}_{path.replace('/', '_').replace(':', '_')}",
        )
        
        return endpoint
    
    def generate(self, app=None) -> Dict[str, Any]:
        """
        Generate the complete OpenAPI specification.
        
        Args:
            app: Optional Hypern app to extract routes from
        
        Returns:
            OpenAPI 3.0 specification as a dictionary
        """
        # Extract routes from app if provided
        if app is not None:
            self._extract_routes_from_app(app)
        
        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": self.title,
                "version": self.version,
            },
        }
        
        if self.description:
            spec["info"]["description"] = self.description
        if self.terms_of_service:
            spec["info"]["termsOfService"] = self.terms_of_service
        if self.contact:
            spec["info"]["contact"] = self.contact
        if self.license_info:
            spec["info"]["license"] = self.license_info
        
        if self.servers:
            spec["servers"] = self.servers
        
        if self.external_docs:
            spec["externalDocs"] = self.external_docs
        
        if self.tags:
            spec["tags"] = self.tags
        
        # Build paths
        paths: Dict[str, Dict[str, Any]] = {}
        for endpoint in self.endpoints:
            # Convert path format from :param to {param}
            openapi_path = re.sub(r":(\w+)", r"{\1}", endpoint.path)
            
            if openapi_path not in paths:
                paths[openapi_path] = {}
            
            operation = {}
            
            if endpoint.summary:
                operation["summary"] = endpoint.summary
            if endpoint.description:
                operation["description"] = endpoint.description
            if endpoint.tags:
                operation["tags"] = endpoint.tags
            if endpoint.operation_id:
                operation["operationId"] = endpoint.operation_id
            if endpoint.deprecated:
                operation["deprecated"] = True
            if endpoint.security:
                operation["security"] = endpoint.security
            
            # Parameters
            if endpoint.parameters:
                operation["parameters"] = [
                    {
                        "name": p.name,
                        "in": p.location,
                        "required": p.required,
                        "schema": p.schema,
                        **({"description": p.description} if p.description else {}),
                        **({"example": p.example} if p.example is not None else {}),
                    }
                    for p in endpoint.parameters
                ]
            
            # Request body
            if endpoint.request_body:
                rb = endpoint.request_body
                operation["requestBody"] = {
                    "required": rb.required,
                    "content": {
                        rb.content_type: {
                            "schema": rb.schema,
                            **({"example": rb.example} if rb.example is not None else {}),
                        }
                    },
                    **({"description": rb.description} if rb.description else {}),
                }
            
            # Responses
            operation["responses"] = {}
            for status_code, response in endpoint.responses.items():
                resp = {"description": response.description}
                if response.schema:
                    resp["content"] = {
                        response.content_type: {
                            "schema": response.schema,
                            **({"example": response.example} if response.example is not None else {}),
                        }
                    }
                if response.headers:
                    resp["headers"] = response.headers
                operation["responses"][str(status_code)] = resp
            
            paths[openapi_path][endpoint.method] = operation
        
        spec["paths"] = paths
        
        # Components
        components = {}
        if self.schemas:
            components["schemas"] = self.schemas
        if self.security_schemes:
            components["securitySchemes"] = self.security_schemes
        if components:
            spec["components"] = components
        
        return spec
    
    def _extract_routes_from_app(self, app) -> None:
        """Extract routes from a Hypern app."""
        if hasattr(app, "router") and hasattr(app.router, "routes"):
            for route in app.router.routes:
                endpoint = self.endpoint_from_route(
                    path=route.path,
                    method=route.method,
                    handler=route.function if hasattr(route, "function") else lambda: None,
                )
                self.endpoints.append(endpoint)
    
    def to_json(self, indent: int = 2) -> str:
        """Convert spec to JSON string."""
        return orjson.dumps(self.generate(), option=orjson.OPT_INDENT_2).decode()
    
# Decorators for documenting endpoints

def tags(*tag_names: str):
    """Add tags to an endpoint."""
    def decorator(func):
        func._tags = list(tag_names)
        return func
    return decorator


def deprecated(func):
    """Mark an endpoint as deprecated."""
    func._deprecated = True
    return func


def operation_id(op_id: str):
    """Set a custom operation ID."""
    def decorator(func):
        func._operation_id = op_id
        return func
    return decorator


def requires_auth(func):
    """Mark an endpoint as requiring authentication."""
    func._requires_auth = True
    return func


def response(status_code: int, description: str, schema: Optional[Type] = None):
    """Document a response for an endpoint."""
    def decorator(func):
        if not hasattr(func, "_responses"):
            func._responses = {}
        func._responses[status_code] = {
            "description": description,
            "schema": schema,
        }
        return func
    return decorator


def summary(text: str):
    """Set the summary for an endpoint."""
    def decorator(func):
        func._summary = text
        return func
    return decorator


def description(text: str):
    """Set the description for an endpoint."""
    def decorator(func):
        func._description = text
        return func
    return decorator


# Swagger UI HTML template
SWAGGER_UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>{title} - Swagger UI</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        window.onload = function() {{
            SwaggerUIBundle({{
                url: "{spec_url}",
                dom_id: '#swagger-ui',
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
            }})
        }}
    </script>
</body>
</html>
"""

# ReDoc HTML template
REDOC_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>{title} - ReDoc</title>
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
    <style>body {{ margin: 0; padding: 0; }}</style>
</head>
<body>
    <redoc spec-url='{spec_url}'></redoc>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>
"""


def setup_openapi_routes(
    app,
    openapi: OpenAPIGenerator,
    spec_path: str = "/openapi.json",
    docs_path: str = "/docs",
    redoc_path: Optional[str] = "/redoc",
):
    """
    Set up OpenAPI documentation routes on an app.
    
    Args:
        app: Hypern app instance
        openapi: OpenAPIGenerator instance
        spec_path: Path for the OpenAPI JSON spec
        docs_path: Path for Swagger UI
        redoc_path: Path for ReDoc (None to disable)
    """
    
    @app.get(spec_path)
    async def openapi_spec(req, res, ctx):
        """OpenAPI specification."""
        spec = openapi.generate(app)
        res.json(spec)
    
    @app.get(docs_path)
    async def swagger_ui(req, res, ctx):
        """Swagger UI documentation."""
        html = SWAGGER_UI_HTML.format(
            title=openapi.title,
            spec_url=spec_path,
        )
        res.html(html)
    
    if redoc_path:
        @app.get(redoc_path)
        async def redoc_ui(req, res, ctx):
            """ReDoc documentation."""
            html = REDOC_HTML.format(
                title=openapi.title,
                spec_url=spec_path,
            )
            res.html(html)


# Aliases for alternative naming conventions
api_tags = tags
api_doc = summary  # api_doc is an alias for summary


__all__ = [
    "OpenAPIGenerator",
    "APIEndpoint",
    "APIParameter",
    "APIRequestBody",
    "APIResponse",
    "setup_openapi_routes",
    # Decorators
    "tags",
    "api_tags",  # Alias for tags
    "deprecated",
    "operation_id",
    "requires_auth",
    "response",
    "summary",
    "api_doc",  # Alias for summary
    "description",
    # HTML templates
    "SWAGGER_UI_HTML",
    "REDOC_HTML",
]
