"""
LangGraph Orchestrator for NexDesk AI Agent.

This module implements a sophisticated multi-step AI agent using LangGraph
for orchestrating:
1. Intent classification
2. Advanced RAG retrieval
3. Response generation
4. Ticket escalation decisions
"""

import os
import time
from typing import TypedDict, Literal, Optional, List, Dict, Any, Annotated
from dataclasses import dataclass, field
from enum import Enum
from dotenv import load_dotenv

# LangGraph imports
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# STATE DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────


class Intent(str, Enum):
    """Detected user intent categories."""

    QUESTION = "question"  # Asking for help/info
    COMPLAINT = "complaint"  # Frustrated user
    REQUEST = "request"  # Requesting action/access
    FOLLOWUP = "followup"  # Following up on previous issue
    GREETING = "greeting"  # Just saying hi
    OTHER = "other"


class AgentState(TypedDict):
    """State passed through the LangGraph workflow."""

    # Input
    user_message: str
    session_id: str
    history: List[Dict[str, str]]

    # Processing
    intent: Optional[str]
    retrieved_docs: List[Dict[str, Any]]
    confidence: float
    category: str

    # Output
    response: str
    should_create_ticket: bool
    knowledge_sources: List[str]

    # Metadata
    latency_ms: int
    aws_used: bool
    hyde_used: bool
    rerank_used: bool
    error: Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# LLM UTILITIES
# ─────────────────────────────────────────────────────────────────────────────


def get_groq_client():
    """Get Groq client."""
    from groq import Groq

    return Groq(api_key=os.getenv("GROQ_API_KEY"))


