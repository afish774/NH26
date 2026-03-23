"""
AWS Textract — screenshot to structured ticket data.
Only called when USE_AWS=true AND a screenshot is provided.
Falls back gracefully to Gemini Vision when AWS is not configured.
"""
import os, json
from dotenv import load_dotenv
load_dotenv()


def extract_ticket_from_screenshot(s3_bucket: str, s3_key: str) -> dict:
    """Extract IT error details from a screenshot using Textract + Bedrock."""
    try:
        import boto3
        textract = boto3.client("textract", region_name=os.getenv("AWS_REGION", "us-east-1"))
        bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))

        # Extract text from image
        response = textract.detect_document_text(
            Document={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}}
        )
        lines = [
            b["Text"] for b in response["Blocks"]
            if b["BlockType"] == "LINE" and b.get("Confidence", 0) > 75
        ]
        extracted = "\n".join(lines)

        if not extracted.strip():
            return {"error": "No readable text found in screenshot"}

        # Interpret with Bedrock
        prompt = f"""Analyze this text extracted from an IT error screenshot and create a support ticket.

EXTRACTED TEXT:
{extracted[:2000]}

Respond ONLY with valid JSON:
{{
  "title": "concise ticket title under 80 characters",
  "description": "detailed description of the error",
  "category": "network|hardware|software|access|security|other",
  "priority": "low|medium|high|critical",
  "error_code": "error code if found or null",
  "application": "app or system name if identifiable or null"
}}"""

        model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 400,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}]
        })
        br = bedrock.invoke_model(modelId=model_id, body=body)
        result = json.loads(json.loads(br["body"].read())["content"][0]["text"])
        result["extracted_text_preview"] = extracted[:200]
        result["source"] = "aws_textract"
        return result

    except Exception as e:
        return {"error": str(e), "source": "textract_failed"}


def extract_ticket_from_base64(image_b64: str, media_type: str = "image/png") -> dict:
    """
    Gemini Vision fallback — works without AWS.
    Use when USE_AWS=false or Textract fails.
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-1.5-flash")

        response = model.generate_content([
            {"mime_type": media_type, "data": image_b64},
            """Extract the IT error from this screenshot. Return ONLY valid JSON:
{
  "title": "concise ticket title under 80 characters",
  "description": "description of the error",
  "category": "network|hardware|software|access|security|other",
  "priority": "low|medium|high|critical",
  "error_code": "error code if visible or null",
  "application": "application name if visible or null"
}"""
        ])
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        result["source"] = "gemini_vision"
        return result
    except Exception as e:
        return {"error": str(e), "source": "vision_failed"}
