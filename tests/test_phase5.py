"""
tests/test_phase5.py
────────────────────
Phase 5 tests covering Docs & Doctor:
  - Risk 3:  _serve_absolute_path() returns absolute path from venv bin
  - Risk 5:  _check_serve_path() warns when not in a venv
  - Risk 12: _check_chroma_collections() detects RuntimeError (version mismatch)
  - Risk 11: _check_chroma_collections() warns when indexed_at is > 7 days old
  - Docs:    .env.example contains KB_STALE_CHECK_TTL_SECONDS,
             KB_BUDGET_PASSTHROUGH_THRESHOLD, KB_LLM_PROVIDER_GENERATE
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Risk 3 — _serve_absolute_path() / _check_serve_path()
# ─────────────────────────────────────────────────────────────────────────────

class TestServeAbsolutePath:

    def test_in_venv_returns_path(self, tmp_path, monkeypatch):
        """When the venv bin contains kb-agent-serve, its absolute path is returned."""
        # Create a fake venv bin directory with the script
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        serve = bin_dir / "kb-agent-serve"
        serve.touch()
        monkeypatch.setattr(sys, "prefix", str(tmp_path))

        from kb_agent_mcp.cli.doctor import _serve_absolute_path
        result = _serve_absolute_path()
        assert result == str(serve)

    def test_falls_back_to_which(self, tmp_path, monkeypatch):
        """When venv bin not found, falls back to shutil.which."""
        monkeypatch.setattr(sys, "prefix", str(tmp_path))  # no bin/kb-agent-serve here
        import shutil
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/kb-agent-serve")

        from kb_agent_mcp.cli.doctor import _serve_absolute_path
        result = _serve_absolute_path()
        assert result == "/usr/local/bin/kb-agent-serve"

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        import shutil
        monkeypatch.setattr(shutil, "which", lambda _: None)

        from kb_agent_mcp.cli.doctor import _serve_absolute_path
        assert _serve_absolute_path() is None

    def test_check_serve_path_passes_in_venv(self, tmp_path, monkeypatch, capsys):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "kb-agent-serve").touch()
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        monkeypatch.setattr(sys, "base_prefix", "/other")  # simulate being in venv

        from kb_agent_mcp.cli.doctor import _check_serve_path
        result = _check_serve_path()
        assert result is True
        out = capsys.readouterr().out
        assert "kb-agent-serve" in out
        assert "✓" in out

    def test_check_serve_path_warns_when_not_in_venv(self, tmp_path, monkeypatch, capsys):
        """When not in a venv, _check_serve_path warns even if binary found."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "kb-agent-serve").touch()
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        monkeypatch.setattr(sys, "base_prefix", str(tmp_path))  # same → not in venv

        from kb_agent_mcp.cli.doctor import _check_serve_path
        result = _check_serve_path()
        assert result is True
        out = capsys.readouterr().out
        assert "venv" in out.lower()

    def test_check_serve_path_fails_when_not_found(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        import shutil
        monkeypatch.setattr(shutil, "which", lambda _: None)

        from kb_agent_mcp.cli.doctor import _check_serve_path
        result = _check_serve_path()
        assert result is False
        assert "✗" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────────
# Risk 5 — _in_venv()
# ─────────────────────────────────────────────────────────────────────────────

class TestInVenv:

    def test_in_venv_when_prefix_differs(self, monkeypatch):
        monkeypatch.setattr(sys, "prefix", "/venv/path")
        monkeypatch.setattr(sys, "base_prefix", "/usr/local")
        from kb_agent_mcp.cli.doctor import _in_venv
        assert _in_venv() is True

    def test_not_in_venv_when_prefix_same(self, monkeypatch):
        monkeypatch.setattr(sys, "prefix", "/usr/local")
        monkeypatch.setattr(sys, "base_prefix", "/usr/local")
        from kb_agent_mcp.cli.doctor import _in_venv
        assert _in_venv() is False


# ─────────────────────────────────────────────────────────────────────────────
# Risk 12 — ChromaDB version mismatch detection in _check_chroma_collections()
# ─────────────────────────────────────────────────────────────────────────────

class TestChromaVersionMismatch:

    def test_runtime_error_fails_with_fix_hint(self, monkeypatch, capsys):
        """_check_chroma_collections() must fail hard when _get_client() raises RuntimeError."""
        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client",
                            lambda: (_ for _ in ()).throw(RuntimeError("version mismatch")))

        from kb_agent_mcp.cli.doctor import _check_chroma_collections
        _check_chroma_collections(["TestDomain"])

        out = capsys.readouterr().out
        assert "✗" in out
        assert "version" in out.lower() or "mismatch" in out.lower() or "rebuild" in out.lower()

    def test_no_error_proceeds_to_collection_check(self, monkeypatch, capsys):
        """When _get_client() succeeds, we proceed to per-collection checks."""
        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client", lambda: None)

        fake_col = MagicMock()
        fake_col.count.return_value = 5
        fake_col.get.return_value = {"metadatas": []}  # no indexed_at
        monkeypatch.setattr(vs_mod, "get_or_create_collection", lambda name: fake_col)

        from kb_agent_mcp.cli.doctor import _check_chroma_collections
        _check_chroma_collections(["TestDomain"])

        out = capsys.readouterr().out
        assert "✓" in out
        assert "TestDomain" in out


