"""
tests/test_hybrid_search.py
────────────────────────────
Unit tests for hybrid BM25 + vector search with Reciprocal Rank Fusion.

Covers:
  - _tokenise()                  — basic tokenisation
  - _rrf_fuse()                  — score fusion correctness
  - _rrf_fuse() edge cases       — empty lists, single list, score normalisation
  - _bm25_search_sync()          — rank_bm25 absent / no-match / normal
  - _search_sync() integration   — BM25 path, vector-only fallback, BM25 invalidation
  - Cache invalidation           — upsert/delete clear the BM25 cache
"""
from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kb_agent_mcp.vector_store import (
    SearchResult,
    _RRF_K,
    _bm25_search_sync,
    _build_bm25_for_domain,
    _BM25_CACHE,
    _get_bm25,
    _invalidate_bm25,
    _rrf_fuse,
    _tokenise,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_result(path: str, score: float = 0.5) -> SearchResult:
    return SearchResult(
        path=path,
        name=pathlib.Path(path).name,
        folder="test_domain",
        summary="some text",
        score=score,
    )


# ── _tokenise ────────────────────────────────────────────────────────────────

class TestTokenise:
    def test_lowercase(self):
        assert _tokenise("ACE Integration") == ["ace", "integration"]

    def test_numbers_preserved(self):
        tokens = _tokenise("ACE 11.3 FY2025")
        assert "fy2025" in tokens
        assert "11" in tokens
        assert "3" in tokens

    def test_punctuation_stripped(self):
        tokens = _tokenise("ELA-status (check)")
        assert "ela" in tokens
        assert "status" in tokens
        assert "check" in tokens
        assert "-" not in tokens
        assert "(" not in tokens

    def test_empty_string(self):
        assert _tokenise("") == []

    def test_only_special_chars(self):
        assert _tokenise("!@#$%^&*()") == []


# ── _rrf_fuse ────────────────────────────────────────────────────────────────

class TestRrfFuse:
    def test_returns_top_n(self):
        vec = [_make_result(f"doc{i}.pdf") for i in range(5)]
        bm25 = [_make_result(f"doc{i}.pdf") for i in range(5)]
        result = _rrf_fuse(vec, bm25, top_n=3)
        assert len(result) == 3

    def test_scores_normalised(self):
        vec  = [_make_result("a.pdf")]
        bm25 = [_make_result("a.pdf")]
        result = _rrf_fuse(vec, bm25, top_n=1)
        assert len(result) == 1
        # A doc ranked first in both lists gets the maximum possible RRF score
        # which normalises to exactly 1.0
        assert abs(result[0]["score"] - 1.0) < 1e-9

    def test_empty_bm25_returns_vector_order(self):
        vec   = [_make_result("a.pdf", 0.9), _make_result("b.pdf", 0.5)]
        bm25  = []
        result = _rrf_fuse(vec, bm25, top_n=2)
        # With only one list the ordering should match input
        assert result[0]["path"] == "a.pdf"
        assert result[1]["path"] == "b.pdf"

    def test_empty_vector_returns_bm25_order(self):
        vec   = []
        bm25  = [_make_result("x.pdf"), _make_result("y.pdf")]
        result = _rrf_fuse(vec, bm25, top_n=2)
        assert result[0]["path"] == "x.pdf"

    def test_both_empty(self):
        assert _rrf_fuse([], [], top_n=4) == []

    def test_combined_rank_higher_than_single(self):
        """A doc ranked #1 in *both* lists should score higher than one ranked #1 in only one."""
        # "both.pdf" ranks first in vector AND in BM25
        # "vector_only.pdf" ranks first in vector only
        both        = _make_result("both.pdf")
        vector_only = _make_result("vector_only.pdf")
        bm25_only   = _make_result("bm25_only.pdf")

        vec_list  = [both, vector_only]
        bm25_list = [both, bm25_only]

        result = _rrf_fuse(vec_list, bm25_list, top_n=3)
        paths = [r["path"] for r in result]
        # "both.pdf" must outrank documents present in only one list
        assert paths[0] == "both.pdf"

    def test_unique_docs_in_one_list(self):
        """Documents from only one leg should still appear in the result."""
        vec  = [_make_result("vec_exclusive.pdf")]
        bm25 = [_make_result("bm25_exclusive.pdf")]
        result = _rrf_fuse(vec, bm25, top_n=5)
        paths = {r["path"] for r in result}
        assert "vec_exclusive.pdf" in paths
        assert "bm25_exclusive.pdf" in paths

    def test_rrf_formula_correctness(self):
        """Manually verify RRF score for rank-1 result in a single list."""
        r = _make_result("doc.pdf")
        fused = _rrf_fuse([r], [], top_n=1)
        # single list: rrf_score = 1/(k+1); max_possible = 2/(k+1); normalised = 0.5
        expected = 0.5
        assert abs(fused[0]["score"] - expected) < 1e-9


# ── _build_bm25_for_domain ────────────────────────────────────────────────────

class TestBuildBm25:
    def test_returns_none_when_import_missing(self, monkeypatch):
        """If rank_bm25 is not installed, build returns None gracefully."""
        import builtins
        original_import = builtins.__import__

        def _no_rank_bm25(name, *args, **kwargs):
            if name == "rank_bm25":
                raise ImportError("rank_bm25 not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_rank_bm25)
        _BM25_CACHE.clear()
        result = _build_bm25_for_domain("any_domain")
        assert result is None

    def test_returns_none_when_collection_empty(self, monkeypatch):
        """Empty ChromaDB collection → None."""
        mock_col = MagicMock()
        mock_col.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store.get_or_create_collection", lambda d: mock_col
        )
        _BM25_CACHE.clear()
        result = _build_bm25_for_domain("empty_domain")
        assert result is None

    def test_builds_index_with_documents(self, monkeypatch):
        """A non-empty collection should produce a valid _BM25Entry."""
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "ids": ["doc1.pdf", "doc2.pdf"],
            "documents": ["ACE integration platform", "CP4I cloud pak"],
            "metadatas": [
                {"path": "doc1.pdf", "name": "doc1.pdf", "folder": "ACE Docs"},
                {"path": "doc2.pdf", "name": "doc2.pdf", "folder": "ACE Docs"},
            ],
        }
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store.get_or_create_collection", lambda d: mock_col
        )
        _BM25_CACHE.clear()
        entry = _build_bm25_for_domain("ACE Docs")
        assert entry is not None
        assert len(entry.ids) == 2
        assert entry.index is not None


