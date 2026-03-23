"""
==============================================================================
Screenshot Analysis Router
==============================================================================

Handles screenshot-based ticket creation using OCR.
Uses AWS Textract (when USE_AWS=true) or Gemini Vision (fallback).

Endpoints:
    POST /api/tickets/screenshot/ - Analyze screenshot and extract ticket data

==============================================================================
"""

import os
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from schemas.models import ScreenshotRequest
from utils.exceptions import (
    NexDeskException,
    ValidationError,
    ExternalServiceError,
    error_response,
)
from utils.performance import PerformanceMonitor, track_time

logger = logging.getLogger("nexdesk.screenshot")

router = APIRouter()


@router.post("/")
@track_time("screenshot_analysis")
async def analyze_screenshot(req: ScreenshotRequest, db: Session = Depends(get_db)):
    """
    Analyze a screenshot to extract error messages and create ticket data.

    Accepts either:
    - S3 bucket/key (when USE_AWS=true)
    - Base64-encoded image data

    Returns:
        Extracted ticket data including title, description, category, priority

    Raises:
        ValidationError: If no image data provided
        ExternalServiceError: If OCR service fails
    """
    use_aws = os.getenv("USE_AWS", "false").lower() == "true"

    try:
        # Validate input
        if use_aws and req.s3_key and req.s3_bucket:
            # AWS Textract path
            logger.info(f"Processing screenshot from S3: {req.s3_bucket}/{req.s3_key}")

            from aws.textract import extract_ticket_from_screenshot

            with PerformanceMonitor.timer("textract_ocr"):
                result = extract_ticket_from_screenshot(req.s3_bucket, req.s3_key)

        elif req.image_base64:
            # Base64/Gemini Vision path
            logger.info("Processing base64-encoded screenshot")

            # Validate base64 data
            if len(req.image_base64) < 100:
                raise ValidationError(
                    "image_base64",
                    "Image data too small to be valid",
                    {"min_length": 100, "actual_length": len(req.image_base64)},
                )

            from aws.textract import extract_ticket_from_base64

            with PerformanceMonitor.timer("gemini_vision_ocr"):
                result = extract_ticket_from_base64(
                    req.image_base64, req.media_type or "image/png"
                )
        else:
            raise ValidationError(
                "image_data",
                "Either (s3_bucket + s3_key) or image_base64 must be provided",
            )

        # Check for errors in result
        if isinstance(result, dict) and result.get("error"):
            error_msg = result.get("error", "Unknown OCR error")
            source = result.get("source", "unknown")

            logger.error(f"OCR extraction failed: {error_msg} (source: {source})")

            raise ExternalServiceError(
                service=f"OCR ({source})", message=error_msg, details={"source": source}
            )

        # Validate result has expected fields
        if not isinstance(result, dict):
            raise ExternalServiceError(
                service="OCR", message="Invalid response format from OCR service"
            )

        # Log successful extraction
        logger.info(
            f"Screenshot analyzed successfully: "
            f"category={result.get('category', 'unknown')}, "
            f"priority={result.get('priority', 'unknown')}"
        )

        return result

    except NexDeskException:
        # Re-raise our custom exceptions
        raise
    except ImportError as e:
        logger.error(f"OCR module import failed: {e}")
        raise ExternalServiceError(
            service="OCR",
            message=f"OCR module not available: {str(e)}",
            details={
                "missing_module": str(e).split("'")[1] if "'" in str(e) else str(e)
            },
        )
    except Exception as e:
        logger.exception(f"Unexpected error in screenshot analysis: {e}")
        raise ExternalServiceError(
            service="Screenshot Analysis",
            message=f"Failed to analyze screenshot: {str(e)}",
        )


@router.get("/config")
async def get_screenshot_config():
    """
    Get current screenshot analysis configuration.

    Returns:
        Configuration details including OCR provider and limits
    """
    use_aws = os.getenv("USE_AWS", "false").lower() == "true"

    return {
        "ocr_provider": "aws_textract" if use_aws else "gemini_vision",
        "aws_enabled": use_aws,
        "max_image_size_mb": 10,
        "supported_formats": ["image/png", "image/jpeg", "image/webp", "image/gif"],
        "s3_upload_supported": use_aws,
    }
