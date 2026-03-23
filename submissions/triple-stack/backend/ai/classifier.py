import os
import json
import time
from typing import Optional, Dict, Any, List
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Feature flag for advanced retrieval in classifier
USE_ADVANCED_RETRIEVAL = os.getenv("USE_ADVANCED_RETRIEVAL", "true").lower() == "true"

PRIORITY_KEYWORDS = {
    "critical": [
        "data loss",
        "breach",
        "security incident",
        "system down",
        "emergency",
        "cannot work",
        "production down",
    ],
    "high": [
        "client call",
        "meeting",
        "deadline",
        "urgent",
        "completely broken",
        "cracked",
        "2 hours",
        "today",
        "immediately",
    ],
    "medium": ["slow", "intermittent", "sometimes", "not working", "help"],
    "low": ["how to", "setup", "configure", "question", "when", "tutorial"],
}

SLA_HOURS = {"critical": 1, "high": 4, "medium": 8, "low": 24}


def detect_priority(text: str) -> str:
    """Detect ticket priority from text content."""
    lower = text.lower()
    for level, keywords in PRIORITY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return level
    return "medium"


def get_advanced_kb_context(
    query: str, top_k: int = 3
) -> tuple[str, List[Dict[str, Any]]]:
    """
    Get knowledge base context using advanced retrieval.
    Returns (context_string, retrieved_docs).
    """
    if not USE_ADVANCED_RETRIEVAL:
        return get_basic_kb_context(query, top_k)

    try:
        from ai.advanced_retriever import get_advanced_retriever, advanced_retrieve
        from ai.knowledge_base import KNOWLEDGE_BASE
        import numpy as np

        # Get retriever
        retriever = get_advanced_retriever()

        # Build index if needed
        if not retriever.bm25_index:
            retriever.build_index(KNOWLEDGE_BASE)

        # Get embeddings
        doc_texts = [f"{d['question']} {d['answer']}" for d in KNOWLEDGE_BASE]
        doc_embeddings = retriever.embedder.encode(doc_texts)

        # Advanced retrieval with HyDE + Hybrid + Reranking
        retrieved = advanced_retrieve(
            query=query,
            documents=KNOWLEDGE_BASE,
            doc_embeddings=np.array(doc_embeddings),
            top_k=top_k,
        )

        if retrieved and retrieved[0]["similarity"] > 0.35:
            context = "\n\nRELEVANT INTERNAL KNOWLEDGE BASE ARTICLES (use these to craft a helpful suggested reply):\n"
            for d in retrieved:
                context += f"- Q: {d['question']}\n  A: {d['answer']}\n  [Relevance: {d['similarity']:.2f}]\n"

            print(
                f"Classifier Advanced RAG: Found {len(retrieved)} articles (top score: {retrieved[0]['similarity']:.2f})"
            )
            return context, retrieved

        return "", []

    except Exception as e:
        print(f"Advanced retrieval failed, falling back to basic: {e}")
        return get_basic_kb_context(query, top_k)


def get_basic_kb_context(
    query: str, top_k: int = 3
) -> tuple[str, List[Dict[str, Any]]]:
    """Fallback to basic retrieval."""
    try:
        from ai.rag import retrieve_context

        retrieved = retrieve_context(query, n=top_k)

        if retrieved and retrieved[0]["similarity"] > 0.4:
            context = "\n\nRELEVANT INTERNAL KNOWLEDGE BASE ARTICLES:\n"
            for d in retrieved:
                context += f"- Q: {d['question']}\n  A: {d['answer']}\n"

            print(f"Classifier Basic RAG: Found {len(retrieved)} articles")
            return context, retrieved

        return "", []

    except Exception as e:
        print(f"Basic retrieval failed: {e}")
        return "", []


