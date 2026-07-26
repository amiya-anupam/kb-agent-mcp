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
