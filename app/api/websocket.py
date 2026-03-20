"""WebSocket endpoint for real-time signal and price push.

All connected clients receive broadcasts when:
  - Price updates (every monitor poll cycle)
  - Signal fires (entry conditions met)
  - Regime changes
  - Calendar alerts
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info("WebSocket disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send a JSON message to all connected clients."""
        if not self._connections:
            return
        message = json.dumps(data)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


# Singleton manager — imported by monitor.py
manager = ConnectionManager()


async def broadcast(data: dict[str, Any]) -> None:
    """Module-level shortcut for broadcasting."""
    await manager.broadcast(data)


@router.websocket("/ws/signals")
async def websocket_signals(ws: WebSocket):
    """WebSocket endpoint for real-time signal push."""
    await manager.connect(ws)
    try:
        while True:
            # Keep alive — client can send pings or commands
            data = await ws.receive_text()
            # Echo back for debugging or handle client commands
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
