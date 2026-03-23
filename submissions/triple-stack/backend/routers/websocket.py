"""
WebSocket router for real-time updates.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional, List
from utils.websocket_manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: Optional[str] = Query(None),
    channels: Optional[str] = Query(None),  # comma-separated channels
):
    """
    WebSocket endpoint for real-time updates.

    Query params:
    - user_id: Optional user identifier
    - channels: Comma-separated list of channels (tickets,chat,agents,analytics,all)

    Example: ws://localhost:8000/ws?user_id=user123&channels=tickets,chat
    """
    channel_list = channels.split(",") if channels else ["all"]

    await manager.connect(websocket, user_id, channel_list)

    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()

            # Handle different message types
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await manager.send_personal(websocket, {"type": "pong"})

            elif msg_type == "subscribe":
                # Subscribe to additional channels
                new_channels = data.get("channels", [])
                for ch in new_channels:
                    if ch in manager.channel_subscriptions:
                        manager.channel_subscriptions[ch].add(websocket)
                await manager.send_personal(
                    websocket, {"type": "subscribed", "channels": new_channels}
                )

            elif msg_type == "unsubscribe":
                # Unsubscribe from channels
                remove_channels = data.get("channels", [])
                for ch in remove_channels:
                    if ch in manager.channel_subscriptions:
                        manager.channel_subscriptions[ch].discard(websocket)
                await manager.send_personal(
                    websocket, {"type": "unsubscribed", "channels": remove_channels}
                )

            elif msg_type == "stats":
                # Return connection stats
                await manager.send_personal(
                    websocket, {"type": "stats", "data": manager.get_stats()}
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


@router.get("/ws/stats")
async def get_websocket_stats():
    """Get WebSocket connection statistics."""
    return manager.get_stats()
