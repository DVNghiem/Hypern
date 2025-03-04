from hypern.hypern import WebsocketRouter
from hypern.ws.route import WebsocketRoute


class WebsocketManager:
    def __init__(self):
        self.websocket_router = WebsocketRouter(path="/")

    def add_websocket(self, ws_route: WebsocketRoute):
        for route in ws_route.routes:
            self.websocket_router.add_route(route=route)
