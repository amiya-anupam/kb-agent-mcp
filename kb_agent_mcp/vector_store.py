"""
kb_agent_mcp/vector_store.py
─────────────────────────────
ChromaDB-backed persistent vector store.

Each knowledge domain gets its own ChromaDB collection.
Domain metadata (description, keywords, system_prompt, etc.) is stored as
ChromaDB collection metadata so no separate domain_meta.json is needed.

Storage location: {KB_ROOT}/.kb_index/chroma/

Public API
----------
Async (call from async context):
  await upsert_file(domain, file_path)          — add/update a file in a domain
  await delete_file(domain, file_path)           — remove a file from a domain
  await search(domain, query, top_n)             → list[SearchResult]
  await build_collection(domain, folder_path)    — full rebuild for a folder

Sync (safe to call from CLI / generate tools):
  get_or_create_collection(domain)               → chromadb.Collection
  set_domain_metadata(domain, metadata)          — store domain config
  get_domain_metadata(domain)                    → dict | None
  list_domains()                                 → list[str]
  collection_exists(domain)                      → bool
  delete_collection(domain)                      — remove domain entirely

Types
-----
SearchResult = TypedDict with keys: path, name, folder, summary, score
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import pathlib
from collections import OrderedDict
from typing import TypedDict

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from kb_agent_mcp.config import cfg
from kb_agent_mcp.embeddings import embed as _async_embed, _embed_sync
from kb_agent_mcp.file_parser import INCLUDE_EXTS, should_skip, snippet as _snippet

logger = logging.getLogger(__name__)

# ── Query-embedding LRU cache ─────────────────────────────────────────────────
# Embedding the same query text is deterministic — cache the result to avoid
# re-running the model (or making a network call) when the same question is
# asked across domains in one orchestrator dispatch, or again in a follow-up.
_EMBED_CACHE_MAX = 128  # entries
_embed_cache: OrderedDict[str, list[float]] = OrderedDict()


def _embed_cached(text: str) -> list[float]:
    """Return the embedding for text, computing it only on the first call."""
    key = hashlib.sha1(text.encode()).hexdigest()
    if key in _embed_cache:
        _embed_cache.move_to_end(key)       # mark as recently used
        return _embed_cache[key]
    vec = _embed_sync(text)
    _embed_cache[key] = vec
    if len(_embed_cache) > _EMBED_CACHE_MAX:
        _embed_cache.popitem(last=False)    # evict oldest
    return vec


# ── Types ─────────────────────────────────────────────────────────────────────

class SearchResult(TypedDict):
    path: str         # relative path from KB_ROOT
    name: str         # filename
    folder: str       # domain folder name
    summary: str      # text snippet used for embedding
    score: float      # cosine similarity 0.0–1.0


# ── ChromaDB client singleton ─────────────────────────────────────────────────

_client = None


def _get_client():
    """Return (or lazily create) the persistent ChromaDB client."""
    global _client
    if _client is None:
        import chromadb
        index_path = cfg.kb_index_path / "chroma"
        index_path.mkdir(parents=True, exist_ok=True)
        try:
            _client = chromadb.PersistentClient(path=str(index_path))
        except Exception as exc:
            raise RuntimeError(
                f"ChromaDB failed to open the index at {index_path}.\n"
                "This can happen after a package upgrade if the index schema changed.\n"
                "Fix: delete the index directory and re-run kb-agent-generate:\n"
                f"  rm -rf \"{index_path}\"\n"
                "  kb-agent-generate\n"
                f"Original error: {exc}"
            ) from exc
    return _client


def _safe_name(domain: str) -> str:
    """Convert a domain folder name to a ChromaDB-safe collection name."""
    import re
    name = domain.lower()
    name = re.sub(r"[^a-z0-9_-]", "_", name)
    name = name.strip("_-")
    # ChromaDB requires 3–63 chars
    if len(name) < 3:
        name = name + "_kb"
    if len(name) > 63:
        name = name[:63]
    return name


def _file_id(file_path: str | pathlib.Path, kb_root: pathlib.Path | None = None) -> str:
    """Stable document ID = relative path from KB_ROOT."""
    p = pathlib.Path(file_path)
    root = kb_root or cfg.kb_root_path
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _file_hash(file_path: pathlib.Path) -> str:
    """MD5 of file contents — used for change detection."""
    try:
        h = hashlib.md5()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


# ── Collection management (sync) ──────────────────────────────────────────────

def get_or_create_collection(domain: str):
    """Return (or create) the ChromaDB collection for a domain."""
    client = _get_client()
    return client.get_or_create_collection(
        name=_safe_name(domain),
        metadata={"hnsw:space": "cosine"},
    )


def collection_exists(domain: str) -> bool:
    """Return True if a collection for this domain already exists."""
    client = _get_client()
    try:
        client.get_collection(_safe_name(domain))
        return True
    except Exception as exc:
        logger.warning(
            "collection_exists check for domain %r failed (%s); returning False",
            domain, exc,
        )
        return False


def list_domains() -> list[str]:
    """
    Return all domain names that have been indexed.
    Reads the human-readable name from collection metadata (folder_name key).
    """
    client = _get_client()
    domains = []
    for col in client.list_collections():
        meta = col.metadata or {}
        name = meta.get("folder_name") or col.name
        domains.append(name)
    return sorted(domains)


def set_domain_metadata(domain: str, metadata: dict) -> None:
    """
    Store domain configuration as ChromaDB collection metadata.
    Replaces any previously stored metadata for this domain.
    """
    client = _get_client()
    safe = _safe_name(domain)
    # ChromaDB metadata values must be str/int/float/bool — serialize nested dicts
    flat: dict[str, str | int | float | bool] = {}
    for k, v in metadata.items():
        if isinstance(v, (str, int, float, bool)):
            flat[k] = v
        elif isinstance(v, list):
            import json
            flat[k] = json.dumps(v)
        elif isinstance(v, dict):
            import json
            flat[k] = json.dumps(v)
        else:
            flat[k] = str(v)
    flat["hnsw:space"] = "cosine"
    try:
        col = client.get_collection(safe)
        col.modify(metadata=flat)
    except Exception as exc:
        logger.debug(
            "Metadata modify failed for domain %r (%s); falling back to get_or_create",
            domain, exc,
        )
        client.get_or_create_collection(safe, metadata=flat)


def get_domain_metadata(domain: str) -> dict | None:
    """Return stored domain metadata dict, or None if domain not found."""
    import json as _json
    client = _get_client()
    try:
        col = client.get_collection(_safe_name(domain))
        meta = dict(col.metadata or {})
        meta.pop("hnsw:space", None)
        # Deserialize JSON-encoded lists/dicts
        for k, v in meta.items():
            if isinstance(v, str) and v.startswith(("[", "{")):
                try:
                    meta[k] = _json.loads(v)
                except Exception as exc:
                    logger.debug(
                        "JSON decode failed for metadata key %r in domain %r (%s)",
                        k, domain, exc,
                    )
        return meta
    except Exception as exc:
        logger.warning(
            "get_domain_metadata for domain %r failed (%s); returning None",
            domain, exc,
        )
        return None


def delete_collection(domain: str) -> None:
    """Permanently delete a domain's ChromaDB collection."""
    client = _get_client()
    try:
        client.delete_collection(_safe_name(domain))
    except Exception as exc:
        logger.warning(
            "delete_collection for domain %r failed (%s); collection may still exist",
            domain, exc,
        )


