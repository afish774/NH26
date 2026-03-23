"""
Voice Router for NexDesk.

Handles:
1. Voice chat (transcribe + RAG response)
2. Voice ticket creation (transcribe + classify)
3. Audio file uploads
"""

import os
import uuid
import base64
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta

from database.connection import get_db
from database.models import Ticket, ChatMessage, AiAuditLog
from aws.transcribe import (
    transcribe_audio,
    process_voice_with_rag,
    create_ticket_from_voice,
    TranscriptionResult,
)

router = APIRouter()

# Supported audio formats
SUPPORTED_FORMATS = {
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/webm",
    "audio/ogg",
    "audio/flac",
}

MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25MB (Groq Whisper limit)


def validate_audio(content_type: str, size: int) -> None:
    """Validate audio file format and size."""
    if content_type not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {content_type}. Supported: wav, mp3, mp4, m4a, webm, ogg, flac",
        )

    if size > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=400, detail=f"Audio file too large. Maximum size: 25MB"
        )


@router.post("/transcribe")
async def transcribe_audio_endpoint(
    audio: UploadFile = File(...), language: str = Form(default="en")
):
    """
    Transcribe audio to text.

    Accepts audio file upload.
    Returns transcript with confidence and metadata.
    """
    content_type = audio.content_type or "audio/wav"
    audio_data = await audio.read()

    validate_audio(content_type, len(audio_data))

    result = transcribe_audio(
        audio_data=audio_data, filename=audio.filename or "audio.wav", language=language
    )

    if result.error:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Transcription failed",
                "details": result.error,
                "source": result.source,
            },
        )

    return {
        "transcript": result.text,
        "confidence": result.confidence,
        "language": result.language,
        "duration_seconds": result.duration_seconds,
        "source": result.source,
        "latency_ms": result.latency_ms,
    }


