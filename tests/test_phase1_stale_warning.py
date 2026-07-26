"""
tests/test_phase1_stale_warning.py
────────────────────────────────────
Phase 1.3 — Stale-index warning:
  - DomainAgent.stale_file_count() returns correct (on_disk, indexed) counts
  - _stale_warnings() applies the >5% threshold correctly across boundary cases
  - _stale_warnings() returns "" when nothing is stale
  - _stale_warnings() handles missing/erroring agents gracefully
  - Warning message format is correct and actionable
"""
from __future__ import annotations

import math
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

class _MockAgent:
    """Minimal stand-in for DomainAgent with a controlled stale_file_count."""

    def __init__(self, on_disk: int, indexed: int, error: bool = False):
        self._on_disk  = on_disk
        self._indexed  = indexed
        self._error    = error
        self.config    = type("cfg", (), {"description": "mock domain"})()

    def stale_file_count(self) -> tuple[int, int]:
        if self._error:
            return 0, 0
        return self._on_disk, self._indexed


def _warn(domain_names: list[str], on_disk: int, indexed: int, error: bool = False) -> str:
    from kb_agent_mcp.orchestrator import _stale_warnings
    agents = {n: _MockAgent(on_disk, indexed, error) for n in domain_names}
    return _stale_warnings(domain_names, agents)


# ── threshold boundary tests ──────────────────────────────────────────────────

class TestStaleThreshold:
    """Test every boundary of the max(1, floor(indexed * 0.05)) rule."""

    # ── small domains (indexed ≤ 20 → threshold = 1) ─────────────────────────

    def test_small_domain_zero_new_no_warn(self):
        assert _warn(["D"], on_disk=10, indexed=10) == ""

    def test_small_domain_exactly_threshold_no_warn(self):
        # 1 new file, threshold = max(1, floor(10*0.05)) = 1 — NOT > 1
        assert _warn(["D"], on_disk=11, indexed=10) == ""

    def test_small_domain_one_over_threshold_warns(self):
        # 2 new files > threshold(1) → warn
        result = _warn(["D"], on_disk=12, indexed=10)
        assert result != ""
        assert "2 new file" in result

    def test_single_indexed_file_zero_new(self):
        assert _warn(["D"], on_disk=1, indexed=1) == ""

    def test_single_indexed_file_one_new_no_warn(self):
        # threshold = max(1, floor(1*0.05)) = max(1,0) = 1; 1 new is NOT > 1
        assert _warn(["D"], on_disk=2, indexed=1) == ""

    def test_single_indexed_file_two_new_warns(self):
        result = _warn(["D"], on_disk=3, indexed=1)
        assert result != ""

    # ── medium domains (indexed = 100 → threshold = 5) ───────────────────────

    def test_medium_domain_four_new_no_warn(self):
        assert _warn(["D"], on_disk=104, indexed=100) == ""

    def test_medium_domain_exactly_five_no_warn(self):
        # 5 new is NOT > 5
        assert _warn(["D"], on_disk=105, indexed=100) == ""

    def test_medium_domain_six_new_warns(self):
        result = _warn(["D"], on_disk=106, indexed=100)
        assert result != ""
        assert "6 new file" in result

    # ── large domains (indexed = 200 → threshold = 10) ───────────────────────

    def test_large_domain_nine_new_no_warn(self):
        assert _warn(["D"], on_disk=209, indexed=200) == ""

    def test_large_domain_ten_new_no_warn(self):
        # 10 new is NOT > 10
        assert _warn(["D"], on_disk=210, indexed=200) == ""

    def test_large_domain_eleven_new_warns(self):
        result = _warn(["D"], on_disk=211, indexed=200)
        assert result != ""
        assert "11 new file" in result

    # ── no files indexed (cold start) ────────────────────────────────────────

    def test_zero_indexed_zero_on_disk_no_warn(self):
        assert _warn(["D"], on_disk=0, indexed=0) == ""

    def test_zero_indexed_one_on_disk_no_warn(self):
        # threshold = max(1, 0) = 1; 1 new is NOT > 1
        assert _warn(["D"], on_disk=1, indexed=0) == ""

    def test_zero_indexed_two_on_disk_warns(self):
        result = _warn(["D"], on_disk=2, indexed=0)
        assert result != ""


# ── warning message format ────────────────────────────────────────────────────

