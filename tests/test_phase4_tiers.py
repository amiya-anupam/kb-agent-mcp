"""Phase 4: tiered retrieval from the context store (flag KB_CONTEXT_STORE)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_agent_mcp import base_agent
from kb_agent_mcp.context_store.sync import sync


def _cfgs():
    """Every distinct `cfg` object in use. Other tests importlib.reload() the
    config module, so modules may hold different instances."""
    import kb_agent_mcp.config as config
    from kb_agent_mcp import orchestrator, security_gate, tiered
    from kb_agent_mcp.context_store import paths
    seen = {}
    for m in (config, base_agent, orchestrator, security_gate, tiered, paths):
        c = getattr(m, "cfg", None)
        if c is not None:
            seen[id(c)] = c
    return list(seen.values())


def _set_all(name, value):
    for c in _cfgs():
        object.__setattr__(c, name, value)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / "BizOps").mkdir(parents=True)
    (root / "BizOps" / "parts.md").write_text(
        "# Parts\n\nThe production VPC perpetual part number is D1Q4ELL.\n", encoding="utf-8")
    (root / "BizOps" / "notes.md").write_text(
        "# Notes\n\nQuarterly planning notes about hiring.\n", encoding="utf-8")
    (root / "BizOps" / "sales.csv").write_text(
        "Region,Amount\nEMEA,10\nAPAC,20\n", encoding="utf-8")
    for c in _cfgs():
        monkeypatch.setattr(type(c), "kb_root_path", property(lambda self: root))
        monkeypatch.setattr(type(c), "kb_index_path", property(lambda self: root / ".kb_index"))
    _set_all("KB_SECURITY_GATE_ENABLED", False)
    yield root
    _set_all("KB_SECURITY_GATE_ENABLED", True)


@pytest.fixture
def store(kb):
    sync(kb)
    return kb / ".kb_index" / "context"


@pytest.fixture
def flag():
    original = _cfgs()[0].KB_CONTEXT_STORE
    yield lambda value: _set_all("KB_CONTEXT_STORE", value)
    _set_all("KB_CONTEXT_STORE", original)


# ── Config ─────────────────────────────────────────────────────────────────────

def test_flag_defaults_on_and_reads_env():
    # Subprocess: reloading config in-process would split `cfg` across modules.
    import os
    import subprocess
    import sys
    code = "from kb_agent_mcp.config import cfg; print(cfg.KB_CONTEXT_STORE)"
    base = {k: v for k, v in os.environ.items() if k != "KB_CONTEXT_STORE"}
    on = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=base)
    off_env = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env={**base, "KB_CONTEXT_STORE": "0"})
    assert on.stdout.strip() == "True", on.stderr
    assert off_env.stdout.strip() == "False", off_env.stderr


# ── Digest selection ───────────────────────────────────────────────────────────

async def test_digest_selected_for_matching_question(store):
    from kb_agent_mcp.tiered import tiered_context
    tr = await tiered_context("BizOps", "What is the production VPC perpetual part number?")
    assert tr is not None
    assert tr.tiers == ["digest"]
    assert tr.sources[0]["name"] == "parts.md"
    assert "D1Q4ELL" in tr.context


async def test_unrelated_question_falls_through(store):
    from kb_agent_mcp.tiered import tiered_context
    assert await tiered_context("BizOps", "zzzz qqqq xxxx") is None


async def test_missing_store_returns_none(kb):
    from kb_agent_mcp.tiered import tiered_context
    assert await tiered_context("BizOps", "part number") is None


async def test_overview_question_returns_domain_index(store):
    from kb_agent_mcp.tiered import tiered_context
    tr = await tiered_context("BizOps", "What files are in this folder?")
    assert tr is not None and tr.tiers == ["index"]
    assert "parts.md" in tr.context


# ── Tier 4: analyst ────────────────────────────────────────────────────────────

async def test_analyst_answer_appended_for_data_question(store, monkeypatch):
    from kb_agent_mcp import tiered

    async def fake(path, question, session_id=None):
        assert path.endswith("sales.csv")
        return {"status": "answered", "answer": "APAC total is 20"}
    monkeypatch.setattr("kb_agent_mcp.analyst.engine.query_data", fake)
    tr = await tiered.tiered_context("BizOps", "sales Region Amount total", data_question=True)
    assert tr is not None and tr.tiers == ["digest", "analyst"]
    assert "APAC total is 20" in tr.context


@pytest.mark.parametrize("result", [
    {"status": "clarifying", "question": "which column?"},
    {"status": "error", "error": "boom"},
    {"status": "answered", "answer": "  "},
])
async def test_analyst_non_answers_are_ignored(store, monkeypatch, result):
    from kb_agent_mcp import tiered

    async def fake(path, question, session_id=None):
        return result
    monkeypatch.setattr("kb_agent_mcp.analyst.engine.query_data", fake)
    tr = await tiered.tiered_context("BizOps", "sales Region Amount total", data_question=True)
    assert tr is not None and tr.tiers == ["digest"]


async def test_analyst_exception_is_ignored(store, monkeypatch):
    from kb_agent_mcp import tiered

    async def fake(path, question, session_id=None):
        raise RuntimeError("down")
    monkeypatch.setattr("kb_agent_mcp.analyst.engine.query_data", fake)
    tr = await tiered.tiered_context("BizOps", "sales Region Amount total", data_question=True)
    assert tr is not None and tr.tiers == ["digest"]


async def test_analyst_not_called_for_non_data_question(store, monkeypatch):
    from kb_agent_mcp import tiered

    async def fake(*a, **k):
        raise AssertionError("analyst must not run")
    monkeypatch.setattr("kb_agent_mcp.analyst.engine.query_data", fake)
    tr = await tiered.tiered_context("BizOps", "sales Region Amount total", data_question=False)
    assert tr is not None and tr.tiers == ["digest"]


# ── Security gate ──────────────────────────────────────────────────────────────

async def test_confidential_digest_redacted_until_acknowledged(store, monkeypatch):
    from kb_agent_mcp import security_gate, tiered
    _set_all("KB_SECURITY_GATE_ENABLED", True)
    monkeypatch.setattr(security_gate, "classify_confidential",
                        lambda p: (p.name == "parts.md", "test"))
    monkeypatch.setattr(security_gate, "is_gate_acknowledged", lambda sid: False)

    q = "production VPC perpetual part number"
    tr = await tiered.tiered_context("BizOps", q)
    assert tr is None or "D1Q4ELL" not in tr.context
    if tr:
        assert "parts.md" in tr.redacted

    monkeypatch.setattr(security_gate, "is_gate_acknowledged", lambda sid: True)
    tr = await tiered.tiered_context("BizOps", q)
    assert tr is not None and "D1Q4ELL" in tr.context
    assert tr.sources[0]["confidential"] is True and tr.sources[0]["name"].startswith("🔒")


# ── ask() integration ──────────────────────────────────────────────────────────

async def _ask(question):
    base_agent._passthrough_cache = True
    try:
        return await base_agent.ask(question, "BizOps", "BizOps Agent", "sys")
    finally:
        base_agent._passthrough_cache = None


async def test_ask_uses_store_when_flag_on(store, flag):
    flag(True)
    res = await _ask("What is the production VPC perpetual part number?")
    assert res["passthrough"] is True and res["found"] is True
    assert "D1Q4ELL" in res["passthrough_block"]
    assert res["sources"][0]["name"] == "parts.md"


async def test_ask_skips_store_when_flag_off(store, flag, monkeypatch):
    flag(False)

    async def boom(*a, **k):
        raise AssertionError("tiered path must not run")
    monkeypatch.setattr("kb_agent_mcp.tiered.tiered_context", boom)
    monkeypatch.setattr(base_agent, "_get_readme_context", lambda f, q: (None, ""))

    async def no_results(*a, **k):
        return []
    monkeypatch.setattr("kb_agent_mcp.vector_store.search", no_results)
    res = await _ask("What is the production VPC perpetual part number?")
    assert res["found"] is False


async def test_ask_falls_back_when_store_has_nothing(kb, flag, monkeypatch):
    flag(True)                                            # no store built
    monkeypatch.setattr(base_agent, "_get_readme_context", lambda f, q: ("README body", "README"))
    res = await _ask("part number")
    assert res["sources"][0]["name"] == "README"


# ── Orchestrator: manifest keywords ────────────────────────────────────────────

MANIFEST = """# Knowledge base manifest