# ── _invalidate_bm25 ─────────────────────────────────────────────────────────

class TestInvalidateBm25:
    def test_clears_domain_entry(self):
        from kb_agent_mcp.vector_store import _BM25Entry
        _BM25_CACHE["test"] = _BM25Entry(index=object(), ids=["x"])
        _invalidate_bm25("test")
        assert "test" not in _BM25_CACHE

    def test_noop_when_not_cached(self):
        _BM25_CACHE.pop("missing", None)
        _invalidate_bm25("missing")   # should not raise


# ── _bm25_search_sync ─────────────────────────────────────────────────────────

class TestBm25SearchSync:
    def _make_mock_col(self, ids, docs, metas):
        col = MagicMock()
        col.get.return_value = {
            "ids": ids,
            "documents": docs,
            "metadatas": metas,
        }
        return col

    def test_returns_empty_when_no_bm25_entry(self, monkeypatch):
        monkeypatch.setattr("kb_agent_mcp.vector_store._get_bm25", lambda d: None)
        col = MagicMock()
        result = _bm25_search_sync("domain", "query", 4, col)
        assert result == []

    def test_returns_empty_for_empty_query_tokens(self, monkeypatch):
        from kb_agent_mcp.vector_store import _BM25Entry
        mock_index = MagicMock()
        mock_index.get_scores.return_value = [0.0, 0.0]
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._get_bm25",
            lambda d: _BM25Entry(index=mock_index, ids=["a.pdf", "b.pdf"]),
        )
        col = MagicMock()
        # All-punctuation query → no tokens
        result = _bm25_search_sync("domain", "!!! ---", 4, col)
        assert result == []

    def test_returns_empty_when_all_scores_zero(self, monkeypatch):
        from kb_agent_mcp.vector_store import _BM25Entry
        mock_index = MagicMock()
        mock_index.get_scores.return_value = [0.0, 0.0]
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._get_bm25",
            lambda d: _BM25Entry(index=mock_index, ids=["a.pdf", "b.pdf"]),
        )
        col = self._make_mock_col(["a.pdf"], ["text"], [{"name": "a.pdf", "path": "a.pdf", "folder": "d"}])
        result = _bm25_search_sync("domain", "FY2025", 4, col)
        assert result == []

    def test_returns_results_for_matching_query(self, monkeypatch):
        from kb_agent_mcp.vector_store import _BM25Entry
        mock_index = MagicMock()
        mock_index.get_scores.return_value = [5.0, 1.0]
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._get_bm25",
            lambda d: _BM25Entry(index=mock_index, ids=["best.pdf", "second.pdf"]),
        )
        col = self._make_mock_col(
            ["best.pdf", "second.pdf"],
            ["best doc", "second doc"],
            [
                {"name": "best.pdf",   "path": "best.pdf",   "folder": "d"},
                {"name": "second.pdf", "path": "second.pdf", "folder": "d"},
            ],
        )
        result = _bm25_search_sync("domain", "best query", 2, col)
        assert len(result) == 2
        assert result[0]["path"] == "best.pdf"
        assert result[0]["score"] == pytest.approx(1.0)  # best/max = 5/5

    def test_top_n_limits_results(self, monkeypatch):
        from kb_agent_mcp.vector_store import _BM25Entry
        mock_index = MagicMock()
        mock_index.get_scores.return_value = [5.0, 4.0, 3.0, 2.0]
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._get_bm25",
            lambda d: _BM25Entry(
                index=mock_index,
                ids=["a.pdf", "b.pdf", "c.pdf", "d.pdf"],
            ),
        )
        col = self._make_mock_col(
            ["a.pdf", "b.pdf"],
            ["a doc", "b doc"],
            [
                {"name": "a.pdf", "path": "a.pdf", "folder": "d"},
                {"name": "b.pdf", "path": "b.pdf", "folder": "d"},
            ],
        )
        result = _bm25_search_sync("domain", "query", 2, col)
        assert len(result) <= 2


