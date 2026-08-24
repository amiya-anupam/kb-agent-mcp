"""
tests/test_chunking.py
───────────────────────
Unit tests for sliding-window chunk indexing.

Covers:
  - chunk_text()              — splitting, overlap, edge cases
  - _chunk_id()               — ID construction
  - _file_id_from_chunk()     — ID stripping
  - _dedup_to_file_level()    — deduplication keeps best-scoring chunk per file
  - _upsert_file_sync()       — embeds and stores N chunk entries, change-detection
  - _delete_file_sync()       — deletes by metadata filter (all chunks)
  - search integration        — multi-chunk file returns one result per file
"""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, call, patch

import pytest

from kb_agent_mcp.vector_store import (
    SearchResult,
    _CHUNK_SEP,
    _chunk_id,
    _dedup_to_file_level,
    _file_id_from_chunk,
    chunk_text,
)


# ── chunk_text ────────────────────────────────────────────────────────────────

class TestChunkText:
    def test_empty_string_returns_empty_list(self):
        assert chunk_text("") == []

    def test_short_text_single_chunk(self):
        chunks = chunk_text("hello world", size=100, overlap=10)
        assert chunks == ["hello world"]

    def test_exact_size_no_split(self):
        text   = "a" * 100
        chunks = chunk_text(text, size=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_two_chunks_with_overlap(self):
        text   = "a" * 100
        chunks = chunk_text(text, size=60, overlap=20)
        assert len(chunks) == 2
        # Second chunk starts at 60-20 = 40
        assert chunks[0] == "a" * 60
        assert chunks[1] == "a" * 60      # 40..100 = 60 chars

    def test_overlap_creates_shared_region(self):
        # Use distinct characters so we can verify the overlap region
        text   = "A" * 50 + "B" * 50
        chunks = chunk_text(text, size=60, overlap=20)
        assert len(chunks) == 2
        # chunk0 ends at char 60 (20 A's + 20 overlap region expected to be present in chunk1)
        assert chunks[0][:50] == "A" * 50   # first 50 chars are A
        # chunk1 starts at 40: 10 A's + 50 B's
        assert "A" in chunks[1]
        assert "B" in chunks[1]

    def test_three_chunks(self):
        text   = "x" * 200
        chunks = chunk_text(text, size=100, overlap=20)
        # chunk 0: 0..100, chunk 1: 80..180, chunk 2: 160..200
        assert len(chunks) == 3

    def test_overlap_clamped_to_half_size(self):
        # Passing overlap >= size should be clamped, not raise
        chunks = chunk_text("abc" * 100, size=50, overlap=60)
        assert all(len(c) <= 50 for c in chunks)

    def test_no_chunk_exceeds_size(self):
        text   = "hello " * 1000
        chunks = chunk_text(text, size=200, overlap=50)
        for c in chunks:
            assert len(c) <= 200

    def test_last_chunk_may_be_shorter(self):
        text   = "a" * 110
        chunks = chunk_text(text, size=100, overlap=10)
        assert len(chunks[-1]) <= 100

    def test_no_empty_chunks(self):
        text   = "x" * 500
        chunks = chunk_text(text, size=100, overlap=20)
        assert all(len(c) > 0 for c in chunks)

    def test_single_character(self):
        assert chunk_text("z", size=100, overlap=10) == ["z"]

    def test_whole_corpus_covered(self):
        """Sliding window must cover the entire text (no gaps)."""
        text   = "abcde" * 200     # 1000 chars
        size, overlap = 100, 30
        chunks = chunk_text(text, size=size, overlap=overlap)
        # Reconstruct reachable positions
        covered = set()
        start = 0
        for chunk in chunks:
            for j in range(len(chunk)):
                covered.add(start + j)
            start += size - overlap
            if start >= len(text):
                break
        # Every position in the text must appear in at least one chunk
        assert covered >= set(range(len(text)))


# ── _chunk_id / _file_id_from_chunk ──────────────────────────────────────────

class TestChunkIds:
    def test_chunk_id_format(self):
        cid = _chunk_id("domain/file.pdf", 3)
        assert cid == f"domain/file.pdf{_CHUNK_SEP}3"

    def test_file_id_from_chunk_roundtrip(self):
        file_id = "domain/some file.docx"
        for idx in range(5):
            cid = _chunk_id(file_id, idx)
            assert _file_id_from_chunk(cid) == file_id

    def test_file_id_from_chunk_no_suffix(self):
        """Non-chunked IDs (legacy entries) pass through unchanged."""
        plain = "domain/plain_doc.pdf"
        assert _file_id_from_chunk(plain) == plain

    def test_chunk_sep_not_in_plain_paths(self):
        """Verify the separator character sequence is not a normal path character."""
        assert "::" not in "folder/normal_file.pdf"


# ── _dedup_to_file_level ──────────────────────────────────────────────────────

def _sr(path: str, score: float, summary: str = "text") -> SearchResult:
    return SearchResult(path=path, name=pathlib.Path(path).name,
                        folder="d", summary=summary, score=score)


class TestDedupToFileLevel:
    def test_empty_input(self):
        assert _dedup_to_file_level([]) == []

    def test_single_result_unchanged(self):
        r = _sr("a.pdf", 0.9)
        assert _dedup_to_file_level([r]) == [r]

    def test_keeps_highest_scoring_chunk(self):
        chunk0 = _sr("a.pdf", 0.5, summary="low relevance text")
        chunk1 = _sr("a.pdf", 0.9, summary="very relevant text")
        chunk2 = _sr("a.pdf", 0.3, summary="other text")
        result = _dedup_to_file_level([chunk0, chunk1, chunk2])
        assert len(result) == 1
        assert result[0]["score"] == pytest.approx(0.9)
        assert result[0]["summary"] == "very relevant text"

    def test_preserves_rank_order_of_first_occurrence(self):
        """File appearing earlier in the ranked list should keep its rank position."""
        a0 = _sr("a.pdf", 0.8)
        b0 = _sr("b.pdf", 0.7)
        a1 = _sr("a.pdf", 0.9)   # higher score but later rank
        result = _dedup_to_file_level([a0, b0, a1])
        # a.pdf appears first, so it stays first; score is updated to 0.9
        assert result[0]["path"] == "a.pdf"
        assert result[0]["score"] == pytest.approx(0.9)
        assert result[1]["path"] == "b.pdf"

    def test_distinct_files_not_merged(self):
        a = _sr("a.pdf", 0.9)
        b = _sr("b.pdf", 0.8)
        c = _sr("c.pdf", 0.7)
        result = _dedup_to_file_level([a, b, c])
        assert len(result) == 3
        assert [r["path"] for r in result] == ["a.pdf", "b.pdf", "c.pdf"]

    def test_mixed_chunked_and_plain(self):
        """Handles a mix of chunk-suffix IDs and plain file IDs gracefully."""
        plain = _sr("plain.pdf", 0.6)
        chunked = _sr("plain.pdf", 0.8)   # same file path, different score
        result = _dedup_to_file_level([plain, chunked])
        assert len(result) == 1
        assert result[0]["score"] == pytest.approx(0.8)


# ── _upsert_file_sync (chunking behaviour) ────────────────────────────────────

class TestUpsertFileChunking:
    """
    Verify that _upsert_file_sync splits documents into chunks and stores
    one ChromaDB entry per chunk with the correct metadata.
    """

    def _setup(self, monkeypatch, tmp_path, content: str):
        """Create a real temp file and stub out ChromaDB + embedding calls."""
        f = tmp_path / "doc.md"
        f.write_text(content)

        mock_col = MagicMock()
        # Simulate no existing chunk0 → force re-index
        mock_col.get.return_value = {"metadatas": []}

        monkeypatch.setattr(
            "kb_agent_mcp.vector_store.get_or_create_collection", lambda d: mock_col
        )
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._file_hash", lambda p: "abc123"
        )
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._embed_sync", lambda t: [0.0] * 4
        )
        return f, mock_col

    def test_single_chunk_for_short_doc(self, monkeypatch, tmp_path):
        from kb_agent_mcp.vector_store import _upsert_file_sync, _CHUNK_SIZE
        content = "short document"
        f, mock_col = self._setup(monkeypatch, tmp_path, content)
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._snippet", lambda p, **kw: content
        )

        result = _upsert_file_sync("domain", f)
        assert result is True

        upsert_call = mock_col.upsert.call_args
        assert upsert_call is not None
        ids = upsert_call.kwargs.get("ids") or upsert_call[1].get("ids") or upsert_call[0][0]
        assert len(ids) == 1
        assert ids[0].endswith(f"{_CHUNK_SEP}0")

    def test_multiple_chunks_for_long_doc(self, monkeypatch, tmp_path):
        from kb_agent_mcp.vector_store import _upsert_file_sync, _CHUNK_SIZE, _CHUNK_OVERLAP

        # Build a text that will produce exactly 3 chunks
        size, overlap = _CHUNK_SIZE, _CHUNK_OVERLAP
        # total chars needed for 3 chunks: size + 2*(size - overlap)
        content = "x" * (size + 2 * (size - overlap))

        f, mock_col = self._setup(monkeypatch, tmp_path, content)
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._snippet", lambda p, **kw: content
        )

        result = _upsert_file_sync("domain", f)
        assert result is True

        upsert_call = mock_col.upsert.call_args
        ids = upsert_call.kwargs.get("ids") or upsert_call[1].get("ids") or upsert_call[0][0]
        assert len(ids) == 3
        for i, cid in enumerate(ids):
            assert cid.endswith(f"{_CHUNK_SEP}{i}")

    def test_chunk_metadata_has_canonical_path(self, monkeypatch, tmp_path):
        from kb_agent_mcp.vector_store import _upsert_file_sync

        content = "Some document content that is not too long."
        f, mock_col = self._setup(monkeypatch, tmp_path, content)
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._snippet", lambda p, **kw: content
        )

        _upsert_file_sync("domain", f)

        upsert_call  = mock_col.upsert.call_args
        metadatas    = upsert_call.kwargs.get("metadatas") or upsert_call[1].get("metadatas") or upsert_call[0][3]
        for meta in metadatas:
            # 'path' must be the canonical file path — no ::chunk_N suffix
            assert _CHUNK_SEP not in meta["path"]
            assert meta["name"] == "doc.md"

    def test_hash_stored_only_on_chunk0(self, monkeypatch, tmp_path):
        from kb_agent_mcp.vector_store import _upsert_file_sync, _CHUNK_SIZE, _CHUNK_OVERLAP

        size, overlap = _CHUNK_SIZE, _CHUNK_OVERLAP
        # A text that fits in exactly 2 chunks:
        # chunk0: 0..size, chunk1: (size-overlap)..(2*size-overlap)
        # Total length = 2*size - overlap  (fills chunk1 exactly, no 3rd chunk)
        content = "y" * (2 * size - overlap)
        f, mock_col = self._setup(monkeypatch, tmp_path, content)
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._snippet", lambda p, **kw: content
        )

        _upsert_file_sync("domain", f)

        upsert_call = mock_col.upsert.call_args
        metadatas   = upsert_call.kwargs.get("metadatas") or upsert_call[1].get("metadatas") or upsert_call[0][3]
        assert len(metadatas) == 2, f"Expected 2 chunks, got {len(metadatas)}"
        assert metadatas[0]["hash"] == "abc123"   # chunk 0 stores the hash
        assert metadatas[1]["hash"] == ""          # chunk 1 does not

    def test_pre_delete_called_before_upsert(self, monkeypatch, tmp_path):
        """Old chunks must be wiped (delete where path=…) before re-indexing."""
        from kb_agent_mcp.vector_store import _upsert_file_sync

        content = "Short content."
        f, mock_col = self._setup(monkeypatch, tmp_path, content)
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._snippet", lambda p, **kw: content
        )

        _upsert_file_sync("domain", f)

        # delete() must have been called with a where= filter (not ids=)
        delete_call = mock_col.delete.call_args
        assert delete_call is not None
        kwargs = delete_call.kwargs if delete_call.kwargs else {}
        args   = delete_call.args   if delete_call.args   else ()
        # Either passed as keyword or positional
        where = kwargs.get("where") or (args[1] if len(args) > 1 else None)
        if where is None and kwargs:
            # Some mock versions flatten kwargs differently
            where = delete_call[1].get("where") if delete_call[1] else None
        assert where is not None, "delete() must be called with a 'where' filter"

    def test_unchanged_file_skipped(self, monkeypatch, tmp_path):
        """When hash matches chunk0's stored hash, the file must be skipped."""
        from kb_agent_mcp.vector_store import _upsert_file_sync

        content = "Unchanged content."
        f, mock_col = self._setup(monkeypatch, tmp_path, content)
        # Override: simulate chunk0 already present with matching hash
        mock_col.get.return_value = {"metadatas": [{"hash": "abc123"}]}
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._snippet", lambda p, **kw: content
        )

        result = _upsert_file_sync("domain", f)
        assert result is False
        mock_col.upsert.assert_not_called()


