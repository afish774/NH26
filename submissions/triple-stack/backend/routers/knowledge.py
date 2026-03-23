"""
Knowledge Base Management Router.

Provides endpoints for:
- Managing knowledge sources
- Detecting and resolving conflicts
- Tracking knowledge gaps
- Scope control for sources
- Knowledge base unification
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database.connection import get_db
from database.models import KnowledgeSource, KnowledgeGap, KnowledgeConflict
from schemas.models import (
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    KnowledgeGapResponse,
    KnowledgeConflictResponse,
    KnowledgeConflictResolveRequest,
    KnowledgeDashboardResponse,
    KnowledgeSyncRequest,
    KnowledgeScopeUpdateRequest,
)
from utils.exceptions import (
    KnowledgeSourceNotFoundError,
    ValidationError,
    DatabaseError,
)
from utils.websocket_manager import manager as ws_manager
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# Knowledge Source Management
# =============================================================================


@router.post("/sources", response_model=KnowledgeSourceResponse)
async def create_source(
    req: KnowledgeSourceCreate,
    db: Session = Depends(get_db),
):
    """
    Add a new knowledge source.

    Knowledge sources can be:
    - faq: FAQ documents
    - document: General documents
    - api: External API endpoints
    - confluence: Confluence pages
    - zendesk: Zendesk articles
    """
    # Check for duplicate
    existing = (
        db.query(KnowledgeSource)
        .filter(KnowledgeSource.name == req.name, KnowledgeSource.is_active == True)
        .first()
    )
    if existing:
        raise ValidationError("name", f"Source with name '{req.name}' already exists")

    source = KnowledgeSource(
        id=str(uuid.uuid4()),
        name=req.name,
        source_type=req.source_type,
        content=req.content,
        url=req.url,
        scope=req.scope,
        priority=req.priority,
        is_active=req.is_active,
        entry_count=0,
        created_at=datetime.utcnow(),
    )

    try:
        db.add(source)
        db.commit()
        db.refresh(source)
        logger.info(f"Knowledge source created: {source.name} ({source.source_type})")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create knowledge source: {e}")
        raise DatabaseError(f"Failed to create source: {e}")

    return _source_to_response(source)


@router.get("/sources", response_model=List[KnowledgeSourceResponse])
async def list_sources(
    db: Session = Depends(get_db),
    source_type: Optional[str] = Query(None, description="Filter by type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    scope: Optional[str] = Query(None, description="Filter by scope tag"),
):
    """Get all knowledge sources."""
    query = db.query(KnowledgeSource)

    if source_type:
        query = query.filter(KnowledgeSource.source_type == source_type)
    if is_active is not None:
        query = query.filter(KnowledgeSource.is_active == is_active)
    if scope:
        query = query.filter(KnowledgeSource.scope.contains([scope]))

    sources = query.order_by(KnowledgeSource.name).all()
    return [_source_to_response(s) for s in sources]


@router.get("/sources/{source_id}", response_model=KnowledgeSourceResponse)
async def get_source(source_id: str, db: Session = Depends(get_db)):
    """Get details for a specific knowledge source."""
    source = db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
    if not source:
        raise KnowledgeSourceNotFoundError(source_id)
    return _source_to_response(source)


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: str,
    name: Optional[str] = None,
    priority: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """Update a knowledge source."""
    source = db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
    if not source:
        raise KnowledgeSourceNotFoundError(source_id)

    if name is not None:
        source.name = name
    if priority is not None:
        source.priority = priority
    if is_active is not None:
        source.is_active = is_active

    try:
        db.commit()
        logger.info(f"Knowledge source updated: {source_id}")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to update source: {e}")

    return {"success": True, "source_id": source_id}


@router.patch("/sources/{source_id}/scope")
async def update_source_scope(
    source_id: str,
    req: KnowledgeScopeUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Update scope for a knowledge source.

    Scope controls when this source is used for RAG retrieval.
    Examples: ["billing", "technical"], ["all"], ["premium_support"]
    """
    source = db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
    if not source:
        raise KnowledgeSourceNotFoundError(source_id)

    source.scope = req.scope

    try:
        db.commit()
        logger.info(f"Knowledge source scope updated: {source_id} -> {req.scope}")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to update scope: {e}")

    return {"success": True, "source_id": source_id, "new_scope": req.scope}


