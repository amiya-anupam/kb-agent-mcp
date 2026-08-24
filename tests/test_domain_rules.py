"""
tests/test_domain_rules.py — DomainConfig and retrieval-rule tests
"""
from __future__ import annotations

import pytest
from pathlib import Path


# ── DomainConfig ────────────────────────────────────────────────────────────────

def test_domain_config_data_pattern():
    from kb_agent_mcp.domain_rules import DomainConfig
    cfg = DomainConfig(
        folder_name="BizOps",
        agent_name="BizOps Agent",
        description="Revenue data",
        keywords=["revenue", "ACE"],
        top_n=5,
        max_chars=8000,
        system_prompt="You are a specialist.",
        data_patterns=[r"\brevenue\b"],
    )
    assert cfg.is_data_question("What is the total revenue for Q3?")
    assert not cfg.is_data_question("How does ACE work?")


def test_domain_config_complex_pattern():
    from kb_agent_mcp.domain_rules import DomainConfig
    cfg = DomainConfig(
        folder_name="ACE Docs",
        agent_name="ACE Docs Agent",
        description="ACE documentation",
        keywords=["ace", "integration"],
        top_n=4,
        max_chars=6000,
        system_prompt="You are a specialist.",
        complex_patterns=[r"\barchitecture\b"],
    )
    assert cfg.is_complex_question("Explain the architecture of ACE")
    assert not cfg.is_complex_question("What version is ACE?")


def test_load_domain_config_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    import importlib
    import kb_agent_mcp.config as cfg_mod
    importlib.reload(cfg_mod)
    import kb_agent_mcp.domain_rules as dr_mod
    importlib.reload(dr_mod)

    # Folder exists but no domain_config.yaml
    (tmp_path / "MyDomain").mkdir()
    result = dr_mod.load_domain_config("MyDomain")
    assert result is None


def test_load_domain_config_from_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    import importlib
    import kb_agent_mcp.config as cfg_mod
    importlib.reload(cfg_mod)
    import kb_agent_mcp.domain_rules as dr_mod
    importlib.reload(dr_mod)

    folder = tmp_path / "TestDomain"
    folder.mkdir()
    yaml_content = """
folder_name: TestDomain
agent_name: TestDomain Agent
description: A test knowledge domain
keywords:
  - test
  - example
top_n: 3
max_chars: 5000
system_prompt: |
  You are the TestDomain Agent.
retrieval_rules:
  pin_files:
    - "*important*.pdf"
  boost_keywords:
    - important
  question_classifier:
    data_patterns:
      - "\\\\bmetric\\\\b"
    complex_patterns: []
"""
    (folder / "domain_config.yaml").write_text(yaml_content, encoding="utf-8")

    result = dr_mod.load_domain_config("TestDomain")
    assert result is not None
    assert result.folder_name == "TestDomain"
    assert result.top_n == 3
    assert "test" in result.keywords
    assert "*important*.pdf" in result.pin_files
    assert "important" in result.boost_keywords