# ─────────────────────────────────────────────────────────────────────────────
# Risk 11 — Stale-index detection via indexed_at timestamp
# ─────────────────────────────────────────────────────────────────────────────

class TestChromaStaleIndexDoctor:

    def _fake_col(self, count: int, age_days: int | None):
        import datetime
        fake_col = MagicMock()
        fake_col.count.return_value = count
        if age_days is not None:
            ts = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(days=age_days)).isoformat()
            fake_col.get.return_value = {"metadatas": [{"indexed_at": ts}]}
        else:
            fake_col.get.return_value = {"metadatas": [{}]}
        return fake_col

    def test_fresh_index_passes(self, monkeypatch, capsys):
        """When indexed_at is < 7 days old, check must pass with ✓."""
        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client", lambda: None)
        monkeypatch.setattr(vs_mod, "get_or_create_collection",
                            lambda name: self._fake_col(10, age_days=2))

        from kb_agent_mcp.cli.doctor import _check_chroma_collections
        _check_chroma_collections(["TestDomain"])
        out = capsys.readouterr().out
        assert "✓" in out
        assert "⚠" not in out

    def test_stale_index_warns(self, monkeypatch, capsys):
        """When indexed_at is > 7 days old, check must warn with ⚠."""
        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client", lambda: None)
        monkeypatch.setattr(vs_mod, "get_or_create_collection",
                            lambda name: self._fake_col(10, age_days=10))

        from kb_agent_mcp.cli.doctor import _check_chroma_collections
        _check_chroma_collections(["TestDomain"])
        out = capsys.readouterr().out
        assert "⚠" in out
        assert "10" in out  # age in days shown

    def test_no_indexed_at_falls_back_to_count(self, monkeypatch, capsys):
        """When indexed_at is absent, fall back to count-based pass/warn."""
        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client", lambda: None)
        monkeypatch.setattr(vs_mod, "get_or_create_collection",
                            lambda name: self._fake_col(3, age_days=None))

        from kb_agent_mcp.cli.doctor import _check_chroma_collections
        _check_chroma_collections(["TestDomain"])
        out = capsys.readouterr().out
        assert "✓" in out


# ─────────────────────────────────────────────────────────────────────────────
# Docs — .env.example contains all new config vars
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvExample:

    def _env_text(self) -> str:
        p = Path(__file__).parent.parent / ".env.example"
        return p.read_text(encoding="utf-8")

    def test_kb_stale_check_ttl_present(self):
        assert "KB_STALE_CHECK_TTL_SECONDS" in self._env_text()

    def test_kb_budget_passthrough_threshold_present(self):
        assert "KB_BUDGET_PASSTHROUGH_THRESHOLD" in self._env_text()

    def test_kb_llm_provider_generate_present(self):
        assert "KB_LLM_PROVIDER_GENERATE" in self._env_text()

    def test_new_vars_have_comments(self):
        text = self._env_text()
        # Each new var must have at least a comment line (# prefix) explaining it
        for var in ("KB_STALE_CHECK_TTL_SECONDS", "KB_BUDGET_PASSTHROUGH_THRESHOLD",
                    "KB_LLM_PROVIDER_GENERATE"):
            idx = text.index(var)
            # The line containing the var should be commented out or have a comment above
            surrounding = text[max(0, idx - 200): idx + 100]
            assert "#" in surrounding, f"No comment found near {var}"
