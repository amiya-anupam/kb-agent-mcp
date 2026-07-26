"""
tests/test_config.py — Config module tests
"""
from __future__ import annotations

import os
import pytest
from pathlib import Path


def test_config_defaults(tmp_path, monkeypatch):
    """Config defaults are correct when no env vars are set."""
    monkeypatch.delenv("KB_ROOT", raising=False)
    monkeypatch.delenv("KB_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    # Re-import to pick up the patched env
    import importlib
    import kb_agent_mcp.config as mod
    importlib.reload(mod)
    cfg = mod.Config()
    assert cfg.KB_LLM_PROVIDER == "ollama"
    assert cfg.KB_MODEL == "qwen3:14b"
    assert cfg.KB_SESSION_MAX_TURNS == 20
    assert cfg.KB_SESSION_TIMEOUT_HOURS == 2.0


def test_config_kb_root_path(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    import importlib
    import kb_agent_mcp.config as mod
    importlib.reload(mod)
    cfg = mod.Config()
    assert cfg.kb_root_path == tmp_path.resolve()


def test_config_validate_missing_root(tmp_path, monkeypatch):
    missing = tmp_path / "does_not_exist"
    monkeypatch.setenv("KB_ROOT", str(missing))
    import importlib
    import kb_agent_mcp.config as mod
    importlib.reload(mod)
    cfg = mod.Config()
    errors = cfg.validate()
    assert any("KB_ROOT" in e for e in errors)


def test_config_is_ignored():
    from kb_agent_mcp.config import cfg
    assert cfg.is_ignored(".git")
    assert cfg.is_ignored("agents")
    assert cfg.is_ignored(".hidden")
    assert not cfg.is_ignored("ACE Docs")
    assert not cfg.is_ignored("BizOps")


def test_config_session_memory_path(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    import importlib
    import kb_agent_mcp.config as mod
    importlib.reload(mod)
    cfg = mod.Config()
    assert cfg.session_memory_path == tmp_path / ".kb_index" / "session_memory.json"