def test_apply_pin_rules_boost(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    import importlib
    import kb_agent_mcp.config as cfg_mod
    importlib.reload(cfg_mod)
    import kb_agent_mcp.domain_rules as dr_mod
    importlib.reload(dr_mod)

    domain_cfg = dr_mod.DomainConfig(
        folder_name="Revenue",
        agent_name="Revenue Agent",
        description="Revenue data",
        keywords=["revenue"],
        top_n=4,
        max_chars=8000,
        system_prompt="",
        boost_keywords=["revenue"],
    )

    results = [
        {"path": "Revenue/Other.pdf",   "name": "Other.pdf",   "score": 0.9},
        {"path": "Revenue/Revenue.xlsx", "name": "Revenue.xlsx", "score": 0.7},
    ]
    ordered = dr_mod.apply_pin_rules(results, "Revenue", domain_cfg)
    # Revenue.xlsx should be first because it contains "revenue" keyword
    assert ordered[0]["name"] == "Revenue.xlsx"


# ── system_prompt_extra ─────────────────────────────────────────────────────────

def test_system_prompt_extra_parsed_from_yaml():
    """system_prompt_extra from YAML is stored on DomainConfig."""
    from kb_agent_mcp.domain_rules import load_domain_config_from_dict
    raw = {
        "folder_name": "TestDomain",
        "agent_name": "TestDomain Agent",
        "description": "A test domain",
        "keywords": ["test"],
        "top_n": 4,
        "max_chars": 8000,
        "system_prompt": "You are the TestDomain Agent.",
        "system_prompt_extra": "Always cite the contract reference number.",
    }
    cfg = load_domain_config_from_dict("TestDomain", raw)
    assert cfg.system_prompt_extra == "Always cite the contract reference number."


def test_system_prompt_extra_absent_defaults_empty():
    """Absent system_prompt_extra field defaults to empty string."""
    from kb_agent_mcp.domain_rules import load_domain_config_from_dict
    raw = {
        "folder_name": "TestDomain",
        "agent_name": "TestDomain Agent",
        "description": "A test domain",
        "keywords": [],
        "top_n": 4,
        "max_chars": 8000,
        "system_prompt": "You are the TestDomain Agent.",
    }
    cfg = load_domain_config_from_dict("TestDomain", raw)
    assert cfg.system_prompt_extra == ""


def test_system_prompt_extra_empty_string_stays_empty():
    """Explicitly set empty system_prompt_extra is normalised to ''."""
    from kb_agent_mcp.domain_rules import load_domain_config_from_dict
    raw = {
        "folder_name": "TestDomain",
        "agent_name": "TestDomain Agent",
        "description": "A test domain",
        "keywords": [],
        "top_n": 4,
        "max_chars": 8000,
        "system_prompt": "You are the TestDomain Agent.",
        "system_prompt_extra": "",
    }
    cfg = load_domain_config_from_dict("TestDomain", raw)
    assert cfg.system_prompt_extra == ""


def test_system_prompt_extra_appended_in_domain_agent(monkeypatch):
    """DomainAgent.run() appends system_prompt_extra between system_prompt and format directive."""
    import asyncio
    from kb_agent_mcp.domain_rules import DomainConfig
    from kb_agent_mcp.domain_agent import DomainAgent

    captured: dict = {}

    async def _fake_base_ask(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return {"agent": "test", "answer": "ok", "sources": [], "found": True}

    monkeypatch.setattr("kb_agent_mcp.domain_agent._base_ask", _fake_base_ask)
    monkeypatch.setattr("kb_agent_mcp.domain_agent._global_data_q", lambda q: False)

    config = DomainConfig(
        folder_name="TestDomain",
        agent_name="TestDomain Agent",
        description="A test domain",
        keywords=[],
        top_n=4,
        max_chars=8000,
        system_prompt="You are the base agent.",
        system_prompt_extra="Always cite the contract ref.",
    )
    agent = DomainAgent("TestDomain", config=config)
    asyncio.run(agent.run("Any question?", []))

    prompt = captured["system_prompt"]
    assert "You are the base agent." in prompt
    assert "Always cite the contract ref." in prompt
    # extra comes before any format directive (no format_instruction given)
    assert prompt.index("You are the base agent.") < prompt.index("Always cite the contract ref.")


def test_system_prompt_extra_absent_no_double_newline(monkeypatch):
    """When system_prompt_extra is empty, no extra newline is injected."""
    import asyncio
    from kb_agent_mcp.domain_rules import DomainConfig
    from kb_agent_mcp.domain_agent import DomainAgent

    captured: dict = {}

    async def _fake_base_ask(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return {"agent": "test", "answer": "ok", "sources": [], "found": True}

    monkeypatch.setattr("kb_agent_mcp.domain_agent._base_ask", _fake_base_ask)
    monkeypatch.setattr("kb_agent_mcp.domain_agent._global_data_q", lambda q: False)

    config = DomainConfig(
        folder_name="TestDomain",
        agent_name="TestDomain Agent",
        description="A test domain",
        keywords=[],
        top_n=4,
        max_chars=8000,
        system_prompt="You are the base agent.",
        # system_prompt_extra not set — defaults to ""
    )
    agent = DomainAgent("TestDomain", config=config)
    asyncio.run(agent.run("Any question?", []))

    assert captured["system_prompt"] == "You are the base agent."


def test_system_prompt_extra_before_format_directive(monkeypatch):
    """system_prompt_extra appears before the format directive in the final prompt."""
    import asyncio
    from kb_agent_mcp.domain_rules import DomainConfig
    from kb_agent_mcp.domain_agent import DomainAgent

    captured: dict = {}

    async def _fake_base_ask(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return {"agent": "test", "answer": "ok", "sources": [], "found": True}

    monkeypatch.setattr("kb_agent_mcp.domain_agent._base_ask", _fake_base_ask)
    monkeypatch.setattr("kb_agent_mcp.domain_agent._global_data_q", lambda q: False)

    config = DomainConfig(
        folder_name="TestDomain",
        agent_name="TestDomain Agent",
        description="A test domain",
        keywords=[],
        top_n=4,
        max_chars=8000,
        system_prompt="You are the base agent.",
        system_prompt_extra="Cite all sources.",
    )
    agent = DomainAgent("TestDomain", config=config)
    asyncio.run(agent.run("Any question?", [], format_instruction="Return JSON"))

    prompt = captured["system_prompt"]
    assert "Cite all sources." in prompt
    assert "Return JSON" in prompt
    # ordering: base → extra → format
    assert prompt.index("Cite all sources.") < prompt.index("Return JSON")
