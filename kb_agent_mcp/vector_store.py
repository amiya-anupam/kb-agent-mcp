"""
kb_agent_mcp/vector_store.py
─────────────────────────────
ChromaDB-backed persistent vector store with hybrid BM25 + vector search
and sliding-window chunked indexing.

Each knowledge domain gets its own ChromaDB collection and an in-process
BM25 index (rank_bm25).  Every search fuses both ranked lists using
Reciprocal Rank Fusion (RRF), which improves recall for exact-term queries
("FY2025", "ACE 11.3", "ELA status") where cosine similarity alone can miss.

Files are split into overlapping chunks so answers that straddle a boundary
are never silently lost.  Each chunk is stored as a separate ChromaDB entry;
search results are deduplicated back to file level before being returned.

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
import re
from collections import OrderedDict
from typing import NamedTuple, TypedDict

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from kb_agent_mcp.config import cfg
from kb_agent_mcp.embeddings import embed as _async_embed, _embed_sync
from kb_agent_mcp.file_parser import INCLUDE_EXTS, should_skip, snippet as _snippet

# ── Chunking parameters ───────────────────────────────────────────────────────
# Documents are split into overlapping windows so answers near chunk boundaries
# are never silently dropped.
#
# CHUNK_SIZE  — characters per chunk (~875 tokens at 4 chars/token; fits
#               comfortably within any embedding model's context window).
# CHUNK_OVERLAP — characters shared between consecutive chunks (~50 tokens).
#               This is the sliding-window margin that recovers boundary answers.
#
# These defaults can be overridden via KB_CHUNK_SIZE / KB_CHUNK_OVERLAP env vars
# (read once at module import so hot-reload is not needed for tests).
import os as _os

_CHUNK_SIZE    = int(_os.environ.get("KB_CHUNK_SIZE",    "3500"))
_CHUNK_OVERLAP = int(_os.environ.get("KB_CHUNK_OVERLAP", "200"))

# Separator used in ChromaDB document IDs to attach the chunk index.
# Must not appear in normal file paths.
_CHUNK_SEP = "::chunk_"


def chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """
    Split *text* into overlapping character-level windows.

    Args:
        text:    Full document text to split.
        size:    Maximum characters per chunk.
        overlap: Characters shared between consecutive chunks (sliding window).

    Returns:
        A list of non-empty chunk strings.  If the text fits in a single chunk
        the list contains exactly one element (no splitting overhead).

    Notes:
        • The last chunk may be shorter than *size*.
        • overlap must be < size; if not, it is clamped to size // 2.
    """
    if not text:
        return []
    overlap = min(overlap, size // 2)   # guard against misconfiguration
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap           # slide back by *overlap* characters
    return chunks


def _chunk_id(file_id: str, idx: int) -> str:
    """Build the ChromaDB document ID for chunk *idx* of *file_id*."""
    return f"{file_id}{_CHUNK_SEP}{idx}"


def _file_id_from_chunk(chunk_id: str) -> str:
    """Strip the ``::chunk_N`` suffix to recover the canonical file path."""
    sep_pos = chunk_id.find(_CHUNK_SEP)
    return chunk_id[:sep_pos] if sep_pos != -1 else chunk_id

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
    score: float      # RRF-fused relevance score (0.0–1.0 range)


# ── BM25 index (one per domain, lazily built) ─────────────────────────────────
# Stored as: {domain: _BM25Entry} — invalidated on every upsert/delete so the
# next search transparently rebuilds it.  Building is O(N) over the corpus
# (N = number of indexed documents), which is fast enough in-process for the
# typical KB sizes we target (hundreds to low-thousands of documents).

_BM25_CACHE: dict[str, "_BM25Entry"] = {}  # domain → entry


class _BM25Entry(NamedTuple):
    index: object          # BM25Okapi instance
    ids: list[str]         # parallel list of doc IDs


def _tokenise(text: str) -> list[str]:
    """
    Simple whitespace + punctuation tokeniser that preserves alphanumeric tokens.
    Lowercases so 'ACE' and 'ace' match; keeps numbers so 'FY2025' is a token.
    """
    return re.findall(r"[a-z0-9]+", text.lower())


def _build_bm25_for_domain(domain: str) -> "_BM25Entry | None":
    """
    Fetch all documents from the ChromaDB collection and build a BM25Okapi index.
    Returns None if the collection is empty or rank_bm25 is not installed.
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        logger.debug("rank_bm25 not installed; BM25 disabled for domain %r", domain)
        return None

    col = get_or_create_collection(domain)
    try:
        all_docs = col.get(include=["documents", "metadatas"])
    except Exception as exc:
        logger.warning("BM25 build: col.get() failed for domain %r (%s)", domain, exc)
        return None

    ids       = all_docs.get("ids") or []
    documents = all_docs.get("documents") or []
    metadatas = all_docs.get("metadatas") or []

    if not ids:
        return None

    corpus: list[list[str]] = []
    doc_ids: list[str] = []
    for doc_id, doc, meta in zip(ids, documents, metadatas):
        # Prepend the filename so exact-name matches score higher
        name = (meta or {}).get("name", "")
        combined = f"{name} {doc or ''}"
        corpus.append(_tokenise(combined))
        doc_ids.append(doc_id)

    return _BM25Entry(index=BM25Okapi(corpus), ids=doc_ids)