@router.post("/chat")
async def voice_chat(
    audio: UploadFile = File(...),
    session_id: Optional[str] = Form(default=None),
    language: str = Form(default="en"),
    db: Session = Depends(get_db),
):
    """
    Voice-based chat with AI deflection.

    1. Transcribes audio
    2. Processes through RAG pipeline (LangGraph agent)
    3. Returns response with transcript

    Same deflection logic as text chat.
    """
    content_type = audio.content_type or "audio/wav"
    audio_data = await audio.read()

    validate_audio(content_type, len(audio_data))

    session_id = session_id or str(uuid.uuid4())

    # Process voice through RAG
    result = process_voice_with_rag(
        audio_data=audio_data,
        filename=audio.filename or "audio.wav",
        session_id=session_id,
        history=[],  # Could be extended to support voice conversation history
    )

    if result.get("transcription_error"):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Voice processing failed",
                "details": result.get("transcription_error"),
                "session_id": session_id,
            },
        )

    # Persist messages
    try:
        db.add(
            ChatMessage(
                session_id=session_id,
                role="user",
                content=result["transcript"],
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

        # Audit log
        db.add(
            AiAuditLog(
                action_type="voice_deflect"
                if result["deflected"]
                else "voice_escalate",
                input_text=result["transcript"][:500],
                ai_output={
                    "reply": result["reply"][:200],
                    "confidence": result["confidence"],
                    "transcript_source": result.get("transcript_source"),
                    "intent": result.get("intent"),
                },
                confidence=result["confidence"],
                model_used="voice_rag",
                latency_ms=result.get("latency_ms", 0),
                aws_used=result.get("transcript_source") == "aws_transcribe",
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Database error during voice chat persistence: {e}")

    return {"session_id": session_id, **result}


@router.post("/ticket")
async def create_voice_ticket(
    audio: UploadFile = File(...),
    user_id: str = Form(default="voice_user"),
    language: str = Form(default="en"),
    db: Session = Depends(get_db),
):
    """
    Create a support ticket from voice input.

    1. Transcribes audio
    2. Classifies with advanced RAG
    3. Creates ticket with smart suggested reply
    """
    content_type = audio.content_type or "audio/wav"
    audio_data = await audio.read()

    validate_audio(content_type, len(audio_data))

    # Process voice to ticket data
    result = create_ticket_from_voice(
        audio_data=audio_data, filename=audio.filename or "audio.wav", user_id=user_id
    )

    if result.get("error"):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Voice ticket creation failed",
                "details": result.get("details", result.get("error")),
            },
        )

    # Create ticket in database
    try:
        from ai.classifier import SLA_HOURS

        ticket = Ticket(
            id=str(uuid.uuid4()),
            title=result.get("suggested_title", result["transcript"][:100]),
            description=result["transcript"],
            category=result["category"],
            priority=result["priority"],
            ai_summary=result.get("ai_summary", ""),
            ai_suggested_reply=result.get("ai_suggested_reply", ""),
            ai_confidence=result["confidence"],
            sla_deadline=datetime.utcnow()
            + timedelta(hours=result.get("sla_hours", 8)),
            sla_hours=result.get("sla_hours", 8),
            user_id=user_id,
            voice_transcript=result["transcript"],
        )

        db.add(ticket)

        # Audit log
        db.add(
            AiAuditLog(
                ticket_id=ticket.id,
                action_type="voice_classify",
                input_text=result["transcript"][:500],
                ai_output={
                    "category": result["category"],
                    "priority": result["priority"],
                    "confidence": result["confidence"],
                    "transcript_confidence": result.get("transcript_confidence"),
                },
                confidence=result["confidence"],
                model_used="voice_classifier",
                latency_ms=result.get("latency_ms", 0),
            )
        )

        db.commit()
        db.refresh(ticket)

        return {
            "ticket_id": ticket.id,
            "title": ticket.title,
            "description": ticket.description,
            "category": ticket.category,
            "priority": ticket.priority,
            "status": ticket.status.value
            if hasattr(ticket.status, "value")
            else ticket.status,
            "ai_summary": ticket.ai_summary,
            "ai_suggested_reply": ticket.ai_suggested_reply,
            "ai_confidence": ticket.ai_confidence,
            "sla_deadline": str(ticket.sla_deadline),
            "voice_transcript": result["transcript"],
            "transcript_confidence": result.get("transcript_confidence", 0.0),
            "created_at": str(ticket.created_at),
            "latency_ms": result.get("latency_ms", 0),
        }

    except Exception as e:
        db.rollback()
        print(f"Database error during voice ticket creation: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create ticket: {str(e)}"
        )


@router.post("/base64/transcribe")
async def transcribe_base64_audio(
    audio_base64: str = Form(...),
    filename: str = Form(default="audio.wav"),
    language: str = Form(default="en"),
):
    """
    Transcribe base64-encoded audio.

    Useful for web apps that capture audio as base64.
    """
    try:
        audio_data = base64.b64decode(audio_base64)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid base64 encoding: {str(e)}"
        )

    if len(audio_data) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=400, detail="Audio data too large. Maximum: 25MB"
        )

    result = transcribe_audio(
        audio_data=audio_data, filename=filename, language=language
    )

    if result.error:
        return JSONResponse(
            status_code=500,
            content={"error": "Transcription failed", "details": result.error},
        )

    return {
        "transcript": result.text,
        "confidence": result.confidence,
        "language": result.language,
        "duration_seconds": result.duration_seconds,
        "source": result.source,
        "latency_ms": result.latency_ms,
    }


@router.get("/config")
async def get_voice_config():
    """Get current voice configuration."""
    return {
        "transcription_provider": "aws_transcribe"
        if os.getenv("USE_AWS", "false").lower() == "true"
        else "groq_whisper",
        "supported_formats": list(SUPPORTED_FORMATS),
        "max_file_size_mb": MAX_AUDIO_SIZE / (1024 * 1024),
        "advanced_rag_enabled": os.getenv("USE_ADVANCED_RAG", "true").lower() == "true",
        "default_language": "en",
    }
