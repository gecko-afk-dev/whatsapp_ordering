import logging
from fastapi import WebSocket
from typing import Dict, List

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # This dictionary stores active connections: {restaurant_id: [list_of_websockets]}
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, restaurant_id: int):
        await websocket.accept()
        if restaurant_id not in self.active_connections:
            self.active_connections[restaurant_id] = []
        self.active_connections[restaurant_id].append(websocket)

    def disconnect(self, websocket: WebSocket, restaurant_id: int):
        if restaurant_id in self.active_connections:
            self.active_connections[restaurant_id].remove(websocket)

    async def broadcast_to_restaurant(self, restaurant_id: int, message: dict):
        """Sends a message ONLY to the specific restaurant's dashboards"""
        if restaurant_id not in self.active_connections:
            return

        for connection in list(self.active_connections[restaurant_id]):
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.warning(
                    "WebSocket send failed for restaurant %s: %s",
                    restaurant_id,
                    exc,
                )
                self.disconnect(connection, restaurant_id)

# One global manager for the whole app
manager = ConnectionManager()