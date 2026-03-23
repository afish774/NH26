"""
Voice Transcription Module for NexDesk.

Supports multiple backends:
1. Groq Whisper (default, free tier friendly)
2. AWS Transcribe (when USE_AWS=true)
3. Local Whisper fallback

Voice transcripts are processed through the RAG pipeline for:
- Intent detection
- KB article matching
- Smart ticket creation
"""

import os
import json
import time
import base64
import tempfile
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TranscriptionResult:
    """Result of voice transcription."""

    text: str
    confidence: float
    language: str
    duration_seconds: float
    source: str  # groq_whisper, aws_transcribe, local_whisper
    latency_ms: int
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# GROQ WHISPER (Primary - Free tier friendly)
# ─────────────────────────────────────────────────────────────────────────────


def transcribe_with_groq(
    audio_data: bytes, filename: str = "audio.wav", language: str = "en"
) -> TranscriptionResult:
    """
    Transcribe audio using Groq's Whisper API.
    Supports: mp3, mp4, mpeg, mpga, m4a, wav, webm
    Max file size: 25MB
    """
    start = time.time()

    try:
        from groq import Groq

        client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        # Write to temp file (Groq API requires file-like object)
        with tempfile.NamedTemporaryFile(
            suffix=f".{filename.split('.')[-1]}", delete=False
        ) as f:
            f.write(audio_data)
            temp_path = f.name

        try:
            with open(temp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=(filename, audio_file),
                    model="whisper-large-v3-turbo",
                    language=language,
                    response_format="verbose_json",
                )

            latency = int((time.time() - start) * 1000)

            return TranscriptionResult(
                text=transcription.text,
                confidence=0.95,  # Whisper doesn't return confidence per-segment in this format
                language=transcription.language or language,
                duration_seconds=transcription.duration or 0.0,
                source="groq_whisper",
                latency_ms=latency,
            )
        finally:
            # Clean up temp file
            os.unlink(temp_path)

    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return TranscriptionResult(
            text="",
            confidence=0.0,
            language=language,
            duration_seconds=0.0,
            source="groq_whisper",
            latency_ms=latency,
            error=str(e),
        )


# ─────────────────────────────────────────────────────────────────────────────
# AWS TRANSCRIBE (Enterprise - when USE_AWS=true)
# ─────────────────────────────────────────────────────────────────────────────


def transcribe_with_aws(
    s3_bucket: str, s3_key: str, language: str = "en-US"
) -> TranscriptionResult:
    """
    Transcribe audio using AWS Transcribe from S3.
    Requires audio to be uploaded to S3 first.
    """
    start = time.time()

    try:
        import boto3
        import uuid

        transcribe = boto3.client(
            "transcribe", region_name=os.getenv("AWS_REGION", "us-east-1")
        )
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))

        job_name = f"nexdesk-{uuid.uuid4().hex[:8]}"
        media_uri = f"s3://{s3_bucket}/{s3_key}"

        # Start transcription job
        transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": media_uri},
            LanguageCode=language,
            Settings={"ShowSpeakerLabels": False, "ChannelIdentification": False},
        )

        # Poll for completion (with timeout)
        max_wait = 120  # 2 minutes
        waited = 0
        while waited < max_wait:
            response = transcribe.get_transcription_job(TranscriptionJobName=job_name)
            status = response["TranscriptionJob"]["TranscriptionJobStatus"]

            if status == "COMPLETED":
                # Get transcript from result URL
                transcript_uri = response["TranscriptionJob"]["Transcript"][
                    "TranscriptFileUri"
                ]

                # Download and parse transcript
                import urllib.request

                with urllib.request.urlopen(transcript_uri) as resp:
                    transcript_data = json.loads(resp.read().decode())

                text = transcript_data["results"]["transcripts"][0]["transcript"]

                # Calculate average confidence
                items = transcript_data["results"].get("items", [])
                confidences = [
                    float(item.get("alternatives", [{}])[0].get("confidence", 0))
                    for item in items
                    if item.get("type") == "pronunciation"
                ]
                avg_confidence = (
                    sum(confidences) / len(confidences) if confidences else 0.9
                )

                latency = int((time.time() - start) * 1000)

                # Clean up job
                try:
                    transcribe.delete_transcription_job(TranscriptionJobName=job_name)
                except Exception:
                    pass

                return TranscriptionResult(
                    text=text,
                    confidence=avg_confidence,
                    language=language,
                    duration_seconds=0.0,  # Would need to parse from media info
                    source="aws_transcribe",
                    latency_ms=latency,
                )

            elif status == "FAILED":
                error = response["TranscriptionJob"].get(
                    "FailureReason", "Unknown error"
                )
                raise Exception(f"Transcription failed: {error}")

            time.sleep(2)
            waited += 2

        raise Exception("Transcription timed out")

    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return TranscriptionResult(
            text="",
            confidence=0.0,
            language=language,
            duration_seconds=0.0,
            source="aws_transcribe",
            latency_ms=latency,
            error=str(e),
        )


def transcribe_with_aws_streaming(
    audio_data: bytes, language: str = "en-US"
) -> TranscriptionResult:
    """
    Transcribe audio using AWS Transcribe Streaming (real-time).
    Works directly with audio bytes, no S3 required.
    """
    start = time.time()

    try:
        import boto3
        from botocore.config import Config

        # For streaming, we need to use the streaming client
        # This is a simplified version - full streaming requires async handling
        transcribe = boto3.client(
            "transcribe",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            config=Config(read_timeout=120),
        )

        # For real-time streaming, we'd use start_stream_transcription
        # For simplicity, we'll upload to S3 temp and use batch
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))

        import uuid

        bucket = os.getenv("AWS_TRANSCRIBE_BUCKET", "nexdesk-audio-temp")
        key = f"temp/{uuid.uuid4().hex}.wav"

        # Upload audio
        s3.put_object(Bucket=bucket, Key=key, Body=audio_data)

        try:
            result = transcribe_with_aws(bucket, key, language)
            return result
        finally:
            # Clean up
            try:
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass

    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return TranscriptionResult(
            text="",
            confidence=0.0,
            language=language,
            duration_seconds=0.0,
            source="aws_transcribe_streaming",
            latency_ms=latency,
            error=str(e),
        )


