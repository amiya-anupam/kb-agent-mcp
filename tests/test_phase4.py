"""
tests/test_phase4.py
────────────────────
Phase 4 tests covering Runtime & Query Path:
  - Risk 14: _estimate_context_size(), _adjusted_top_n() helpers
  - Risk 14: Two-tier budget warning in _unwrap_passthrough_blocks()
  - Risk 14: Passthrough context quality — explicit host AI instructions
  - Risk 14: top_n_override wires through DomainAgent.run()
  - Risk 14: orchestrator ask() computes budget reduction for passthrough
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Risk 14 — _estimate_context_size()
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateContextSize:

    def test_basic(self):
        from kb_agent_mcp.orchestrator import _estimate_context_size
        assert _estimate_context_size(2, 4, 8000) == 64000

    def test_single_domain(self):
        from kb_agent_mcp.orchestrator import _estimate_context_size
        assert _estimate_context_size(1, 5, 10000) == 50000

    def test_zero_domains(self):
        from kb_agent_mcp.orchestrator import _estimate_context_size
        assert _estimate_context_size(0, 4, 8000) == 0

    def test_proportional(self):
        from kb_agent_mcp.orchestrator import _estimate_context_size
        base = _estimate_context_size(1, 1, 1000)
        assert _estimate_context_size(2, 1, 1000) == base * 2
        assert _estimate_context_size(1, 2, 1000) == base * 2
        assert _estimate_context_size(1, 1, 2000) == base * 2


# ─────────────────────────────────────────────────────────────────────────────
# Risk 14 — _adjusted_top_n()
# ─────────────────────────────────────────────────────────────────────────────

def _patch_cfg(monkeypatch, total: int, threshold: float) -> None:
    """
    Patch kb_agent_mcp.orchestrator.cfg with a simple namespace so the
    frozen Config dataclass is not mutated.
    """
    import types
    import kb_agent_mcp.orchestrator as orch_mod
    fake = types.SimpleNamespace(
        KB_BUDGET_TOTAL=total,
        KB_BUDGET_PASSTHROUGH_THRESHOLD=threshold,
    )
    monkeypatch.setattr(orch_mod, "cfg", fake)


class TestAdjustedTopN:

    def test_within_budget_no_change(self, monkeypatch):
        _patch_cfg(monkeypatch, total=100000, threshold=0.8)
        from kb_agent_mcp.orchestrator import _adjusted_top_n
        top_n, status = _adjusted_top_n(1, 4, 8000)
        assert status == ""
        assert top_n == 4

    def test_over_threshold_reduces_top_n(self, monkeypatch):
        # 2 domains × 4 top_n × 8000 chars = 64000; threshold = 0.8 * 24000 = 19200
        _patch_cfg(monkeypatch, total=24000, threshold=0.8)
        from kb_agent_mcp.orchestrator import _adjusted_top_n
        top_n, status = _adjusted_top_n(2, 4, 8000)
        assert status == "narrowed"
        assert top_n < 4

    def test_even_top_n_1_over_budget_returns_truncated(self, monkeypatch):
        # 1 domain × 1 × 100000 chars = 100000; threshold = 0.8 * 100 = 80
        _patch_cfg(monkeypatch, total=100, threshold=0.8)
        from kb_agent_mcp.orchestrator import _adjusted_top_n
        top_n, status = _adjusted_top_n(1, 4, 100000)
        assert status == "truncated"
        assert top_n == 1

    def test_adjusted_top_n_is_positive(self, monkeypatch):
        _patch_cfg(monkeypatch, total=24000, threshold=0.8)
        from kb_agent_mcp.orchestrator import _adjusted_top_n
        top_n, _ = _adjusted_top_n(5, 10, 9000)
        assert top_n >= 1

    def test_exact_budget_boundary(self, monkeypatch):
        """Exactly at threshold → no change."""
        _patch_cfg(monkeypatch, total=20000, threshold=1.0)
        from kb_agent_mcp.orchestrator import _adjusted_top_n
        # 1 domain × 4 top_n × 5000 chars = 20000 ≤ 20000
        top_n, status = _adjusted_top_n(1, 4, 5000)
        assert status == ""
        assert top_n == 4


# ─────────────────────────────────────────────────────────────────────────────
# Risk 14 — _unwrap_passthrough_blocks() budget warnings
# ─────────────────────────────────────────────────────────────────────────────

class TestUnwrapPassthroughBlocks:

    def _make_raw(self, agent="TestAgent", source="test.md", context="Test context") -> str:
        from kb_agent_mcp.orchestrator import _PT_START, _PT_END
        return (
            f"\n{_PT_START}\n"
            f"AGENT: {agent}\n"
            f"QUESTION: What is X?\n"
            f"SOURCE: {source}\n"
            f"---CONTEXT---\n{context}\n"
            f"{_PT_END}\n"
        )

    def test_no_budget_status_has_instructions(self):
        from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks
        raw = self._make_raw()
        result = _unwrap_passthrough_blocks(raw, budget_status="")
        # Must contain explicit host AI instructions
        assert "instructions" in result.lower() or "passthrough mode" in result.lower()

    def test_narrowed_warning_present(self):
        from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks
        raw = self._make_raw()
        result = _unwrap_passthrough_blocks(raw, budget_status="narrowed")
        assert "narrowed" in result.lower() or "reduced" in result.lower()

    def test_truncated_warning_present(self):
        from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks
        raw = self._make_raw()
        result = _unwrap_passthrough_blocks(raw, budget_status="truncated")
        assert "truncated" in result.lower()

    def test_no_warning_when_normal(self):
        from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks
        raw = self._make_raw()
        result = _unwrap_passthrough_blocks(raw, budget_status="")
        # No narrowed / truncated mention when status is normal
        assert "narrowed" not in result.lower()
        assert "truncated" not in result.lower()

    def test_context_preserved(self):
        from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks
        raw = self._make_raw(context="Important fact: X = 42")
        result = _unwrap_passthrough_blocks(raw)
        assert "Important fact: X = 42" in result

    def test_agent_name_in_heading(self):
        from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks
        raw = self._make_raw(agent="BizOps Agent")
        result = _unwrap_passthrough_blocks(raw)
        assert "BizOps Agent" in result

    def test_no_blocks_returns_raw(self):
        from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks
        raw = "plain text without markers"
        assert _unwrap_passthrough_blocks(raw) == raw

    def test_multiple_blocks_merged(self):
        from kb_agent_mcp.orchestrator import _PT_START, _PT_END, _unwrap_passthrough_blocks
        block1 = self._make_raw(agent="Agent1", context="Context1")
        block2 = self._make_raw(agent="Agent2", context="Context2")
        combined = block1 + block2
        result = _unwrap_passthrough_blocks(combined)
        assert "Agent1" in result
        assert "Agent2" in result
        assert "Context1" in result
        assert "Context2" in result


# ─────────────────────────────────────────────────────────────────────────────
# Risk 14 — _build_passthrough_block() has explicit INSTRUCTION field
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildPassthroughBlock:

    def test_instruction_field_present(self):
        from kb_agent_mcp.base_agent import _build_passthrough_block
        block = _build_passthrough_block(
            question="What is revenue?",
            context="Revenue = $100",
            system_prompt="You are a helpful agent.",
            agent_name="BizOps Agent",
            source_label="revenue.xlsx",
        )
        assert "INSTRUCTION:" in block

    def test_instruction_says_use_context(self):
        from kb_agent_mcp.base_agent import _build_passthrough_block
        block = _build_passthrough_block(
            question="What is revenue?",
            context="Revenue = $100",
            system_prompt="You are a helpful agent.",
            agent_name="BizOps Agent",
            source_label="revenue.xlsx",
        )
        assert "CONTEXT" in block
        assert "QUESTION" in block

    def test_markers_present(self):
        from kb_agent_mcp.base_agent import (
            _build_passthrough_block,
            _PASSTHROUGH_MARKER,
            _PASSTHROUGH_END,
        )
        block = _build_passthrough_block(
            question="Q",
            context="C",
            system_prompt="SP",
            agent_name="A",
            source_label="s.md",
        )
        assert _PASSTHROUGH_MARKER in block
        assert _PASSTHROUGH_END in block

    def test_context_included(self):
        from kb_agent_mcp.base_agent import _build_passthrough_block
        block = _build_passthrough_block(
            question="Q",
            context="Unique content XYZ",
            system_prompt="SP",
            agent_name="A",
            source_label="s.md",
        )
        assert "Unique content XYZ" in block


# ─────────────────────────────────────────────────────────────────────────────
# Risk 14 — DomainAgent.run() accepts top_n_override
# ─────────────────────────────────────────────────────────────────────────────

class TestDomainAgentTopNOverride:

    def test_run_accepts_top_n_override_kwarg(self):
        import inspect
        from kb_agent_mcp.domain_agent import DomainAgent
        sig = inspect.signature(DomainAgent.run)
        assert "top_n_override" in sig.parameters

    def test_top_n_override_defaults_to_none(self):
        import inspect
        from kb_agent_mcp.domain_agent import DomainAgent
        sig = inspect.signature(DomainAgent.run)
        assert sig.parameters["top_n_override"].default is None

    def test_top_n_override_passed_to_base_ask(self, monkeypatch):
        """When top_n_override is set, base_agent.ask() receives it, not config.top_n."""
        import asyncio
        from kb_agent_mcp.domain_agent import DomainAgent
        from kb_agent_mcp.domain_rules import DomainConfig

        received_top_n: list[int] = []

        async def _fake_ask(question, folder_name, agent_name, system_prompt,
                            conversation_history=None, top_n=4, max_chars=None,
                            pre_ranked_results=None, **kwargs):
            received_top_n.append(top_n)
            return {"agent": agent_name, "answer": "ok", "sources": [], "found": True,
                    "passthrough": False}

        monkeypatch.setattr("kb_agent_mcp.domain_agent._base_ask", _fake_ask)
        monkeypatch.setattr("kb_agent_mcp.domain_agent._global_data_q", lambda q: False)

        cfg_mock = DomainConfig(
            folder_name="Test",
            agent_name="Test Agent",
            description="desc",
            keywords=[],
            top_n=5,
            max_chars=8000,
            system_prompt="SP",
        )
        agent = DomainAgent("Test", config=cfg_mock)
        asyncio.run(agent.run("question", [], top_n_override=2))

        assert received_top_n == [2], f"Expected [2], got {received_top_n}"

    def test_top_n_override_none_uses_config(self, monkeypatch):
        """When top_n_override is None, base_agent.ask() receives config.top_n."""
        import asyncio
        from kb_agent_mcp.domain_agent import DomainAgent
        from kb_agent_mcp.domain_rules import DomainConfig

        received_top_n: list[int] = []

        async def _fake_ask(question, folder_name, agent_name, system_prompt,
                            conversation_history=None, top_n=4, max_chars=None,
                            pre_ranked_results=None, **kwargs):
            received_top_n.append(top_n)
            return {"agent": agent_name, "answer": "ok", "sources": [], "found": True,
                    "passthrough": False}

        monkeypatch.setattr("kb_agent_mcp.domain_agent._base_ask", _fake_ask)
        monkeypatch.setattr("kb_agent_mcp.domain_agent._global_data_q", lambda q: False)

        cfg_mock = DomainConfig(
            folder_name="Test",
            agent_name="Test Agent",
            description="desc",
            keywords=[],
            top_n=7,
            max_chars=8000,
            system_prompt="SP",
        )
        agent = DomainAgent("Test", config=cfg_mock)
        asyncio.run(agent.run("question", [], top_n_override=None))

        assert received_top_n == [7], f"Expected [7], got {received_top_n}"


# ─────────────────────────────────────────────────────────────────────────────
# Risk 14 — orchestrator ask() budget integration
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestratorBudgetIntegration:

    def test_budget_status_signature_in_merge(self):
        """_merge_answers() must accept a budget_status kwarg."""
        import inspect
        from kb_agent_mcp.orchestrator import _merge_answers
        sig = inspect.signature(_merge_answers)
        assert "budget_status" in sig.parameters

    def test_merge_passes_budget_status_to_unwrap(self, monkeypatch):
        """_merge_answers() must forward budget_status to _unwrap_passthrough_blocks()."""
        from kb_agent_mcp.orchestrator import _merge_answers

        received: list[str] = []

        def _fake_unwrap(raw: str, budget_status: str = "") -> str:
            received.append(budget_status)
            return "UNWRAPPED"

        monkeypatch.setattr("kb_agent_mcp.orchestrator._unwrap_passthrough_blocks", _fake_unwrap)

        results = [{
            "agent": "A",
            "answer": "block",
            "found": True,
            "passthrough": True,
            "passthrough_block": "BLOCK",
        }]
        agents = {}
        _merge_answers(results, agents, question="Q?", budget_status="narrowed")

        assert received == ["narrowed"]

    def test_adjusted_top_n_function_is_present(self):
        from kb_agent_mcp.orchestrator import _adjusted_top_n
        assert callable(_adjusted_top_n)

    def test_estimate_context_size_function_is_present(self):
        from kb_agent_mcp.orchestrator import _estimate_context_size
        assert callable(_estimate_context_size)
