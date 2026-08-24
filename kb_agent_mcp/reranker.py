"""
kb_agent_mcp/reranker.py
─────────────────────────
Cross-encoder re-ranker for the RAG retrieval pipeline.

After the vector/BM25 hybrid search retrieves a candidate pool (typically
top-20), this module scores each (query, passage) pair with a cross-encoder
model and returns the candidates re-sorted by relevance.

Cross-encoders read both the query and the passage jointly, so they capture
fine-grained query–document interactions that a bi-encoder (embedding model)
cannot — this is the classical "retrieval + re-ranking" two-stage setup.

Model
-----
Default: cross-encoder/ms-marco-MiniLM-L-6-v2
  • ~80 MB, CPU-friendly, widely deployed for passage re-ranking.
  • Override via KB_RERANKER_MODEL env var.

Opt-out
-------
Set KB_RERANKER_ENABLED=false to bypass the re-ranker entirely (useful when
sentence-transformers is not installed, or for latency-critical deployments).

Latency note
------------
Scoring 20 (query, passage) pairs on CPU typically takes 20–80 ms on modern
hardware — comparable to a single embedding call — so the re-ranker adds
negligible latency for the default top-4 / top-5 final cut.

Public API
----------
rerank(query, results, top_n)   → list[dict]   (sync, call from thread pool)
is_available()                  → bool
"""

from __future__ import annotations

import logging
from typing import Any

from kb_agent_mcp.config import cfg

logger = logging.getLogger(__name__)

# ── Lazy model singleton ──────────────────────────────────────────────────────

_cross_encoder: Any = None
_load_attempted: bool = False    # prevent repeated import failures from spamming logs


def _load_cross_encoder() -> Any | None:
    """
    Lazily load the cross-encoder model.  Returns None on any failure so that
    callers can transparently fall back to the un-re-ranked ordering.
    """
    global _cross_encoder, _load_attempted
    if _load_attempted:
        return _cross_encoder
    _load_attempted = True

    if not cfg.KB_RERANKER_ENABLED:
        logger.debug("Re-ranker disabled via KB_RERANKER_ENABLED=false")
        return None

    model_name = cfg.KB_RERANKER_MODEL
    try:
        from sentence_transformers import CrossEncoder
        _cross_encoder = CrossEncoder(model_name)
        logger.info("Re-ranker loaded: %s", model_name)
    except ImportError:
        logger.debug(
            "sentence-transformers not installed; cross-encoder re-ranker disabled"
        )
    except Exception as exc:
        logger.warning(
            "Failed to load cross-encoder model %r (%s); re-ranker disabled",
            model_name, exc,
        )
    return _cross_encoder


def is_available() -> bool:
    """Return True if the cross-encoder loaded successfully."""
    return _load_cross_encoder() is not None


def rerank(
    query: str,
    results: list[dict],
    top_n: int,
) -> list[dict]:
    """
    Re-rank *results* using the cross-encoder and return the top-*top_n* items.

    Args:
        query:   The user's question string.
        results: Candidate list from vector/BM25 search — each item must have
                 at least a ``summary`` field (the passage text).
        top_n:   Number of results to return after re-ranking.

    Returns:
        A new list of up to *top_n* dicts from *results*, re-sorted by
        cross-encoder relevance score (descending).  Each item gains a
        ``rerank_score`` key with the raw cross-encoder logit so callers
        can inspect it.

    Falls back to the original ordering (sliced to *top_n*) when:
      • The cross-encoder model is unavailable.
      • *results* is empty.
      • Any exception occurs during scoring (logged at WARNING level).
    """
    if not results:
        return results[:top_n]

    model = _load_cross_encoder()
    if model is None:
        return results[:top_n]

    try:
        # Build (query, passage) pairs.  Use summary as the passage — it is the
        # best-matching chunk text surfaced by the retrieval layer.
        pairs = [(query, r.get("summary", "") or "") for r in results]
        scores: list[float] = model.predict(pairs).tolist()

        # Attach the raw score so downstream code / tests can inspect it
        scored = [
            {**r, "rerank_score": float(s)}
            for r, s in zip(results, scores)
        ]
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_n]

    except Exception as exc:
        logger.warning(
            "Cross-encoder re-ranking failed (%s); falling back to original order",
            exc,
        )
        return results[:top_n]


def reset() -> None:
    """
    Reset the singleton (used by tests to force a fresh load attempt).
    Should not be called in production code.
    """
    global _cross_encoder, _load_attempted
    _cross_encoder   = None
    _load_attempted  = False