class TestStaleWarningFormat:

    def test_contains_domain_name(self):
        result = _warn(["BizOps"], on_disk=12, indexed=10)
        assert "BizOps" in result

    def test_contains_old_count(self):
        result = _warn(["BizOps"], on_disk=12, indexed=10)
        assert "10" in result

    def test_contains_new_count(self):
        result = _warn(["BizOps"], on_disk=12, indexed=10)
        assert "12" in result

    def test_contains_generate_command(self):
        result = _warn(["BizOps"], on_disk=12, indexed=10)
        assert "kb-agent-generate" in result

    def test_separator_prefix(self):
        result = _warn(["BizOps"], on_disk=12, indexed=10)
        # Starts with the --- separator so it appends cleanly to any answer
        assert result.startswith("\n\n---\n\n")

    def test_warning_emoji_present(self):
        result = _warn(["BizOps"], on_disk=12, indexed=10)
        assert "⚠" in result

    def test_multiple_domains_all_stale(self):
        from kb_agent_mcp.orchestrator import _stale_warnings
        agents = {
            "ACE Docs": _MockAgent(12, 10),
            "BizOps":   _MockAgent(22, 20),
        }
        result = _stale_warnings(["ACE Docs", "BizOps"], agents)
        assert "ACE Docs" in result
        assert "BizOps" in result

    def test_multiple_domains_only_one_stale(self):
        from kb_agent_mcp.orchestrator import _stale_warnings
        agents = {
            "ACE Docs": _MockAgent(10, 10),  # up to date
            "BizOps":   _MockAgent(22, 20),  # stale
        }
        result = _stale_warnings(["ACE Docs", "BizOps"], agents)
        assert "BizOps" in result
        assert "ACE Docs" not in result

    def test_no_stale_returns_empty_string(self):
        result = _warn(["Clean Domain"], on_disk=10, indexed=10)
        assert result == ""

    def test_empty_domain_list_returns_empty_string(self):
        from kb_agent_mcp.orchestrator import _stale_warnings
        assert _stale_warnings([], {}) == ""


# ── error resilience ──────────────────────────────────────────────────────────

class TestStaleWarningResilience:

    def test_agent_error_returns_empty_not_raises(self):
        """stale_file_count returning (0,0) on error must not trigger a warning."""
        result = _warn(["BrokenDomain"], on_disk=0, indexed=0, error=True)
        assert result == ""

    def test_missing_agent_key_skipped(self):
        from kb_agent_mcp.orchestrator import _stale_warnings
        # domain_names references a domain not in the agents dict
        result = _stale_warnings(["GhostDomain"], {})
        assert result == ""

    def test_partial_missing_agents(self):
        from kb_agent_mcp.orchestrator import _stale_warnings
        agents = {"RealDomain": _MockAgent(12, 10)}
        result = _stale_warnings(["GhostDomain", "RealDomain"], agents)
        # GhostDomain skipped, RealDomain warns (2 new > threshold 1)
        assert "RealDomain" in result
        assert "GhostDomain" not in result


# ── DomainAgent.stale_file_count() integration ───────────────────────────────

def _setup_stale_test(tmp_path, monkeypatch):
    """Shared setup for stale_file_count integration tests.

    Reloads config AND resets the vector_store ChromaDB client so it opens
    against the tmp_path rather than the real KB_ROOT.
    """
    import importlib
    import kb_agent_mcp.config as config_mod
    import kb_agent_mcp.vector_store as vs_mod

    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    importlib.reload(config_mod)
    # Reset the ChromaDB client singleton so it re-opens at the new path
    vs_mod._client = None


def test_stale_file_count_returns_tuple(tmp_path, monkeypatch):
    """DomainAgent.stale_file_count() must return a 2-tuple of ints."""
    domain = tmp_path / "TestDomain"
    domain.mkdir()
    (domain / "file1.txt").write_text("hello")
    (domain / "file2.md").write_text("# Doc")
    (domain / "domain_config.yaml").write_text(
        "folder_name: TestDomain\nagent_name: TestDomain Agent\n"
        "description: Test\nkeywords: [test]\ntop_n: 4\nmax_chars: 4000\n"
        "system_prompt: You are an agent.\n"
    )

    _setup_stale_test(tmp_path, monkeypatch)

    from kb_agent_mcp.domain_agent import build_domain_agent
    agent = build_domain_agent("TestDomain")

    on_disk, indexed = agent.stale_file_count()

    assert isinstance(on_disk, int), f"on_disk must be int, got {type(on_disk)}"
    assert isinstance(indexed, int), f"indexed must be int, got {type(indexed)}"
    # 2 indexable files on disk (.txt + .md); domain_config.yaml is .yaml → not indexed
    assert on_disk == 2, f"Expected 2 files on disk, got {on_disk}"
    # ChromaDB collection was never built → 0 indexed
    assert indexed == 0, f"Expected 0 indexed (never built), got {indexed}"


def test_stale_file_count_ignores_non_indexable_files(tmp_path, monkeypatch):
    """Non-indexable files (images, pyc, etc.) must not inflate the on-disk count."""
    domain = tmp_path / "TestDomain"
    domain.mkdir()
    (domain / "file.txt").write_text("real doc")
    (domain / "image.png").write_bytes(b"\x89PNG")     # not indexable
    (domain / "script.py").write_text("pass")           # not indexable
    (domain / "domain_config.yaml").write_text(
        "folder_name: TestDomain\nagent_name: TestDomain Agent\n"
        "description: Test\nkeywords: [test]\ntop_n: 4\nmax_chars: 4000\n"
        "system_prompt: You are an agent.\n"
    )

    _setup_stale_test(tmp_path, monkeypatch)

    from kb_agent_mcp.domain_agent import build_domain_agent
    agent = build_domain_agent("TestDomain")
    on_disk, _ = agent.stale_file_count()

    assert on_disk == 1, \
        f"Only .txt should count as indexable, got on_disk={on_disk}"
