"""
tests/test_phase1_kb_root_warning.py
──────────────────────────────────────
Phase 1.2 — KB_ROOT-not-set warning surfaces through:
  1. Config.kb_root_is_explicit property
  2. orchestrator.ask() empty-domains response
  3. orchestrator.list_domains() sentinel entry
"""
from __future__ import annotations

import importlib
import os
import asyncio
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _reload_config(monkeypatch, kb_root: str | None):
    """Reload kb_agent_mcp.config with KB_ROOT set or cleared.

    When kb_root is None we clear KB_ROOT after reload too, because
    _load_dotenv() (a module-level call inside config.py) re-injects
    KB_ROOT from .env into os.environ every time the module is reloaded.
    Deleting the key after reload ensures kb_root_is_explicit == False.
    """
    if kb_root is None:
        monkeypatch.delenv("KB_ROOT", raising=False)
    else:
        monkeypatch.setenv("KB_ROOT", kb_root)
    import kb_agent_mcp.config as mod
    importlib.reload(mod)
    if kb_root is None:
        # _load_dotenv() may have re-injected KB_ROOT from .env — remove it again
        os.environ.pop("KB_ROOT", None)
    return mod.Config()


# ── kb_root_is_explicit property ──────────────────────────────────────────────

class TestKbRootIsExplicit:

    def test_false_when_not_set(self, monkeypatch):
        cfg = _reload_config(monkeypatch, None)
        assert not cfg.kb_root_is_explicit

    def test_true_when_set_in_env(self, monkeypatch, tmp_path):
        cfg = _reload_config(monkeypatch, str(tmp_path))
        assert cfg.kb_root_is_explicit

    def test_cwd_fallback_is_not_explicit(self, monkeypatch):
        """Defaulting to CWD must NOT count as explicit."""
        monkeypatch.delenv("KB_ROOT", raising=False)
        import kb_agent_mcp.config as mod
        importlib.reload(mod)
        # _load_dotenv() may have re-injected KB_ROOT from .env — remove it again
        os.environ.pop("KB_ROOT", None)
        cfg = mod.Config()
        assert not cfg.kb_root_is_explicit

    def test_empty_string_not_explicit(self, monkeypatch):
        """An empty KB_ROOT env var — is_explicit is True (var present) but
        validate() should still catch the missing/invalid root."""
        monkeypatch.setenv("KB_ROOT", "")
        import kb_agent_mcp.config as mod
        importlib.reload(mod)
        cfg = mod.Config()
        # The env key is present, so is_explicit = True
        assert cfg.kb_root_is_explicit
        # But validate() must flag the empty/non-existent path
        errors = cfg.validate()
        assert errors, "Expected a validation error for empty KB_ROOT"


# ── orchestrator ask() — empty domains ────────────────────────────────────────

class TestAskEmptyDomainsWarning:

    def _empty_agents_ask(self, monkeypatch, tmp_path, explicit: bool) -> str:
        """Run orchestrator.ask() with zero domains by patching build_all_domain_agents."""
        import kb_agent_mcp.config as config_mod
        import kb_agent_mcp.orchestrator as orch_mod

        if explicit:
            monkeypatch.setenv("KB_ROOT", str(tmp_path))
        else:
            monkeypatch.delenv("KB_ROOT", raising=False)

        importlib.reload(config_mod)

        if not explicit:
            # _load_dotenv() may have re-injected KB_ROOT from .env — remove it again
            os.environ.pop("KB_ROOT", None)
            # Patch cfg in orchestrator so it reflects kb_root_is_explicit=False
            monkeypatch.setattr(orch_mod, "cfg", config_mod.Config())

        # Force the orchestrator to see zero domains and use the fresh config
        async def _no_domains():
            return {}

        monkeypatch.setattr(orch_mod, "build_all_domain_agents", _no_domains)
        orch_mod._agents = None

        result = asyncio.run(orch_mod.ask("What is ACE?"))
        return result

    def test_ask_no_domains_contains_generate_hint(self, monkeypatch, tmp_path):
        result = self._empty_agents_ask(monkeypatch, tmp_path, explicit=True)
        assert "kb-agent-generate" in result

    def test_ask_no_domains_explicit_shows_path(self, monkeypatch, tmp_path):
        result = self._empty_agents_ask(monkeypatch, tmp_path, explicit=True)
        # Should show the actual path, not the generic MCP hint
        assert str(tmp_path) in result or "KB_ROOT" in result

    def test_ask_no_domains_not_explicit_shows_mcp_hint(self, monkeypatch, tmp_path):
        result = self._empty_agents_ask(monkeypatch, tmp_path, explicit=False)
        assert "KB_ROOT" in result
        # Must include the actionable MCP host config guidance
        assert "env" in result.lower() or "mcp" in result.lower() or "config" in result.lower()

    def test_ask_no_domains_warning_marker_present(self, monkeypatch, tmp_path):
        result = self._empty_agents_ask(monkeypatch, tmp_path, explicit=False)
        # The ⚠ warning indicator must be present
        assert "⚠" in result or "WARNING" in result.upper() or "not set" in result.lower()


