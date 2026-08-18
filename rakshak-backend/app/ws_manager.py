from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, Set[WebSocket]] = {}

    async def connect(self, sat_id: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(sat_id, set()).add(ws)

    def disconnect(self, sat_id: str, ws: WebSocket):
        if sat_id in self.active:
            self.active[sat_id].discard(ws)

    async def broadcast(self, sat_id: str, message: dict):
        dead = []
        for ws in list(self.active.get(sat_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(sat_id, ws)


manager = ConnectionManager()