# ── _search_sync integration ──────────────────────────────────────────────────

class TestSearchSyncIntegration:
    """
    Integration-level tests for _search_sync().
    All ChromaDB and embedding calls are mocked.
    """

    def _setup_mocks(self, monkeypatch, docs=2, bm25_available=True):
        """Return mock_col and patch everything needed."""
        mock_col = MagicMock()
        mock_col.count.return_value = docs
        # vector search response
        mock_col.query.return_value = {
            "ids": [["a.pdf", "b.pdf"][:docs]],
            "metadatas": [[
                {"path": "a.pdf", "name": "a.pdf", "folder": "d"},
                {"path": "b.pdf", "name": "b.pdf", "folder": "d"},
            ][:docs]],
            "documents": [["doc A text", "doc B text"][:docs]],
            "distances": [[0.1, 0.3][:docs]],
        }
        # bm25 metadata batch fetch
        mock_col.get.return_value = {
            "ids": ["a.pdf", "b.pdf"][:docs],
            "documents": ["doc A text", "doc B text"][:docs],
            "metadatas": [
                {"path": "a.pdf", "name": "a.pdf", "folder": "d"},
                {"path": "b.pdf", "name": "b.pdf", "folder": "d"},
            ][:docs],
        }

        monkeypatch.setattr(
            "kb_agent_mcp.vector_store.get_or_create_collection", lambda d: mock_col
        )
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store._embed_cached", lambda q: [0.1] * 384
        )

        if not bm25_available:
            monkeypatch.setattr(
                "kb_agent_mcp.vector_store._bm25_search_sync", lambda *a, **kw: []
            )
        else:
            # Provide a real-ish BM25 result list (no need to invoke rank_bm25)
            monkeypatch.setattr(
                "kb_agent_mcp.vector_store._bm25_search_sync",
                lambda domain, query, top_n, col: [
                    SearchResult(path="b.pdf", name="b.pdf", folder="d", summary="doc B text", score=0.9),
                    SearchResult(path="a.pdf", name="a.pdf", folder="d", summary="doc A text", score=0.4),
                ],
            )

        return mock_col

    def test_returns_list_of_search_results(self, monkeypatch):
        from kb_agent_mcp.vector_store import _search_sync
        self._setup_mocks(monkeypatch)
        results = _search_sync("domain", "ACE integration", top_n=2)
        assert isinstance(results, list)
        for r in results:
            assert "path" in r
            assert "score" in r

    def test_respects_top_n(self, monkeypatch):
        from kb_agent_mcp.vector_store import _search_sync
        self._setup_mocks(monkeypatch)
        results = _search_sync("domain", "query", top_n=1)
        assert len(results) <= 1

    def test_empty_collection_returns_empty(self, monkeypatch):
        from kb_agent_mcp.vector_store import _search_sync
        mock_col = MagicMock()
        mock_col.count.return_value = 0
        monkeypatch.setattr(
            "kb_agent_mcp.vector_store.get_or_create_collection", lambda d: mock_col
        )
        assert _search_sync("domain", "query") == []

    def test_falls_back_to_pure_vector_when_no_bm25(self, monkeypatch):
        """When BM25 returns empty, _search_sync should return pure vector results."""
        from kb_agent_mcp.vector_store import _search_sync
        self._setup_mocks(monkeypatch, bm25_available=False)
        results = _search_sync("domain", "query", top_n=2)
        # Still returns valid SearchResult objects from vector path
        assert len(results) >= 1

    def test_scores_between_0_and_1(self, monkeypatch):
        from kb_agent_mcp.vector_store import _search_sync
        self._setup_mocks(monkeypatch)
        results = _search_sync("domain", "FY2025 renewal", top_n=2)
        for r in results:
            assert 0.0 <= r["score"] <= 1.0


