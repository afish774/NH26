import os, time
from typing import Any
import chromadb
from sentence_transformers import SentenceTransformer
from groq import Groq
import google.generativeai as genai
from .knowledge_base import KNOWLEDGE_BASE
from dotenv import load_dotenv

load_dotenv()

# ── Clients ───────────────────────────────────────────────────────────────────
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ── ChromaDB ──────────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "chroma_data")
CHROMA_PERSISTENT = os.getenv("CHROMA_PERSISTENT", "true").lower() == "true"

if CHROMA_PERSISTENT:
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    except Exception as e:
        print(f"ChromaDB persistent client failed: {e} — falling back to in-memory")
        chroma_client = chromadb.Client()
        CHROMA_PERSISTENT = False
else:
    chroma_client = chromadb.Client()

collection = chroma_client.get_or_create_collection(
    name="nexdesk_kb", metadata={"hnsw:space": "cosine"}
)

# ── Embedder ──────────────────────────────────────────────────────────────────
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# ── AWS Bedrock client (lazy — only if USE_AWS=true) ──────────────────────────
_bedrock = None


def get_bedrock():
    global _bedrock
    if _bedrock is None and os.getenv("USE_AWS", "false").lower() == "true":
        import boto3

        _bedrock = boto3.client(
            "bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1")
        )
    return _bedrock


# Configurable deflection threshold
DEFLECT_THRESHOLD = float(os.getenv("DEFLECT_THRESHOLD", "0.72"))


def seed_knowledge_base():
    if collection.count() >= len(KNOWLEDGE_BASE):
        print(f"✅ KB already seeded ({collection.count()} docs)")
        return
    docs, ids, metas = [], [], []
    for item in KNOWLEDGE_BASE:
        docs.append(f"{item['question']} {item['answer']}")
        ids.append(item["id"])
        metas.append(
            {
                "question": item["question"],
                "answer": item["answer"],
                "category": item["category"],
            }
        )
    embeddings = embedder.encode(docs).tolist()
    collection.add(documents=docs, embeddings=embeddings, ids=ids, metadatas=metas)
    print(f"✅ Seeded {len(docs)} documents")


def retrieve_context(query: str, n: int = 3) -> list[dict[str, Any]]:
    emb = embedder.encode([query]).tolist()
    results = collection.query(
        query_embeddings=emb, n_results=n, include=["metadatas", "distances"]
    )
    docs = []
    for i, meta in enumerate(results["metadatas"][0]):
        sim = round(1 - results["distances"][0][i], 4)
        docs.append({**meta, "similarity": sim})
    return docs


def call_llm(messages: list[dict], system: str) -> str:
    """
    Smart LLM router:
      USE_AWS=true  → Amazon Bedrock Claude 3.5 Sonnet
      USE_AWS=false → Groq llama-3.3-70b (fallback: Gemini Flash)
    """
    bedrock = get_bedrock()
    if bedrock:
        import json

        model_id = os.getenv(
            "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
        )
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "temperature": 0.3,
                "system": system,
                "messages": messages,
            }
        )
        try:
            response = bedrock.invoke_model(modelId=model_id, body=body)
            return json.loads(response["body"].read())["content"][0]["text"]
        except Exception as e:
            print(f"Bedrock error: {e} — falling back")

    # Groq path
    try:
        r = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=500,
            temperature=0.3,
        )
        return r.choices[0].message.content
    except Exception as e:
        print(f"Groq error: {e} — falling back to Gemini")
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"{system}\n\nUser: {messages[-1]['content']}"
            return model.generate_content(prompt).text
        except Exception as e:
            print(f"Gemini error: {e} — all LLMs failed")
            return "I am currently experiencing technical difficulties connecting to my AI brains. However, I have created a priority ticket for you and an agent will respond shortly."


def chat_with_deflection(user_message: str, history: list[dict]) -> dict:
    """
    Core deflection logic. Returns full result dict.
    confidence >= DEFLECT_THRESHOLD → answer from KB (no ticket)
    confidence <  DEFLECT_THRESHOLD → escalate to ticket creation
    """
    start = time.time()
    try:
        retrieved = retrieve_context(user_message)
        confidence = retrieved[0]["similarity"] if retrieved else 0.0
    except Exception as e:
        print(f"ChromaDB retrieval error: {e}")
        retrieved = []
        confidence = 0.0

    if confidence >= DEFLECT_THRESHOLD:
        context = "\n\n".join(
            [f"Q: {d['question']}\nA: {d['answer']}" for d in retrieved[:2]]
        )
        system = f"""You are NexDesk AI, an intelligent IT support assistant.
Answer the user's question using ONLY the knowledge base below.
Be concise, friendly, and give numbered steps when needed.
End with: "If this doesn't resolve your issue, I can create a support ticket for you."

KNOWLEDGE BASE:
{context}"""
        reply = call_llm(history + [{"role": "user", "content": user_message}], system)
        return {
            "reply": reply,
            "deflected": True,
            "confidence": round(confidence, 2),
            "category": retrieved[0].get("category", "other"),
            "create_ticket": False,
            "knowledge_sources": [d["question"] for d in retrieved[:2]],
            "latency_ms": int((time.time() - start) * 1000),
            "aws_used": get_bedrock() is not None,
        }
    else:
        system = """You are NexDesk AI. The user's issue needs a human agent.
Acknowledge their issue with empathy in 1 sentence.
Confirm you are creating a priority ticket for them.
Ask for one clarifying detail that will help the agent resolve it faster.
Maximum 3 sentences total."""
        reply = call_llm([{"role": "user", "content": user_message}], system)
        return {
            "reply": reply,
            "deflected": False,
            "confidence": round(confidence, 2),
            "category": retrieved[0].get("category", "other") if retrieved else "other",
            "create_ticket": True,
            "knowledge_sources": [],
            "latency_ms": int((time.time() - start) * 1000),
            "aws_used": get_bedrock() is not None,
        }