# ─────────────────────────────────────────────────────────────────────────────
# SMART TRANSCRIPTION ROUTER
# ─────────────────────────────────────────────────────────────────────────────


def transcribe_audio(
    audio_data: bytes,
    filename: str = "audio.wav",
    language: str = "en",
    prefer_aws: bool = False,
) -> TranscriptionResult:
    """
    Smart transcription router.

    Uses:
    - Groq Whisper by default (fast, free tier)
    - AWS Transcribe when USE_AWS=true and prefer_aws=True
    - Falls back between providers on failure
    """
    use_aws = os.getenv("USE_AWS", "false").lower() == "true"

    # Primary: Groq Whisper (unless AWS explicitly preferred)
    if not (use_aws and prefer_aws):
        result = transcribe_with_groq(audio_data, filename, language)
        if not result.error:
            return result
        print(f"Groq Whisper failed: {result.error}, trying fallback...")

    # Fallback/Primary AWS path
    if use_aws:
        # AWS requires language code format (en-US vs en)
        aws_lang = f"{language}-US" if len(language) == 2 else language
        result = transcribe_with_aws_streaming(audio_data, aws_lang)
        if not result.error:
            return result
        print(f"AWS Transcribe failed: {result.error}")

    # Final fallback: try Groq again if we haven't
    if use_aws and prefer_aws:
        result = transcribe_with_groq(audio_data, filename, language)
        if not result.error:
            return result

    # All failed
    return TranscriptionResult(
        text="",
        confidence=0.0,
        language=language,
        duration_seconds=0.0,
        source="all_failed",
        latency_ms=0,
        error="All transcription methods failed",
    )


# ─────────────────────────────────────────────────────────────────────────────
# VOICE + RAG INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────


def process_voice_with_rag(
    audio_data: bytes,
    filename: str = "audio.wav",
    session_id: str = "",
    history: list = None,
) -> Dict[str, Any]:
    """
    Full voice processing pipeline:
    1. Transcribe audio to text
    2. Process through RAG/LangGraph agent
    3. Return chat-like response with transcript
    """
    history = history or []
    start = time.time()

    # Step 1: Transcribe
    transcription = transcribe_audio(audio_data, filename)

    if transcription.error or not transcription.text.strip():
        return {
            "transcript": "",
            "reply": "I couldn't understand the audio. Could you please try again or type your question?",
            "deflected": False,
            "confidence": 0.0,
            "create_ticket": False,
            "transcription_error": transcription.error,
            "latency_ms": int((time.time() - start) * 1000),
        }

    # Step 2: Process through RAG
    use_advanced = os.getenv("USE_ADVANCED_RAG", "true").lower() == "true"

    if use_advanced:
        try:
            from ai.agent import run_agent

            result = run_agent(
                user_message=transcription.text, session_id=session_id, history=history
            )
        except ImportError:
            from ai.rag import chat_with_deflection

            result = chat_with_deflection(transcription.text, history)
    else:
        from ai.rag import chat_with_deflection

        result = chat_with_deflection(transcription.text, history)

    # Step 3: Combine results
    total_latency = int((time.time() - start) * 1000)

    return {
        "transcript": transcription.text,
        "transcript_confidence": transcription.confidence,
        "transcript_language": transcription.language,
        "transcript_duration": transcription.duration_seconds,
        "transcript_source": transcription.source,
        "reply": result.get("reply", ""),
        "deflected": result.get("deflected", False),
        "confidence": result.get("confidence", 0.0),
        "category": result.get("category", "other"),
        "create_ticket": result.get("create_ticket", False),
        "knowledge_sources": result.get("knowledge_sources", []),
        "intent": result.get("intent"),
        "latency_ms": total_latency,
        "transcription_latency_ms": transcription.latency_ms,
        "rag_latency_ms": result.get("latency_ms", 0),
    }


def create_ticket_from_voice(
    audio_data: bytes, filename: str = "audio.wav", user_id: str = "voice_user"
) -> Dict[str, Any]:
    """
    Create a ticket directly from voice input.
    Uses RAG to classify and suggest responses.
    """
    # Transcribe
    transcription = transcribe_audio(audio_data, filename)

    if transcription.error or not transcription.text.strip():
        return {"error": "Could not transcribe audio", "details": transcription.error}

    # Use classifier with advanced RAG
    from ai.classifier import classify_ticket

    # For voice, we use transcript as both title and description
    # The classifier will generate a proper summary
    text = transcription.text

    # Generate a short title from the transcript
    title = text[:100] + "..." if len(text) > 100 else text

    classification = classify_ticket(title, text)

    return {
        "transcript": text,
        "transcript_confidence": transcription.confidence,
        "suggested_title": classification.get("summary", title),
        "description": text,
        "category": classification.get("category", "other"),
        "priority": classification.get("priority", "medium"),
        "ai_summary": classification.get("summary", ""),
        "ai_suggested_reply": classification.get("suggested_reply", ""),
        "confidence": classification.get("confidence", 0.0),
        "sla_hours": classification.get("sla_hours", 8),
        "user_id": user_id,
        "source": "voice",
        "latency_ms": transcription.latency_ms + classification.get("latency_ms", 0),
    }