# ── BM25 cache invalidation via upsert/delete ─────────────────────────────────

class TestCacheInvalidation:
    def test_upsert_invalidates_bm25_cache(self, monkeypatch, tmp_path):
        """_upsert_file_sync() must call _invalidate_bm25 after writing to ChromaDB."""
        from kb_agent_mcp.vector_store import _BM25Entry

        invalidated: list[str] = []
        _BM25_CACHE["ACE Docs"] = _BM25Entry(index=object(), ids=["x"])

        monkeypatch.setattr("kb_agent_mcp.vector_store._invalidate_bm25",
                            lambda d: invalidated.append(d))

        # Stub out all the heavy IO
        mock_col = MagicMock()
        mock_col.get.return_value = {"metadatas": []}  # force re-index path
        monkeypatch.setattr("kb_agent_mcp.vector_store.get_or_create_collection",
                            lambda d: mock_col)
        monkeypatch.setattr("kb_agent_mcp.vector_store._file_hash", lambda p: "newhash")
        monkeypatch.setattr("kb_agent_mcp.vector_store._snippet", lambda p, **kw: "snippet text")
        monkeypatch.setattr("kb_agent_mcp.vector_store._embed_sync", lambda t: [0.0] * 384)

        # Create a real temp file with an indexed extension
        f = tmp_path / "test_doc.md"
        f.write_text("hello world")

        from kb_agent_mcp.vector_store import _upsert_file_sync
        _upsert_file_sync("ACE Docs", f)

        assert "ACE Docs" in invalidated

    def test_delete_invalidates_bm25_cache(self, monkeypatch, tmp_path):
        """_delete_file_sync() must call _invalidate_bm25 after deleting from ChromaDB."""
        from kb_agent_mcp.vector_store import _BM25Entry

        invalidated: list[str] = []
        _BM25_CACHE["ACE Docs"] = _BM25Entry(index=object(), ids=["x"])

        monkeypatch.setattr("kb_agent_mcp.vector_store._invalidate_bm25",
                            lambda d: invalidated.append(d))

        mock_col = MagicMock()
        monkeypatch.setattr("kb_agent_mcp.vector_store.get_or_create_collection",
                            lambda d: mock_col)

        f = tmp_path / "old_doc.pdf"
        f.write_text("content")

        from kb_agent_mcp.vector_store import _delete_file_sync
        _delete_file_sync("ACE Docs", f)

        assert "ACE Docs" in invalidated
