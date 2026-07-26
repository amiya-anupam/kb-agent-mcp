"""
tests/test_doctor_fix.py
─────────────────────────
Tests for the --fix flag added to kb-agent-doctor.

Covers:
  - --fix flag accepted by argparse (via run_doctor)
  - CheckResult NamedTuple structure
  - _run_fixes() calls fix_fn and reports results
  - When KB_ROOT dir is missing and --fix runs, directory is created
  - When domain_config.yaml is missing, --fix runs generate for that domain
  - When ChromaDB index is empty, --fix runs generate for that domain
  - When fix_fn returns True, final re-check passes
  - When no fix_fn available, _unfixable is called
  - Embedding model fix_fn calls _ensure_embedding_model
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import types

import pytest


# ── CheckResult structure ──────────────────────────────────────────────────────

class TestCheckResult:

    def test_namedtuple_fields(self):
        from kb_agent_mcp.cli.doctor import CheckResult
        r = CheckResult(label="test", passed=True, fix_fn=None)
        assert r.label == "test"
        assert r.passed is True
        assert r.fix_fn is None

    def test_failed_with_fix(self):
        from kb_agent_mcp.cli.doctor import CheckResult
        fn = lambda: True
        r = CheckResult("mycheck", False, fn)
        assert r.passed is False
        assert r.fix_fn is fn


# ── _run_fixes() ───────────────────────────────────────────────────────────────

class TestRunFixes:

    def test_calls_fix_fn(self, capsys):
        from kb_agent_mcp.cli.doctor import CheckResult, _run_fixes
        called = []
        def my_fix():
            called.append(True)
            return True

        results = [CheckResult("check1", False, my_fix)]
        unfixed = _run_fixes(results)
        assert called == [True]
        assert unfixed == []

    def test_no_fix_fn_goes_to_unfixed(self, capsys):
        from kb_agent_mcp.cli.doctor import CheckResult, _run_fixes
        results = [CheckResult("check1", False, None)]
        unfixed = _run_fixes(results)
        assert "check1" in unfixed

    def test_fix_fn_returning_false_goes_to_unfixed(self, capsys):
        from kb_agent_mcp.cli.doctor import CheckResult, _run_fixes
        results = [CheckResult("check1", False, lambda: False)]
        unfixed = _run_fixes(results)
        assert "check1" in unfixed

    def test_multiple_fixes(self, capsys):
        from kb_agent_mcp.cli.doctor import CheckResult, _run_fixes
        results = [
            CheckResult("a", False, lambda: True),
            CheckResult("b", False, None),
            CheckResult("c", False, lambda: True),
        ]
        unfixed = _run_fixes(results)
        assert "b" in unfixed
        assert "a" not in unfixed
        assert "c" not in unfixed


# ── _check_kb_root() fix_fn ───────────────────────────────────────────────────

class TestKbRootFix:

    def test_fix_creates_directory(self, tmp_path, monkeypatch):
        from kb_agent_mcp.cli.doctor import _check_kb_root

        missing = tmp_path / "new_kb"
        assert not missing.exists()

        import types
        fake_cfg = types.SimpleNamespace(
            kb_root_path=missing,
            kb_root_is_explicit=True,
        )

        result, root = _check_kb_root(fake_cfg)
        assert result.passed is False
        assert result.fix_fn is not None

        # Call the fix
        ok = result.fix_fn()
        assert ok is True
        assert missing.exists()

    def test_no_fix_when_kb_root_not_set(self, tmp_path, monkeypatch):
        from kb_agent_mcp.cli.doctor import _check_kb_root

        import types
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            kb_root_is_explicit=False,
        )
        result, root = _check_kb_root(fake_cfg)
        assert result.passed is False
        assert result.fix_fn is None  # can't automate env var changes


# ── _check_domain_configs() fix_fn ────────────────────────────────────────────

class TestDomainConfigFix:

    def test_missing_yaml_has_fix_fn(self, tmp_path):
        from kb_agent_mcp.cli.doctor import _check_domain_configs

        domain_dir = tmp_path / "TestDomain"
        domain_dir.mkdir()
        # No domain_config.yaml

        results = _check_domain_configs(tmp_path, ["TestDomain"])
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].fix_fn is not None

    def test_present_yaml_passes(self, tmp_path):
        from kb_agent_mcp.cli.doctor import _check_domain_configs

        domain_dir = tmp_path / "TestDomain"
        domain_dir.mkdir()
        (domain_dir / "domain_config.yaml").write_text("folder_name: TestDomain\n")

        results = _check_domain_configs(tmp_path, ["TestDomain"])
        assert results[0].passed is True
        assert results[0].fix_fn is None

    def test_fix_fn_calls_generate(self, tmp_path, monkeypatch):
        from kb_agent_mcp.cli.doctor import _check_domain_configs
        import subprocess as sp

        domain_dir = tmp_path / "TestDomain"
        domain_dir.mkdir()

        calls = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0)

        monkeypatch.setattr(sp, "run", fake_run)

        results = _check_domain_configs(tmp_path, ["TestDomain"])
        assert results[0].fix_fn is not None
        ok = results[0].fix_fn()
        assert ok is True
        # Should have called generate with --domain TestDomain
        assert any("TestDomain" in str(c) for c in calls)


# ── _check_chroma_collections() fix_fn ───────────────────────────────────────

class TestChromaFixFn:

    def test_empty_index_has_fix_fn(self, monkeypatch):
        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client", lambda: None)
        col = MagicMock()
        col.count.return_value = 0
        col.get.return_value = {"metadatas": [{}]}
        monkeypatch.setattr(vs_mod, "get_or_create_collection", lambda _: col)

        from kb_agent_mcp.cli.doctor import _check_chroma_collections
        results = _check_chroma_collections(["TestDomain"])
        empty_results = [r for r in results if not r.passed]
        assert len(empty_results) > 0
        assert empty_results[0].fix_fn is not None

    def test_version_mismatch_has_fix_fn(self, monkeypatch):
        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client",
                            lambda: (_ for _ in ()).throw(RuntimeError("version mismatch")))

        from kb_agent_mcp.cli.doctor import _check_chroma_collections
        results = _check_chroma_collections(["TestDomain"])
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].fix_fn is not None


# ── _check_embedding_model() fix_fn ──────────────────────────────────────────

class TestEmbeddingFix:

    def test_not_cached_returns_fix_fn(self, monkeypatch):
        import kb_agent_mcp.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "_st_model_is_cached", lambda: False)
        monkeypatch.setattr(emb_mod, "_ST_MODEL_NAME", "all-MiniLM-L6-v2")

        from kb_agent_mcp.cli.doctor import _check_embedding_model
        result = _check_embedding_model()
        assert result.passed is False
        assert result.fix_fn is not None

    def test_cached_returns_pass(self, monkeypatch):
        import kb_agent_mcp.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "_st_model_is_cached", lambda: True)
        monkeypatch.setattr(emb_mod, "_ST_MODEL_NAME", "all-MiniLM-L6-v2")

        from kb_agent_mcp.cli.doctor import _check_embedding_model
        result = _check_embedding_model()
        assert result.passed is True

    def test_fix_fn_calls_ensure_model(self, monkeypatch):
        import kb_agent_mcp.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "_st_model_is_cached", lambda: False)
        monkeypatch.setattr(emb_mod, "_ST_MODEL_NAME", "all-MiniLM-L6-v2")

        called = []
        monkeypatch.setattr(emb_mod, "_ensure_embedding_model",
                            lambda: called.append(True))

        from kb_agent_mcp.cli.doctor import _check_embedding_model
        result = _check_embedding_model()
        ok = result.fix_fn()
        assert ok is True
        assert called == [True]


# ── Bob skill fix_fn ──────────────────────────────────────────────────────────

class TestBobSkillFix:

    def test_missing_skill_has_fix_fn(self, tmp_path, monkeypatch):
        # Point home to tmp so skill path doesn't exist
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

        from kb_agent_mcp.cli.doctor import _check_bob_skill
        result = _check_bob_skill()
        assert result.passed is False
        assert result.fix_fn is not None

    def test_fix_fn_calls_generate(self, tmp_path, monkeypatch):
        import subprocess as sp
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

        calls = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0)
        monkeypatch.setattr(sp, "run", fake_run)

        from kb_agent_mcp.cli.doctor import _check_bob_skill
        result = _check_bob_skill()
        ok = result.fix_fn()
        assert ok is True
        assert any("generate" in str(c) for c in calls)


# ── run_doctor() integration ──────────────────────────────────────────────────

class TestRunDoctorFix:

    def test_all_pass_returns_0(self, monkeypatch):
        """When all checks pass, run_doctor returns 0 without fix."""
        from kb_agent_mcp.cli import doctor as doc_mod

        # Patch every check to return a passing result
        from kb_agent_mcp.cli.doctor import CheckResult
        passing = CheckResult("x", True, None)

        monkeypatch.setattr(doc_mod, "_check_python", lambda: passing)
        monkeypatch.setattr(doc_mod, "_check_kb_root",
                            lambda cfg: (passing, Path("/tmp")))
        monkeypatch.setattr(doc_mod, "_check_domain_folders",
                            lambda root, cfg: (passing, []))
        monkeypatch.setattr(doc_mod, "_check_embedding_model", lambda: passing)
        monkeypatch.setattr(doc_mod, "_check_llm", lambda cfg: passing)
        monkeypatch.setattr(doc_mod, "_check_serve_path", lambda: passing)
        monkeypatch.setattr(doc_mod, "_check_bob_skill", lambda: passing)

        rc = doc_mod.run_doctor(fix=False)
        assert rc == 0

    def test_fix_false_returns_1_on_failure(self, monkeypatch, tmp_path):
        """Without --fix, failures return exit code 1."""
        from kb_agent_mcp.cli import doctor as doc_mod
        from kb_agent_mcp.cli.doctor import CheckResult

        passing = CheckResult("x", True, None)
        failing = CheckResult("y", False, None)

        monkeypatch.setattr(doc_mod, "_check_python", lambda: failing)
        monkeypatch.setattr(doc_mod, "_check_kb_root",
                            lambda cfg: (passing, None))
        monkeypatch.setattr(doc_mod, "_check_embedding_model", lambda: passing)
        monkeypatch.setattr(doc_mod, "_check_llm", lambda cfg: passing)
        monkeypatch.setattr(doc_mod, "_check_serve_path", lambda: passing)
        monkeypatch.setattr(doc_mod, "_check_bob_skill", lambda: passing)

        rc = doc_mod.run_doctor(fix=False)
        assert rc == 1

    def test_fix_true_attempts_fix_fn(self, monkeypatch):
        """With --fix, fix_fn is called for failing checks."""
        from kb_agent_mcp.cli import doctor as doc_mod
        from kb_agent_mcp.cli.doctor import CheckResult

        fix_called = []
        def my_fix():
            fix_called.append(True)
            return True

        passing = CheckResult("x", True, None)
        failing = CheckResult("y", False, my_fix)

        # First pass: one failure. Second pass (after fix): all pass.
        pass_count = [0]
        def mock_python():
            pass_count[0] += 1
            return failing if pass_count[0] == 1 else passing

        monkeypatch.setattr(doc_mod, "_check_python", mock_python)
        monkeypatch.setattr(doc_mod, "_check_kb_root",
                            lambda cfg: (passing, None))
        monkeypatch.setattr(doc_mod, "_check_embedding_model", lambda: passing)
        monkeypatch.setattr(doc_mod, "_check_llm", lambda cfg: passing)
        monkeypatch.setattr(doc_mod, "_check_serve_path", lambda: passing)
        monkeypatch.setattr(doc_mod, "_check_bob_skill", lambda: passing)

        rc = doc_mod.run_doctor(fix=True)
        assert fix_called == [True]
        assert rc == 0
