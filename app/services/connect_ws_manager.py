"""In-memory WebSocket Connection Manager for OFC360 Connect real-time events and WebRTC signaling."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from typing import Any
import uuid

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _normalize_uuid(val: Any) -> uuid.UUID | None:
    """Normalize input into a valid uuid.UUID or return None."""
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val).strip())
    except (ValueError, AttributeError):
        return None


class ConnectWSManager:
    """Manages active WebSocket connections by user, tenant, and room with multi-device support."""

    def __init__(self) -> None:
        # Map: user_id (uuid.UUID) -> set of active WebSockets
        self.active_user_connections: dict[uuid.UUID, set[WebSocket]] = {}
        # Map: user_id (uuid.UUID) -> company_id (uuid.UUID)
        self.user_tenants: dict[uuid.UUID, uuid.UUID] = {}
        # Map: room_id -> set of user_ids
        self.room_members: dict[str, set[uuid.UUID]] = {}
        # Map: WebSocket -> user_id
        self.socket_user_map: dict[WebSocket, uuid.UUID] = {}
        self._lock = asyncio.Lock()

    def is_online(self, user_id: uuid.UUID | str) -> bool:
        """Check if a specific user has at least one active WebSocket connection."""
        uid = _normalize_uuid(user_id)
        if not uid:
            return False
        sockets = self.active_user_connections.get(uid)
        return bool(sockets and len(sockets) > 0)

    def get_active_socket_count(self, user_id: uuid.UUID | str) -> int:
        """Return the number of active WebSocket connections for a user."""
        uid = _normalize_uuid(user_id)
        if not uid:
            return 0
        return len(self.active_user_connections.get(uid, set()))

    async def connect(
        self,
        websocket: WebSocket,
        user_id: uuid.UUID | str,
        company_id: uuid.UUID | str,
    ) -> None:
        """Register an accepted WebSocket connection."""
        uid = _normalize_uuid(user_id)
        cid = _normalize_uuid(company_id)
        if not uid or not cid:
            logger.warning("Rejecting WebSocket connection registration due to invalid UUIDs: user=%s company=%s", user_id, company_id)
            return

        async with self._lock:
            if uid not in self.active_user_connections:
                self.active_user_connections[uid] = set()
            self.active_user_connections[uid].add(websocket)
            self.user_tenants[uid] = cid
            self.socket_user_map[websocket] = uid

        logger.info(
            "WEBSOCKET_CONNECTED | user_id=%s company_id=%s user_sockets=%d total_sockets=%d",
            uid, cid, len(self.active_user_connections.get(uid, set())), len(self.socket_user_map),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a disconnected WebSocket and maintain other active sockets for the user."""
        uid: uuid.UUID | None = None
        remaining_count = 0
        async with self._lock:
            uid = self.socket_user_map.pop(websocket, None)
            if uid and uid in self.active_user_connections:
                self.active_user_connections[uid].discard(websocket)
                remaining_count = len(self.active_user_connections[uid])
                if remaining_count == 0:
                    del self.active_user_connections[uid]
                    self.user_tenants.pop(uid, None)

        if uid:
            logger.info(
                "WEBSOCKET_DISCONNECTED | user_id=%s remaining_user_sockets=%d total_sockets=%d",
                uid, remaining_count, len(self.socket_user_map),
            )

    async def join_room(self, user_id: uuid.UUID | str, room_id: str) -> None:
        """Add user to a room (e.g. channel:123 or meeting:456)."""
        uid = _normalize_uuid(user_id)
        if not uid or not room_id:
            return
        async with self._lock:
            if room_id not in self.room_members:
                self.room_members[room_id] = set()
            self.room_members[room_id].add(uid)

    async def leave_room(self, user_id: uuid.UUID | str, room_id: str) -> None:
        """Remove user from a room."""
        uid = _normalize_uuid(user_id)
        if not uid or not room_id:
            return
        async with self._lock:
            if room_id in self.room_members:
                self.room_members[room_id].discard(uid)
                if not self.room_members[room_id]:
                    del self.room_members[room_id]

    async def send_to_user(
        self,
        user_id: uuid.UUID | str,
        company_id: uuid.UUID | str,
        event: str,
        data: Any,
    ) -> int:
        """Send a real-time event to all active sockets of a user with dual-compatible payload format.

        Returns number of successful deliveries.
        """
        uid = _normalize_uuid(user_id)
        cid = _normalize_uuid(company_id)
        if not uid or not cid:
            logger.warning("send_to_user aborted: invalid user_id=%s or company_id=%s", user_id, company_id)
            return 0

        # Tenant isolation check
        target_company = self.user_tenants.get(uid)
        if target_company and target_company != cid:
            logger.warning(
                "Prevented cross-tenant WebSocket message: sender_tenant=%s target_tenant=%s target_user=%s",
                cid, target_company, uid,
            )
            return 0

        sockets = list(self.active_user_connections.get(uid, set()))
        if not sockets:
            if event.startswith("call:"):
                logger.info("CALL_INCOMING_DELIVERY_FAILED | user_offline | user_id=%s event=%s", uid, event)
            return 0

        # Build dual-compatible payload for frontends expecting root-level fields or nested data
        iso_timestamp = datetime.utcnow().isoformat()
        payload: dict[str, Any] = {
            "type": event,
            "event": event,
            "timestamp": iso_timestamp,
        }

        if isinstance(data, dict):
            # Unpack all data properties at the root level
            for k, v in data.items():
                if k not in payload:
                    payload[k] = v
            payload["data"] = data
        else:
            payload["data"] = data

        raw_msg = json.dumps(payload, default=str)

        dead_sockets: list[WebSocket] = []
        success_count = 0

        for ws in sockets:
            try:
                await ws.send_text(raw_msg)
                success_count += 1
            except Exception as e:
                logger.debug("Failed sending to websocket for user %s: %s", uid, e)
                dead_sockets.append(ws)

        if dead_sockets:
            for ws in dead_sockets:
                await self.disconnect(ws)

        if success_count > 0 and event.startswith("call:"):
            logger.info("CALL_DELIVERED | user_id=%s event=%s delivered_sockets=%d", uid, event, success_count)

        return success_count

    async def send_to_room(
        self,
        room_id: str,
        company_id: uuid.UUID | str,
        event: str,
        data: Any,
        exclude_user_id: uuid.UUID | str | None = None,
    ) -> None:
        """Broadcast an event to all users currently subscribed to a room."""
        members = self.room_members.get(room_id, set())
        if not members:
            return

        cid = _normalize_uuid(company_id)
        ex_uid = _normalize_uuid(exclude_user_id) if exclude_user_id else None
        if not cid:
            return

        tasks = []
        for member_id in list(members):
            if ex_uid and member_id == ex_uid:
                continue
            tasks.append(self.send_to_user(member_id, cid, event, data))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_to_tenant(
        self,
        company_id: uuid.UUID | str,
        event: str,
        data: Any,
        exclude_user_id: uuid.UUID | str | None = None,
    ) -> None:
        """Broadcast an event to all connected users in a company."""
        cid = _normalize_uuid(company_id)
        ex_uid = _normalize_uuid(exclude_user_id) if exclude_user_id else None
        if not cid:
            return

        target_users = [
            uid for uid, target_cid in self.user_tenants.items()
            if target_cid == cid and (ex_uid is None or uid != ex_uid)
        ]
        tasks = [self.send_to_user(uid, cid, event, data) for uid in target_users]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# Singleton instance provider
_ws_manager = ConnectWSManager()


def get_connect_ws_manager() -> ConnectWSManager:
    """Dependency provider for ConnectWSManager."""
    return _ws_manager