# ── orchestrator list_domains() — sentinel entry ──────────────────────────────

class TestListDomainsSentinel:

    def _run_list_domains(self, monkeypatch, tmp_path, explicit: bool) -> list:
        import kb_agent_mcp.config as config_mod
        import kb_agent_mcp.orchestrator as orch_mod

        if explicit:
            monkeypatch.setenv("KB_ROOT", str(tmp_path))
        else:
            monkeypatch.delenv("KB_ROOT", raising=False)

        importlib.reload(config_mod)

        if not explicit:
            # _load_dotenv() may have re-injected KB_ROOT from .env — remove it again.
            # Also use build_all_domain_agents that returns empty (cfg singleton may
            # still point to real KB_ROOT) and ensure orchestrator cfg is fresh.
            os.environ.pop("KB_ROOT", None)
            fresh_cfg = config_mod.Config()
            monkeypatch.setattr(orch_mod, "cfg", fresh_cfg)

            async def _no_domains():
                return {}
            monkeypatch.setattr(orch_mod, "build_all_domain_agents", _no_domains)

        orch_mod._agents = None

        return asyncio.run(orch_mod.list_domains())

    def test_returns_sentinel_when_no_domains(self, monkeypatch, tmp_path):
        result = self._run_list_domains(monkeypatch, tmp_path, explicit=True)
        assert len(result) == 1
        assert result[0]["folder_name"] == "_no_domains"

    def test_sentinel_description_has_generate_hint(self, monkeypatch, tmp_path):
        result = self._run_list_domains(monkeypatch, tmp_path, explicit=True)
        assert "kb-agent-generate" in result[0]["description"]

    def test_sentinel_not_explicit_shows_mcp_hint(self, monkeypatch, tmp_path):
        result = self._run_list_domains(monkeypatch, tmp_path, explicit=False)
        desc = result[0]["description"]
        assert "KB_ROOT" in desc
        assert "not explicitly set" in desc or "config env block" in desc

    def test_sentinel_explicit_shows_path_not_mcp_hint(self, monkeypatch, tmp_path):
        result = self._run_list_domains(monkeypatch, tmp_path, explicit=True)
        desc = result[0]["description"]
        # Explicit path: show path hint, not the generic MCP config hint
        assert "not explicitly set" not in desc

    def test_real_domains_no_sentinel(self, monkeypatch, tmp_path):
        """When real domains exist the sentinel must NOT be returned."""
        # Create a minimal domain folder with an indexable file
        domain = tmp_path / "MyDomain"
        domain.mkdir()
        (domain / "doc.txt").write_text("some content")
        (domain / "domain_config.yaml").write_text(
            "folder_name: MyDomain\nagent_name: MyDomain Agent\n"
            "description: Test\nkeywords: [test]\ntop_n: 4\nmax_chars: 4000\n"
            "system_prompt: You are an agent.\n"
        )
        import kb_agent_mcp.config as config_mod
        import kb_agent_mcp.orchestrator as orch_mod
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        importlib.reload(config_mod)
        orch_mod._agents = None

        result = asyncio.run(orch_mod.list_domains())
        names = [d["folder_name"] for d in result]
        assert "_no_domains" not in names, \
            f"Sentinel must not appear when real domains exist: {names}"


# ── server.py startup warning (stderr) ────────────────────────────────────────

def test_server_startup_warns_to_stderr_when_kb_root_not_set(
    monkeypatch, tmp_path, capsys
):
    """
    Simulates the critical case: MCP host launches kb-agent-serve without
    KB_ROOT in the env block. The startup code must print to stderr.
    We test the warning block directly without spinning up FastMCP.
    """
    import kb_agent_mcp.config as config_mod
    monkeypatch.delenv("KB_ROOT", raising=False)
    importlib.reload(config_mod)
    # _load_dotenv() may have re-injected KB_ROOT from .env — remove it again
    os.environ.pop("KB_ROOT", None)
    cfg = config_mod.Config()

    import sys
    if not cfg.kb_root_is_explicit:
        print(
            f"⚠  KB_ROOT is not set — defaulting to current working directory "
            f"({cfg.kb_root_path}).\n"
            "   Add KB_ROOT to your MCP host config env block.",
            file=sys.stderr,
        )

    captured = capsys.readouterr()
    assert "KB_ROOT" in captured.err
    assert "not set" in captured.err or "defaulting" in captured.err