def _get_bm25(domain: str) -> "_BM25Entry | None":
    """Return (or lazily build) the BM25 index for a domain."""
    if domain not in _BM25_CACHE:
        entry = _build_bm25_for_domain(domain)
        if entry is None:
            return None
        _BM25_CACHE[domain] = entry
    return _BM25_CACHE[domain]


def _invalidate_bm25(domain: str) -> None:
    """Drop the cached BM25 index for a domain (called on upsert/delete)."""
    _BM25_CACHE.pop(domain, None)


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────
# Standard RRF formula: score(d) = Σ 1 / (k + rank(d))
# k=60 is the canonical value from Cormack et al. 2009 and works well in
# practise without tuning.

_RRF_K = 60


def _rrf_fuse(
    vector_results: list[SearchResult],
    bm25_results:   list[SearchResult],
    top_n: int,
) -> list[SearchResult]:
    """
    Merge two ranked lists using Reciprocal Rank Fusion.

    Both lists are ranked 1-based (rank 1 = most relevant).
    Returns up to *top_n* results re-sorted by fused RRF score, descending.
    The final `score` field on each result is normalised to [0, 1] so callers
    (confidence footer etc.) remain compatible.
    """
    # Build path → result mapping (path is the stable document ID)
    all_by_path: dict[str, SearchResult] = {}
    for r in vector_results + bm25_results:
        all_by_path.setdefault(r["path"], r)

    rrf_scores: dict[str, float] = {}

    for rank, r in enumerate(vector_results, start=1):
        rrf_scores[r["path"]] = rrf_scores.get(r["path"], 0.0) + 1.0 / (_RRF_K + rank)

    for rank, r in enumerate(bm25_results, start=1):
        rrf_scores[r["path"]] = rrf_scores.get(r["path"], 0.0) + 1.0 / (_RRF_K + rank)

    if not rrf_scores:
        return []

    # Normalise to [0, 1]: max possible RRF score when a doc ranks first in both lists
    max_possible = 2.0 / (_RRF_K + 1)
    sorted_paths = sorted(rrf_scores, key=lambda p: rrf_scores[p], reverse=True)[:top_n]

    fused: list[SearchResult] = []
    for path in sorted_paths:
        r = dict(all_by_path[path])
        r["score"] = min(1.0, rrf_scores[path] / max_possible)
        fused.append(SearchResult(**r))  # type: ignore[misc]
    return fused


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
    Index or re-index a single file using overlapping chunk windows.

    Each document is split into chunks of ~_CHUNK_SIZE characters with
    _CHUNK_OVERLAP characters of overlap.  Every chunk is stored as a
    separate ChromaDB entry so answers near chunk boundaries are not lost.

    Change detection: the file hash is stored on chunk_0's metadata.  If the
    hash matches the stored value the file is skipped (no re-embedding needed).

    Returns True if the file was (re-)indexed, False if it was skipped.
    """
    if should_skip(file_path):
        return False
    if file_path.suffix.lower() not in INCLUDE_EXTS:
        return False

    col = get_or_create_collection(domain)
    doc_id       = _file_id(file_path)
    current_hash = _file_hash(file_path)

    # Change-detection: check hash stored on the first chunk (chunk_0).
    # If the hash matches, the file content is unchanged — skip re-indexing.
    chunk0_id = _chunk_id(doc_id, 0)
    try:
        existing = col.get(ids=[chunk0_id], include=["metadatas"])
        if existing["metadatas"] and existing["metadatas"][0].get("hash") == current_hash:
            return False  # unchanged
    except Exception as exc:
        logger.warning("Hash-check for %s failed (%s); will re-index", doc_id, exc)

    # Extract the full document text (up to KB_BUDGET_EMBED_CHARS) and chunk it.
    full_text = _snippet(file_path, max_chars=cfg.KB_BUDGET_EMBED_CHARS)
    chunks    = chunk_text(full_text)

    # Delete any previously stored chunks for this file before re-indexing.
    # We use a metadata filter so stale chunks from a previously larger file
    # are also removed (e.g. if _CHUNK_SIZE shrank between runs).
    try:
        col.delete(where={"path": doc_id})
    except Exception as exc:
        logger.debug("Pre-delete of old chunks for %s failed (%s); continuing", doc_id, exc)

    # Embed and upsert each chunk.
    ids:        list[str]        = []
    embeddings: list[list[float]] = []
    documents:  list[str]        = []
    metadatas:  list[dict]       = []

    for idx, chunk in enumerate(chunks):
        # Prepend the filename to every chunk so keyword/semantic search for the
        # file name always scores highly, regardless of which chunk matches.
        embed_input = f"{file_path.name}\n{chunk}"
        vector = _embed_sync(embed_input)

        ids.append(_chunk_id(doc_id, idx))
        embeddings.append(vector)
        documents.append(chunk)
        metadatas.append({
            "path":        doc_id,          # canonical file path (no ::chunk_N suffix)
            "name":        file_path.name,
            "folder":      domain,
            "chunk_index": idx,
            "chunk_total": len(chunks),
            # hash only stored on chunk 0 — sufficient for change detection
            "hash": current_hash if idx == 0 else "",
        })

    col.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    _invalidate_bm25(domain)   # corpus changed — next search rebuilds the index
    return True


def _delete_file_sync(domain: str, file_path: pathlib.Path) -> None:
    """Remove all chunks of a file from the domain's vector index."""
    col    = get_or_create_collection(domain)
    doc_id = _file_id(file_path)
    try:
        # Delete every chunk that carries this file's canonical path in metadata.
        col.delete(where={"path": doc_id})
        _invalidate_bm25(domain)   # corpus changed — next search rebuilds the index
    except Exception as exc:
        logger.warning(
            "Failed to delete file %s from domain %r index (%s)",
            file_path, domain, exc,
        )


