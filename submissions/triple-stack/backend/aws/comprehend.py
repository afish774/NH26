"""
AWS Comprehend helper — sentiment detection.
Core Comprehend logic is embedded in ai/classifier.py gated on USE_AWS=true.
This module exposes reusable helpers.
"""
import os


def detect_sentiment(text: str) -> dict:
    """Returns {'sentiment': str, 'score': float}. Requires USE_AWS=true."""
    import boto3
    comprehend = boto3.client("comprehend", region_name=os.getenv("AWS_REGION", "us-east-1"))
    result = comprehend.detect_sentiment(Text=text[:4500], LanguageCode="en")
    sentiment = result["Sentiment"]
    score = result["SentimentScore"].get(sentiment.capitalize(), 0)
    return {"sentiment": sentiment, "score": score}


def detect_key_phrases(text: str) -> list[str]:
    """Extract key phrases from text. Requires USE_AWS=true."""
    import boto3
    comprehend = boto3.client("comprehend", region_name=os.getenv("AWS_REGION", "us-east-1"))
    result = comprehend.detect_key_phrases(Text=text[:4500], LanguageCode="en")
    return [p["Text"] for p in result["KeyPhrases"] if p["Score"] > 0.8]