@router.post("/sources/{source_id}/sync")
async def sync_source(
    source_id: str,
    req: KnowledgeSyncRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger sync for a knowledge source.

    For external sources (API, Confluence, etc.), this fetches
    the latest content and updates the knowledge base.
    """
    source = db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
    if not source:
        raise KnowledgeSourceNotFoundError(source_id)

    # Queue sync in background
    background_tasks.add_task(_sync_knowledge_source, source_id, req.force)

    return {
        "success": True,
        "source_id": source_id,
        "message": "Sync started in background",
        "force": req.force,
    }


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, db: Session = Depends(get_db)):
    """Deactivate a knowledge source."""
    source = db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
    if not source:
        raise KnowledgeSourceNotFoundError(source_id)

    source.is_active = False

    try:
        db.commit()
        logger.info(f"Knowledge source deactivated: {source_id}")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to delete source: {e}")

    return {"success": True, "source_id": source_id, "action": "deactivated"}


# =============================================================================
# Knowledge Gaps
# =============================================================================


@router.get("/gaps", response_model=List[KnowledgeGapResponse])
async def list_gaps(
    db: Session = Depends(get_db),
    status: str = Query("open", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get detected knowledge gaps.

    Gaps are queries that the AI couldn't answer confidently,
    indicating missing information in the knowledge base.
    """
    query = db.query(KnowledgeGap)

    if status:
        query = query.filter(KnowledgeGap.status == status)

    gaps = query.order_by(KnowledgeGap.frequency.desc()).limit(limit).all()

    return [
        KnowledgeGapResponse(
            id=g.id,
            query=g.query,
            frequency=g.frequency,
            first_seen=str(g.first_seen),
            last_seen=str(g.last_seen),
            suggested_topics=g.suggested_topics or [],
            status=g.status,
        )
        for g in gaps
    ]


@router.post("/gaps/{gap_id}/address")
async def address_gap(
    gap_id: str,
    action: str = Query(..., description="Action: addressed, ignored"),
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Mark a knowledge gap as addressed or ignored."""
    gap = db.query(KnowledgeGap).filter(KnowledgeGap.id == gap_id).first()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap not found")

    if action not in ["addressed", "ignored"]:
        raise ValidationError("action", "Must be 'addressed' or 'ignored'")

    gap.status = action
    gap.addressed_at = datetime.utcnow()
    if notes:
        gap.notes = notes

    try:
        db.commit()
        logger.info(f"Knowledge gap {action}: {gap_id}")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to update gap: {e}")

    return {"success": True, "gap_id": gap_id, "action": action}


@router.post("/gaps/detect")
async def detect_gaps(
    background_tasks: BackgroundTasks,
    days: int = Query(7, ge=1, le=30, description="Days to analyze"),
    db: Session = Depends(get_db),
):
    """
    Run gap detection on recent queries.

    Analyzes chat sessions with low confidence scores
    to identify missing knowledge topics.
    """
    background_tasks.add_task(_detect_knowledge_gaps, days)

    return {
        "success": True,
        "message": f"Gap detection started for last {days} days",
    }


# =============================================================================
# Knowledge Conflicts
# =============================================================================


@router.get("/conflicts", response_model=List[KnowledgeConflictResponse])
async def list_conflicts(
    db: Session = Depends(get_db),
    status: str = Query("pending", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get detected knowledge conflicts.

    Conflicts occur when different sources provide
    contradictory information on the same topic.
    """
    query = db.query(KnowledgeConflict).join(
        KnowledgeSource, KnowledgeConflict.source_a_id == KnowledgeSource.id
    )

    if status:
        query = query.filter(KnowledgeConflict.status == status)

    conflicts = query.order_by(KnowledgeConflict.detected_at.desc()).limit(limit).all()

    return [_conflict_to_response(c, db) for c in conflicts]


@router.get("/conflicts/{conflict_id}")
async def get_conflict(conflict_id: str, db: Session = Depends(get_db)):
    """Get details for a specific conflict."""
    conflict = (
        db.query(KnowledgeConflict).filter(KnowledgeConflict.id == conflict_id).first()
    )
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")

    return _conflict_to_response(conflict, db)


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: str,
    req: KnowledgeConflictResolveRequest,
    db: Session = Depends(get_db),
):
    """
    Resolve a knowledge conflict.

    Resolutions:
    - prefer_a: Use source A's content
    - prefer_b: Use source B's content
    - merge: Use merged content (provide merged_content)
    - ignore: Mark as not a conflict
    """
    conflict = (
        db.query(KnowledgeConflict).filter(KnowledgeConflict.id == conflict_id).first()
    )
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")

    if req.resolution == "merge" and not req.merged_content:
        raise ValidationError(
            "merged_content", "Merged content required for merge resolution"
        )

    conflict.status = "resolved"
    conflict.resolution = req.resolution
    conflict.merged_content = req.merged_content
    conflict.resolution_notes = req.notes
    conflict.resolved_at = datetime.utcnow()

    try:
        db.commit()
        logger.info(f"Knowledge conflict resolved: {conflict_id} ({req.resolution})")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to resolve conflict: {e}")

    return {"success": True, "conflict_id": conflict_id, "resolution": req.resolution}


@router.post("/conflicts/detect")
async def detect_conflicts(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Run conflict detection across knowledge sources.

    Compares entries across sources to find contradictions.
    """
    background_tasks.add_task(_detect_knowledge_conflicts)

    return {
        "success": True,
        "message": "Conflict detection started",
    }


# =============================================================================
# Dashboard
# =============================================================================


@router.get("/dashboard", response_model=KnowledgeDashboardResponse)
async def get_dashboard(db: Session = Depends(get_db)):
    """
    Get knowledge base dashboard overview.

    Shows:
    - Source statistics
    - Coverage score
    - Open gaps
    - Pending conflicts
    """
    # Get sources
    sources = db.query(KnowledgeSource).filter(KnowledgeSource.is_active == True).all()
    total_sources = len(sources)
    total_entries = sum(s.entry_count or 0 for s in sources)

    # Count gaps and conflicts
    open_gaps = db.query(KnowledgeGap).filter(KnowledgeGap.status == "open").count()
    pending_conflicts = (
        db.query(KnowledgeConflict)
        .filter(KnowledgeConflict.status == "pending")
        .count()
    )

    # Calculate coverage score (simplified)
    # In production, this would analyze query success rates
    coverage_score = (
        min(100.0, (total_entries / 100) * 100) if total_entries > 0 else 0.0
    )

    # Get recent gaps
    recent_gaps = (
        db.query(KnowledgeGap)
        .filter(KnowledgeGap.status == "open")
        .order_by(KnowledgeGap.frequency.desc())
        .limit(5)
        .all()
    )

    # Get pending conflicts
    conflicts = (
        db.query(KnowledgeConflict)
        .filter(KnowledgeConflict.status == "pending")
        .order_by(KnowledgeConflict.detected_at.desc())
        .limit(5)
        .all()
    )

    return KnowledgeDashboardResponse(
        total_sources=total_sources,
        active_sources=total_sources,
        total_entries=total_entries,
        coverage_score=round(coverage_score, 2),
        open_gaps=open_gaps,
        pending_conflicts=pending_conflicts,
        sources=[_source_to_response(s) for s in sources],
        recent_gaps=[
            KnowledgeGapResponse(
                id=g.id,
                query=g.query,
                frequency=g.frequency,
                first_seen=str(g.first_seen),
                last_seen=str(g.last_seen),
                suggested_topics=g.suggested_topics or [],
                status=g.status,
            )
            for g in recent_gaps
        ],
        pending_conflicts_list=[_conflict_to_response(c, db) for c in conflicts],
    )


# =============================================================================
# Background Tasks
# =============================================================================


async def _sync_knowledge_source(source_id: str, force: bool = False):
    """Background task to sync a knowledge source."""
    from database.connection import SessionLocal

    db = SessionLocal()
    try:
        source = (
            db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
        )
        if not source:
            logger.error(f"Source not found for sync: {source_id}")
            return

        # In production, this would:
        # 1. Fetch content from source URL/API
        # 2. Parse and chunk the content
        # 3. Update ChromaDB/vector store
        # 4. Update entry_count

        source.last_synced = datetime.utcnow()
        db.commit()

        logger.info(f"Knowledge source synced: {source.name}")
    finally:
        db.close()


async def _detect_knowledge_gaps(days: int = 7):
    """Background task to detect knowledge gaps."""
    from database.connection import SessionLocal
    from database.models import AiAuditLog

    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(days=days)

        # Find low-confidence queries
        low_confidence = (
            db.query(AiAuditLog)
            .filter(
                AiAuditLog.timestamp >= since,
                AiAuditLog.confidence < 0.5,  # Low confidence threshold
                AiAuditLog.action_type == "chat",
            )
            .all()
        )

        # Group by similar queries and track frequency
        gap_queries = {}
        for log in low_confidence:
            query = log.input_text[:200] if log.input_text else ""
            if query:
                if query in gap_queries:
                    gap_queries[query]["frequency"] += 1
                    gap_queries[query]["last_seen"] = log.timestamp
                else:
                    gap_queries[query] = {
                        "frequency": 1,
                        "first_seen": log.timestamp,
                        "last_seen": log.timestamp,
                    }

        # Create or update gaps
        for query, data in gap_queries.items():
            if data["frequency"] >= 2:  # Only track repeated gaps
                existing = (
                    db.query(KnowledgeGap).filter(KnowledgeGap.query == query).first()
                )

                if existing:
                    existing.frequency += data["frequency"]
                    existing.last_seen = data["last_seen"]
                else:
                    gap = KnowledgeGap(
                        id=str(uuid.uuid4()),
                        query=query,
                        frequency=data["frequency"],
                        first_seen=data["first_seen"],
                        last_seen=data["last_seen"],
                        status="open",
                    )
                    db.add(gap)

        db.commit()
        logger.info(f"Gap detection completed: {len(gap_queries)} potential gaps found")
    finally:
        db.close()


async def _detect_knowledge_conflicts():
    """Background task to detect knowledge conflicts."""
    from database.connection import SessionLocal

    db = SessionLocal()
    try:
        # In production, this would:
        # 1. Compare embeddings across sources
        # 2. Find semantically similar but textually different entries
        # 3. Use LLM to determine if they conflict

        # For now, just log that detection ran
        logger.info("Conflict detection completed (placeholder)")
    finally:
        db.close()


# =============================================================================
# Helpers
# =============================================================================


def _source_to_response(source: KnowledgeSource) -> KnowledgeSourceResponse:
    """Convert a KnowledgeSource model to response."""
    return KnowledgeSourceResponse(
        id=source.id,
        name=source.name,
        source_type=source.source_type,
        scope=source.scope or ["all"],
        priority=source.priority or 1,
        is_active=source.is_active,
        entry_count=source.entry_count or 0,
        last_synced=str(source.last_synced) if source.last_synced else None,
        created_at=str(source.created_at),
    )


def _conflict_to_response(
    conflict: KnowledgeConflict, db: Session
) -> KnowledgeConflictResponse:
    """Convert a KnowledgeConflict model to response."""
    source_a = (
        db.query(KnowledgeSource)
        .filter(KnowledgeSource.id == conflict.source_a_id)
        .first()
    )
    source_b = (
        db.query(KnowledgeSource)
        .filter(KnowledgeSource.id == conflict.source_b_id)
        .first()
    )

    return KnowledgeConflictResponse(
        id=conflict.id,
        topic=conflict.topic,
        source_a_id=conflict.source_a_id,
        source_a_name=source_a.name if source_a else "Unknown",
        source_a_content=conflict.source_a_content,
        source_b_id=conflict.source_b_id,
        source_b_name=source_b.name if source_b else "Unknown",
        source_b_content=conflict.source_b_content,
        detected_at=str(conflict.detected_at),
        resolution=conflict.resolution,
        status=conflict.status,
    )