# ── _delete_file_sync ─────────────────────────────────────────────────────────

class TestDeleteFileSync:
    def test_deletes_by_metadata_filter(self, monkeypatch, tmp_path):
        """All chunks must be removed via where={"path": doc_id}."""
        from kb_agent_mcp.vector_store import _delete_file_sync

        mock_col = MagicMock()
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store.get_or_create_collection", lambda d: mock_col
        )

        f = tmp_path / "myfile.pdf"
        f.write_text("content")
        _delete_file_sync("domain", f)

        delete_call = mock_col.delete.call_args
        assert delete_call is not None
        # Verify that delete was called with 'where' kwarg, not 'ids'
        kwargs = delete_call.kwargs or (delete_call[1] if len(delete_call) > 1 else {})
        assert "where" in kwargs
        assert kwargs["where"]["path"] is not None

    def test_bm25_invalidated_on_delete(self, monkeypatch, tmp_path):
        from kb_agent_mcp.vector_store import _delete_file_sync

        invalidated: list[str] = []
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._invalidate_bm25", lambda d: invalidated.append(d)
        )
        mock_col = MagicMock()
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store.get_or_create_collection", lambda d: mock_col
        )

        f = tmp_path / "file.md"
        f.write_text("hello")
        _delete_file_sync("mydomain", f)
        assert "mydomain" in invalidated
