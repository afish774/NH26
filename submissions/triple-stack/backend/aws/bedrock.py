"""
AWS Bedrock helper — stub module.
Core Bedrock routing is handled inside ai/rag.py via call_llm().
This module can be extended for direct Bedrock calls outside of RAG.
"""
import os, json


def invoke_claude(prompt: str, system: str = "", max_tokens: int = 500) -> str:
    """Direct Bedrock Claude invocation. Requires USE_AWS=true."""
    import boto3
    client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
    model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "system": system,
        "messages": [{"role": "user", "content": prompt}]
    })
    response = client.invoke_model(modelId=model_id, body=body)
    return json.loads(response["body"].read())["content"][0]["text"]
