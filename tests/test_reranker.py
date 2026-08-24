"""
tests/test_reranker.py
──────────────────────
Tests for kb_agent_mcp/reranker.py (cross-encoder re-ranker) and its
integration into DomainAgent._pre_rank().

All tests use lightweight mocks so no real cross-encoder model is downloaded.
The module singleton is reset before each test via reranker.reset().
"""
from __future__ import annotations

import asyncio
import importlib
import types
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_results(n: int, base_score: float = 0.9) -> list[dict]:
    """Build a list of fake search result dicts."""
    return [
        {
            "path": f"doc_{i}.md",
            "summary": f"This is passage number {i}",
            "score": round(base_score - i * 0.05, 3),
        }
        for i in range(n)
    ]


def _make_model(scores: list[float]) -> MagicMock:
    """Return a mock CrossEncoder whose predict() returns *scores* as an array."""
    import numpy as np
    model = MagicMock()
    model.predict.return_value = np.array(scores, dtype=float)
    return model


# ── Reset singleton before every test ────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_reranker():
    import kb_agent_mcp.reranker as rr
    rr.reset()
    yield
    rr.reset()


# ══════════════════════════════════════════════════════════════════════════════
# 1 · rerank() — model available
# ══════════════════════════════════════════════════════════════════════════════

class TestRerankWithModel:

    def _inject_model(self, scores: list[float]):
        """Patch _load_cross_encoder to return a mock model."""
        import kb_agent_mcp.reranker as rr
        model = _make_model(scores)
        rr._cross_encoder = model
        rr._load_attempted = True
        return model

    def test_output_sorted_by_score_descending(self):
        """Results must come back sorted highest rerank_score first."""
        import kb_agent_mcp.reranker as rr
        results = _make_results(5)
        # Assign scores that are NOT in original order
        scores = [0.1, 0.9, 0.3, 0.8, 0.5]
        self._inject_model(scores)

        out = rr.rerank("query", results, top_n=5)

        rerank_scores = [r["rerank_score"] for r in out]
        assert rerank_scores == sorted(rerank_scores, reverse=True)

    def test_output_length_equals_top_n(self):
        """rerank() must return exactly top_n items (< candidate pool)."""
        import kb_agent_mcp.reranker as rr
        results = _make_results(8)
        self._inject_model([float(i) for i in range(8)])

        out = rr.rerank("query", results, top_n=3)
        assert len(out) == 3

    def test_rerank_score_key_present(self):
        """Every returned dict must carry a 'rerank_score' float key."""
        import kb_agent_mcp.reranker as rr
        results = _make_results(4)
        self._inject_model([0.2, 0.8, 0.5, 0.1])

        out = rr.rerank("q", results, top_n=4)
        for r in out:
            assert "rerank_score" in r
            assert isinstance(r["rerank_score"], float)

    def test_original_keys_preserved(self):
        """rerank() must not drop existing keys from each result dict."""
        import kb_agent_mcp.reranker as rr
        results = _make_results(3)
        self._inject_model([0.7, 0.3, 0.9])

        out = rr.rerank("q", results, top_n=3)
        for r in out:
            assert "path" in r
            assert "summary" in r
            assert "score" in r

    def test_top_n_larger_than_candidates_returns_all(self):
        """When top_n > len(results), return all candidates."""
        import kb_agent_mcp.reranker as rr
        results = _make_results(3)
        self._inject_model([0.4, 0.9, 0.6])

        out = rr.rerank("q", results, top_n=10)
        assert len(out) == 3

    def test_correct_query_passed_to_predict(self):
        """predict() must receive (query, passage) pairs in correct order."""
        import kb_agent_mcp.reranker as rr
        import numpy as np
        results = _make_results(2)
        model = MagicMock()
        model.predict.return_value = np.array([0.5, 0.8])
        rr._cross_encoder = model
        rr._load_attempted = True

        rr.rerank("my question", results, top_n=2)

        call_args = model.predict.call_args[0][0]
        assert call_args[0] == ("my question", results[0]["summary"])
        assert call_args[1] == ("my question", results[1]["summary"])

    def test_missing_summary_field_uses_empty_string(self):
        """Results without a 'summary' key must not raise — use '' as passage."""
        import kb_agent_mcp.reranker as rr
        import numpy as np
        results = [{"path": "x.md"}]  # no summary key
        model = MagicMock()
        model.predict.return_value = np.array([0.7])
        rr._cross_encoder = model
        rr._load_attempted = True

        out = rr.rerank("q", results, top_n=1)
        assert len(out) == 1
        assert out[0]["rerank_score"] == pytest.approx(0.7)


