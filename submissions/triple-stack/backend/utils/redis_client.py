"""
Redis client for caching, queuing, and pub/sub.
"""

import os
import json
import time
import uuid
from typing import Optional, Any, Dict
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Global client
_redis = None


def _get_sync_redis():
    """Get sync Redis client for non-async contexts."""
    import redis

    return redis.from_url(REDIS_URL, decode_responses=True)


async def get_redis():
    """Get or create async Redis connection."""
    global _redis

    try:
        import redis.asyncio as aioredis

        if _redis is not None:
            try:
                await _redis.ping()
                return _redis
            except Exception:
                _redis = None

        _redis = await aioredis.from_url(
            REDIS_URL, encoding="utf-8", decode_responses=True
        )
        await _redis.ping()
        print("✅ Redis connected")
        return _redis
    except Exception as e:
        print(f"⚠️ Redis unavailable: {e}")
        return None


async def close_redis():
    """Close Redis connection."""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


# ─────────────────────────────────────────────────────────────────────────────
# CACHING
# ─────────────────────────────────────────────────────────────────────────────


async def cache_get(key: str) -> Optional[Any]:
    """Get cached value."""
    client = await get_redis()
    if not client:
        return None
    try:
        val = await client.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    """Set cached value with TTL in seconds."""
    client = await get_redis()
    if not client:
        return False
    try:
        await client.setex(key, ttl, json.dumps(value))
        return True
    except Exception:
        return False


async def cache_delete(key: str) -> bool:
    """Delete cached key."""
    client = await get_redis()
    if not client:
        return False
    try:
        await client.delete(key)
        return True
    except Exception:
        return False


async def cache_invalidate_pattern(pattern: str) -> int:
    """Delete all keys matching pattern."""
    client = await get_redis()
    if not client:
        return 0
    try:
        keys = []
        async for key in client.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            return await client.delete(*keys)
        return 0
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────────────────────────────────────


async def check_rate_limit(key: str, limit: int, window: int):
    """Check rate limit. Returns (allowed, remaining)."""
    client = await get_redis()
    if not client:
        return True, limit

    try:
        current = await client.get(key)
        if current is None:
            await client.setex(key, window, 1)
            return True, limit - 1

        count = int(current)
        if count >= limit:
            return False, 0

        await client.incr(key)
        return True, limit - count - 1
    except Exception:
        return True, limit


# ─────────────────────────────────────────────────────────────────────────────
# JOB QUEUE
# ─────────────────────────────────────────────────────────────────────────────

QUEUE_KEY = "nexdesk:jobs"
PROCESSING_KEY = "nexdesk:jobs:processing"


async def enqueue_job(job_type: str, payload: dict, priority: int = 5) -> Optional[str]:
    """Add job to queue. Returns job_id."""
    client = await get_redis()
    if not client:
        return None

    try:
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "type": job_type,
            "payload": payload,
            "priority": priority,
            "created_at": time.time(),
        }
        await client.zadd(QUEUE_KEY, {json.dumps(job): priority})
        return job_id
    except Exception:
        return None


async def dequeue_job() -> Optional[dict]:
    """Get next job from queue."""
    client = await get_redis()
    if not client:
        return None

    try:
        result = await client.zpopmin(QUEUE_KEY, count=1)
        if result:
            job_data, _ = result[0]
            job = json.loads(job_data)
            await client.hset(PROCESSING_KEY, job["id"], json.dumps(job))
            return job
        return None
    except Exception:
        return None


async def complete_job(job_id: str) -> bool:
    """Mark job complete."""
    client = await get_redis()
    if not client:
        return False
    try:
        await client.hdel(PROCESSING_KEY, job_id)
        return True
    except Exception:
        return False


async def get_queue_stats() -> dict:
    """Get queue statistics."""
    client = await get_redis()
    if not client:
        return {"pending": 0, "processing": 0, "available": False}

    try:
        pending = await client.zcard(QUEUE_KEY)
        processing = await client.hlen(PROCESSING_KEY)
        return {"pending": pending, "processing": processing, "available": True}
    except Exception:
        return {"pending": 0, "processing": 0, "available": False}