# ── Sync search (used by base_agent via thread pool) ─────────────────────────

def _dedup_to_file_level(results: list[SearchResult]) -> list[SearchResult]:
    """
    Deduplicate a list of chunk-level SearchResults to file level.

    When a document is split into multiple chunks, several results may share
    the same ``path`` (the canonical file path stored in metadata).  Keep
    only the highest-scoring chunk per file, preserving the original rank
    order of the winner.

    If a result carries a chunk ``summary``, it is the most relevant excerpt
    for this file — callers (passthrough block, confidence footer) already
    display the summary verbatim, so the best-matching chunk is exactly what
    we want.
    """
    seen:    dict[str, float]        = {}   # path → best score so far
    winners: dict[str, SearchResult] = {}   # path → winning SearchResult

    for r in results:
        path = r["path"]
        if path not in seen or r["score"] > seen[path]:
            seen[path]    = r["score"]
            winners[path] = r

    # Preserve input rank order (first occurrence wins for tie-breaking)
    deduped: list[SearchResult] = []
    seen_paths: set[str] = set()
    for r in results:
        path = r["path"]
        if path not in seen_paths:
            seen_paths.add(path)
            deduped.append(winners[path])
    return deduped


def _vector_search_sync(
    domain: str, query: str, top_n: int, col, count: int, query_vec: list[float]
) -> list[SearchResult]:
    """
    Run ChromaDB ANN vector search and return up to *top_n* file-level results.
    Falls back to full-scan cosine or keyword on any failure.

    ChromaDB is queried for more candidates than top_n so that after
    chunk-to-file deduplication we still have enough distinct files.
    """
    # Over-fetch to account for multiple chunks per file; cap at collection size.
    fetch_n = min(top_n * 4, count)
    try:
        res = col.query(
            query_embeddings=[query_vec],
            n_results=fetch_n,
            include=["documents", "metadatas", "distances"],
        )
        ids       = res["ids"][0]
        metas     = res["metadatas"][0]
        docs      = res["documents"][0]
        distances = res["distances"][0]

        raw: list[SearchResult] = []
        for doc_id, meta, doc, dist in zip(ids, metas, docs, distances):
            meta = meta or {}
            # ChromaDB returns L2 distance; convert to a 0–1 similarity score
            score = max(0.0, 1.0 - float(dist))
            raw.append(SearchResult(
                path=meta.get("path", _file_id_from_chunk(doc_id)),
                name=meta.get("name", pathlib.Path(_file_id_from_chunk(doc_id)).name),
                folder=meta.get("folder", domain),
                summary=doc or "",
                score=score,
            ))
        return _dedup_to_file_level(raw)[:top_n]

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
            query_arr    = np.array([query_vec])
            doc_arr      = np.array(embeddings)
            q_dim        = query_arr.shape[1]
            mask         = [i for i, e in enumerate(embeddings) if len(e) == q_dim]
            if not mask:
                return _keyword_fallback(domain, query, top_n, all_docs)
            filtered_arr = doc_arr[mask]
            scores       = cosine_similarity(query_arr, filtered_arr)[0]
            # Over-fetch before dedup — same logic as the ANN path
            top_indices  = np.argsort(scores)[::-1][:top_n * 4]
            raw_fallback: list[SearchResult] = []
            for rank_idx in top_indices:
                orig_idx  = mask[rank_idx]
                raw_id    = all_docs["ids"][orig_idx]
                meta      = all_docs["metadatas"][orig_idx] or {}
                file_path = meta.get("path", _file_id_from_chunk(raw_id))
                raw_fallback.append(SearchResult(
                    path=file_path,
                    name=meta.get("name", pathlib.Path(file_path).name),
                    folder=meta.get("folder", domain),
                    summary=all_docs["documents"][orig_idx] or "",
                    score=float(scores[rank_idx]),
                ))
            return _dedup_to_file_level(raw_fallback)[:top_n]
        except Exception as exc3:
            logger.warning("Full-scan fallback also failed (%s); using keyword fallback", exc3)
            return _keyword_fallback(domain, query, top_n, all_docs)


