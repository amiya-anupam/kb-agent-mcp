"""
tests/test_orchestrator.py — Orchestrator routing tests
"""
from __future__ import annotations

import pytest


def test_detect_format_intent_no_format():
    from kb_agent_mcp.orchestrator import detect_format_intent
    q, instruction = detect_format_intent("What is ACE?")
    assert q == "What is ACE?"
    assert instruction == ""


def test_detect_format_intent_phrase_table():
    from kb_agent_mcp.orchestrator import detect_format_intent
    q, instruction = detect_format_intent("Show me the results as a table")
    assert "table" in instruction.lower()


def test_detect_format_intent_phrase_bullets():
    from kb_agent_mcp.orchestrator import detect_format_intent
    q, instruction = detect_format_intent("Give me a summary as bullet points")
    assert "bullet" in instruction.lower()


def test_detect_format_intent_explicit_flag():
    from kb_agent_mcp.orchestrator import detect_format_intent
    q, instruction = detect_format_intent("What is ACE?", explicit_flag="table")
    assert "table" in instruction.lower()


def test_detect_format_intent_alias():
    from kb_agent_mcp.orchestrator import detect_format_intent
    _, instruction = detect_format_intent("x", explicit_flag="bullet")
    assert "bullet" in instruction.lower()


def test_keyword_confidence_single_domain():
    from kb_agent_mcp.orchestrator import _keyword_confidence
    from kb_agent_mcp.domain_agent import DomainAgent
    from kb_agent_mcp.domain_rules import DomainConfig

    def _make_agent(folder: str, keywords: list[str]) -> DomainAgent:
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

    agents = {
        "ACE Docs": _make_agent("ACE Docs", ["ace", "integration bus", "ibm ace", "iib"]),
        "BizOps":   _make_agent("BizOps",   ["revenue", "quota", "attainment"]),
    }

    # Question with ≥2 ACE keywords
    matched, confident = _keyword_confidence("How does IBM ACE and integration bus work?", agents)
    assert confident
    assert matched == ["ACE Docs"]


def test_keyword_confidence_ambiguous():
    from kb_agent_mcp.orchestrator import _keyword_confidence
    from kb_agent_mcp.domain_agent import DomainAgent
    from kb_agent_mcp.domain_rules import DomainConfig

    def _make_agent(folder: str, keywords: list[str]) -> DomainAgent:
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

    agents = {
        "ACE Docs": _make_agent("ACE Docs", ["ace"]),
        "BizOps":   _make_agent("BizOps",   ["ace"]),  # both have same keyword
    }
    # Both domains match with 1 hit each — not confident
    matched, confident = _keyword_confidence("What is the ACE revenue?", agents)
    assert not confident


# ── Passthrough unwrap tests ──────────────────────────────────────────────────

def test_unwrap_passthrough_single_block():
    from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks

    raw = (
        "<<<KB_PASSTHROUGH>>>\n"
        "AGENT: BizOps Agent\n"
        "QUESTION: What is the revenue?\n"
        "SOURCE: BizOps/Revenue.xlsx\n"
        "SYSTEM_PROMPT:\nYou are the BizOps Agent.\n"
        "---CONTEXT---\n"
        "Q1 revenue: $1.2M\nQ2 revenue: $1.5M\n"
        "<<<KB_PASSTHROUGH_END>>>"
    )
    result = _unwrap_passthrough_blocks(raw)

    assert "<<<KB_PASSTHROUGH>>>" not in result
    assert "<<<KB_PASSTHROUGH_END>>>" not in result
    assert "passthrough mode" in result.lower() or "no local llm" in result.lower()
    assert "BizOps Agent" in result
    assert "BizOps/Revenue.xlsx" in result
    assert "Q1 revenue: $1.2M" in result


def test_unwrap_passthrough_multiple_blocks():
    from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks

    def _block(agent: str, source: str, context: str) -> str:
        return (
            f"<<<KB_PASSTHROUGH>>>\n"
            f"AGENT: {agent}\n"
            f"SOURCE: {source}\n"
            f"SYSTEM_PROMPT:\nYou are {agent}.\n"
            f"---CONTEXT---\n{context}\n"
            f"<<<KB_PASSTHROUGH_END>>>"
        )

    raw = _block("ACE Agent", "ACE Docs/FAQ.pdf", "ACE runs on JVM") + "\n" + \
          _block("BizOps Agent", "BizOps/Rev.xlsx", "Revenue: $2M")

    result = _unwrap_passthrough_blocks(raw)

    assert "<<<KB_PASSTHROUGH>>>" not in result
    assert "ACE Agent" in result
    assert "BizOps Agent" in result
    assert "ACE runs on JVM" in result
    assert "Revenue: $2M" in result


def test_unwrap_passthrough_no_blocks_returns_raw():
    from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks

    raw = "Just a normal answer with no passthrough markers."
    assert _unwrap_passthrough_blocks(raw) == raw


def test_unwrap_passthrough_no_source_field():
    from kb_agent_mcp.orchestrator import _unwrap_passthrough_blocks

    raw = (
        "<<<KB_PASSTHROUGH>>>\n"
        "AGENT: My Agent\n"
        "SYSTEM_PROMPT:\nYou are My Agent.\n"
        "---CONTEXT---\n"
        "Some context here.\n"
        "<<<KB_PASSTHROUGH_END>>>"
    )
    result = _unwrap_passthrough_blocks(raw)
    assert "My Agent" in result
    assert "Some context here." in result
    # No source line — no *Source:* line should appear
    assert "*Source:" not in result
