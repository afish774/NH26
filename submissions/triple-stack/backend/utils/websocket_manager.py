"""
WebSocket Manager for real-time updates.
"""

import json
import asyncio
from typing import Dict, Set, Optional, List
from datetime import datetime
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.channel_subscriptions: Dict[str, Set[WebSocket]] = {
            "tickets": set(),
            "chat": set(),
            "agents": set(),
            "analytics": set(),
            "all": set(),
        }
        self.connection_info: Dict[WebSocket, dict] = {}

    async def connect(
        self,
        websocket: WebSocket,
        user_id: Optional[str] = None,
        channels: List[str] = None,
    ):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)

        self.connection_info[websocket] = {
            "user_id": user_id,
            "channels": channels or ["all"],
            "connected_at": datetime.utcnow().isoformat(),
        }

        for channel in channels or ["all"]:
            if channel in self.channel_subscriptions:
                self.channel_subscriptions[channel].add(websocket)

        await self.send_personal(
            websocket,
            {
                "type": "connected",
                "message": "Connected to NexDesk real-time updates",
                "channels": channels or ["all"],
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        print(f"✅ WebSocket connected: {user_id or 'anonymous'} → {channels}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        self.active_connections.discard(websocket)

        for channel_subs in self.channel_subscriptions.values():
            channel_subs.discard(websocket)

        info = self.connection_info.pop(websocket, {})
        print(f"❌ WebSocket disconnected: {info.get('user_id', 'anonymous')}")

    async def send_personal(self, websocket: WebSocket, message: dict):
        """Send message to a specific connection."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"WebSocket send error: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connections."""
        disconnected = set()
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.add(conn)

        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_to_channel(self, channel: str, message: dict):
        """Broadcast message to channel subscribers."""
        if channel not in self.channel_subscriptions:
            return

        subscribers = self.channel_subscriptions[
            channel
        ] | self.channel_subscriptions.get("all", set())

        disconnected = set()
        for conn in subscribers:
            try:
                await conn.send_json({"channel": channel, **message})
            except Exception:
                disconnected.add(conn)

        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_to_user(self, user_id: str, message: dict):
        """Send message to a specific user."""
        for websocket, info in self.connection_info.items():
            if info.get("user_id") == user_id:
                await self.send_personal(websocket, message)

    async def send_to_user(self, user_id: str, message: dict):
        """Alias for broadcast_to_user - send message to a specific user."""
        await self.broadcast_to_user(user_id, message)

    def get_stats(self) -> dict:
        """Get connection statistics."""
        return {
            "total_connections": len(self.active_connections),
            "channels": {
                ch: len(subs) for ch, subs in self.channel_subscriptions.items()
            },
        }

    async def disconnect_all(self):
        """Disconnect all WebSocket connections (used during shutdown)."""
        for websocket in list(self.active_connections):
            try:
                await websocket.close()
            except Exception:
                pass
        self.active_connections.clear()
        for channel_subs in self.channel_subscriptions.values():
            channel_subs.clear()
        self.connection_info.clear()
        print("🔌 All WebSocket connections closed")


# Global instance
manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────────────────────
# EVENT HELPERS
# ─────────────────────────────────────────────────────────────────────────────


async def emit_ticket_event(event_type: str, ticket_data: dict):
    """Emit ticket event."""
    from utils.redis_client import publish_event

    event = {
        "type": event_type,
        "data": ticket_data,
        "timestamp": datetime.utcnow().isoformat(),
    }

    await manager.broadcast_to_channel("tickets", event)
    await publish_event("tickets", event_type, ticket_data)


async def emit_chat_event(event_type: str, chat_data: dict, session_id: str = None):
    """Emit chat event."""
    from utils.redis_client import publish_event

    event = {
        "type": event_type,
        "data": chat_data,
        "session_id": session_id,
        "timestamp": datetime.utcnow().isoformat(),
    }

    await manager.broadcast_to_channel("chat", event)
    await publish_event("chat", event_type, chat_data)


async def emit_agent_event(event_type: str, agent_data: dict):
    """Emit agent event."""
    from utils.redis_client import publish_event

    event = {
        "type": event_type,
        "data": agent_data,
        "timestamp": datetime.utcnow().isoformat(),
    }

    await manager.broadcast_to_channel("agents", event)
    await publish_event("agents", event_type, agent_data)


async def emit_analytics_update(analytics_data: dict):
    """Emit analytics update."""
    event = {
        "type": "analytics_update",
        "data": analytics_data,
        "timestamp": datetime.utcnow().isoformat(),
    }

    await manager.broadcast_to_channel("analytics", event)
