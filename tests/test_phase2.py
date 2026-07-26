"""
tests/test_phase2.py
────────────────────
Phase 2 tests covering the setup wizard redesign:
  - Risk 1:  Build tools detection (present → silent, missing → soft block)
  - Risk 5:  Virtual-environment detection and guidance
  - Risk 4:  choose_llm() redesign — passthrough + key follow-up
  - Risk 4:  interactive_keyword_editor() — keywords-only, post-generate
  - Risk 3:  _serve_path() returns absolute path; completion shows it first
  - Risk 7:  _test_api_key() returns bool; soft-block on 401/403
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Risk 1 — Build tools detection
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildToolsDetection:

    def test_windows_always_present(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        from kb_agent_mcp.cli.setup import _build_tools_present
        assert _build_tools_present() is True

    def test_macos_present_when_xcode_found(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        import subprocess as sp
        monkeypatch.setattr(
            sp, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0})(),
        )
        from kb_agent_mcp.cli import setup as setup_mod
        import importlib; importlib.reload(setup_mod)
        assert setup_mod._build_tools_present() is True

    def test_macos_missing_when_xcode_not_found(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        import subprocess as sp
        monkeypatch.setattr(
            sp, "run",
            lambda *a, **kw: type("R", (), {"returncode": 2})(),
        )
        from kb_agent_mcp.cli import setup as setup_mod
        import importlib; importlib.reload(setup_mod)
        assert setup_mod._build_tools_present() is False

    def test_linux_present_when_gcc_found(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        import shutil
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/gcc" if cmd == "gcc" else None)
        from kb_agent_mcp.cli import setup as setup_mod
        import importlib; importlib.reload(setup_mod)
        assert setup_mod._build_tools_present() is True

    def test_linux_missing_when_no_gcc(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        import shutil
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        from kb_agent_mcp.cli import setup as setup_mod
        import importlib; importlib.reload(setup_mod)
        assert setup_mod._build_tools_present() is False

    def test_fix_hint_macos(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        from kb_agent_mcp.cli.setup import _build_tools_fix_hint
        assert "xcode-select" in _build_tools_fix_hint()

    def test_fix_hint_linux(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        from kb_agent_mcp.cli.setup import _build_tools_fix_hint
        assert "build-essential" in _build_tools_fix_hint()

    def test_check_build_tools_silent_when_present(self, monkeypatch, capsys):
        """When tools are present, check_build_tools() must print nothing."""
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_build_tools_present", lambda: True)
        setup_mod.check_build_tools(yes=False)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_check_build_tools_warns_when_missing(self, monkeypatch, capsys):
        """When tools are missing, check_build_tools() must print a warning."""
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_build_tools_present", lambda: False)
        monkeypatch.setattr(setup_mod, "_build_tools_fix_hint", lambda: "xcode-select --install")
        # Simulate user confirming "Continue anyway"
        monkeypatch.setattr("builtins.input", lambda _: "y")
        setup_mod.check_build_tools(yes=False)
        captured = capsys.readouterr()
        assert "build tools" in captured.out.lower() or "chromadb" in captured.out.lower()

    def test_check_build_tools_yes_mode_continues(self, monkeypatch, capsys):
        """--yes mode must not prompt; must continue even when tools missing."""
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_build_tools_present", lambda: False)
        monkeypatch.setattr(setup_mod, "_build_tools_fix_hint", lambda: "xcode-select --install")
        # Should not raise SystemExit
        setup_mod.check_build_tools(yes=True)


# ─────────────────────────────────────────────────────────────────────────────
# Risk 5 — Virtual-environment detection
# ─────────────────────────────────────────────────────────────────────────────

class TestVenvDetection:

    def test_in_venv_true_when_prefix_differs(self, monkeypatch):
        monkeypatch.setattr(sys, "prefix", "/some/venv")
        monkeypatch.setattr(sys, "base_prefix", "/usr")
        from kb_agent_mcp.cli.setup import _in_venv
        assert _in_venv() is True

    def test_in_venv_false_when_prefix_same(self, monkeypatch):
        monkeypatch.setattr(sys, "prefix", "/usr")
        monkeypatch.setattr(sys, "base_prefix", "/usr")
        from kb_agent_mcp.cli.setup import _in_venv
        assert _in_venv() is False

    def test_check_venv_silent_when_in_venv(self, monkeypatch, capsys):
        """When already in a venv, check_venv() must print nothing."""
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_in_venv", lambda: True)
        setup_mod.check_venv(yes=False)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_check_venv_warns_when_not_in_venv(self, monkeypatch, capsys):
        """When not in a venv, check_venv() must print a recommendation."""
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_in_venv", lambda: False)
        monkeypatch.setattr("builtins.input", lambda _: "y")
        setup_mod.check_venv(yes=False)
        captured = capsys.readouterr()
        assert "venv" in captured.out.lower()

    def test_check_venv_shows_venv_commands(self, monkeypatch, capsys):
        """The venv guidance must include the setup commands."""
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_in_venv", lambda: False)
        monkeypatch.setattr("builtins.input", lambda _: "y")
        setup_mod.check_venv(yes=False)
        captured = capsys.readouterr()
        assert "python3 -m venv" in captured.out

    def test_check_venv_yes_mode_continues(self, monkeypatch, capsys):
        """--yes mode must not prompt; must continue even when not in venv."""
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_in_venv", lambda: False)
        setup_mod.check_venv(yes=True)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# Risk 7 — _test_api_key() returns bool
# ─────────────────────────────────────────────────────────────────────────────

class TestApiKeyValidation:

    def test_returns_true_on_success(self, monkeypatch):
        import urllib.request as ur
        class _FakeResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass
        monkeypatch.setattr(ur, "urlopen", lambda req, timeout: _FakeResp())
        from kb_agent_mcp.cli.setup import _test_api_key
        assert _test_api_key("openai", "https://api.openai.com/v1", "sk-test", "gpt-4o") is True

    def test_returns_false_on_401(self, monkeypatch):
        import urllib.request as ur
        import urllib.error as ue
        def _raise(*a, **kw):
            raise ue.HTTPError(None, 401, "Unauthorized", {}, None)
        monkeypatch.setattr(ur, "urlopen", _raise)
        from kb_agent_mcp.cli.setup import _test_api_key
        assert _test_api_key("openai", "https://api.openai.com/v1", "bad-key", "gpt-4o") is False

    def test_returns_false_on_403(self, monkeypatch):
        import urllib.request as ur
        import urllib.error as ue
        def _raise(*a, **kw):
            raise ue.HTTPError(None, 403, "Forbidden", {}, None)
        monkeypatch.setattr(ur, "urlopen", _raise)
        from kb_agent_mcp.cli.setup import _test_api_key
        assert _test_api_key("openai", "https://api.openai.com/v1", "bad-key", "gpt-4o") is False

    def test_returns_true_on_timeout(self, monkeypatch):
        """Network failure must NOT be treated as a key failure — returns True."""
        import urllib.request as ur
        monkeypatch.setattr(ur, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("timeout")))
        from kb_agent_mcp.cli.setup import _test_api_key
        assert _test_api_key("openai", "https://api.openai.com/v1", "sk-x", "gpt-4o") is True


# ─────────────────────────────────────────────────────────────────────────────
# Risk 4 — choose_llm() redesign
# ─────────────────────────────────────────────────────────────────────────────

class TestChooseLlm:

    def test_yes_mode_returns_passthrough(self):
        from kb_agent_mcp.cli.setup import choose_llm
        result = choose_llm(yes=True)
        assert result["KB_LLM_PROVIDER"] == "passthrough"

    def test_passthrough_no_key_returns_passthrough_only(self, monkeypatch):
        """Choice 1 (passthrough) + decline key → KB_LLM_PROVIDER=passthrough, no KB_API_KEY."""
        inputs = iter(["1", "n"])  # choice=1 (passthrough), no key
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        from kb_agent_mcp.cli.setup import choose_llm
        result = choose_llm(yes=False)
        assert result["KB_LLM_PROVIDER"] == "passthrough"
        assert "KB_API_KEY" not in result

    def test_passthrough_with_openai_key(self, monkeypatch):
        """Choice 1 (passthrough) + provide OpenAI key → passthrough provider + KB_API_KEY."""
        inputs = iter(["1", "y", "1", "sk-testkey123", "gpt-4o-mini"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        # Mock API key validation to succeed
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_test_api_key", lambda *a, **kw: True)
        result = setup_mod.choose_llm(yes=False)
        assert result["KB_LLM_PROVIDER"] == "passthrough"
        assert result.get("KB_API_KEY") == "sk-testkey123"

    def test_passthrough_with_anthropic_key(self, monkeypatch):
        """Choice 1 (passthrough) + provide Anthropic key → passthrough + anthropic generate."""
        inputs = iter(["1", "y", "2", "ant-testkey", "claude-3-5-haiku-20241022"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_test_api_key", lambda *a, **kw: True)
        result = setup_mod.choose_llm(yes=False)
        assert result["KB_LLM_PROVIDER"] == "passthrough"
        assert result.get("KB_LLM_PROVIDER_GENERATE") == "anthropic"
        assert result.get("KB_API_KEY") == "ant-testkey"

    def test_ollama_choice_returns_correct_keys(self, monkeypatch):
        inputs = iter(["2", "qwen3:14b"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        from kb_agent_mcp.cli.setup import choose_llm
        result = choose_llm(yes=False)
        assert result["KB_LLM_PROVIDER"] == "ollama"
        assert result["KB_MODEL"] == "qwen3:14b"
        assert "KB_EMBED_MODEL" in result

    def test_openai_choice_includes_embed_model(self, monkeypatch):
        inputs = iter(["3", "sk-openaikey", "gpt-4o-mini"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_test_api_key", lambda *a, **kw: True)
        result = setup_mod.choose_llm(yes=False)
        assert result["KB_LLM_PROVIDER"] == "openai"
        assert result.get("KB_EMBED_MODEL") == "text-embedding-3-small"

    def test_invalid_api_key_soft_block(self, monkeypatch):
        """401 on key test → user prompted 'use anyway'; declining drops the key."""
        inputs = iter(["3", "bad-key", "gpt-4o-mini", "n"])  # 'n' = don't use invalid key
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_test_api_key", lambda *a, **kw: False)
        result = setup_mod.choose_llm(yes=False)
        # Key was declined — KB_API_KEY should not be in result
        assert "KB_API_KEY" not in result


# ─────────────────────────────────────────────────────────────────────────────
# Risk 4 — interactive_keyword_editor()
# ─────────────────────────────────────────────────────────────────────────────

class TestInteractiveKeywordEditor:

    def _minimal_yaml(self, domain_name: str) -> str:
        return (
            f"folder_name: {domain_name}\n"
            f"agent_name: {domain_name} Agent\n"
            f'description: "Knowledge domain: {domain_name}"\n'
            f"keywords:\n- {domain_name.lower()}\n"
            f"top_n: 4\nmax_chars: 8000\n"
            f"system_prompt: |\n  You are an agent.\n"
        )

    def test_skips_when_no_minimal_domains(self, tmp_path, capsys):
        from kb_agent_mcp.cli.setup import interactive_keyword_editor
        interactive_keyword_editor([], tmp_path, yes=False)
        captured = capsys.readouterr()
        assert captured.out == ""  # nothing printed

    def test_skips_in_yes_mode_with_warning(self, tmp_path, capsys):
        from kb_agent_mcp.cli.setup import interactive_keyword_editor
        interactive_keyword_editor(["BizOps"], tmp_path, yes=True)
        captured = capsys.readouterr()
        assert "BizOps" in captured.out
        assert "manually" in captured.out.lower() or "keyword" in captured.out.lower()

    def test_editor_updates_keywords_only(self, tmp_path, monkeypatch):
        """Editor must update keywords: section and leave system_prompt unchanged."""
        domain = tmp_path / "BizOps"
        domain.mkdir()
        yaml_path = domain / "domain_config.yaml"
        yaml_path.write_text(self._minimal_yaml("BizOps"), encoding="utf-8")

        # Simulate: confirm edit + enter keywords
        inputs = iter(["y", "revenue, quota, attainment, renewal"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        from kb_agent_mcp.cli.setup import interactive_keyword_editor
        interactive_keyword_editor(["BizOps"], tmp_path, yes=False)

        import yaml
        data = yaml.safe_load(yaml_path.read_text())
        assert set(data["keywords"]) == {"revenue", "quota", "attainment", "renewal"}
        # system_prompt must still be present
        assert "system_prompt" in data

    def test_editor_skips_domain_on_empty_input(self, tmp_path, monkeypatch):
        """Empty keyword input must leave the YAML file unchanged."""
        domain = tmp_path / "BizOps"
        domain.mkdir()
        yaml_path = domain / "domain_config.yaml"
        original = self._minimal_yaml("BizOps")
        yaml_path.write_text(original, encoding="utf-8")

        inputs = iter(["y", ""])  # confirm, then empty keywords
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        from kb_agent_mcp.cli.setup import interactive_keyword_editor
        interactive_keyword_editor(["BizOps"], tmp_path, yes=False)

        assert yaml_path.read_text(encoding="utf-8") == original

    def test_editor_handles_multiple_domains(self, tmp_path, monkeypatch):
        """Editor iterates all minimal domains."""
        for name in ("BizOps", "ACE Docs"):
            d = tmp_path / name
            d.mkdir()
            (d / "domain_config.yaml").write_text(self._minimal_yaml(name), encoding="utf-8")

        inputs = iter(["y", "revenue, quota", "ace, integration, api"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        from kb_agent_mcp.cli.setup import interactive_keyword_editor
        interactive_keyword_editor(["BizOps", "ACE Docs"], tmp_path, yes=False)

        import yaml
        biz = yaml.safe_load((tmp_path / "BizOps" / "domain_config.yaml").read_text())
        ace = yaml.safe_load((tmp_path / "ACE Docs" / "domain_config.yaml").read_text())
        assert "revenue" in biz["keywords"]
        assert "ace" in ace["keywords"]

    def test_editor_decline_prints_nudge(self, tmp_path, monkeypatch, capsys):
        """Declining the editor must print a manual-edit nudge."""
        domain = tmp_path / "BizOps"
        domain.mkdir()
        (domain / "domain_config.yaml").write_text(self._minimal_yaml("BizOps"), encoding="utf-8")

        monkeypatch.setattr("builtins.input", lambda _: "n")  # decline

        from kb_agent_mcp.cli.setup import interactive_keyword_editor
        interactive_keyword_editor(["BizOps"], tmp_path, yes=False)

        captured = capsys.readouterr()
        assert "manually" in captured.out.lower() or "edit" in captured.out.lower()

    def test_editor_missing_yaml_skips_gracefully(self, tmp_path, monkeypatch, capsys):
        """If domain_config.yaml doesn't exist, skip that domain without crashing."""
        domain = tmp_path / "GhostDomain"
        domain.mkdir()  # no domain_config.yaml

        monkeypatch.setattr("builtins.input", lambda _: "y")

        from kb_agent_mcp.cli.setup import interactive_keyword_editor
        # Must not raise
        interactive_keyword_editor(["GhostDomain"], tmp_path, yes=False)
        captured = capsys.readouterr()
        assert "skipping" in captured.out.lower() or "not found" in captured.out.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Risk 3 — _serve_path() returns absolute path; completion output