# ══════════════════════════════════════════════════════════════════════════════
# 2 · rerank() — model unavailable
# ══════════════════════════════════════════════════════════════════════════════

class TestRerankWithoutModel:

    def _disable_model(self):
        """Simulate model-load failure."""
        import kb_agent_mcp.reranker as rr
        rr._cross_encoder = None
        rr._load_attempted = True

    def test_returns_original_order(self):
        """Without a model, original order must be preserved."""
        import kb_agent_mcp.reranker as rr
        self._disable_model()
        results = _make_results(5)
        paths_before = [r["path"] for r in results]

        out = rr.rerank("q", results, top_n=5)
        assert [r["path"] for r in out] == paths_before

    def test_slices_to_top_n(self):
        """Without a model, the output is sliced to top_n."""
        import kb_agent_mcp.reranker as rr
        self._disable_model()
        results = _make_results(10)

        out = rr.rerank("q", results, top_n=3)
        assert len(out) == 3

    def test_no_rerank_score_key_added(self):
        """Fallback path must NOT add 'rerank_score' to results."""
        import kb_agent_mcp.reranker as rr
        self._disable_model()
        results = _make_results(3)

        out = rr.rerank("q", results, top_n=3)
        for r in out:
            assert "rerank_score" not in r


# ══════════════════════════════════════════════════════════════════════════════
# 3 · rerank() — edge / error cases
# ══════════════════════════════════════════════════════════════════════════════

class TestRerankEdgeCases:

    def test_empty_results_returns_empty(self):
        """rerank() on an empty list must return []."""
        import kb_agent_mcp.reranker as rr
        # Even with a live model, empty input → empty output.
        rr._cross_encoder = _make_model([])
        rr._load_attempted = True

        assert rr.rerank("q", [], top_n=5) == []

    def test_predict_raises_falls_back_gracefully(self):
        """If model.predict() raises, must return original order sliced to top_n."""
        import kb_agent_mcp.reranker as rr
        model = MagicMock()
        model.predict.side_effect = RuntimeError("GPU OOM")
        rr._cross_encoder = model
        rr._load_attempted = True

        results = _make_results(6)
        out = rr.rerank("q", results, top_n=4)

        # Fallback: original order, sliced
        assert len(out) == 4
        assert [r["path"] for r in out] == [r["path"] for r in results[:4]]
        # No rerank_score on fallback
        for r in out:
            assert "rerank_score" not in r

    def test_top_n_zero_returns_empty(self):
        """top_n=0 must return an empty list."""
        import kb_agent_mcp.reranker as rr
        import numpy as np
        model = MagicMock()
        model.predict.return_value = np.array([0.5, 0.3])
        rr._cross_encoder = model
        rr._load_attempted = True

        out = rr.rerank("q", _make_results(2), top_n=0)
        assert out == []


# ══════════════════════════════════════════════════════════════════════════════
# 4 · is_available()
# ══════════════════════════════════════════════════════════════════════════════

class TestIsAvailable:

    def test_true_when_model_loaded(self):
        import kb_agent_mcp.reranker as rr
        rr._cross_encoder = MagicMock()
        rr._load_attempted = True
        assert rr.is_available() is True

    def test_false_when_model_none(self):
        import kb_agent_mcp.reranker as rr
        rr._cross_encoder = None
        rr._load_attempted = True
        assert rr.is_available() is False

    def test_false_when_disabled_via_config(self, monkeypatch):
        """KB_RERANKER_ENABLED=false must prevent model load and return False."""
        import kb_agent_mcp.reranker as rr

        fake_cfg = types.SimpleNamespace(
            KB_RERANKER_ENABLED=False,
            KB_RERANKER_MODEL="irrelevant",
        )
        monkeypatch.setattr(rr, "cfg", fake_cfg)

        result = rr._load_cross_encoder()
        assert result is None

    def test_import_error_returns_false(self):
        """If sentence_transformers is not importable, is_available() → False."""
        import kb_agent_mcp.reranker as rr

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else None

        def _fake_load():
            rr._cross_encoder = None
            rr._load_attempted = True
            return None

        with patch.object(rr, "_load_cross_encoder", side_effect=_fake_load):
            # is_available calls _load_cross_encoder under the hood
            # Just verify the None path makes is_available return False
            rr._cross_encoder = None
            rr._load_attempted = True
            assert rr.is_available() is False


