"""
tests/test_routing_and_passthrough.py

Covers two behaviours in both the legacy agents/ tree and the kb_agent_mcp package:
  1. Keyword routing matches whole words only ("ace" must not match "workspace").
  2. Passthrough mode is also used when Ollama is up but the configured model
     has not been pulled.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_AGENTS_DIR = pathlib.Path(__file__).parent.parent / "agents"


def _agents_module(name: str):
    if str(_AGENTS_DIR) not in sys.path:
        sys.path.insert(0, str(_AGENTS_DIR))
    return __import__(name)


# ── Keyword routing: agents/agent_knowledgebase._keyword_hits ─────────────────

def _domain(folder: str, keywords: list[str]) -> dict:
    return {"folder_name": folder, "keywords": keywords}


class TestLegacyKeywordHits:
    @pytest.fixture()
    def hits(self):
        return _agents_module("agent_knowledgebase")._keyword_hits

    def test_whole_word_matches(self, hits):
        assert hits("Tell me about ACE docs", _domain("ACE Docs", ["ace"])) >= 1

    def test_substring_does_not_match(self, hits):
        d = _domain("ACE Docs", ["ace"])
        assert hits("Where is my workspace?", d) == 0
        assert hits("Which place is best?", d) == 0

    def test_case_insensitive_and_punctuation(self, hits):
        d = _domain("BizOps", ["revenue"])
        assert hits("What is the REVENUE?", d) == 1
        assert hits("revenue, quota", d) == 1

    def test_plural_suffix_allowed(self, hits):
        assert hits("list the renewals", _domain("BizOps", ["renewal"])) == 1

    def test_folder_name_is_implicit_keyword(self, hits):
        assert hits("what is in bizops", _domain("BizOps", ["revenue"])) == 1

    def test_folder_name_not_used_without_keywords(self, hits):
        assert hits("what is in bizops", _domain("BizOps", [])) == 0

    def test_duplicate_keywords_counted_once(self, hits):
        assert hits("ace", _domain("X", ["ace", "ACE"])) == 1


# ── Keyword routing: kb_agent_mcp.orchestrator._keyword_hit_counts ────────────

def _make_agent(folder: str, keywords: list[str]):
    from kb_agent_mcp.domain_agent import DomainAgent
    from kb_agent_mcp.domain_rules import DomainConfig

    cfg = DomainConfig(
        folder_name=folder,
        agent_name=folder + " Agent",
        description="",
        keywords=keywords,
        top_n=4,
        max_chars=6000,
        system_prompt="",
    )
    return DomainAgent(folder, config=cfg)


class TestOrchestratorKeywordHitCounts:
    def test_whole_word_matches(self):
        from kb_agent_mcp.orchestrator import _keyword_hit_counts
        agents = {"ACE Docs": _make_agent("ACE Docs", ["ace"])}
        assert _keyword_hit_counts("Tell me about ACE docs", agents)["ACE Docs"] >= 1

    def test_substring_does_not_match(self):
        from kb_agent_mcp.orchestrator import _keyword_hit_counts
        agents = {"ACE Docs": _make_agent("ACE Docs", ["ace"])}
        assert _keyword_hit_counts("Where is my workspace?", agents)["ACE Docs"] == 0
        assert _keyword_hit_counts("Which place is best?", agents)["ACE Docs"] == 0

    def test_plural_suffix_allowed(self):
        from kb_agent_mcp.orchestrator import _keyword_hit_counts
        agents = {"BizOps": _make_agent("BizOps", ["renewal"])}
        assert _keyword_hit_counts("list the renewals", agents)["BizOps"] == 1

    def test_folder_name_is_implicit_keyword(self):
        from kb_agent_mcp.orchestrator import _keyword_hit_counts
        agents = {"BizOps": _make_agent("BizOps", ["revenue"])}
        assert _keyword_hit_counts("what is in bizops", agents)["BizOps"] == 1

    def test_folder_name_not_used_without_keywords(self):
        from kb_agent_mcp.orchestrator import _keyword_hit_counts
        agents = {"BizOps": _make_agent("BizOps", [])}
        assert _keyword_hit_counts("what is in bizops", agents)["BizOps"] == 0

    def test_workspace_question_is_not_routed_to_ace(self):
        from kb_agent_mcp.orchestrator import _keyword_confidence
        agents = {"ACE Docs": _make_agent("ACE Docs", ["ace"])}
        matched, confident = _keyword_confidence("Where is my workspace?", agents)
        assert matched == [] and not confident


# ── Passthrough: agents/agent_base._is_passthrough_mode ───────────────────────

class _Resp:
    def __init__(self, status: int = 200, body: dict | None = None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body


class TestLegacyPassthrough:
    @pytest.fixture()
    def ab(self, monkeypatch):
        mod = _agents_module("agent_base")
        monkeypatch.setattr(mod, "LLM_PROVIDER", "ollama")
        monkeypatch.setattr(mod, "API_KEY", "")
        monkeypatch.setattr(mod, "MODEL", "qwen3:14b")
        monkeypatch.setattr(mod, "LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.delenv("KB_PASSTHROUGH_FALLBACK", raising=False)
        return mod

    def _tags(self, monkeypatch, resp=None, exc=None):
        import httpx

        def fake_get(*a, **k):
            if exc:
                raise exc
            return resp

        monkeypatch.setattr(httpx, "get", fake_get)

    def test_no_models_pulled_is_passthrough(self, ab, monkeypatch):
        self._tags(monkeypatch, _Resp(200, {"models": []}))
        assert ab._is_passthrough_mode() is True

    def test_model_present_is_not_passthrough(self, ab, monkeypatch):
        self._tags(monkeypatch, _Resp(200, {"models": [{"name": "qwen3:14b"}]}))
        assert ab._is_passthrough_mode() is False

    def test_other_model_only_is_passthrough(self, ab, monkeypatch):
        self._tags(monkeypatch, _Resp(200, {"models": [{"name": "llama3:8b"}]}))
        assert ab._is_passthrough_mode() is True

    def test_unqualified_model_name_matches_tagged(self, ab, monkeypatch):
        monkeypatch.setattr(ab, "MODEL", "qwen3")
        self._tags(monkeypatch, _Resp(200, {"models": [{"name": "qwen3:14b"}]}))
        assert ab._is_passthrough_mode() is False

    def test_http_error_is_passthrough(self, ab, monkeypatch):
        self._tags(monkeypatch, _Resp(500))
        assert ab._is_passthrough_mode() is True

    def test_unreachable_is_passthrough(self, ab, monkeypatch):
        self._tags(monkeypatch, exc=ConnectionError("down"))
        assert ab._is_passthrough_mode() is True

    def test_fallback_disabled_never_passthrough(self, ab, monkeypatch):
        monkeypatch.setenv("KB_PASSTHROUGH_FALLBACK", "false")
        self._tags(monkeypatch, _Resp(200, {"models": []}))
        assert ab._is_passthrough_mode() is False


# ── Passthrough: kb_agent_mcp.base_agent._check_passthrough ───────────────────

class TestPackagePassthrough:
    @pytest.fixture()
    def ba(self, monkeypatch):
        import types
        from kb_agent_mcp import base_agent
        # cfg is a frozen dataclass, so swap the module attribute instead.
        monkeypatch.setattr(base_agent, "cfg", types.SimpleNamespace(
            KB_LLM_PROVIDER="ollama",
            KB_API_KEY="",
            KB_MODEL="qwen3:14b",
            KB_PASSTHROUGH_FALLBACK=True,
            KB_LLM_BASE_URL="http://localhost:11434",
        ))
        return base_agent

    def _client(self, monkeypatch, ba, resp=None, exc=None):
        class FakeClient:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **k):
                if exc:
                    raise exc
                return resp

        monkeypatch.setattr(ba.httpx, "AsyncClient", FakeClient)

    async def test_no_models_pulled_is_passthrough(self, ba, monkeypatch):
        self._client(monkeypatch, ba, _Resp(200, {"models": []}))
        assert await ba._check_passthrough() is True

    async def test_model_present_is_not_passthrough(self, ba, monkeypatch):
        self._client(monkeypatch, ba, _Resp(200, {"models": [{"name": "qwen3:14b"}]}))
        assert await ba._check_passthrough() is False

    async def test_other_model_only_is_passthrough(self, ba, monkeypatch):
        self._client(monkeypatch, ba, _Resp(200, {"models": [{"name": "llama3:8b"}]}))
        assert await ba._check_passthrough() is True

    async def test_unqualified_model_name_matches_tagged(self, ba, monkeypatch):
        ba.cfg.KB_MODEL = "qwen3"
        self._client(monkeypatch, ba, _Resp(200, {"models": [{"name": "qwen3:14b"}]}))
        assert await ba._check_passthrough() is False

    async def test_http_error_is_passthrough(self, ba, monkeypatch):
        self._client(monkeypatch, ba, _Resp(503))
        assert await ba._check_passthrough() is True

    async def test_unreachable_is_passthrough(self, ba, monkeypatch):
        self._client(monkeypatch, ba, exc=ConnectionError("down"))
        assert await ba._check_passthrough() is True

    async def test_fallback_disabled_never_passthrough(self, ba, monkeypatch):
        ba.cfg.KB_PASSTHROUGH_FALLBACK = False
        self._client(monkeypatch, ba, _Resp(200, {"models": []}))
        assert await ba._check_passthrough() is False
