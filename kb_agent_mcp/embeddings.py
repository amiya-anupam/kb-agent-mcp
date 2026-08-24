"""
kb_agent_mcp/embeddings.py
──────────────────────────
Async embedding backends with automatic fallback chain.

Provider priority
-----------------
1. Configured provider  (Ollama / OpenAI-compatible / Anthropic → uses OpenAI-compat)
2. sentence-transformers offline (all-MiniLM-L6-v2, ~80 MB, 384-dim)

"passthrough" provider goes directly to sentence-transformers (no LLM available).

Public API
----------
await embed(text)       → list[float]
embedding_dim()         → int   (dimension of the current backend's vectors)
backend_name()          → str   (human-readable backend label)
INCLUDE_EXTS            — re-exported from file_parser for convenience
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from kb_agent_mcp.config import cfg
from kb_agent_mcp.context_budget import get as _budget

# ── Lazy sentence-transformers singleton ──────────────────────────────────────

_st_model: Any = None

_ST_MODEL_NAME = "all-MiniLM-L6-v2"
# Hugging Face / sentence-transformers cache paths (the download lands in one of these)
_ST_CACHE_DIRS = [
    Path.home() / ".cache" / "huggingface" / "hub",
    Path.home() / ".cache" / "torch" / "sentence_transformers",
]


def _st_model_is_cached() -> bool:
    """Return True if the sentence-transformers model is already on disk."""
    model_slug = _ST_MODEL_NAME.replace("/", "_")
    # HF hub stores models as "models--sentence-transformers--<name>" directories
    hf_dir = _ST_CACHE_DIRS[0] / f"models--sentence-transformers--{model_slug}"
    if hf_dir.exists():
        return True
    # Legacy torch cache path used by older sentence-transformers versions
    torch_dir = _ST_CACHE_DIRS[1] / f"sentence-transformers_{model_slug}"
    if torch_dir.exists():
        return True
    return False


def _ensure_embedding_model() -> None:
    """Download the embedding model now (at generate-time) if not already cached.

    Call this before any build_collection() call so the download happens during
    the generate step — not silently during the first ask() query.

    Prints a one-time informational message only when the download is needed.
    """
    if _st_model_is_cached():
        return  # Already on disk — no message needed
    print(
        "  ⬇  Downloading embedding model (~80 MB) on first use — "
        "this is a one-time step."
    )
    # Trigger the actual download by loading the model
    _load_st_model()


def _load_st_model() -> Any:
    global _st_model
    if _st_model is None:
        try:
            import os as _os
            # Propagate offline / mirror env vars so the underlying library respects them.
            # HF_ENDPOINT: custom Hugging Face mirror (e.g. for corporate proxies).
            # TRANSFORMERS_OFFLINE=1: never attempt a download; raise if model not cached.
            if "HF_ENDPOINT" in _os.environ:
                _os.environ.setdefault("HF_ENDPOINT", _os.environ["HF_ENDPOINT"])
            if _os.environ.get("TRANSFORMERS_OFFLINE") == "1":
                if not _st_model_is_cached():
                    raise RuntimeError(
                        f"Embedding model '{_ST_MODEL_NAME}' is not cached and "
                        "TRANSFORMERS_OFFLINE=1.\n"
                        "Pre-download the model on a machine with internet access:\n"
                        f"  python -c \"from sentence_transformers import SentenceTransformer; "
                        f"SentenceTransformer('{_ST_MODEL_NAME}')\"\n"
                        "Then copy the cache directory to this machine."
                    )
            from sentence_transformers import SentenceTransformer
            _st_model = SentenceTransformer(_ST_MODEL_NAME)
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed and no other embedding backend "
                "is reachable.\n"
                "Install it with:  pip install sentence-transformers\n"
                "(Downloads ~80 MB model on first use, then works fully offline.)"
            ) from exc
    return _st_model


# ── Sync embedding implementations (run in thread pool) ──────────────────────

def _embed_ollama(text: str) -> list[float]:
    import httpx

    model = cfg.KB_EMBED_MODEL or "nomic-embed-text"
    response = httpx.post(
        f"{cfg.KB_LLM_BASE_URL}/api/embeddings",
        json={"model": model, "prompt": text[: _budget("embed_chars")]},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def _embed_openai(text: str) -> list[float]:
    import httpx

    base = cfg.KB_LLM_BASE_URL.rstrip("/")
    model = cfg.KB_EMBED_MODEL or "text-embedding-3-small"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.KB_API_KEY:
        headers["Authorization"] = f"Bearer {cfg.KB_API_KEY}"
    response = httpx.post(
        f"{base}/embeddings",
        headers=headers,
        json={"model": model, "input": text[: _budget("embed_chars")]},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def _embed_sentence_transformers(text: str) -> list[float]:
    model = _load_st_model()
    return model.encode(text[: _budget("embed_chars")]).tolist()


def _embed_sync(text: str) -> list[float]:
    """
    Try embedding backends in priority order:
      passthrough  → sentence-transformers directly
      openai/custom/anthropic → OpenAI-compatible API
      ollama       → Ollama /api/embeddings
    Fallback to sentence-transformers on primary failure (when KB_PASSTHROUGH_FALLBACK).
    """
    provider = cfg.KB_LLM_PROVIDER.lower()

    if provider == "passthrough":
        return _embed_sentence_transformers(text)

    try:
        if provider in ("openai", "anthropic", "custom"):
            return _embed_openai(text)
        else:  # ollama or unknown
            return _embed_ollama(text)
    except Exception as primary_err:
        if cfg.KB_PASSTHROUGH_FALLBACK:
            try:
                return _embed_sentence_transformers(text)
            except ImportError:
                pass
        raise RuntimeError(
            f"Primary embedding failed ({primary_err}) and sentence-transformers "
            f"is not available as a fallback.\n"
            f"Either fix the LLM connection or run:  pip install sentence-transformers"
        ) from primary_err


# ── Dimension cache ───────────────────────────────────────────────────────────

_cached_dim: int | None = None


def embedding_dim() -> int:
    """Return the dimension of the current embedding backend (cached after first call)."""
    global _cached_dim
    if _cached_dim is None:
        vec = _embed_sync("dimension probe")
        _cached_dim = len(vec)
    return _cached_dim


def backend_name() -> str:
    """Human-readable label for the active embedding backend."""
    provider = cfg.KB_LLM_PROVIDER.lower()
    if provider == "passthrough":
        return "sentence-transformers (offline)"
    if provider in ("openai", "anthropic", "custom"):
        return f"openai-compat ({cfg.KB_EMBED_MODEL or 'text-embedding-3-small'})"
    return f"ollama ({cfg.KB_EMBED_MODEL or 'nomic-embed-text'})"


def effective_model_name() -> str:
    """
    Return the canonical embedding model identifier for the current configuration.

    This is a stable, machine-comparable string (not a display label) intended
    for stamping into ChromaDB collection metadata at index time and comparing
    against that stamp at query / doctor time.

    Format: "<provider>:<model_name>"
      passthrough → "st:all-MiniLM-L6-v2"
      ollama      → "ollama:<KB_EMBED_MODEL or 'nomic-embed-text'>"
      openai/...  → "openai:<KB_EMBED_MODEL or 'text-embedding-3-small'>"
    """
    provider = cfg.KB_LLM_PROVIDER.lower()
    if provider == "passthrough":
        return f"st:{_ST_MODEL_NAME}"
    if provider in ("openai", "anthropic", "custom"):
        return f"openai:{cfg.KB_EMBED_MODEL or 'text-embedding-3-small'}"
    return f"ollama:{cfg.KB_EMBED_MODEL or 'nomic-embed-text'}"


# ── Public async API ──────────────────────────────────────────────────────────

async def embed(text: str) -> list[float]:
    """
    Async embedding — returns a float vector.
    All network/CPU work runs in a thread pool so the event loop is never blocked.
    """
    return await asyncio.to_thread(_embed_sync, text)