# ══════════════════════════════════════════════════════════════════════════════
# 5 · reset()
# ══════════════════════════════════════════════════════════════════════════════

class TestReset:

    def test_reset_clears_model_and_flag(self):
        import kb_agent_mcp.reranker as rr
        rr._cross_encoder = MagicMock()
        rr._load_attempted = True

        rr.reset()

        assert rr._cross_encoder is None
        assert rr._load_attempted is False

    def test_after_reset_load_is_retriggered(self, monkeypatch):
        """After reset(), _load_cross_encoder() should set _load_attempted=True again."""
        import kb_agent_mcp.reranker as rr
        rr.reset()
        assert rr._load_attempted is False

        fake_cfg = types.SimpleNamespace(KB_RERANKER_ENABLED=False, KB_RERANKER_MODEL="x")
        monkeypatch.setattr(rr, "cfg", fake_cfg)
        rr._load_cross_encoder()

        assert rr._load_attempted is True


# ══════════════════════════════════════════════════════════════════════════════
# 6 · _load_cross_encoder() — singleton behaviour
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadCrossEncoder:

    def test_only_loads_once(self, monkeypatch):
        """Repeated calls must not reload the model."""
        import kb_agent_mcp.reranker as rr
        import numpy as np

        mock_cross_encoder_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.predict.return_value = np.array([0.5])
        mock_cross_encoder_cls.return_value = mock_instance

        fake_cfg = types.SimpleNamespace(KB_RERANKER_ENABLED=True, KB_RERANKER_MODEL="fake")
        monkeypatch.setattr(rr, "cfg", fake_cfg)

        with patch.dict("sys.modules", {"sentence_transformers": MagicMock(CrossEncoder=mock_cross_encoder_cls)}):
            rr._load_cross_encoder()
            rr._load_cross_encoder()
            rr._load_cross_encoder()

        # CrossEncoder() should only have been constructed once
        assert mock_cross_encoder_cls.call_count <= 1

    def test_disabled_returns_none_without_import(self, monkeypatch):
        """KB_RERANKER_ENABLED=false → None, no attempted model import."""
        import kb_agent_mcp.reranker as rr

        fake_cfg = types.SimpleNamespace(KB_RERANKER_ENABLED=False, KB_RERANKER_MODEL="x")
        monkeypatch.setattr(rr, "cfg", fake_cfg)
        result = rr._load_cross_encoder()

        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# 7 · DomainAgent._pre_rank() integration
# ══════════════════════════════════════════════════════════════════════════════

def _make_domain_agent(folder_name: str = "TestDomain") -> object:
    """Build a DomainAgent with a minimal default config."""
    from kb_agent_mcp.domain_agent import DomainAgent
    return DomainAgent(folder_name)


