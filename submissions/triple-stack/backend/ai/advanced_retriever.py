"""
Advanced RAG Retriever with:
- HyDE (Hypothetical Document Embeddings) query reformulation
- Hybrid Vector + BM25 sparse search
- Cross-Encoder re-ranking pipeline
"""

import os
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer, CrossEncoder
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

HYDE_ENABLED = os.getenv("HYDE_ENABLED", "true").lower() == "true"
CROSS_ENCODER_ENABLED = os.getenv("CROSS_ENCODER_ENABLED", "true").lower() == "true"
HYBRID_ALPHA = float(os.getenv("HYBRID_ALPHA", "0.7"))  # 0.7 = 70% vector, 30% BM25

# Models
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@dataclass
class RetrievalResult:
    """Single retrieval result with full metadata."""

    id: str
    question: str
    answer: str
    category: str
    vector_score: float
    bm25_score: float
    hybrid_score: float
    rerank_score: Optional[float] = None
    final_score: Optional[float] = None


class AdvancedRetriever:
    """
    Production-grade retriever with:
    1. HyDE query expansion
    2. Hybrid (dense + sparse) retrieval
    3. Cross-encoder reranking
    """

    def __init__(self):
        print("🔧 Initializing Advanced Retriever...")

        # Dense embedder (same as base RAG for consistency)
        self.embedder = SentenceTransformer(EMBEDDING_MODEL)
        print(f"   ✓ Embedder: {EMBEDDING_MODEL}")

        # Cross-encoder for reranking
        if CROSS_ENCODER_ENABLED:
            self.cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
            print(f"   ✓ Cross-encoder: {CROSS_ENCODER_MODEL}")
        else:
            self.cross_encoder = None
            print("   ⚠ Cross-encoder disabled")

        # BM25 index (built on first use)
        self.bm25_index: Optional[BM25Okapi] = None
        self.bm25_corpus: List[str] = []
        self.documents: List[Dict[str, Any]] = []

        # LLM for HyDE (lazy loaded)
        self._llm = None

        print("   ✓ Advanced Retriever ready")

    def _get_llm(self):
        """Lazy load LLM for HyDE."""
        if self._llm is None:
            try:
                from groq import Groq

                self._llm = Groq(api_key=os.getenv("GROQ_API_KEY"))
            except Exception as e:
                print(f"   ⚠ LLM init failed: {e}")
        return self._llm

    # ─────────────────────────────────────────────────────────────────────────
    # INDEX BUILDING
    # ─────────────────────────────────────────────────────────────────────────

    def build_index(self, documents: List[Dict[str, Any]]):
        """Build BM25 sparse index from documents."""
        self.documents = documents

        # Build corpus for BM25
        self.bm25_corpus = []
        tokenized_corpus = []

        for doc in documents:
            text = f"{doc.get('question', '')} {doc.get('answer', '')}"
            self.bm25_corpus.append(text)
            # Simple tokenization for BM25
            tokens = text.lower().split()
            tokenized_corpus.append(tokens)

        self.bm25_index = BM25Okapi(tokenized_corpus)
        print(f"   ✓ BM25 index built: {len(documents)} documents")

    # ─────────────────────────────────────────────────────────────────────────
    # HYDE: Hypothetical Document Embeddings
    # ─────────────────────────────────────────────────────────────────────────

    def generate_hyde_document(self, query: str) -> str:
        """
        HyDE: Generate a hypothetical answer document.
        This helps match user questions to KB answers more accurately.
        """
        if not HYDE_ENABLED:
            return query

        llm = self._get_llm()
        if not llm:
            return query

        try:
            prompt = f"""You are an IT support knowledge base. Given this user question, write a SHORT hypothetical answer (2-3 sentences max) that would appear in an IT FAQ.
Do NOT solve the problem, just write what a typical KB article answer would look like.

User Question: {query}

Hypothetical KB Answer:"""

            response = llm.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.3,
            )
            hyde_doc = response.choices[0].message.content.strip()
            return f"{query} {hyde_doc}"
        except Exception as e:
            print(f"HyDE generation failed: {e}")
            return query

    # ─────────────────────────────────────────────────────────────────────────
    # HYBRID RETRIEVAL
    # ─────────────────────────────────────────────────────────────────────────

    def _vector_search(
        self, query_embedding: np.ndarray, doc_embeddings: np.ndarray, top_k: int
    ) -> List[Tuple[int, float]]:
        """Dense vector search using cosine similarity."""
        # Normalize for cosine similarity
        query_norm = query_embedding / np.linalg.norm(query_embedding)
        doc_norms = doc_embeddings / np.linalg.norm(
            doc_embeddings, axis=1, keepdims=True
        )

        # Cosine similarity
        similarities = np.dot(doc_norms, query_norm)

        # Top-k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]
        return [(int(idx), float(similarities[idx])) for idx in top_indices]

    def _bm25_search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        """Sparse BM25 search."""
        if self.bm25_index is None:
            return []

        tokens = query.lower().split()
        scores = self.bm25_index.get_scores(tokens)

        # Normalize BM25 scores to 0-1
        max_score = max(scores) if max(scores) > 0 else 1
        normalized = scores / max_score

        top_indices = np.argsort(normalized)[::-1][:top_k]
        return [(int(idx), float(normalized[idx])) for idx in top_indices]

    def hybrid_retrieve(
        self,
        query: str,
        doc_embeddings: np.ndarray,
        top_k: int = 10,
        alpha: float = HYBRID_ALPHA,
    ) -> List[RetrievalResult]:
        """
        Hybrid retrieval combining vector and BM25 search.

        Args:
            query: User query (or HyDE-expanded query)
            doc_embeddings: Pre-computed document embeddings
            top_k: Number of results to return
            alpha: Weight for vector search (1-alpha = BM25 weight)
        """
        # Get query embedding
        query_embedding = self.embedder.encode(query)

        # Vector search
        vector_results = self._vector_search(query_embedding, doc_embeddings, top_k * 2)

        # BM25 search
        bm25_results = self._bm25_search(query, top_k * 2)

        # Combine scores using Reciprocal Rank Fusion (RRF)
        # or simple weighted combination
        score_map: Dict[int, Dict[str, float]] = {}

        for idx, score in vector_results:
            if idx not in score_map:
                score_map[idx] = {"vector": 0, "bm25": 0}
            score_map[idx]["vector"] = score

        for idx, score in bm25_results:
            if idx not in score_map:
                score_map[idx] = {"vector": 0, "bm25": 0}
            score_map[idx]["bm25"] = score

        # Calculate hybrid scores
        results = []
        for idx, scores in score_map.items():
            hybrid_score = alpha * scores["vector"] + (1 - alpha) * scores["bm25"]
            doc = self.documents[idx]
            results.append(
                RetrievalResult(
                    id=doc.get("id", f"doc_{idx}"),
                    question=doc.get("question", ""),
                    answer=doc.get("answer", ""),
                    category=doc.get("category", "other"),
                    vector_score=scores["vector"],
                    bm25_score=scores["bm25"],
                    hybrid_score=hybrid_score,
                )
            )

        # Sort by hybrid score
        results.sort(key=lambda x: x.hybrid_score, reverse=True)
        return results[:top_k]

    # ─────────────────────────────────────────────────────────────────────────
    # CROSS-ENCODER RE-RANKING
    # ─────────────────────────────────────────────────────────────────────────

    def rerank(
        self, query: str, results: List[RetrievalResult], top_k: int = 5
    ) -> List[RetrievalResult]:
        """
        Re-rank results using cross-encoder.
        Cross-encoders are more accurate but slower than bi-encoders.
        """
        if not CROSS_ENCODER_ENABLED or self.cross_encoder is None:
            # Just use hybrid scores
            for r in results:
                r.final_score = r.hybrid_score
            return results[:top_k]

        # Prepare pairs for cross-encoder
        pairs = [(query, f"{r.question} {r.answer}") for r in results]

        # Get cross-encoder scores
        try:
            ce_scores = self.cross_encoder.predict(pairs)

            # Normalize to 0-1
            min_s, max_s = min(ce_scores), max(ce_scores)
            if max_s > min_s:
                ce_scores = (ce_scores - min_s) / (max_s - min_s)
            else:
                ce_scores = [0.5] * len(ce_scores)

            # Assign rerank scores
            for i, result in enumerate(results):
                result.rerank_score = float(ce_scores[i])
                # Final score: weighted combination of hybrid and rerank
                result.final_score = (
                    0.4 * result.hybrid_score + 0.6 * result.rerank_score
                )

            # Sort by final score
            results.sort(key=lambda x: x.final_score or 0, reverse=True)

        except Exception as e:
            print(f"Cross-encoder reranking failed: {e}")
            for r in results:
                r.final_score = r.hybrid_score

        return results[:top_k]

    # ─────────────────────────────────────────────────────────────────────────
    # FULL RETRIEVAL PIPELINE
    # ─────────────────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        doc_embeddings: np.ndarray,
        top_k: int = 5,
        use_hyde: bool = True,
        use_rerank: bool = True,
    ) -> List[RetrievalResult]:
        """
        Full advanced retrieval pipeline:
        1. HyDE query expansion (optional)
        2. Hybrid vector + BM25 retrieval
        3. Cross-encoder re-ranking (optional)
        """
        # Step 1: HyDE expansion
        if use_hyde and HYDE_ENABLED:
            expanded_query = self.generate_hyde_document(query)
        else:
            expanded_query = query

        # Step 2: Hybrid retrieval
        candidates = self.hybrid_retrieve(
            expanded_query,
            doc_embeddings,
            top_k=top_k * 2,  # Get more candidates for reranking
        )

        # Step 3: Re-ranking
        if use_rerank and CROSS_ENCODER_ENABLED:
            # Re-rank using ORIGINAL query (not HyDE expanded)
            results = self.rerank(query, candidates, top_k=top_k)
        else:
            for r in candidates:
                r.final_score = r.hybrid_score
            results = candidates[:top_k]

        return results


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON INSTANCE
# ─────────────────────────────────────────────────────────────────────────────

_retriever: Optional[AdvancedRetriever] = None


def get_advanced_retriever() -> AdvancedRetriever:
    """Get or create the advanced retriever singleton."""
    global _retriever
    if _retriever is None:
        _retriever = AdvancedRetriever()
    return _retriever


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────


def advanced_retrieve(
    query: str,
    documents: List[Dict[str, Any]],
    doc_embeddings: np.ndarray,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Convenience function for advanced retrieval.
    Returns results in the same format as the basic retrieve_context.
    """
    retriever = get_advanced_retriever()

    # Ensure BM25 index is built
    if not retriever.bm25_index:
        retriever.build_index(documents)

    results = retriever.retrieve(query, doc_embeddings, top_k=top_k)

    # Convert to dict format for backward compatibility
    return [
        {
            "id": r.id,
            "question": r.question,
            "answer": r.answer,
            "category": r.category,
            "similarity": r.final_score or r.hybrid_score,
            "vector_score": r.vector_score,
            "bm25_score": r.bm25_score,
            "rerank_score": r.rerank_score,
        }
        for r in results
    ]