def generate_smart_suggested_reply(
    title: str,
    description: str,
    category: str,
    priority: str,
    kb_context: str,
    retrieved_docs: List[Dict[str, Any]],
) -> str:
    """
    Generate a smart suggested reply using KB context.
    This gives agents a head start on responding to tickets.
    """
    # If we have good KB matches, use them to craft a detailed response
    if retrieved_docs and retrieved_docs[0].get("similarity", 0) > 0.5:
        top_doc = retrieved_docs[0]

        prompt = f"""You are an expert IT support agent. A ticket just came in.
Based on the knowledge base article below, write a professional first response 
that the agent can send immediately (with minor customization if needed).

TICKET:
Title: {title}
Description: {description}
Priority: {priority}
Category: {category}

MOST RELEVANT KB ARTICLE:
Q: {top_doc.get("question", "")}
A: {top_doc.get("answer", "")}

Write a 2-3 sentence professional response that:
1. Acknowledges the user's issue
2. Provides the most relevant troubleshooting steps from the KB
3. Offers to help further if needed

Response:"""
    else:
        # Generic prompt without strong KB match
        prompt = f"""You are an expert IT support agent. Write a professional first response 
for this ticket that an agent can send immediately.

TICKET:
Title: {title}
Description: {description}  
Priority: {priority}
Category: {category}

Write a 2-3 sentence professional response that:
1. Acknowledges the user's issue with appropriate urgency for {priority} priority
2. Asks clarifying questions if needed
3. Sets expectations for next steps

Response:"""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Smart reply generation failed: {e}")
        return "Thank you for contacting IT support. An agent will review your issue and respond shortly."


def classify_ticket(title: str, description: str) -> Dict[str, Any]:
    """
    Classify a ticket with advanced RAG-powered suggested reply.

    Returns category, priority, summary, and a smart suggested reply
    based on knowledge base content.
    """
    start = time.time()
    combined = f"{title} {description}"
    priority = detect_priority(combined)

    # AWS Comprehend path (if enabled)
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None

    if os.getenv("USE_AWS", "false").lower() == "true":
        try:
            import boto3

            comprehend = boto3.client(
                "comprehend", region_name=os.getenv("AWS_REGION", "us-east-1")
            )
            sentiment_result = comprehend.detect_sentiment(
                Text=combined[:4500], LanguageCode="en"
            )
            sentiment = sentiment_result["Sentiment"]
            sentiment_score = sentiment_result["SentimentScore"].get(
                sentiment.capitalize(), 0
            )

            # Escalate frustrated users
            if sentiment == "NEGATIVE" and sentiment_score > 0.88 and priority == "low":
                priority = "medium"
            if sentiment == "NEGATIVE" and sentiment_score > 0.94:
                priority = "high" if priority in ("low", "medium") else priority
        except Exception as e:
            print(f"Comprehend error (non-fatal): {e}")

    # Advanced Knowledge Base Retrieval
    kb_context, retrieved_docs = get_advanced_kb_context(combined, top_k=3)

    # LLM classification
    prompt = f"""Classify this IT support ticket. Return ONLY valid JSON, no other text.

TITLE: {title}
DESCRIPTION: {description}{kb_context}

Return exactly this JSON:
{{
  "category": "network|hardware|software|access|security|other",
  "summary": "one sentence max 120 chars",
  "confidence": 0.0-1.0
}}"""

    try:
        # Use Bedrock if enabled
        if os.getenv("USE_AWS", "false").lower() == "true":
            from ai.rag import call_llm

            raw = call_llm(
                [{"role": "user", "content": prompt}],
                "You are an IT ticket classifier. Respond only with JSON.",
            )
        else:
            r = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.1,
            )
            raw = (
                r.choices[0].message.content.strip()
                if r.choices[0].message.content
                else "{}"
            )

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())

    except Exception as e:
        print(f"Classifier LLM error: {e}")
        result = {"category": "other", "summary": title[:120], "confidence": 0.5}

    # Generate smart suggested reply using retrieved KB context
    category = result.get("category", "other")
    suggested_reply = generate_smart_suggested_reply(
        title=title,
        description=description,
        category=category,
        priority=priority,
        kb_context=kb_context,
        retrieved_docs=retrieved_docs,
    )

    return {
        "category": category,
        "priority": priority,
        "summary": result.get("summary", ""),
        "suggested_reply": suggested_reply,
        "confidence": result.get("confidence", 0.7),
        "sla_hours": SLA_HOURS.get(priority, 8),
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "latency_ms": int((time.time() - start) * 1000),
        "aws_used": os.getenv("USE_AWS", "false").lower() == "true",
        "kb_articles_found": len(retrieved_docs),
        "top_kb_relevance": retrieved_docs[0]["similarity"] if retrieved_docs else 0.0,
        "advanced_retrieval": USE_ADVANCED_RETRIEVAL,
    }