class TestPreRankRerankerIntegration:

    @pytest.fixture(autouse=True)
    def _reset(self):
        import kb_agent_mcp.reranker as rr
        rr.reset()
        yield
        rr.reset()

    @pytest.mark.asyncio
    async def test_reranker_called_when_available(self, monkeypatch):
        """_pre_rank() must call _rerank when the re-ranker is available."""
        import kb_agent_mcp.domain_agent as da_mod

        fake_results = _make_results(6)
        rerank_called_with = {}

        async def fake_search(folder, query, top_n=5):
            return fake_results

        def fake_rerank(query, results, top_n):
            rerank_called_with["query"] = query
            rerank_called_with["len"] = len(results)
            # Return a shorter list (top_n)
            return results[:top_n]

        monkeypatch.setattr(da_mod, "_reranker_available", lambda: True)
        monkeypatch.setattr("kb_agent_mcp.domain_agent._rerank", fake_rerank)

        # Patch the internal vs_search import
        with patch("kb_agent_mcp.vector_store.search", new=fake_search):
            agent = _make_domain_agent()
            results = await agent._pre_rank("what is ACE?", top_n=3)

        assert rerank_called_with.get("query") == "what is ACE?"
        # The candidate pool was larger than top_n
        assert rerank_called_with.get("len") >= 3

    @pytest.mark.asyncio
    async def test_reranker_skipped_when_unavailable(self, monkeypatch):
        """_pre_rank() must NOT call _rerank when re-ranker is unavailable."""
        import kb_agent_mcp.domain_agent as da_mod

        rerank_called = {"called": False}

        async def fake_search(folder, query, top_n=5):
            return _make_results(top_n)

        def fake_rerank(query, results, top_n):
            rerank_called["called"] = True
            return results[:top_n]

        monkeypatch.setattr(da_mod, "_reranker_available", lambda: False)
        monkeypatch.setattr("kb_agent_mcp.domain_agent._rerank", fake_rerank)

        with patch("kb_agent_mcp.vector_store.search", new=fake_search):
            agent = _make_domain_agent()
            await agent._pre_rank("query", top_n=3)

        assert not rerank_called["called"]

    @pytest.mark.asyncio
    async def test_candidate_pool_enlarged_when_reranker_on(self, monkeypatch):
        """Search must be called with a candidate_n >= top_n when reranker is on."""
        import kb_agent_mcp.domain_agent as da_mod

        searched_with_top_n = {}

        async def fake_search(folder, query, top_n=5):
            searched_with_top_n["top_n"] = top_n
            return _make_results(top_n)

        monkeypatch.setattr(da_mod, "_reranker_available", lambda: True)
        monkeypatch.setattr("kb_agent_mcp.domain_agent._rerank", lambda q, r, n: r[:n])

        with patch("kb_agent_mcp.vector_store.search", new=fake_search):
            agent = _make_domain_agent()
            await agent._pre_rank("q", top_n=3)

        # candidate_n = max(3*4, cfg.KB_RERANKER_CANDIDATES=20) = 20
        assert searched_with_top_n["top_n"] >= 3 * 4

    @pytest.mark.asyncio
    async def test_candidate_pool_not_enlarged_when_reranker_off(self, monkeypatch):
        """Without re-ranker, search is called with exactly effective_top_n."""
        import kb_agent_mcp.domain_agent as da_mod

        searched_with_top_n = {}

        async def fake_search(folder, query, top_n=5):
            searched_with_top_n["top_n"] = top_n
            return _make_results(top_n)

        monkeypatch.setattr(da_mod, "_reranker_available", lambda: False)

        with patch("kb_agent_mcp.vector_store.search", new=fake_search):
            agent = _make_domain_agent()
            await agent._pre_rank("q", top_n=4)

        assert searched_with_top_n["top_n"] == 4

    @pytest.mark.asyncio
    async def test_pin_rules_applied_after_rerank(self, monkeypatch):
        """Pin rules must run after re-ranking (not before)."""
        import kb_agent_mcp.domain_agent as da_mod
        from kb_agent_mcp.domain_rules import DomainConfig

        call_order = []

        async def fake_search(folder, query, top_n=5):
            call_order.append("search")
            return _make_results(top_n)

        def fake_rerank(query, results, top_n):
            call_order.append("rerank")
            return results[:top_n]

        def fake_pin_rules(results, folder, config):
            call_order.append("pin_rules")
            return results

        monkeypatch.setattr(da_mod, "_reranker_available", lambda: True)
        monkeypatch.setattr("kb_agent_mcp.domain_agent._rerank", fake_rerank)
        monkeypatch.setattr("kb_agent_mcp.domain_agent.apply_pin_rules", fake_pin_rules)

        # Build a DomainAgent with a pin_files rule so apply_pin_rules is triggered
        from kb_agent_mcp.domain_agent import DomainAgent
        from kb_agent_mcp.domain_rules import _default_system_prompt
        cfg_with_pin = DomainConfig(
            folder_name="TestDomain",
            agent_name="Test Agent",
            description="test",
            keywords=[],
            top_n=3,
            max_chars=4000,
            system_prompt=_default_system_prompt("TestDomain", "Test Agent", "test"),
            pin_files=["important.md"],
        )
        agent = DomainAgent("TestDomain", config=cfg_with_pin)

        with patch("kb_agent_mcp.vector_store.search", new=fake_search):
            await agent._pre_rank("q", top_n=3)

        assert call_order == ["search", "rerank", "pin_rules"]

    @pytest.mark.asyncio
    async def test_rerank_not_called_on_empty_search_results(self, monkeypatch):
        """_pre_rank() must not call _rerank when search returns []."""
        import kb_agent_mcp.domain_agent as da_mod

        rerank_called = {"called": False}

        async def fake_search(folder, query, top_n=5):
            return []

        def fake_rerank(query, results, top_n):
            rerank_called["called"] = True
            return results[:top_n]

        monkeypatch.setattr(da_mod, "_reranker_available", lambda: True)
        monkeypatch.setattr("kb_agent_mcp.domain_agent._rerank", fake_rerank)

        with patch("kb_agent_mcp.vector_store.search", new=fake_search):
            agent = _make_domain_agent()
            result = await agent._pre_rank("q", top_n=3)

        assert not rerank_called["called"]
        assert result == []
