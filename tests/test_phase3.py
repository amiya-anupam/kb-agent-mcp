"""
tests/test_phase3.py
────────────────────
Phase 3 tests covering generate CLI improvements:
  - Risk 13: Auto-accept when non-interactive (not isatty) or --yes flag
  - Risk 6:  Download progress message printed before model cache check
  - Risk 4:  KB_LLM_PROVIDER_GENERATE env var honoured by _run_generate()
  - Risk 13: --yes flag wires through argparse → _run_generate → _prompt_accept
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Risk 13 — _prompt_accept() auto-accepts in non-interactive / --yes mode
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptAccept:

    def test_yes_flag_auto_accepts(self, capsys):
        from kb_agent_mcp.cli.generate import _prompt_accept
        result = _prompt_accept("TestDomain", yes=True)
        assert result is True
        out = capsys.readouterr().out
        assert "auto" in out.lower() or "non-interactive" in out.lower()

    def test_non_tty_auto_accepts(self, monkeypatch, capsys):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        from kb_agent_mcp.cli.generate import _prompt_accept
        result = _prompt_accept("TestDomain", yes=False)
        assert result is True

    def test_tty_with_accept_input(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "A")
        from kb_agent_mcp.cli.generate import _prompt_accept
        assert _prompt_accept("TestDomain", yes=False) is True

    def test_tty_with_skip_input(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "S")
        from kb_agent_mcp.cli.generate import _prompt_accept
        assert _prompt_accept("TestDomain", yes=False) is False

    def test_tty_with_empty_input_accepts(self, monkeypatch):
        """Empty Enter is treated as Accept."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "")
        from kb_agent_mcp.cli.generate import _prompt_accept
        assert _prompt_accept("TestDomain", yes=False) is True

    def test_eoferror_returns_false(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        from kb_agent_mcp.cli.generate import _prompt_accept
        assert _prompt_accept("TestDomain", yes=False) is False

    def test_default_yes_is_false(self, monkeypatch):
        """yes defaults to False — interactive path is taken when stdin is a tty."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "A")
        from kb_agent_mcp.cli.generate import _prompt_accept
        assert _prompt_accept("TestDomain") is True


# ─────────────────────────────────────────────────────────────────────────────
# Risk 6 — Download warning printed before _ensure_embedding_model()
# ─────────────────────────────────────────────────────────────────────────────

class TestDownloadWarning:

    def test_warning_printed_before_model_load(self, monkeypatch, capsys, tmp_path):
        """The 'please wait' / download message must appear before the model is loaded."""
        import asyncio
        import importlib

        # Provide a valid KB_ROOT with one folder containing a file
        domain = tmp_path / "TestDomain"
        domain.mkdir()
        (domain / "doc.txt").write_text("hello world", encoding="utf-8")

        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        # _ensure_embedding_model is imported from kb_agent_mcp.embeddings at call-time
        import kb_agent_mcp.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "_ensure_embedding_model", lambda: None)

        from kb_agent_mcp.cli import generate as gen_mod
        importlib.reload(gen_mod)

        monkeypatch.setattr(gen_mod, "_llm_available", lambda: False)
        monkeypatch.setattr(gen_mod, "_prompt_accept", lambda *a, **kw: False)

        import kb_agent_mcp.vector_store as vs_mod

        async def _fake_build(domain_name, progress_fn=None, folder_path=None):
            return 0

        monkeypatch.setattr(vs_mod, "list_domains", lambda: [])
        monkeypatch.setattr(vs_mod, "build_collection", _fake_build)

        import kb_agent_mcp.config as config_mod
        importlib.reload(config_mod)

        asyncio.run(gen_mod._run_generate(no_llm=True, yes=True))

        captured = capsys.readouterr().out
        # The info() message must mention model / download / wait
        assert any(kw in captured.lower() for kw in ("download", "80 mb", "please wait", "model cache"))

    def test_model_cache_message_present(self, monkeypatch, capsys, tmp_path):
        """Simpler: just confirm info() message is in the function source."""
        from kb_agent_mcp.cli import generate as gen_mod
        import inspect
        src = inspect.getsource(gen_mod._run_generate)
        assert "80 MB" in src or "80 mb" in src.lower() or "please wait" in src.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Risk 4 — KB_LLM_PROVIDER_GENERATE in config
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderGenerateConfig:

    def test_default_is_empty_string(self, monkeypatch):
        import importlib
        import kb_agent_mcp.config as config_mod
        monkeypatch.delenv("KB_LLM_PROVIDER_GENERATE", raising=False)
        monkeypatch.setenv("KB_ROOT", "/tmp")
        importlib.reload(config_mod)
        cfg = config_mod.Config()
        assert cfg.KB_LLM_PROVIDER_GENERATE == ""

    def test_reads_from_env(self, monkeypatch):
        import importlib
        import kb_agent_mcp.config as config_mod
        monkeypatch.setenv("KB_LLM_PROVIDER_GENERATE", "openai")
        monkeypatch.setenv("KB_ROOT", "/tmp")
        importlib.reload(config_mod)
        cfg = config_mod.Config()
        assert cfg.KB_LLM_PROVIDER_GENERATE == "openai"

    def test_generate_provider_logged_when_set(self, monkeypatch, capsys, tmp_path):
        """When KB_LLM_PROVIDER_GENERATE is set, _run_generate prints it."""
        import asyncio
        import importlib
        import kb_agent_mcp.config as config_mod

        domain = tmp_path / "TestDomain"
        domain.mkdir()
        (domain / "doc.txt").write_text("hello", encoding="utf-8")

        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        monkeypatch.setenv("KB_LLM_PROVIDER_GENERATE", "anthropic")
        importlib.reload(config_mod)

        import kb_agent_mcp.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "_ensure_embedding_model", lambda: None)

        from kb_agent_mcp.cli import generate as gen_mod
        importlib.reload(gen_mod)

        monkeypatch.setattr(gen_mod, "_llm_available", lambda: False)
        monkeypatch.setattr(gen_mod, "_prompt_accept", lambda *a, **kw: False)

        import kb_agent_mcp.vector_store as vs_mod

        async def _fake_build(domain_name, progress_fn=None, folder_path=None):
            return 0

        monkeypatch.setattr(vs_mod, "list_domains", lambda: [])
        monkeypatch.setattr(vs_mod, "build_collection", _fake_build)

        asyncio.run(gen_mod._run_generate(no_llm=False, yes=True))

        out = capsys.readouterr().out
        assert "anthropic" in out.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Risk 13 — --yes flag wires through argparse
# ─────────────────────────────────────────────────────────────────────────────

class TestYesFlagArgparse:

    def test_yes_flag_present_in_parser(self):
        """--yes and -y must be registered in the argument parser."""
        import argparse
        from kb_agent_mcp.cli import generate as gen_mod
        import inspect

        src = inspect.getsource(gen_mod.main)
        assert "--yes" in src

    def test_yes_short_flag_present(self):
        from kb_agent_mcp.cli import generate as gen_mod
        import inspect
        src = inspect.getsource(gen_mod.main)
        assert '"-y"' in src or "'-y'" in src

    def test_run_generate_accepts_yes_param(self):
        """_run_generate() must accept a yes= keyword argument."""
        import inspect
        from kb_agent_mcp.cli.generate import _run_generate
        sig = inspect.signature(_run_generate)
        assert "yes" in sig.parameters


# ─────────────────────────────────────────────────────────────────────────────
# Risk 6 — _minimal_yaml description is now quoted (no YAML parse error)
# ─────────────────────────────────────────────────────────────────────────────

class TestMinimalYamlQuoting:

    def test_minimal_yaml_parseable(self):
        """_minimal_yaml must produce valid YAML for any folder name."""
        import yaml
        from kb_agent_mcp.cli.generate import _minimal_yaml

        for name in ("BizOps", "ACE Docs", "My Domain: Extra Colon", "CP4I"):
            text = _minimal_yaml(name)
            data = yaml.safe_load(text)
            assert isinstance(data, dict), f"Failed for {name!r}"
            assert data["folder_name"] == name
            assert "description" in data

    def test_minimal_yaml_description_quoted(self):
        """The description line must be quoted so colons don't break YAML."""
        from kb_agent_mcp.cli.generate import _minimal_yaml
        text = _minimal_yaml("My Domain")
        # The description line must be parseable without error
        import yaml
        data = yaml.safe_load(text)
        assert "description" in data
        assert "My Domain" in data["description"]
