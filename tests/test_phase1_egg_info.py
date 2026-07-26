"""
tests/test_phase1_egg_info.py
─────────────────────────────
Phase 1.1 — Verify .egg-info and .dist-info folders are excluded from
domain discovery in BOTH the pip package path and the legacy scripts path.
"""
from __future__ import annotations

import pathlib
import pytest


# ── pip path: Config.is_ignored() ────────────────────────────────────────────

class TestIsIgnoredEggInfo:
    """cfg.is_ignored() must block packaging artifacts in every casing."""

    def setup_method(self):
        from kb_agent_mcp.config import cfg
        self.cfg = cfg

    def test_egg_info_exact(self):
        assert self.cfg.is_ignored("kb_agent_mcp.egg-info")

    def test_egg_info_other_package(self):
        assert self.cfg.is_ignored("knowledgebase_mcp.egg-info")

    def test_egg_info_uppercase(self):
        assert self.cfg.is_ignored("KB_AGENT_MCP.EGG-INFO")

    def test_egg_info_mixed_case(self):
        assert self.cfg.is_ignored("MyPackage.Egg-Info")

    def test_dist_info(self):
        assert self.cfg.is_ignored("requests-2.31.0.dist-info")

    def test_dist_info_uppercase(self):
        assert self.cfg.is_ignored("NUMPY-1.26.0.DIST-INFO")

    def test_real_domain_not_ignored(self):
        assert not self.cfg.is_ignored("ACE Docs")

    def test_real_domain_bizops(self):
        assert not self.cfg.is_ignored("BizOps")

    def test_real_domain_cp4i(self):
        assert not self.cfg.is_ignored("CP4I Docs")

    def test_dotfile_still_ignored(self):
        # Ensure pre-existing dotfile rule still works
        assert self.cfg.is_ignored(".hidden_folder")

    def test_git_still_ignored(self):
        assert self.cfg.is_ignored(".git")

    def test_agents_still_ignored(self):
        assert self.cfg.is_ignored("agents")


# ── pip path: discover_folders does not return egg-info ───────────────────────

def test_discover_folders_excludes_egg_info(tmp_path):
    """build_all_domain_agents must not register egg-info as a domain."""
    import os
    # Create a realistic KB_ROOT with one real domain and two packaging artifacts
    real_domain = tmp_path / "ACE Docs"
    real_domain.mkdir()
    (real_domain / "guide.pdf").write_bytes(b"%PDF fake")

    egg1 = tmp_path / "kb_agent_mcp.egg-info"
    egg1.mkdir()
    (egg1 / "PKG-INFO").write_text("Name: kb-agent-mcp\n")

    egg2 = tmp_path / "requests-2.31.0.dist-info"
    egg2.mkdir()
    (egg2 / "RECORD").write_text("")

    # Patch KB_ROOT and reload config
    import importlib
    import kb_agent_mcp.config as config_mod
    os.environ["KB_ROOT"] = str(tmp_path)
    importlib.reload(config_mod)

    from kb_agent_mcp.domain_agent import build_all_domain_agents
    import asyncio

    agents = asyncio.run(build_all_domain_agents())

    # Restore env
    del os.environ["KB_ROOT"]
    importlib.reload(config_mod)

    discovered = list(agents.keys())
    assert "kb_agent_mcp.egg-info" not in discovered, \
        f"egg-info leaked into domains: {discovered}"
    assert "requests-2.31.0.dist-info" not in discovered, \
        f"dist-info leaked into domains: {discovered}"
    # The real domain must still be present
    assert "ACE Docs" in discovered, \
        f"Expected 'ACE Docs' in discovered domains, got: {discovered}"


# ── legacy scripts path: discover_folders ─────────────────────────────────────

def test_scripts_discover_folders_excludes_egg_info(tmp_path):
    """scripts/generate.py discover_folders must also exclude egg-info folders."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from scripts.generate import discover_folders, get_blocklist

    # Set up KB_ROOT with a real domain and packaging artifacts
    real = tmp_path / "CP4I Docs"
    real.mkdir()
    (real / "architecture.md").write_text("# Architecture")

    egg = tmp_path / "my_package.egg-info"
    egg.mkdir()
    (egg / "PKG-INFO").write_text("Name: my-package\n")

    dist = tmp_path / "some-1.0.0.dist-info"
    dist.mkdir()
    (dist / "WHEEL").write_text("Wheel-Version: 1.0\n")

    blocklist = get_blocklist()
    found = discover_folders(tmp_path, blocklist)

    assert "my_package.egg-info" not in found, \
        f"egg-info leaked into scripts discover: {found}"
    assert "some-1.0.0.dist-info" not in found, \
        f"dist-info leaked into scripts discover: {found}"
    assert "CP4I Docs" in found, \
        f"Expected 'CP4I Docs' in discovered: {found}"


# ── SKILL.md does not contain egg-info domain names ───────────────────────────

def test_skill_md_has_no_egg_info_domains():
    """The checked-in agents/SKILL.md must not list egg-info as a domain.

    This catches the regression where a stale SKILL.md was generated before
    the fix and is still committed in the repo.
    """
    skill_path = pathlib.Path(__file__).parent.parent / "agents" / "SKILL.md"
    if not skill_path.exists():
        pytest.skip("agents/SKILL.md not present")

    content = skill_path.read_text(encoding="utf-8")
    assert ".egg-info" not in content, \
        "agents/SKILL.md still references .egg-info domains — re-run kb-agent-generate"
    assert ".dist-info" not in content, \
        "agents/SKILL.md still references .dist-info domains"