# ── Sync upsert / delete (used internally and by CLI tools) ──────────────────

def _upsert_file_sync(domain: str, file_path: pathlib.Path) -> bool:
    """
    Index or re-index a single file.
    Returns True if the file was (re-)indexed, False if it was skipped (unchanged).
    """
    if should_skip(file_path):
        return False
    if file_path.suffix.lower() not in INCLUDE_EXTS:
        return False

    col = get_or_create_collection(domain)
    doc_id = _file_id(file_path)
    current_hash = _file_hash(file_path)

    # Check if file is unchanged
    try:
        existing = col.get(ids=[doc_id], include=["metadatas"])
        if existing["metadatas"] and existing["metadatas"][0].get("hash") == current_hash:
            return False  # unchanged
    except Exception as exc:
        logger.warning("Hash-check for %s failed (%s); will re-index", doc_id, exc)

    # Extract snippet and embed
    text = _snippet(file_path, max_chars=2000)
    embed_input = f"{file_path.name}\n{text}"
    vector = _embed_sync(embed_input)

    col.upsert(
        ids=[doc_id],
        embeddings=[vector],
        documents=[text],
        metadatas=[{
            "path": doc_id,
            "name": file_path.name,
            "folder": domain,
            "hash": current_hash,
        }],
    )
    return True


