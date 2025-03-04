# -*- coding: utf-8 -*-
from hypern import Hypern, Request, Response
from hypern.routing import HTTPEndpoint, Route
from hypern.response import JSONResponse, HTMLResponse, PlainTextResponse, RedirectResponse, FileResponse

from pydantic import BaseModel

__base_route__ = "/benchmark"

MESSAGE = "Hello World!"


class DefaultRoute(HTTPEndpoint):
    def post(self, request: Request):
        return JSONResponse({"message": MESSAGE})


class RequestFile(HTTPEndpoint):
    def post(self, request: Request):
        return Response(
            status_code=200,
            description="multipart form data",
            headers={"Content-Type": "application/json"},
        )


class SyncQuery(HTTPEndpoint):
    def get(self, request: Request):
        return JSONResponse({"message": MESSAGE})


class AsyncQuery(HTTPEndpoint):
    async def get(self, request: Request):
        return JSONResponse({"message": MESSAGE})


class ResponseObject(HTTPEndpoint):
    def get(self, request: Request):
        return Response(
            status_code=200,
            description={"message": MESSAGE},
            headers={"Content-Type": "application/json"},
        )


class ModelRequest(BaseModel):
    name: str
    age: int


class ModelResponse(BaseModel):
    message: str


class ValidateModel(HTTPEndpoint):
    def post(self, request: Request, form_data: ModelRequest) -> ModelResponse:
        return ModelResponse(message=f"Hello {form_data.name}! You are {form_data.age} years old.")

    async def get(self) -> ModelResponse:
        return ModelResponse(message=MESSAGE)


# response type
class TestJsonResponse(HTTPEndpoint):
    def post(self, request: Request):
        return JSONResponse({"message": MESSAGE})


class TestHtmlResponse(HTTPEndpoint):
    def post(self, request: Request):
        return HTMLResponse("<h1>Hello World!</h1>")


class TestPlainTextResponse(HTTPEndpoint):
    def post(self, request: Request):
        return PlainTextResponse("Hello World!")


class TestRedirectResponse(HTTPEndpoint):
    def post(self, request: Request):
        return RedirectResponse("/benchmark/default")


class TestFileResponse(HTTPEndpoint):
    def get(self, request: Request):
        return FileResponse(b"Hello", "hello.txt")


functional_route = Route("/functional")
sync_route = Route("/sync")


@functional_route.get("/default")
def get(request: Request, query_params: ModelRequest):
    return JSONResponse({"message": MESSAGE})


@functional_route.post("/default")
def post(request: Request, global_dependencies):
    return JSONResponse({"message": MESSAGE})


@functional_route.put("/default")
def put(request: Request, router_dependencies):
    return JSONResponse({"message": MESSAGE})


@functional_route.delete("/default")
def delete(request: Request):
    return JSONResponse({"message": MESSAGE})


routes = [
    Route(f"{__base_route__}/default", DefaultRoute),
    Route(f"{__base_route__}/file", RequestFile),
    Route(f"{__base_route__}/sync", SyncQuery),
    Route(f"{__base_route__}/async", AsyncQuery),
    Route(f"{__base_route__}/response", ResponseObject),
    Route(f"{__base_route__}/validate", ValidateModel),
    Route(f"{__base_route__}/json", TestJsonResponse),
    Route(f"{__base_route__}/html", TestHtmlResponse),
    Route(f"{__base_route__}/plain_text", TestPlainTextResponse),
    Route(f"{__base_route__}/redirect", TestRedirectResponse),
    Route(f"{__base_route__}/file", TestFileResponse),
    functional_route,
]

app = Hypern(routes=routes)
app.inject("global_dependencies", "global_dependencies")
app.inject("router_dependencies", "router_dependencies")

if __name__ == "__main__":
    app.start()