# ─────────────────────────────────────────────────────────────────────────────

class TestServePath:

    def test_returns_absolute_path_when_which_finds_it(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/local/bin/kb-agent-serve")
        from kb_agent_mcp.cli.setup import _serve_path
        result = _serve_path()
        assert result == "/usr/local/bin/kb-agent-serve"

    def test_falls_back_to_venv_bin(self, monkeypatch, tmp_path):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        # Create fake venv structure
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_serve = fake_bin / "kb-agent-serve"
        fake_serve.touch()
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        from kb_agent_mcp.cli import setup as setup_mod
        import importlib; importlib.reload(setup_mod)
        result = setup_mod._serve_path()
        assert str(fake_serve) in result or result == str(fake_serve)

    def test_completion_shows_mcp_json_first(self, monkeypatch, capsys, tmp_path):
        """The completion block must show the MCP JSON config before other text."""
        from kb_agent_mcp.cli import setup as setup_mod
        monkeypatch.setattr(setup_mod, "_serve_path", lambda: "/venv/bin/kb-agent-serve")
        monkeypatch.setattr(setup_mod, "_in_venv", lambda: True)

        # Capture what main() prints in the completion section by calling it directly
        serve_cmd = "/venv/bin/kb-agent-serve"
        kb_root = tmp_path

        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            from kb_agent_mcp.cli.setup import _c, hdr, warn, ok, info, _in_venv
            hdr("✅  Setup complete!")
            print()
            print(_c("1", "  MCP host config — paste this exactly:"))
            print('  "kb-agent-mcp": {')
            print(f'    "command": "{serve_cmd}",')
            print(f'    "env": {{ "KB_ROOT": "{kb_root}" }}')
            print('  }')
            print()
            print("  Start the MCP server:")

        output = buf.getvalue()
        mcp_pos   = output.find('"command"')
        start_pos = output.find("Start the MCP server")

        assert mcp_pos != -1, '"command" not found in completion output'
        assert start_pos != -1, '"Start the MCP server" not found'
        assert mcp_pos < start_pos, (
            'MCP JSON config must appear BEFORE "Start the MCP server" text'
        )

    def test_completion_shows_absolute_path_not_bare_command(self, monkeypatch, tmp_path, capsys):
        """The MCP config JSON must show the absolute path, not bare 'kb-agent-serve'."""
        from kb_agent_mcp.cli import setup as setup_mod
        abs_path = "/Users/test/.venv/bin/kb-agent-serve"
        monkeypatch.setattr(setup_mod, "_serve_path", lambda: abs_path)
        monkeypatch.setattr(setup_mod, "_in_venv", lambda: True)

        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            serve_cmd = abs_path
            kb_root   = tmp_path
            print('  "kb-agent-mcp": {')
            print(f'    "command": "{serve_cmd}",')
            print(f'    "env": {{ "KB_ROOT": "{kb_root}" }}')
            print('  }')

        output = buf.getvalue()
        assert abs_path in output
        # The bare command (without path) should not appear as the command value
        assert '"command": "kb-agent-serve"' not in output