def _bm25_search_sync(
    domain: str, query: str, top_n: int, col
) -> list[SearchResult]:
    """
    Run BM25 search over the domain corpus and return up to *top_n* file-level results.

    The BM25 index contains one entry per chunk.  We over-fetch (top_n × 4) and
    deduplicate to file level so the caller always receives distinct files.

    Returns an empty list when rank_bm25 is unavailable or no chunk matches.
    """
    entry = _get_bm25(domain)
    if entry is None:
        return []

    query_tokens = _tokenise(query)
    if not query_tokens:
        return []

    raw_scores: list[float] = entry.index.get_scores(query_tokens)
    if not any(raw_scores):
        return []

    max_score = max(raw_scores)

    # Over-fetch chunk candidates to survive deduplication back to file level.
    fetch_n     = top_n * 4
    top_indices = sorted(range(len(raw_scores)), key=lambda i: raw_scores[i], reverse=True)[:fetch_n]
    top_ids     = [entry.ids[i] for i in top_indices]

    try:
        fetched = col.get(ids=top_ids, include=["documents", "metadatas"])
    except Exception as exc:
        logger.warning("BM25 meta fetch failed for domain %r (%s)", domain, exc)
        return []

    # Build chunk_id → (doc, meta) map for O(1) lookup
    id_to_doc  = dict(zip(fetched["ids"], fetched["documents"] or []))
    id_to_meta = dict(zip(fetched["ids"], fetched["metadatas"] or []))

    raw: list[SearchResult] = []
    for idx in top_indices:
        chunk_id  = entry.ids[idx]
        score_raw = raw_scores[idx]
        if score_raw <= 0:
            continue
        meta      = id_to_meta.get(chunk_id) or {}
        file_path = meta.get("path", _file_id_from_chunk(chunk_id))
        raw.append(SearchResult(
            path=file_path,
            name=meta.get("name", pathlib.Path(file_path).name),
            folder=meta.get("folder", domain),
            summary=id_to_doc.get(chunk_id) or "",
            score=score_raw / max_score,   # normalise to [0, 1]; overwritten by RRF anyway
        ))
    return _dedup_to_file_level(raw)[:top_n]