- **ACE Docs** — [ace_docs/INDEX.md](ace_docs/INDEX.md) · 26 digests (13 pdf) · updated 2026-11-10 · IBM, Connect, ACE, Pak
- **BizOps** — [bizops/INDEX.md](bizops/INDEX.md) · 128 digests (84 xlsx) · 2 partial · updated 2026-11-10 · IBM, renewal_tracking, EMEA, Pak
"""


def test_manifest_keywords_parsed_and_shared_dropped(tmp_path, monkeypatch):
    from kb_agent_mcp import orchestrator
    monkeypatch.setattr("kb_agent_mcp.context_store.sync.read_context",
                        lambda kind, *a, **k: MANIFEST)
    kws = orchestrator.manifest_keywords()
    assert kws["ACE Docs"] == ["Connect", "ACE"]
    assert kws["BizOps"] == ["renewal_tracking", "EMEA"]


def test_manifest_keywords_empty_without_store(monkeypatch):
    from kb_agent_mcp import orchestrator

    def missing(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr("kb_agent_mcp.context_store.sync.read_context", missing)
    assert orchestrator.manifest_keywords() == {}


def test_manifest_keywords_route_only_when_flag_on_and_no_other_signal(flag, monkeypatch):
    from kb_agent_mcp import orchestrator
    from kb_agent_mcp.domain_agent import DomainAgent
    monkeypatch.setattr("kb_agent_mcp.context_store.sync.read_context",
                        lambda kind, *a, **k: MANIFEST)
    agents = {"ACE Docs": DomainAgent("ACE Docs"), "BizOps": DomainAgent("BizOps")}
    for a in agents.values():
        a.config.keywords = []

    q = "how do EMEA renewal_tracking numbers look"
    flag(False)
    assert not any(orchestrator._keyword_hit_counts(q, agents).values())
    flag(True)
    counts = orchestrator._keyword_hit_counts(q, agents)
    assert counts == {"ACE Docs": 0, "BizOps": 2}
    # whole-word matching: "ace" inside "replace" must not match
    assert orchestrator._keyword_hit_counts("replace the place", agents)["ACE Docs"] == 0


def test_configured_keywords_win_over_manifest(flag, monkeypatch):
    from kb_agent_mcp import orchestrator
    from kb_agent_mcp.domain_agent import DomainAgent
    monkeypatch.setattr("kb_agent_mcp.context_store.sync.read_context",
                        lambda kind, *a, **k: MANIFEST)
    agents = {"ACE Docs": DomainAgent("ACE Docs"), "BizOps": DomainAgent("BizOps")}
    agents["ACE Docs"].config.keywords = ["gateway"]
    agents["BizOps"].config.keywords = []
    flag(True)
    counts = orchestrator._keyword_hit_counts("gateway for EMEA", agents)
    assert counts["BizOps"] == 0 and counts["ACE Docs"] >= 1


# ── Golden set sanity ──────────────────────────────────────────────────────────

def test_golden_question_file_is_well_formed():
    data = json.loads((Path(__file__).parent / "golden_questions.json").read_text())
    assert 10 <= len(data) <= 15
    assert len({q["id"] for q in data}) == len(data)
    for q in data:
        assert q["domain"] and q["question"] and q["expected_facts"]
