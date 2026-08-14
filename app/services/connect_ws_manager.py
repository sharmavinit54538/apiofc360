"""In-memory WebSocket Connection Manager for OFC360 Connect real-time events and WebRTC signaling."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
import uuid

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectWSManager:
    """Manages active WebSocket connections by user, tenant, and room."""

    def __init__(self) -> None:
        # Map: user_id -> set of active WebSockets
        self.active_user_connections: dict[uuid.UUID, set[WebSocket]] = {}
        # Map: user_id -> company_id
        self.user_tenants: dict[uuid.UUID, uuid.UUID] = {}
        # Map: room_id -> set of user_ids
        self.room_members: dict[str, set[uuid.UUID]] = {}
        # Map: WebSocket -> user_id
        self.socket_user_map: dict[WebSocket, uuid.UUID] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: uuid.UUID, company_id: uuid.UUID) -> None:
        """Register an accepted WebSocket connection."""
        async with self._lock:
            if user_id not in self.active_user_connections:
                self.active_user_connections[user_id] = set()
            self.active_user_connections[user_id].add(websocket)
            self.user_tenants[user_id] = company_id
            self.socket_user_map[websocket] = user_id

        logger.info("WebSocket connected | user_id=%s company_id=%s total_sockets=%d", user_id, company_id, len(self.socket_user_map))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a disconnected WebSocket."""
        async with self._lock:
            user_id = self.socket_user_map.pop(websocket, None)
            if user_id and user_id in self.active_user_connections:
                self.active_user_connections[user_id].discard(websocket)
                if not self.active_user_connections[user_id]:
                    del self.active_user_connections[user_id]
                    self.user_tenants.pop(user_id, None)

        logger.info("WebSocket disconnected | user_id=%s total_sockets=%d", user_id, len(self.socket_user_map))

    async def join_room(self, user_id: uuid.UUID, room_id: str) -> None:
        """Add user to a room (e.g. channel:123 or meeting:456)."""
        async with self._lock:
            if room_id not in self.room_members:
                self.room_members[room_id] = set()
            self.room_members[room_id].add(user_id)

    async def leave_room(self, user_id: uuid.UUID, room_id: str) -> None:
        """Remove user from a room."""
        async with self._lock:
            if room_id in self.room_members:
                self.room_members[room_id].discard(user_id)
                if not self.room_members[room_id]:
                    del self.room_members[room_id]

    async def send_to_user(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        event: str,
        data: Any,
    ) -> None:
        """Send a real-time event directly to all active sockets of a specific user in a tenant."""
        # Tenant isolation check
        target_company = self.user_tenants.get(user_id)
        if target_company and target_company != company_id:
            logger.warning("Prevented cross-tenant WebSocket message: sender_tenant=%s target_tenant=%s", company_id, target_company)
            return

        sockets = self.active_user_connections.get(user_id, set())
        if not sockets:
            return

        payload = {
            "event": event,
            "data": data,
            "timestamp": asyncio.get_event_loop().time(),
        }
        raw_msg = json.dumps(payload, default=str)

        dead_sockets: list[WebSocket] = []
        for ws in list(sockets):
            try:
                await ws.send_text(raw_msg)
            except Exception as e:
                logger.debug("Failed sending to ws for user %s: %s", user_id, e)
                dead_sockets.append(ws)

        if dead_sockets:
            for ws in dead_sockets:
                await self.disconnect(ws)

    async def send_to_room(
        self,
        room_id: str,
        company_id: uuid.UUID,
        event: str,
        data: Any,
        exclude_user_id: uuid.UUID | None = None,
    ) -> None:
        """Broadcast an event to all users currently subscribed to a room."""
        members = self.room_members.get(room_id, set())
        if not members:
            return

        tasks = []
        for member_id in list(members):
            if exclude_user_id and member_id == exclude_user_id:
                continue
            tasks.append(self.send_to_user(member_id, company_id, event, data))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_to_tenant(
        self,
        company_id: uuid.UUID,
        event: str,
        data: Any,
        exclude_user_id: uuid.UUID | None = None,
    ) -> None:
        """Broadcast an event to all connected users in a company."""
        target_users = [
            uid for uid, cid in self.user_tenants.items()
            if cid == company_id and (exclude_user_id is None or uid != exclude_user_id)
        ]
        tasks = [self.send_to_user(uid, company_id, event, data) for uid in target_users]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# Singleton instance provider
_ws_manager = ConnectWSManager()


def get_connect_ws_manager() -> ConnectWSManager:
    """Dependency provider for ConnectWSManager."""
    return _ws_manager
