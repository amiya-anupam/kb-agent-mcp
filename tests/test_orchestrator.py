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