def _search_sync(domain: str, query: str, top_n: int = 4) -> list[SearchResult]:
    """
    Hybrid search: BM25 + vector (ChromaDB ANN), fused with Reciprocal Rank Fusion,
    then optionally reweighted by accumulated user-feedback signals.

    Strategy:
    1. Embed the query once (cached per query text).
    2. Run ChromaDB ANN vector search over chunk-level entries; deduplicate to
       file level and return up to fetch_n file results.
    3. Run BM25 keyword search over the same chunk-level corpus; deduplicate
       to file level.
    4. Fuse both file-level ranked lists with RRF and return the top-N results.
    5. Apply feedback-driven score multipliers (boost high-rated files, demote
       low-rated files) and re-sort.  No-op when no feedback exists yet.
    6. If rank_bm25 is unavailable, falls back to pure vector search.
    7. If ChromaDB is unreachable, falls back to keyword matching.

    Documents are stored as overlapping chunks (see chunk_text()).  The
    deduplicate step in each search leg ensures callers always see distinct
    files — the best-matching chunk's text is surfaced as the result summary.
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

    # Pass fetch_n file-level results to each search leg.  Each leg
    # internally over-fetches chunks (×4) and deduplicates back to files,
    # so the total ChromaDB/BM25 candidate pool is fetch_n×4 chunks per leg.
    fetch_n = min(max(top_n * 2, 10), count)

    vector_results = _vector_search_sync(domain, query, fetch_n, col, count, query_vec)
    bm25_results   = _bm25_search_sync(domain, query, fetch_n, col)

    if not bm25_results:
        # rank_bm25 unavailable or corpus empty — pure vector result (already top_n sized)
        fused = vector_results[:top_n]
    else:
        fused = _rrf_fuse(vector_results, bm25_results, top_n)

    # ── Feedback-driven reweighting ───────────────────────────────────────────
    # Applied after RRF fusion so the semantic/lexical ranking is only nudged
    # by user signals, not overridden.  The weight table is cached (5 min TTL)
    # so this adds negligible I/O on the hot path.
    if cfg.KB_FEEDBACK_REWEIGHT_ENABLED and fused:
        try:
            from kb_agent_mcp.feedback import build_file_weights, apply_feedback_weights
            weights = build_file_weights()
            fused   = apply_feedback_weights(fused, weights)
        except Exception as exc:
            # Never let a feedback failure break retrieval
            logger.warning("Feedback reweighting failed (%s); using unweighted results", exc)

    return fused


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
    raw: list[SearchResult] = []
    for score, i in scored[:top_n * 4]:
        raw_id    = all_docs["ids"][i]
        meta      = (all_docs["metadatas"] or [{}])[i] or {}
        file_path = meta.get("path", _file_id_from_chunk(raw_id))
        raw.append(SearchResult(
            path=file_path,
            name=meta.get("name", ""),
            folder=meta.get("folder", domain),
            summary=(all_docs["documents"] or [""])[i] or "",
            score=score,
        ))
    return _dedup_to_file_level(raw)[:top_n]


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

        # Stamp the collection with the current time and the active embedding
        # model so the stale-index TTL cache and the doctor check can detect:
        #   • files modified since last index  (indexed_at / indexed_at_iso)
        #   • KB_EMBED_MODEL changed since last index  (embed_model)
        import datetime as _dt
        from kb_agent_mcp.embeddings import effective_model_name as _eff_model
        _now = _time.time()
        await asyncio.to_thread(
            set_domain_metadata,
            domain,
            {
                "indexed_at":     _now,
                "indexed_at_iso": _dt.datetime.fromtimestamp(
                    _now, tz=_dt.timezone.utc
                ).isoformat(),
                "embed_model":    _eff_model(),
            },
        )
        return count

    return await _do_build()