def _delete_file_sync(domain: str, file_path: pathlib.Path) -> None:
    """Remove a file from the domain's vector index."""
    col = get_or_create_collection(domain)
    doc_id = _file_id(file_path)
    try:
        col.delete(ids=[doc_id])
    except Exception as exc:
        logger.warning(
            "Failed to delete file %s from domain %r index (%s)",
            file_path, domain, exc,
        )


# ── Sync search (used by base_agent via thread pool) ─────────────────────────

def _search_sync(domain: str, query: str, top_n: int = 4) -> list[SearchResult]:
    """
    Semantic search within a domain's collection.
    Returns up to *top_n* results sorted by cosine similarity (descending).
    Falls back to keyword matching if no compatible embeddings exist.

    Strategy:
    1. Embed the query once.
    2. Use ChromaDB's native .query() (ANN index) to fetch only the top-N
       candidates — avoids pulling the full collection into memory.
    3. If the collection is empty or embeddings are absent, fall back to
       keyword matching (which requires the full doc set — fetched lazily).
    """
    col = get_or_create_collection(domain)

    # Fast path: check collection is non-empty without fetching embeddings
    try:
        count = col.count()
    except Exception as exc:
        logger.warning(
            "ChromaDB count() failed for domain %r (%s); returning empty results",
            domain, exc,
        )
        return []

    if count == 0:
        return []

    try:
        query_vec = _embed_cached(query)
    except Exception as exc:
        logger.warning(
            "Query embedding failed for domain %r query %r (%s); returning empty results",
            domain, query, exc,
        )
        return []

    # Use ChromaDB's native ANN query — only top_n rows transferred
    try:
        res = col.query(
            query_embeddings=[query_vec],
            n_results=min(top_n, count),
            include=["documents", "metadatas", "distances"],
        )
        ids       = res["ids"][0]
        metas     = res["metadatas"][0]
        docs      = res["documents"][0]
        distances = res["distances"][0]

        results: list[SearchResult] = []
        for doc_id, meta, doc, dist in zip(ids, metas, docs, distances):
            meta = meta or {}
            # ChromaDB returns L2 distance; convert to a 0–1 similarity score
            score = max(0.0, 1.0 - float(dist))
            results.append(SearchResult(
                path=meta.get("path", doc_id),
                name=meta.get("name", pathlib.Path(doc_id).name),
                folder=meta.get("folder", domain),
                summary=doc or "",
                score=score,
            ))
        return results

    except Exception as exc:
        logger.warning(
            "ChromaDB query() failed for domain %r query %r (%s); falling back to full scan",
            domain, query, exc,
        )
        # Last-resort: full scan fallback (original behaviour)
        try:
            all_docs = col.get(include=["embeddings", "documents", "metadatas"])
        except Exception as exc2:
            logger.warning(
                "ChromaDB get() also failed for domain %r (%s); returning empty results",
                domain, exc2,
            )
            return []
        embeddings = all_docs.get("embeddings")
        if not embeddings:
            return _keyword_fallback(domain, query, top_n, all_docs)
        try:
            query_arr   = np.array([query_vec])
            doc_arr     = np.array(embeddings)
            q_dim       = query_arr.shape[1]
            mask        = [i for i, e in enumerate(embeddings) if len(e) == q_dim]
            if not mask:
                return _keyword_fallback(domain, query, top_n, all_docs)
            filtered_arr = doc_arr[mask]
            scores       = cosine_similarity(query_arr, filtered_arr)[0]
            top_indices  = np.argsort(scores)[::-1][:top_n]
            fallback: list[SearchResult] = []
            for rank_idx in top_indices:
                orig_idx = mask[rank_idx]
                meta = all_docs["metadatas"][orig_idx] or {}
                fallback.append(SearchResult(
                    path=meta.get("path", all_docs["ids"][orig_idx]),
                    name=meta.get("name", pathlib.Path(all_docs["ids"][orig_idx]).name),
                    folder=meta.get("folder", domain),
                    summary=all_docs["documents"][orig_idx] or "",
                    score=float(scores[rank_idx]),
                ))
            return fallback
        except Exception as exc3:
            logger.warning("Full-scan fallback also failed (%s); using keyword fallback", exc3)
            return _keyword_fallback(domain, query, top_n, all_docs)