def call_llm_simple(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """Simple LLM call without full routing."""
    try:
        client = get_groq_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=500,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"LLM call failed: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# GRAPH NODES
# ─────────────────────────────────────────────────────────────────────────────


def classify_intent(state: AgentState) -> AgentState:
    """
    Node 1: Classify user intent.
    This helps route the conversation appropriately.
    """
    user_message = state["user_message"]

    prompt = f"""Classify the intent of this IT support message into ONE category:
- question: User asking for help or information
- complaint: User frustrated or complaining
- request: User requesting specific action or access
- followup: User following up on previous issue
- greeting: Just a greeting or thanks
- other: Doesn't fit other categories

Message: "{user_message}"

Reply with ONLY the category word, nothing else."""

    try:
        intent = call_llm_simple(prompt, temperature=0.1).lower().strip()
        if intent not in [i.value for i in Intent]:
            intent = Intent.OTHER.value
    except Exception:
        intent = Intent.QUESTION.value

    return {**state, "intent": intent}


def retrieve_knowledge(state: AgentState) -> AgentState:
    """
    Node 2: Advanced RAG retrieval.
    Uses HyDE + Hybrid search + Cross-encoder reranking.
    """
    from .advanced_retriever import get_advanced_retriever, advanced_retrieve
    from .knowledge_base import KNOWLEDGE_BASE
    from .rag import embedder, collection

    user_message = state["user_message"]

    try:
        # Get document embeddings from ChromaDB
        all_docs = collection.get(include=["embeddings", "metadatas"])

        if all_docs["embeddings"] and len(all_docs["embeddings"]) > 0:
            import numpy as np

            doc_embeddings = np.array(all_docs["embeddings"])

            # Build document list for advanced retriever
            documents = []
            for i, meta in enumerate(all_docs["metadatas"]):
                documents.append(
                    {
                        "id": all_docs["ids"][i],
                        "question": meta.get("question", ""),
                        "answer": meta.get("answer", ""),
                        "category": meta.get("category", "other"),
                    }
                )

            # Advanced retrieval
            results = advanced_retrieve(
                query=user_message,
                documents=documents,
                doc_embeddings=doc_embeddings,
                top_k=5,
            )

            # Calculate confidence from top result
            confidence = results[0]["similarity"] if results else 0.0
            category = results[0]["category"] if results else "other"

            return {
                **state,
                "retrieved_docs": results,
                "confidence": confidence,
                "category": category,
                "hyde_used": True,
                "rerank_used": True,
            }
        else:
            # Fallback to basic retrieval
            from .rag import retrieve_context

            results = retrieve_context(user_message, n=5)
            confidence = results[0]["similarity"] if results else 0.0
            category = results[0]["category"] if results else "other"

            return {
                **state,
                "retrieved_docs": results,
                "confidence": confidence,
                "category": category,
                "hyde_used": False,
                "rerank_used": False,
            }

    except Exception as e:
        print(f"Retrieval error: {e}")
        return {
            **state,
            "retrieved_docs": [],
            "confidence": 0.0,
            "category": "other",
            "hyde_used": False,
            "rerank_used": False,
            "error": str(e),
        }


def decide_deflection(state: AgentState) -> Literal["generate_answer", "escalate"]:
    """
    Edge: Decide whether to answer from KB or escalate to ticket.
    """
    DEFLECT_THRESHOLD = float(os.getenv("DEFLECT_THRESHOLD", "0.72"))

    confidence = state.get("confidence", 0.0)
    intent = state.get("intent", "question")

    # Always escalate complaints
    if intent == "complaint":
        return "escalate"

    # Deflect if confidence is high enough
    if confidence >= DEFLECT_THRESHOLD:
        return "generate_answer"

    return "escalate"


def generate_answer(state: AgentState) -> AgentState:
    """
    Node 3a: Generate answer from knowledge base.
    Used when confidence is high enough to deflect.
    """
    user_message = state["user_message"]
    retrieved_docs = state.get("retrieved_docs", [])
    history = state.get("history", [])

    # Build context from retrieved docs
    context = "\n\n".join(
        [
            f"Q: {d.get('question', '')}\nA: {d.get('answer', '')}"
            for d in retrieved_docs[:3]
        ]
    )

    system = f"""You are NexDesk AI, an intelligent IT support assistant.
Answer the user's question using ONLY the knowledge base below.
Be concise, friendly, and give numbered steps when appropriate.
End with: "If this doesn't resolve your issue, I can create a support ticket for you."

KNOWLEDGE BASE:
{context}"""

    # Build messages
    messages = []
    for msg in history[-4:]:  # Last 4 messages for context
        messages.append(
            {"role": msg.get("role", "user"), "content": msg.get("content", "")}
        )
    messages.append({"role": "user", "content": user_message})

    try:
        from .rag import call_llm

        response = call_llm(messages, system)
    except Exception as e:
        response = "I found some information that might help, but encountered an error generating the response. Let me create a ticket for you."

    knowledge_sources = [d.get("question", "") for d in retrieved_docs[:2]]

    return {
        **state,
        "response": response,
        "should_create_ticket": False,
        "knowledge_sources": knowledge_sources,
    }


def escalate_to_ticket(state: AgentState) -> AgentState:
    """
    Node 3b: Generate escalation response and mark for ticket creation.
    Used when confidence is too low or user is frustrated.
    """
    user_message = state["user_message"]
    intent = state.get("intent", "question")

    # Customize based on intent
    if intent == "complaint":
        system = """You are NexDesk AI. The user is frustrated.
Acknowledge their frustration with genuine empathy.
Confirm you are creating a PRIORITY ticket immediately.
Ask for one detail that will help resolve this faster.
Maximum 3 sentences. Be warm and professional."""
    else:
        system = """You are NexDesk AI. This issue needs a human agent.
Acknowledge their issue with empathy in 1 sentence.
Confirm you are creating a ticket for them.
Ask for one clarifying detail that will help the agent resolve it faster.
Maximum 3 sentences total."""

    try:
        response = call_llm_simple(user_message, system)
    except Exception:
        response = "I understand you need help with this issue. I'm creating a support ticket for you now, and an agent will assist you shortly. Could you provide any additional details that might help us resolve this faster?"

    return {
        **state,
        "response": response,
        "should_create_ticket": True,
        "knowledge_sources": [],
    }


def finalize_response(state: AgentState) -> AgentState:
    """
    Node 4: Final processing before returning.
    Calculates latency and prepares final response.
    """
    # This is called at the end to finalize metadata
    return state


# ─────────────────────────────────────────────────────────────────────────────
# BUILD LANGGRAPH
# ─────────────────────────────────────────────────────────────────────────────


def build_agent_graph() -> StateGraph:
    """Build and compile the LangGraph agent."""

    # Create graph
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("escalate_to_ticket", escalate_to_ticket)
    graph.add_node("finalize", finalize_response)

    # Add edges
    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "retrieve_knowledge")

    # Conditional edge based on confidence
    graph.add_conditional_edges(
        "retrieve_knowledge",
        decide_deflection,
        {"generate_answer": "generate_answer", "escalate": "escalate_to_ticket"},
    )

    graph.add_edge("generate_answer", "finalize")
    graph.add_edge("escalate_to_ticket", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# AGENT RUNNER
# ─────────────────────────────────────────────────────────────────────────────

# Compiled graph (singleton)
_compiled_graph = None


def get_agent():
    """Get the compiled agent graph."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
    return _compiled_graph


def run_agent(
    user_message: str, session_id: str = "", history: List[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Run the LangGraph agent.

    Returns a dict compatible with the existing chat endpoint.
    """
    start_time = time.time()

    # Initialize state
    initial_state: AgentState = {
        "user_message": user_message,
        "session_id": session_id,
        "history": history or [],
        "intent": None,
        "retrieved_docs": [],
        "confidence": 0.0,
        "category": "other",
        "response": "",
        "should_create_ticket": False,
        "knowledge_sources": [],
        "latency_ms": 0,
        "aws_used": os.getenv("USE_AWS", "false").lower() == "true",
        "hyde_used": False,
        "rerank_used": False,
        "error": None,
    }

    try:
        # Run the graph
        agent = get_agent()
        final_state = agent.invoke(initial_state)

        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)

        # Build response
        return {
            "reply": final_state.get("response", ""),
            "deflected": not final_state.get("should_create_ticket", True),
            "confidence": round(final_state.get("confidence", 0.0), 2),
            "category": final_state.get("category", "other"),
            "create_ticket": final_state.get("should_create_ticket", False),
            "knowledge_sources": final_state.get("knowledge_sources", []),
            "latency_ms": latency_ms,
            "aws_used": final_state.get("aws_used", False),
            "intent": final_state.get("intent", "unknown"),
            "hyde_used": final_state.get("hyde_used", False),
            "rerank_used": final_state.get("rerank_used", False),
            "advanced_rag": True,
        }

    except Exception as e:
        print(f"Agent error: {e}")
        latency_ms = int((time.time() - start_time) * 1000)

        # Fallback response
        return {
            "reply": "I apologize, but I'm experiencing some technical difficulties. Let me create a support ticket for you so a human agent can assist.",
            "deflected": False,
            "confidence": 0.0,
            "category": "other",
            "create_ticket": True,
            "knowledge_sources": [],
            "latency_ms": latency_ms,
            "aws_used": False,
            "intent": "error",
            "hyde_used": False,
            "rerank_used": False,
            "advanced_rag": True,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# ALTERNATIVE: SIMPLE ADVANCED RAG (without full LangGraph)
# ─────────────────────────────────────────────────────────────────────────────


def advanced_chat_with_deflection(
    user_message: str, history: List[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Simpler advanced RAG without full LangGraph orchestration.
    Uses HyDE + Hybrid + Reranking but with simpler flow.
    """
    from .rag import call_llm, get_bedrock, DEFLECT_THRESHOLD
    from .advanced_retriever import get_advanced_retriever, advanced_retrieve
    from .knowledge_base import KNOWLEDGE_BASE

    start = time.time()
    history = history or []

    try:
        # Get retriever and build index if needed
        retriever = get_advanced_retriever()
        if not retriever.bm25_index:
            retriever.build_index(KNOWLEDGE_BASE)

        # Get embeddings for documents
        import numpy as np

        doc_texts = [f"{d['question']} {d['answer']}" for d in KNOWLEDGE_BASE]
        doc_embeddings = retriever.embedder.encode(doc_texts)

        # Advanced retrieval
        retrieved = advanced_retrieve(
            query=user_message,
            documents=KNOWLEDGE_BASE,
            doc_embeddings=np.array(doc_embeddings),
            top_k=5,
        )

        confidence = retrieved[0]["similarity"] if retrieved else 0.0
        category = retrieved[0]["category"] if retrieved else "other"

    except Exception as e:
        print(f"Advanced retrieval error: {e}")
        # Fallback to basic
        from .rag import retrieve_context

        retrieved = retrieve_context(user_message, n=5)
        confidence = retrieved[0]["similarity"] if retrieved else 0.0
        category = retrieved[0].get("category", "other") if retrieved else "other"

    # Deflection decision
    if confidence >= DEFLECT_THRESHOLD:
        context = "\n\n".join(
            [
                f"Q: {d.get('question', '')}\nA: {d.get('answer', '')}"
                for d in retrieved[:2]
            ]
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
            "category": category,
            "create_ticket": False,
            "knowledge_sources": [d.get("question", "") for d in retrieved[:2]],
            "latency_ms": int((time.time() - start) * 1000),
            "aws_used": get_bedrock() is not None,
            "advanced_rag": True,
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
            "category": category,
            "create_ticket": True,
            "knowledge_sources": [],
            "latency_ms": int((time.time() - start) * 1000),
            "aws_used": get_bedrock() is not None,
            "advanced_rag": True,
        }
