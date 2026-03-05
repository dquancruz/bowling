"""
Manager de conexiones WebSocket
Permite broadcast a todos los clientes conectados
"""

from fastapi import WebSocket
from typing import List
import logging
import json

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"🔌 Cliente conectado. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"🔌 Cliente desconectado. Total: {len(self.active_connections)}")

    async def broadcast(self, data: dict):
        """Enviar mensaje a todos los clientes conectados"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.warning(f"Error al enviar WebSocket: {e}")
                disconnected.append(connection)

        # Limpiar conexiones muertas
        for conn in disconnected:
            self.disconnect(conn)