# ─────────────────────────────────────────────────────────────────────────────
# PUB/SUB CHANNELS
# ─────────────────────────────────────────────────────────────────────────────

CHANNELS = {
    "tickets": "nexdesk:events:tickets",
    "chat": "nexdesk:events:chat",
    "agents": "nexdesk:events:agents",
    "analytics": "nexdesk:events:analytics",
}


async def publish_event(channel: str, event_type: str, data: dict) -> bool:
    """Publish event to Redis channel."""
    client = await get_redis()
    if not client:
        return False

    try:
        message = json.dumps(
            {"type": event_type, "data": data, "timestamp": time.time()}
        )
        channel_name = CHANNELS.get(channel, f"nexdesk:events:{channel}")
        await client.publish(channel_name, message)
        return True
    except Exception:
        return False


async def get_pubsub():
    """Get a pubsub instance."""
    client = await get_redis()
    if not client:
        return None
    return client.pubsub()


# ─────────────────────────────────────────────────────────────────────────────
# AGENT STATUS
# ─────────────────────────────────────────────────────────────────────────────

AGENT_STATUS_KEY = "nexdesk:agents:status"
AGENT_QUEUE_KEY = "nexdesk:agents:queue"


async def update_agent_status(agent_id: str, status: dict) -> bool:
    """Update agent status in Redis."""
    client = await get_redis()
    if not client:
        return False
    try:
        await client.hset(AGENT_STATUS_KEY, agent_id, json.dumps(status))
        return True
    except Exception:
        return False


async def get_agent_status(agent_id: str) -> Optional[dict]:
    """Get agent status from Redis."""
    client = await get_redis()
    if not client:
        return None
    try:
        data = await client.hget(AGENT_STATUS_KEY, agent_id)
        return json.loads(data) if data else None
    except Exception:
        return None


async def get_all_agent_statuses() -> dict:
    """Get all agent statuses."""
    client = await get_redis()
    if not client:
        return {}
    try:
        data = await client.hgetall(AGENT_STATUS_KEY)
        return {k: json.loads(v) for k, v in data.items()}
    except Exception:
        return {}


async def increment_agent_queue(agent_id: str, delta: int = 1) -> int:
    """Increment agent queue depth."""
    client = await get_redis()
    if not client:
        return 0
    try:
        result = await client.hincrby(AGENT_QUEUE_KEY, agent_id, delta)
        return max(0, result)
    except Exception:
        return 0


async def get_agent_queue_depth(agent_id: str) -> int:
    """Get agent queue depth from Redis."""
    client = await get_redis()
    if not client:
        return 0
    try:
        depth = await client.hget(AGENT_QUEUE_KEY, agent_id)
        return int(depth) if depth else 0
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STORAGE
# ─────────────────────────────────────────────────────────────────────────────


async def store_session(session_id: str, data: dict, ttl_hours: int = 24) -> bool:
    """Store chat session."""
    return await cache_set(f"nexdesk:session:{session_id}", data, ttl_hours * 3600)


async def get_session(session_id: str) -> Optional[dict]:
    """Get chat session."""
    return await cache_get(f"nexdesk:session:{session_id}")


# ─────────────────────────────────────────────────────────────────────────────
# REDIS CLIENT CLASS (for main.py lifecycle management)
# ─────────────────────────────────────────────────────────────────────────────


class RedisClient:
    """Wrapper class for Redis client lifecycle management."""

    async def connect(self) -> bool:
        """Initialize Redis connection. Returns True if connected."""
        client = await get_redis()
        return client is not None

    async def disconnect(self):
        """Close Redis connection."""
        await close_redis()

    async def health_check(self) -> bool:
        """Check if Redis is healthy."""
        client = await get_redis()
        if not client:
            return False
        try:
            await client.ping()
            return True
        except Exception:
            return False


# Export singleton instance
redis_client = RedisClient()
