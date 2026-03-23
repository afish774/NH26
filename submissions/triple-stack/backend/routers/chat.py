import os
import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database.connection import get_db
from database.models import ChatMessage, AiAuditLog
from schemas.models import ChatRequest

router = APIRouter()

# Feature flag for advanced RAG
USE_ADVANCED_RAG = os.getenv("USE_ADVANCED_RAG", "true").lower() == "true"


def get_chat_handler():
    """Get the appropriate chat handler based on configuration."""
    if USE_ADVANCED_RAG:
        try:
            from ai.agent import run_agent

            return run_agent, "langgraph"
        except ImportError as e:
            print(f"Advanced RAG import failed: {e}, falling back to basic")

    from ai.rag import chat_with_deflection

    return chat_with_deflection, "basic"


@router.post("/")
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """
    Main chat endpoint with AI deflection.

    Uses LangGraph orchestrator with advanced RAG by default:
    - HyDE query expansion
    - Hybrid vector + BM25 retrieval
    - Cross-encoder reranking

    Set USE_ADVANCED_RAG=false to use basic RAG.
    """
    session_id = req.session_id or str(uuid.uuid4())

    # Get the appropriate handler
    handler, handler_type = get_chat_handler()

    # Call the handler
    if handler_type == "langgraph":
        result = handler(
            user_message=req.message, session_id=session_id, history=req.history
        )
    else:
        result = handler(req.message, req.history)

    # Persist messages
    db.add(
        ChatMessage(
            session_id=session_id,
            role="user",
            content=req.message,
            was_deflected=result["deflected"],
            confidence=result["confidence"],
        )
    )
    db.add(
        ChatMessage(
            session_id=session_id,
            role="assistant",
            content=result["reply"],
            was_deflected=result["deflected"],
            confidence=result["confidence"],
            knowledge_sources=result.get("knowledge_sources", []),
        )
    )

    try:
        # Audit log — every AI decision is logged
        model_used = "langgraph" if result.get("advanced_rag") else "groq"
        if result.get("aws_used"):
            model_used = "bedrock"

        db.add(
            AiAuditLog(
                action_type="deflect" if result["deflected"] else "escalate",
                input_text=req.message[:500],
                ai_output={
                    "reply": result["reply"][:200],
                    "confidence": result["confidence"],
                    "intent": result.get("intent"),
                    "hyde_used": result.get("hyde_used", False),
                    "rerank_used": result.get("rerank_used", False),
                },
                confidence=result["confidence"],
                model_used=model_used,
                latency_ms=result.get("latency_ms", 0),
                aws_used=result.get("aws_used", False),
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Database error during chat persistence: {e}")

    return {"session_id": session_id, **result}


@router.get("/config")
async def get_chat_config():
    """Get current chat configuration."""
    _, handler_type = get_chat_handler()

    return {
        "advanced_rag_enabled": USE_ADVANCED_RAG,
        "handler_type": handler_type,
        "hyde_enabled": os.getenv("HYDE_ENABLED", "true").lower() == "true",
        "cross_encoder_enabled": os.getenv("CROSS_ENCODER_ENABLED", "true").lower()
        == "true",
        "deflect_threshold": float(os.getenv("DEFLECT_THRESHOLD", "0.72")),
        "hybrid_alpha": float(os.getenv("HYBRID_ALPHA", "0.7")),
    }