def _keyword_fallback(
    domain: str, query: str, top_n: int, all_docs: dict
) -> list[SearchResult]:
    """Simple keyword fallback when vector search fails."""
    query_words = set(query.lower().split())
    scored: list[tuple[float, int]] = []
    for i, (doc, meta) in enumerate(zip(
        all_docs["documents"] or [],
        all_docs["metadatas"] or [],
    )):
        text = ((meta or {}).get("name", "") + " " + (doc or "")).lower()
        hits = sum(1 for w in query_words if w in text)
        if hits:
            scored.append((hits / len(query_words), i))

    scored.sort(key=lambda x: -x[0])
    results: list[SearchResult] = []
    for score, i in scored[:top_n]:
        meta = (all_docs["metadatas"] or [{}])[i] or {}
        results.append(SearchResult(
            path=meta.get("path", all_docs["ids"][i]),
            name=meta.get("name", ""),
            folder=meta.get("folder", domain),
            summary=(all_docs["documents"] or [""])[i] or "",
            score=score,
        ))
    return results


# ── Async public API ──────────────────────────────────────────────────────────

async def upsert_file(domain: str, file_path: str | pathlib.Path) -> bool:
    """Async: index or re-index a single file. Returns True if file was updated."""
    return await asyncio.to_thread(_upsert_file_sync, domain, pathlib.Path(file_path))


async def delete_file(domain: str, file_path: str | pathlib.Path) -> None:
    """Async: remove a file from the domain index."""
    await asyncio.to_thread(_delete_file_sync, domain, pathlib.Path(file_path))


async def search(
    domain: str,
    query: str,
    top_n: int = 4,
) -> list[SearchResult]:
    """
    Async semantic search. Returns up to *top_n* results sorted by relevance.
    Thread-pooled so the event loop is never blocked.
    """
    return await asyncio.to_thread(_search_sync, domain, query, top_n)


async def build_collection(
    domain: str,
    folder_path: str | pathlib.Path | None = None,
    progress_fn=None,
) -> int:
    """
    Async: (Re)build the vector index for an entire domain folder.
    Recursively walks *folder_path* (defaults to KB_ROOT/domain) and upserts
    all indexable files.  Records `indexed_at` timestamp in collection metadata
    so the stale-index TTL cache in server.py can detect new files.
    Returns the count of files indexed.

    Args:
        domain:      Domain folder name.
        folder_path: Absolute path to the domain folder (optional — defaults to
                     KB_ROOT/domain when omitted).
        progress_fn: Optional callable(current_idx, total, filename) invoked
                     before each file is embedded.  Signature: (int, int, str) -> None.
    """
    import time as _time

    folder = pathlib.Path(folder_path) if folder_path is not None else cfg.kb_root_path / domain
    count = 0

    async def _do_build() -> int:
        nonlocal count
        files = [
            f for f in folder.rglob("*")
            if f.is_file()
            and f.suffix.lower() in INCLUDE_EXTS
            and not should_skip(f)
        ]
        total = len(files)
        for idx, file in enumerate(files, start=1):
            if progress_fn is not None:
                progress_fn(idx, total, file.name)
            updated = await upsert_file(domain, file)
            if updated:
                count += 1

        # Risk 11 — stamp the collection with the current time so the stale
        # TTL cache in server.py can compare file mtimes against this value.
        # indexed_at  — Unix float, used by server.py for mtime comparison
        # indexed_at_iso — ISO string, used by status/doctor for display
        import datetime as _dt
        _now = _time.time()
        await asyncio.to_thread(
            set_domain_metadata,
            domain,
            {
                "indexed_at": _now,
                "indexed_at_iso": _dt.datetime.fromtimestamp(
                    _now, tz=_dt.timezone.utc
                ).isoformat(),
            },
        )
        return count

    return await _do_build()
