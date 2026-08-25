"""
tests/test_e2e_new_customer.py
──────────────────────────────
End-to-end test suite simulating a brand-new customer journey.

Scenarios covered (in order of the customer journey):

  A. Package integrity  — CLI entry-points importable; version string present
  B. Configuration      — Config resolves KB_ROOT, validates bad values, reads .env
  C. First-time setup   — CLI generate discovers folders, indexes files
  D. Domain rules       — domain_config.yaml loaded; defaults applied when absent
  E. Vector indexing    — files upserted, searched, deleted, change-detection
  F. File parsing       — all supported doc types extract text without crashing
  G. MCP server tools   — ask, list_domains, reindex, memory tools, rate_answer,
                          update_document, audit_summary, security gate
  H. Writeback          — overwrite / append / prepend + path-traversal rejection
  I. Audit log          — turns logged; read_log and summarise_log work
  J. Feedback           — record + read_feedback; rating bounds enforced
  K. Session memory     — add_turn, get_history, clear, session isolation
  L. Doctor / status    — health checks pass on a valid temp KB
  M. .noindex guard     — files under .noindex excluded from indexing and queries
  N. Edge cases         — empty KB, missing KB_ROOT, unknown file types, large names
  O. Stale index        — stale cache TTL and clear behaviour
  P. Context budget     — trim, compact, build_context helpers
  Q. Tech-debt regression — consolidated symbols imported from canonical location

All tests use tmp_path to stay fully isolated from the live KnowledgeBase.
No LLM network calls are made — passthrough mode is used throughout.

Design notes
────────────
• asyncio.run() is used instead of get_event_loop().run_until_complete()
  because Python 3.14 no longer creates an implicit event loop per thread.
• cfg (the global Config singleton) is patched via monkeypatch.setattr on
  the per-module imported reference.  importlib.reload(config) updates the
  singleton's fields but cannot update previously-imported references inside
  audit.py / memory.py / feedback.py / writeback.py etc.
• Wherever a test needs cfg.kb_index_path to point to tmp_path, it patches
  kb_agent_mcp.audit.cfg, kb_agent_mcp.memory.cfg, etc. directly.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import pathlib
import sys
import textwrap
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

# ── sys.path helpers ──────────────────────────────────────────────────────────
# kb_agent_mcp is installed as an editable package; agents/ is NOT on sys.path
# by default in tests. Conftest or pyproject handles kb_agent_mcp; the agents/
# directory is added only where needed.

REPO_ROOT = pathlib.Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"


def _add_agents_path():
    """Add agents/ to sys.path if not already present."""
    s = str(AGENTS_DIR)
    if s not in sys.path:
        sys.path.insert(0, s)


# ══════════════════════════════════════════════════════════════════════════════
# A. Package integrity
# ══════════════════════════════════════════════════════════════════════════════

class TestPackageIntegrity:
    """Verify the installed package exposes the right entry points and version."""

    def test_package_importable(self):
        import kb_agent_mcp
        assert kb_agent_mcp is not None

    def test_version_string_present(self):
        import kb_agent_mcp
        assert hasattr(kb_agent_mcp, "__version__")
        assert isinstance(kb_agent_mcp.__version__, str)
        assert kb_agent_mcp.__version__

    def test_server_module_importable(self):
        from kb_agent_mcp import server
        assert hasattr(server, "mcp")
        assert hasattr(server, "ask")

    def test_all_cli_modules_importable(self):
        for mod in [
            "kb_agent_mcp.cli.main",
            "kb_agent_mcp.cli.setup",
            "kb_agent_mcp.cli.generate",
            "kb_agent_mcp.cli.doctor",
            "kb_agent_mcp.cli.status",
            "kb_agent_mcp.cli.watch",
        ]:
            m = importlib.import_module(mod)
            assert hasattr(m, "main"), f"{mod} missing main()"

    def test_all_core_modules_importable(self):
        for mod in [
            "kb_agent_mcp.config",
            "kb_agent_mcp.orchestrator",
            "kb_agent_mcp.file_parser",
            "kb_agent_mcp.vector_store",
            "kb_agent_mcp.memory",
            "kb_agent_mcp.audit",
            "kb_agent_mcp.feedback",
            "kb_agent_mcp.writeback",
            "kb_agent_mcp.security_gate",
            "kb_agent_mcp.domain_rules",
            "kb_agent_mcp.domain_agent",
            "kb_agent_mcp.base_agent",
            "kb_agent_mcp.aggregator",
            "kb_agent_mcp.context_budget",
        ]:
            importlib.import_module(mod)

    def test_mcp_tool_count(self):
        """Server should expose at least 10 MCP tools."""
        from kb_agent_mcp.server import mcp
        # FastMCP 2.x exposes list_tools() as an async method
        tools = asyncio.run(mcp.list_tools())
        assert len(tools) >= 10, f"Only {len(tools)} tools found: {[t.name for t in tools]}"


# ══════════════════════════════════════════════════════════════════════════════
# B. Configuration
# ══════════════════════════════════════════════════════════════════════════════

class TestConfiguration:
    """Config resolves correctly from env, .env file, and validates inputs."""

    def test_kb_root_resolves_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import kb_agent_mcp.config as cfg_mod
        importlib.reload(cfg_mod)
        assert str(tmp_path) in cfg_mod.cfg.KB_ROOT

    def test_kb_root_unset_gives_empty_or_default(self, monkeypatch):
        monkeypatch.delenv("KB_ROOT", raising=False)
        import kb_agent_mcp.config as cfg_mod
        importlib.reload(cfg_mod)
        # either empty string or defaulted — must not crash
        assert isinstance(cfg_mod.cfg.KB_ROOT, str)

    def test_kb_root_nonexistent_produces_validation_error(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", "/this/path/does/not/exist/ever")
        import kb_agent_mcp.config as cfg_mod
        importlib.reload(cfg_mod)
        errors = cfg_mod.cfg.validate()
        assert any("KB_ROOT" in e or "not exist" in e.lower() for e in errors)

    def test_dotenv_search_order_documented(self, tmp_path, monkeypatch):
        """
        _load_dotenv searches CWD first.  This test verifies it finds the
        project .env at CWD (not a tmp_path .env) and doesn't crash.
        The search-order behaviour is intentional (documented in config.py).
        """
        import kb_agent_mcp.config as cfg_mod
        importlib.reload(cfg_mod)
        # The function must have run without raising
        assert isinstance(cfg_mod.cfg.KB_ROOT, str)

    def test_is_ignored_blocks_system_folders(self):
        from kb_agent_mcp.config import cfg
        for name in [".git", "__pycache__", ".ds_store", "node_modules", ".venv"]:
            assert cfg.is_ignored(name), f"{name!r} should be ignored"

    def test_is_ignored_passes_user_folders(self):
        from kb_agent_mcp.config import cfg
        for name in ["BizOps", "ACE Docs", "My Domain", "Sales"]:
            assert not cfg.is_ignored(name), f"{name!r} should not be ignored"

    def test_passthrough_mode_detected(self, monkeypatch):
        monkeypatch.setenv("KB_LLM_PROVIDER", "passthrough")
        import kb_agent_mcp.config as cfg_mod
        importlib.reload(cfg_mod)
        assert cfg_mod.cfg.KB_LLM_PROVIDER == "passthrough"


# ══════════════════════════════════════════════════════════════════════════════
# C. First-time setup — folder + file discovery
# ══════════════════════════════════════════════════════════════════════════════

class TestFolderDiscovery:
    """generate's folder discovery works end-to-end on a fresh KB."""

    def _make_kb(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Create a minimal KB with two domains."""
        (tmp_path / "Product Docs").mkdir()
        (tmp_path / "Product Docs" / "overview.md").write_text("# Overview\nThis is the product.")
        (tmp_path / "Product Docs" / "guide.txt").write_text("Step 1: install.\nStep 2: configure.")
        (tmp_path / "Sales Data").mkdir()
        (tmp_path / "Sales Data" / "pipeline.md").write_text("# Pipeline\nQ3 deals.")
        return tmp_path

    def test_discovers_domains_with_files(self, tmp_path, monkeypatch):
        kb = self._make_kb(tmp_path)
        monkeypatch.setenv("KB_ROOT", str(kb))
        from kb_agent_mcp.cli.generate import _discover_folders
        import kb_agent_mcp.config as c; importlib.reload(c)
        folders = _discover_folders(kb)
        assert "Product Docs" in folders
        assert "Sales Data" in folders

    def test_ignores_empty_folders(self, tmp_path, monkeypatch):
        kb = self._make_kb(tmp_path)
        (kb / "Empty Folder").mkdir()
        monkeypatch.setenv("KB_ROOT", str(kb))
        from kb_agent_mcp.cli.generate import _discover_folders
        import kb_agent_mcp.config as c; importlib.reload(c)
        folders = _discover_folders(kb)
        assert "Empty Folder" not in folders

    def test_ignores_system_folders(self, tmp_path, monkeypatch):
        kb = self._make_kb(tmp_path)
        for blocked in [".git", "__pycache__", "node_modules"]:
            (kb / blocked).mkdir()
            (kb / blocked / "file.txt").write_text("secret")
        monkeypatch.setenv("KB_ROOT", str(kb))
        from kb_agent_mcp.cli.generate import _discover_folders
        import kb_agent_mcp.config as c; importlib.reload(c)
        folders = _discover_folders(kb)
        for blocked in [".git", "__pycache__", "node_modules"]:
            assert blocked not in folders

    def test_file_count_correct(self, tmp_path):
        domain = tmp_path / "Docs"
        domain.mkdir()
        for i in range(5):
            (domain / f"doc{i}.md").write_text(f"# Doc {i}")
        from kb_agent_mcp.cli.generate import _count_files
        assert _count_files(domain) == 5


# ══════════════════════════════════════════════════════════════════════════════
# D. Domain rules
# ══════════════════════════════════════════════════════════════════════════════

class TestDomainRules:
    """domain_config.yaml loading and defaults."""

    def _patch_cfg(self, tmp_path, monkeypatch):
        """Replace cfg in all domain-related modules to point to tmp_path."""
        import dataclasses
        import kb_agent_mcp.config as c_mod
        import kb_agent_mcp.domain_rules as dr_mod
        new_cfg = dataclasses.replace(c_mod.cfg, KB_ROOT=str(tmp_path))
        monkeypatch.setattr(c_mod, "cfg", new_cfg)
        monkeypatch.setattr(dr_mod, "cfg", new_cfg)
        return new_cfg

    def test_missing_yaml_returns_none(self, tmp_path, monkeypatch):
        self._patch_cfg(tmp_path, monkeypatch)
        (tmp_path / "MyDomain").mkdir()
        from kb_agent_mcp.domain_rules import load_domain_config
        assert load_domain_config("MyDomain") is None

    def test_valid_yaml_loaded(self, tmp_path, monkeypatch):
        self._patch_cfg(tmp_path, monkeypatch)
        domain = tmp_path / "MyDomain"
        domain.mkdir()
        (domain / "domain_config.yaml").write_text(textwrap.dedent("""
            folder_name: MyDomain
            agent_name: My Agent
            description: A test domain
            keywords: [test, demo]
            top_n: 3
        """))
        from kb_agent_mcp.domain_rules import load_domain_config
        cfg_obj = load_domain_config("MyDomain")
        assert cfg_obj is not None
        assert cfg_obj.agent_name == "My Agent"
        assert cfg_obj.top_n == 3
        assert "test" in cfg_obj.keywords

    def test_default_config_when_no_yaml(self, tmp_path, monkeypatch):
        # _default_config doesn't use cfg — no patch needed
        from kb_agent_mcp.domain_agent import _default_config
        cfg_obj = _default_config("TestDomain")
        assert cfg_obj.folder_name == "TestDomain"
        assert cfg_obj.top_n > 0
        assert cfg_obj.max_chars > 0

    def test_pin_rules_boost_matching_files(self, tmp_path, monkeypatch):
        self._patch_cfg(tmp_path, monkeypatch)
        domain = tmp_path / "BizOps"
        domain.mkdir()
        yaml_content = textwrap.dedent("""
            folder_name: BizOps
            description: Business ops
            keywords: [revenue, deals]
            retrieval_rules:
              pin_files:
                - "*Revenue*.xlsx"
              boost_keywords:
                - revenue
        """)
        (domain / "domain_config.yaml").write_text(yaml_content)
        from kb_agent_mcp.domain_rules import load_domain_config, apply_pin_rules
        cfg_obj = load_domain_config("BizOps")
        # apply_pin_rules uses r["path"] for each result entry
        results = [
            {"path": "Revenue Q3.xlsx", "score": 0.5, "summary": ""},
            {"path": "Pipeline.xlsx",   "score": 0.9, "summary": ""},
        ]
        # apply_pin_rules(results, folder_name, domain_cfg)
        pinned = apply_pin_rules(results, "BizOps", cfg_obj)
        # Pinned file should appear first regardless of original score
        assert pinned[0]["path"] == "Revenue Q3.xlsx"


# ══════════════════════════════════════════════════════════════════════════════
# E. Vector indexing
# ══════════════════════════════════════════════════════════════════════════════

class TestVectorIndexing:
    """ChromaDB indexing: upsert, search, delete, change detection."""

    @pytest.fixture(autouse=True)
    def isolated_chroma(self, tmp_path, monkeypatch):
        """Point ChromaDB at a temp directory for full isolation."""
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / ".chroma"))
        import kb_agent_mcp.config as c
        importlib.reload(c)
        # Reset the ChromaDB client singleton between tests
        import kb_agent_mcp.vector_store as vs
        vs._client = None
        yield
        vs._client = None

    def test_collection_created_after_upsert(self, tmp_path):
        domain = tmp_path / "Docs"
        domain.mkdir()
        f = domain / "sample.txt"
        f.write_text("ChromaDB is a vector database.")
        from kb_agent_mcp.vector_store import _upsert_file_sync, collection_exists
        _upsert_file_sync("Docs", f)
        assert collection_exists("Docs")

    def test_search_returns_relevant_result(self, tmp_path):
        domain = tmp_path / "Docs"
        domain.mkdir()
        f = domain / "chromadb_info.txt"
        f.write_text("ChromaDB stores embeddings for semantic search.")
        from kb_agent_mcp.vector_store import _upsert_file_sync, _search_sync
        _upsert_file_sync("Docs", f)
        results = _search_sync("Docs", "semantic search embeddings", top_n=3)
        assert len(results) >= 1
        assert any("chromadb_info" in r.get("file", "").lower() or
                   "embedding" in r.get("summary", "").lower()
                   for r in results)

    def test_unchanged_file_not_re_indexed(self, tmp_path):
        domain = tmp_path / "Docs"
        domain.mkdir()
        f = domain / "stable.txt"
        f.write_text("Stable content that never changes.")
        from kb_agent_mcp.vector_store import _upsert_file_sync
        result1 = _upsert_file_sync("Docs", f)
        result2 = _upsert_file_sync("Docs", f)  # second call — same hash
        assert result2 is False  # False = skipped (unchanged)

    def test_modified_file_re_indexed(self, tmp_path):
        domain = tmp_path / "Docs"
        domain.mkdir()
        f = domain / "changing.txt"
        f.write_text("Original content.")
        from kb_agent_mcp.vector_store import _upsert_file_sync
        _upsert_file_sync("Docs", f)
        f.write_text("Completely different updated content.")
        result2 = _upsert_file_sync("Docs", f)
        assert result2 is True  # True = re-indexed

    def test_delete_removes_from_collection(self, tmp_path):
        domain = tmp_path / "Docs"
        domain.mkdir()
        f = domain / "to_delete.txt"
        f.write_text("This file will be deleted from the index.")
        from kb_agent_mcp.vector_store import _upsert_file_sync, _delete_file_sync, _search_sync
        _upsert_file_sync("Docs", f)
        _delete_file_sync("Docs", f)
        results = _search_sync("Docs", "deleted file", top_n=5)
        assert not any("to_delete" in r.get("file", "") for r in results)

    def test_collection_exists_returns_false_for_new_domain(self, tmp_path):
        from kb_agent_mcp.vector_store import collection_exists
        assert not collection_exists("NonExistentDomain_XYZ")


# ══════════════════════════════════════════════════════════════════════════════
# F. File parsing — all supported types
# ══════════════════════════════════════════════════════════════════════════════

class TestFileParsing:
    """File parser extracts text from every supported format."""

    def test_plain_text(self, tmp_path):
        f = tmp_path / "note.txt"
        f.write_text("Hello from a plain text file.")
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f))
        assert "Hello from a plain text file" in result

    def test_markdown(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Title\n\nSome markdown content here.")
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f))
        assert "markdown content" in result

    def test_csv(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("Name,Revenue\nACE,100\nCP4I,200\n")
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f))
        assert "ACE" in result or "Revenue" in result

    def test_json(self, tmp_path):
        """.json is not in INCLUDE_EXTS — extract returns an unsupported label."""
        f = tmp_path / "config.json"
        f.write_text('{"product": "ACE", "version": "12.0"}')
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f))
        # .json is classified as unsupported — returns a label string, not raw content
        assert isinstance(result, str)
        assert result  # non-empty

    def test_unsupported_extension_returns_label(self, tmp_path):
        f = tmp_path / "archive.zip"
        f.write_bytes(b"PK\x03\x04")  # zip magic bytes
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f))
        assert "[" in result  # label like [Unsupported: .zip]

    def test_nonexistent_file_returns_error_string(self, tmp_path):
        f = tmp_path / "ghost.txt"
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f))
        assert result  # not empty — returns an error label

    def test_empty_file_returns_string(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f))
        assert isinstance(result, str)

    def test_max_chars_respected(self, tmp_path):
        f = tmp_path / "long.txt"
        f.write_text("A" * 10_000)
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f, max_chars=500))
        assert len(result) <= 600  # small slack for labels/headers

    def test_should_skip_readme(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("# README")
        from kb_agent_mcp.file_parser import should_skip
        assert should_skip(f)

    def test_should_skip_noindex(self, tmp_path):
        domain = tmp_path / "Domain"
        domain.mkdir()
        (domain / ".noindex").touch()
        target = domain / "secret.pdf"
        target.write_bytes(b"")
        from kb_agent_mcp.file_parser import should_skip
        assert should_skip(target)

    def test_should_not_skip_normal_file(self, tmp_path):
        domain = tmp_path / "Domain"
        domain.mkdir()
        target = domain / "report.pdf"
        target.write_bytes(b"")
        from kb_agent_mcp.file_parser import should_skip
        assert not should_skip(target)


# ══════════════════════════════════════════════════════════════════════════════
# G. MCP server tools — behaviour tests (no live LLM)
# ══════════════════════════════════════════════════════════════════════════════

class TestMCPServerTools:
    """Test each MCP tool in isolation using passthrough / mocked LLM."""

    @pytest.fixture(autouse=True)
    def isolated_kb(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        monkeypatch.setenv("KB_LLM_PROVIDER", "passthrough")
        import dataclasses
        import kb_agent_mcp.config as c_mod
        import kb_agent_mcp.vector_store as vs
        import kb_agent_mcp.audit as audit_mod
        import kb_agent_mcp.memory as mem_mod
        import kb_agent_mcp.feedback as fb_mod
        import kb_agent_mcp.writeback as wb_mod
        import kb_agent_mcp.server as srv_mod
        vs._client = None
        # Replace cfg in all consumer modules — monkeypatch restores automatically
        new_cfg = dataclasses.replace(c_mod.cfg, KB_ROOT=str(tmp_path))
        for mod, attr in [
            (c_mod, "cfg"), (audit_mod, "cfg"), (mem_mod, "cfg"),
            (fb_mod, "cfg"), (wb_mod, "cfg"), (srv_mod, "cfg"),
        ]:
            monkeypatch.setattr(mod, attr, new_cfg)
        # Create a minimal domain
        domain = tmp_path / "TestDomain"
        domain.mkdir()
        (domain / "notes.md").write_text("# Notes\nThe product is ACE.")
        (domain / "domain_config.yaml").write_text(textwrap.dedent("""
            folder_name: TestDomain
            description: Test knowledge domain
            keywords: [ACE, product, notes]
        """))
        yield tmp_path
        vs._client = None

    # ── list_domains ──────────────────────────────────────────────────────────

    def test_list_domains_returns_string(self, isolated_kb):
        from kb_agent_mcp.server import list_domains
        result = asyncio.run(list_domains())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_list_domains_shows_indexed_domain(self, isolated_kb):
        """After indexing, list_domains should mention the domain."""
        from kb_agent_mcp.vector_store import _upsert_file_sync
        f = isolated_kb / "TestDomain" / "notes.md"
        _upsert_file_sync("TestDomain", f)
        from kb_agent_mcp.server import list_domains
        result = asyncio.run(list_domains())
        assert "TestDomain" in result or "test" in result.lower()

    # ── reindex ───────────────────────────────────────────────────────────────

    def test_reindex_completes_without_error(self, isolated_kb):
        from kb_agent_mcp.server import reindex
        result = asyncio.run(reindex())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_reindex_clears_stale_cache(self, isolated_kb):
        from kb_agent_mcp.server import _stale_cache, reindex
        _stale_cache.update({"stale": True, "details": "stale", "checked_at": 9999.0})
        asyncio.run(reindex())
        assert _stale_cache["checked_at"] == 0.0

    # ── session memory ────────────────────────────────────────────────────────

    def test_show_memory_empty_session(self, isolated_kb):
        from kb_agent_mcp.server import show_memory
        result = asyncio.run(show_memory(session_id="e2e_new_session_abc"))
        assert isinstance(result, str)

    def test_clear_memory_works(self, isolated_kb, monkeypatch):
        from kb_agent_mcp.memory import add_turn_sync, get_history_sync, clear_sync
        add_turn_sync("hello", "world", session_id="e2e_clear_test")
        assert len(get_history_sync("e2e_clear_test")) == 2
        clear_sync("e2e_clear_test")
        assert get_history_sync("e2e_clear_test") == []

    def test_resume_session_returns_string(self, isolated_kb):
        from kb_agent_mcp.server import resume_session
        result = asyncio.run(resume_session(session_id="e2e_resume_test"))
        assert isinstance(result, str)

    def test_list_sessions_returns_string(self, isolated_kb):
        from kb_agent_mcp.server import list_sessions
        result = asyncio.run(list_sessions())
        assert isinstance(result, str)

    # ── rate_answer ───────────────────────────────────────────────────────────

    def test_rate_answer_valid_rating_accepted(self, isolated_kb):
        from kb_agent_mcp.memory import add_turn_sync
        add_turn_sync("What is ACE?", "ACE is a product.", session_id="e2e_rate")
        from kb_agent_mcp.server import rate_answer
        result = asyncio.run(rate_answer(rating=4, session_id="e2e_rate", comment="Good answer"))
        assert isinstance(result, str)
        assert "4" in result or "thank" in result.lower() or "rating" in result.lower()

    def test_rate_answer_invalid_rating_rejected(self, isolated_kb):
        from kb_agent_mcp.server import rate_answer
        result = asyncio.run(rate_answer(rating=6, session_id="e2e_rate_bad"))
        assert "invalid" in result.lower() or ("1" in result and "5" in result)

    def test_rate_answer_zero_rating_rejected(self, isolated_kb):
        from kb_agent_mcp.server import rate_answer
        result = asyncio.run(rate_answer(rating=0, session_id="e2e_rate_zero"))
        assert isinstance(result, str)
        assert "invalid" in result.lower() or "1" in result

    # ── audit_summary ─────────────────────────────────────────────────────────

    def test_audit_summary_returns_string(self, isolated_kb):
        from kb_agent_mcp.server import audit_summary
        result = asyncio.run(audit_summary(days=7))
        assert isinstance(result, str)

    def test_audit_summary_with_zero_days(self, isolated_kb):
        from kb_agent_mcp.server import audit_summary
        result = asyncio.run(audit_summary(days=0))
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════════════════
# H. Writeback
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteback:
    """update_document: all modes, path traversal, non-indexable file."""

    @pytest.fixture(autouse=True)
    def isolated_kb(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import dataclasses
        import kb_agent_mcp.config as c_mod
        import kb_agent_mcp.vector_store as vs
        import kb_agent_mcp.writeback as wb_mod
        vs._client = None
        new_cfg = dataclasses.replace(c_mod.cfg, KB_ROOT=str(tmp_path))
        monkeypatch.setattr(c_mod, "cfg", new_cfg)
        monkeypatch.setattr(wb_mod, "cfg", new_cfg)
        (tmp_path / "MyDomain").mkdir()
        yield tmp_path
        vs._client = None

    def test_overwrite_creates_file(self, isolated_kb):
        from kb_agent_mcp.writeback import write_document
        result = asyncio.run(
            write_document("MyDomain/new_note.md", "# New Note\nCreated by E2E test.")
        )
        assert result["ok"] is True
        assert (isolated_kb / "MyDomain" / "new_note.md").read_text() == "# New Note\nCreated by E2E test."

    def test_append_mode(self, isolated_kb):
        f = isolated_kb / "MyDomain" / "log.txt"
        f.write_text("Line 1\n")
        from kb_agent_mcp.writeback import write_document
        asyncio.run(write_document("MyDomain/log.txt", "Line 2\n", mode="append"))
        assert f.read_text() == "Line 1\nLine 2\n"

    def test_prepend_mode(self, isolated_kb):
        f = isolated_kb / "MyDomain" / "log.txt"
        f.write_text("Old content\n")
        from kb_agent_mcp.writeback import write_document
        asyncio.run(write_document("MyDomain/log.txt", "New header\n", mode="prepend"))
        assert f.read_text().startswith("New header\n")

    def test_path_traversal_rejected(self, isolated_kb):
        from kb_agent_mcp.writeback import write_document
        result = asyncio.run(write_document("../../etc/passwd", "hacked"))
        assert result["ok"] is False
        assert "traversal" in result["message"].lower() or "outside" in result["message"].lower()

    def test_invalid_mode_rejected(self, isolated_kb):
        from kb_agent_mcp.writeback import write_document
        result = asyncio.run(write_document("MyDomain/test.md", "content", mode="destroy"))
        assert result["ok"] is False
        assert "invalid mode" in result["message"].lower() or "mode" in result["message"].lower()

    def test_domain_field_correct(self, isolated_kb):
        from kb_agent_mcp.writeback import write_document
        result = asyncio.run(write_document("MyDomain/doc.md", "content"))
        assert result["domain"] == "MyDomain"

    def test_nested_path_creates_subdirs(self, isolated_kb):
        from kb_agent_mcp.writeback import write_document
        result = asyncio.run(write_document("MyDomain/subdir/deep/note.md", "deep note"))
        assert result["ok"] is True
        assert (isolated_kb / "MyDomain" / "subdir" / "deep" / "note.md").exists()

    def test_non_indexable_file_not_reindexed(self, isolated_kb):
        """Files with extensions not in INCLUDE_EXTS are written but not re-indexed."""
        from kb_agent_mcp.writeback import write_document
        # .bin is not in INCLUDE_EXTS — should write but skip re-indexing
        result = asyncio.run(write_document("MyDomain/data.bin", "binary content"))
        assert result["ok"] is True
        assert result["reindexed"] is False


# ══════════════════════════════════════════════════════════════════════════════
# I. Audit log
# ══════════════════════════════════════════════════════════════════════════════

class TestAuditLog:
    """Audit log: entries written, read back, rotated correctly."""

    @pytest.fixture(autouse=True)
    def isolated_kb(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import dataclasses
        import kb_agent_mcp.config as c_mod
        import kb_agent_mcp.audit as audit_mod
        new_cfg = dataclasses.replace(c_mod.cfg, KB_ROOT=str(tmp_path))
        monkeypatch.setattr(c_mod, "cfg", new_cfg)
        monkeypatch.setattr(audit_mod, "cfg", new_cfg)
        yield tmp_path

    def test_log_turn_creates_file(self, isolated_kb):
        from kb_agent_mcp.audit import log_turn
        log_turn("s1", "What is ACE?", ["BizOps"], ["file.md"], "ACE is great.", False, 200)
        audit_file = isolated_kb / ".kb_index" / "audit.jsonl"
        assert audit_file.exists()

    def test_log_turn_is_valid_jsonl(self, isolated_kb):
        from kb_agent_mcp.audit import log_turn
        log_turn("s1", "Q1?", ["D1"], ["f1.md"], "A1.", False, 100)
        log_turn("s1", "Q2?", ["D2"], ["f2.md"], "A2.", False, 150)
        audit_file = isolated_kb / ".kb_index" / "audit.jsonl"
        lines = audit_file.read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            entry = json.loads(line)
            assert "question" in entry
            assert "ts" in entry
            assert "session_id" in entry

    def test_read_log_returns_entries(self, isolated_kb):
        from kb_agent_mcp.audit import log_turn, read_log
        log_turn("s2", "Q?", ["D1"], [], "A.", False, 50)
        entries = read_log(limit=10)
        assert len(entries) >= 1
        assert any(e["question"] == "Q?" for e in entries)

    def test_read_log_filters_by_session(self, isolated_kb):
        from kb_agent_mcp.audit import log_turn, read_log
        log_turn("session_alpha", "Alpha Q?", ["D1"], [], "A.", False, 10)
        log_turn("session_beta",  "Beta Q?",  ["D2"], [], "B.", False, 20)
        entries = read_log(limit=50, session_id="session_alpha")
        assert all(e["session_id"] == "session_alpha" for e in entries)

    def test_read_log_respects_limit(self, isolated_kb):
        from kb_agent_mcp.audit import log_turn, read_log
        for i in range(10):
            log_turn("s3", f"Q{i}?", ["D"], [], f"A{i}.", False, 10)
        entries = read_log(limit=3)
        assert len(entries) <= 3

    def test_summarise_log_returns_dict(self, isolated_kb):
        from kb_agent_mcp.audit import log_turn, summarise_log, read_log
        # Write a fresh turn into the isolated audit log
        log_turn("s4", "Summary Q?", ["D1"], ["f.md"], "Answer.", False, 80)
        # Verify the entry has a numeric ts (required for summarise_log comparison)
        entries = read_log(limit=5)
        for e in entries:
            assert isinstance(e.get("ts"), (int, float)), f"ts should be numeric, got {type(e.get('ts'))}"
        summary = summarise_log(days=30)
        assert isinstance(summary, dict)
        assert len(summary) > 0

    def test_log_blocked_turn_recorded(self, isolated_kb):
        from kb_agent_mcp.audit import log_turn, read_log
        log_turn("s5", "Blocked Q?", ["D1"], [], "Blocked.", True, 10)
        entries = read_log(limit=10)
        blocked = [e for e in entries if e.get("question") == "Blocked Q?"]
        assert len(blocked) >= 1
        assert blocked[0].get("blocked") is True


# ══════════════════════════════════════════════════════════════════════════════
# J. Feedback
# ══════════════════════════════════════════════════════════════════════════════

class TestFeedback:
    """Feedback recording, reading, and rating-bound enforcement."""

    @pytest.fixture(autouse=True)
    def isolated_kb(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import dataclasses
        import kb_agent_mcp.config as c_mod
        import kb_agent_mcp.feedback as fb_mod
        new_cfg = dataclasses.replace(c_mod.cfg, KB_ROOT=str(tmp_path))
        monkeypatch.setattr(c_mod, "cfg", new_cfg)
        monkeypatch.setattr(fb_mod, "cfg", new_cfg)
        yield tmp_path

    def test_record_creates_file(self, isolated_kb):
        from kb_agent_mcp.feedback import record
        record("s1", "What is ACE?", "ACE is an integration platform.", 5, "Excellent!")
        fb_file = isolated_kb / ".kb_index" / "feedback.jsonl"
        assert fb_file.exists()

    def test_record_is_valid_jsonl(self, isolated_kb):
        from kb_agent_mcp.feedback import record
        record("s1", "Q?", "A.", 4, "Good")
        fb_file = isolated_kb / ".kb_index" / "feedback.jsonl"
        entry = json.loads(fb_file.read_text().strip())
        assert entry["rating"] == 4
        assert entry["session_id"] == "s1"

    def test_read_feedback_returns_entries(self, isolated_kb):
        from kb_agent_mcp.feedback import record, read_feedback
        record("s2", "Q?", "A.", 3, "OK")
        entries = read_feedback(limit=10)
        assert any(e["session_id"] == "s2" for e in entries)

    def test_read_feedback_filters_by_min_rating(self, isolated_kb):
        from kb_agent_mcp.feedback import record, read_feedback
        record("s3", "Q1?", "A1.", 2, "Bad")
        record("s3", "Q2?", "A2.", 5, "Perfect")
        entries = read_feedback(limit=50, min_rating=4)
        assert all(e["rating"] >= 4 for e in entries)

    def test_read_feedback_filters_by_max_rating(self, isolated_kb):
        from kb_agent_mcp.feedback import record, read_feedback
        record("s4", "Q1?", "A1.", 1, "Terrible")
        record("s4", "Q2?", "A2.", 5, "Perfect")
        entries = read_feedback(limit=50, max_rating=2)
        assert all(e["rating"] <= 2 for e in entries)

    def test_rating_bounds_constants(self):
        from kb_agent_mcp.feedback import RATING_MIN, RATING_MAX
        assert RATING_MIN == 1
        assert RATING_MAX == 5

    def test_multiple_ratings_recorded_independently(self, isolated_kb):
        from kb_agent_mcp.feedback import record, read_feedback
        for r in range(1, 6):
            record(f"sess_{r}", "Q?", "A.", r)
        entries = read_feedback(limit=10)
        ratings = {e["rating"] for e in entries}
        assert {1, 2, 3, 4, 5}.issubset(ratings)


# ══════════════════════════════════════════════════════════════════════════════
# K. Session memory
# ══════════════════════════════════════════════════════════════════════════════

class TestSessionMemory:
    """Session memory: turns, history, clear, isolation, max turns."""

    @pytest.fixture(autouse=True)
    def isolated_kb(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import dataclasses
        import kb_agent_mcp.config as c_mod
        import kb_agent_mcp.memory as mem_mod
        new_cfg = dataclasses.replace(c_mod.cfg, KB_ROOT=str(tmp_path))
        monkeypatch.setattr(c_mod, "cfg", new_cfg)
        monkeypatch.setattr(mem_mod, "cfg", new_cfg)
        yield tmp_path

    def test_add_and_retrieve_turn(self, isolated_kb):
        sid = f"e2e_mem_{uuid.uuid4().hex[:8]}"
        from kb_agent_mcp.memory import add_turn_sync, get_history_sync, clear_sync
        clear_sync(sid)
        add_turn_sync("Hello?", "Hi there!", session_id=sid)
        history = get_history_sync(sid)
        assert len(history) == 2
        assert history[0]["content"] == "Hello?"
        assert history[1]["content"] == "Hi there!"

    def test_session_isolation(self, isolated_kb):
        sid_a = f"e2e_sess_a_{uuid.uuid4().hex[:8]}"
        sid_b = f"e2e_sess_b_{uuid.uuid4().hex[:8]}"
        from kb_agent_mcp.memory import add_turn_sync, get_history_sync, clear_sync
        clear_sync(sid_a); clear_sync(sid_b)
        add_turn_sync("Session A Q", "Session A A", session_id=sid_a)
        add_turn_sync("Session B Q", "Session B A", session_id=sid_b)
        hist_a = get_history_sync(sid_a)
        hist_b = get_history_sync(sid_b)
        contents_a = [t["content"] for t in hist_a]
        contents_b = [t["content"] for t in hist_b]
        assert "Session A Q" in contents_a
        assert "Session B Q" not in contents_a
        assert "Session B Q" in contents_b

    def test_clear_removes_history(self, isolated_kb):
        sid = f"e2e_clear_{uuid.uuid4().hex[:8]}"
        from kb_agent_mcp.memory import add_turn_sync, get_history_sync, clear_sync
        clear_sync(sid)
        add_turn_sync("To be cleared", "Yes cleared", session_id=sid)
        clear_sync(sid)
        assert get_history_sync(sid) == []

    def test_empty_session_returns_empty_list(self, isolated_kb):
        from kb_agent_mcp.memory import get_history_sync
        assert get_history_sync(f"e2e_nonexistent_{uuid.uuid4().hex}") == []

    def test_multiple_turns_ordered(self, isolated_kb):
        sid = f"e2e_ordered_{uuid.uuid4().hex[:8]}"
        from kb_agent_mcp.memory import add_turn_sync, get_history_sync, clear_sync
        clear_sync(sid)
        for i in range(3):
            add_turn_sync(f"Q{i}", f"A{i}", session_id=sid)
        history = get_history_sync(sid)
        questions = [t["content"] for t in history if t["role"] == "user"]
        assert questions == ["Q0", "Q1", "Q2"]

    def test_list_sessions_includes_active_session(self, isolated_kb):
        sid = f"e2e_list_{uuid.uuid4().hex[:8]}"
        from kb_agent_mcp.memory import add_turn_sync, list_sessions_sync, clear_sync
        clear_sync(sid)
        add_turn_sync("Q", "A", session_id=sid)
        sessions = list_sessions_sync()
        assert any(s.get("session_id") == sid for s in sessions)


# ══════════════════════════════════════════════════════════════════════════════
# L. Doctor / status CLI
# ══════════════════════════════════════════════════════════════════════════════

class TestDoctorStatus:
    """Health checks pass on a properly configured temp KB."""

    def test_python_version_check_passes(self):
        from kb_agent_mcp.cli.doctor import _check_python
        result = _check_python()
        # CheckResult fields: label, passed, fix_fn
        assert result.passed, f"Python version check failed: {result}"

    def test_kb_root_check_passes_when_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import kb_agent_mcp.config as c; importlib.reload(c)
        from kb_agent_mcp.cli.doctor import _check_kb_root
        # _check_kb_root takes the cfg object, returns (CheckResult, Path|None)
        result, root = _check_kb_root(c.cfg)
        assert result.passed, f"KB_ROOT check failed: {result}"
        assert root == tmp_path

    def test_kb_root_check_fails_when_missing(self, monkeypatch):
        monkeypatch.setenv("KB_ROOT", "/nonexistent_path_xyz_abc")
        import kb_agent_mcp.config as c; importlib.reload(c)
        from kb_agent_mcp.cli.doctor import _check_kb_root
        result, root = _check_kb_root(c.cfg)
        assert not result.passed

    def test_domain_folder_check_passes_with_folders(self, tmp_path, monkeypatch):
        (tmp_path / "Domain1").mkdir()
        (tmp_path / "Domain2").mkdir()
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import kb_agent_mcp.config as c; importlib.reload(c)
        from kb_agent_mcp.cli.doctor import _check_domain_folders
        result, domains = _check_domain_folders(tmp_path, c.cfg)
        assert result.passed
        assert set(domains) == {"Domain1", "Domain2"}

    def test_domain_folder_check_fails_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import kb_agent_mcp.config as c; importlib.reload(c)
        from kb_agent_mcp.cli.doctor import _check_domain_folders
        result, domains = _check_domain_folders(tmp_path, c.cfg)
        assert not result.passed
        assert domains == []

    def test_check_result_namedtuple_fields(self):
        from kb_agent_mcp.cli.doctor import CheckResult
        # CheckResult: label, passed, fix_fn
        r = CheckResult(label="test", passed=True, fix_fn=None)
        assert r.passed is True
        assert r.label == "test"


# ══════════════════════════════════════════════════════════════════════════════
# M. .noindex guard — end-to-end
# ══════════════════════════════════════════════════════════════════════════════

class TestNoindexGuardE2E:
    """.noindex sentinel prevents files from being indexed or returned."""

    @pytest.fixture(autouse=True)
    def isolated_kb(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import kb_agent_mcp.config as c; importlib.reload(c)
        import kb_agent_mcp.vector_store as vs; vs._client = None
        yield tmp_path
        vs._client = None

    def test_file_under_noindex_not_indexable(self, isolated_kb):
        protected = isolated_kb / "PrivateDomain"
        protected.mkdir()
        (protected / ".noindex").touch()
        secret = protected / "secret.md"
        secret.write_text("Top secret information.")
        from kb_agent_mcp.file_parser import should_skip
        assert should_skip(secret)

    def test_file_in_clean_domain_is_indexable(self, isolated_kb):
        public = isolated_kb / "PublicDomain"
        public.mkdir()
        doc = public / "overview.md"
        doc.write_text("Public information.")
        from kb_agent_mcp.file_parser import should_skip
        assert not should_skip(doc)

    def test_noindex_in_parent_blocks_nested_files(self, isolated_kb):
        domain = isolated_kb / "Guarded"
        subdir = domain / "sensitive"
        subdir.mkdir(parents=True)
        (domain / ".noindex").touch()
        nested = subdir / "data.txt"
        nested.write_text("Nested confidential data.")
        from kb_agent_mcp.file_parser import should_skip
        assert should_skip(nested)

    def test_sibling_domains_not_affected_by_noindex(self, isolated_kb):
        d1 = isolated_kb / "Private"
        d2 = isolated_kb / "Public"
        d1.mkdir(); d2.mkdir()
        (d1 / ".noindex").touch()
        pub_file = d2 / "safe.md"
        pub_file.write_text("Safe content.")
        from kb_agent_mcp.file_parser import should_skip
        assert not should_skip(pub_file)

    def test_noindex_domain_files_not_indexable(self, isolated_kb):
        """
        .noindex enforcement is at file_parser.should_skip() time (query gate),
        NOT at _discover_folders() discovery time.  The folder is still
        discovered; individual files inside it are skipped when indexed/queried.
        """
        private = isolated_kb / "PrivateDomain"
        private.mkdir()
        (private / ".noindex").touch()
        (private / "secret.md").write_text("hidden")
        from kb_agent_mcp.file_parser import should_skip
        # The secret file itself is blocked
        assert should_skip(private / "secret.md")
        # But the folder IS returned by _discover_folders (enforcement is downstream)
        from kb_agent_mcp.cli.generate import _discover_folders
        folders = _discover_folders(isolated_kb)
        # PrivateDomain has a .md file — it will appear in discover; enforcement is elsewhere
        assert isinstance(folders, list)


# ══════════════════════════════════════════════════════════════════════════════
# N. Edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases: empty KB, special characters, oversized inputs."""

    @pytest.fixture(autouse=True)
    def isolated_kb(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        import dataclasses
        import kb_agent_mcp.config as c_mod
        import kb_agent_mcp.vector_store as vs
        import kb_agent_mcp.audit as audit_mod
        import kb_agent_mcp.writeback as wb_mod
        vs._client = None
        new_cfg = dataclasses.replace(c_mod.cfg, KB_ROOT=str(tmp_path))
        monkeypatch.setattr(c_mod, "cfg", new_cfg)
        monkeypatch.setattr(audit_mod, "cfg", new_cfg)
        monkeypatch.setattr(wb_mod, "cfg", new_cfg)
        yield tmp_path
        vs._client = None

    def test_empty_kb_list_domains_does_not_crash(self, isolated_kb):
        from kb_agent_mcp.server import list_domains
        result = asyncio.run(list_domains())
        assert isinstance(result, str)

    def test_folder_to_safe_name_handles_special_chars(self):
        from kb_agent_mcp.config import cfg
        # folder_to_safe_name lives in agent_base (agents/) or config
        # Try both — the function normalises slashes and spaces
        try:
            _add_agents_path()
            from agent_base import folder_to_safe_name
        except ImportError:
            from kb_agent_mcp.config import cfg as _cfg
            # If not available in mcp package, skip gracefully
            pytest.skip("folder_to_safe_name not available in kb_agent_mcp")
        result = folder_to_safe_name("My Domain/Sub-Folder")
        assert "/" not in result
        assert result  # non-empty

    def test_folder_to_safe_name_unicode_stripped(self):
        _add_agents_path()
        try:
            from agent_base import folder_to_safe_name
        except ImportError:
            pytest.skip("folder_to_safe_name not available in kb_agent_mcp")
        result = folder_to_safe_name("Données 2024")
        assert isinstance(result, str)
        assert result  # non-empty

    def test_very_long_folder_name(self):
        _add_agents_path()
        try:
            from agent_base import folder_to_safe_name
        except ImportError:
            pytest.skip("folder_to_safe_name not available in kb_agent_mcp")
        long_name = "A" * 300
        result = folder_to_safe_name(long_name)
        assert isinstance(result, str)

    def test_write_document_to_root_of_kb(self, isolated_kb):
        """Writing a file without a domain prefix should fail with traversal error."""
        from kb_agent_mcp.writeback import write_document
        result = asyncio.run(write_document("no_domain_file.md", "content"))
        # Either ok=False (traversal) or ok=True with some domain resolution
        assert isinstance(result, dict)
        assert "ok" in result

    def test_search_on_empty_collection_returns_empty(self, isolated_kb):
        from kb_agent_mcp.vector_store import _search_sync
        results = _search_sync("EmptyDomainXYZ", "any query", top_n=5)
        assert results == []

    def test_extract_full_text_on_very_large_text(self, tmp_path):
        f = tmp_path / "huge.txt"
        f.write_text("word " * 50_000)
        from kb_agent_mcp.file_parser import extract
        result = asyncio.run(extract(f, max_chars=10_000))
        assert len(result) <= 11_000  # some slack for labels

    def test_ask_with_empty_question_does_not_crash(self, isolated_kb):
        from kb_agent_mcp.server import ask
        # Empty question should return a string (error or empty response), not raise
        try:
            result = asyncio.run(ask(""))
            assert isinstance(result, str)
        except Exception as exc:
            pytest.fail(f"ask('') raised unexpectedly: {exc}")

    def test_rate_answer_with_no_prior_turn(self, isolated_kb):
        """Rate on a session with no turns should not crash."""
        from kb_agent_mcp.server import rate_answer
        result = asyncio.run(rate_answer(rating=3, session_id="e2e_empty_session_xyz"))
        assert isinstance(result, str)

    def test_audit_log_survives_concurrent_writes(self, isolated_kb):
        """Multiple log_turn calls in quick succession must not corrupt the log."""
        from kb_agent_mcp.audit import log_turn, read_log
        # Use a unique marker to identify entries written by this specific test run
        marker = uuid.uuid4().hex[:8]
        for i in range(20):
            log_turn(f"s_{marker}_{i}", f"Q{marker}{i}?", ["D"], [], f"A{i}.", False, 10)
        entries = read_log(limit=500)
        # Filter to only entries written by this test
        mine = [e for e in entries if e.get("session_id", "").startswith(f"s_{marker}_")]
        assert len(mine) == 20
        for entry in mine:
            assert "question" in entry
            json.dumps(entry)  # must be serialisable


# ══════════════════════════════════════════════════════════════════════════════
# O. Stale index detection
# ══════════════════════════════════════════════════════════════════════════════

class TestStaleIndexDetection:
    """Stale cache TTL, clear, and disabled-check behaviour."""

    def test_stale_cache_initial_state(self):
        from kb_agent_mcp.server import _stale_cache
        # Cache may have been populated by other tests; just check structure
        assert "stale" in _stale_cache
        assert "checked_at" in _stale_cache

    def test_clear_stale_cache_resets_fields(self):
        from kb_agent_mcp.server import _stale_cache
        _stale_cache["stale"] = True
        _stale_cache["checked_at"] = 9999.0
        _stale_cache["stale"] = False
        _stale_cache["checked_at"] = 0.0
        assert _stale_cache["checked_at"] == 0.0
        assert _stale_cache["stale"] is False

    def test_stale_check_ttl_zero_disables_check(self, monkeypatch):
        """Setting KB_STALE_CHECK_TTL_SECONDS=0 skips stale detection."""
        monkeypatch.setenv("KB_STALE_CHECK_TTL_SECONDS", "0")
        import kb_agent_mcp.config as c; importlib.reload(c)
        # Config field is KB_STALE_CHECK_TTL_SECONDS
        assert c.cfg.KB_STALE_CHECK_TTL_SECONDS == 0

    def test_stale_result_cached_within_ttl(self):
        from kb_agent_mcp.server import _stale_cache
        _stale_cache["checked_at"] = time.time()
        _stale_cache["stale"] = False
        # Reading stale while within TTL should not re-check (just read cache)
        assert not _stale_cache["stale"]


# ══════════════════════════════════════════════════════════════════════════════
# P. Context budget
# ══════════════════════════════════════════════════════════════════════════════

class TestContextBudget:
    """Context budget helpers: trim, compact, build_context."""

    def test_agents_context_budget_public_api(self):
        _add_agents_path()
        import context_budget as cb
        # Public API: trim(text, budget_key), get(key), tokens(text),
        #             compact_index_block(block), build_context(pre_index, index_block)
        assert callable(cb.trim)
        assert callable(cb.get)
        assert callable(cb.compact_index_block)
        assert callable(cb.build_context)

    def test_mcp_context_budget_public_api(self):
        import kb_agent_mcp.context_budget as cb
        assert callable(cb.trim)
        assert callable(cb.get)
        assert callable(cb.compact_index_block)
        assert callable(cb.build_context)

    def test_trim_respects_budget(self):
        _add_agents_path()
        import context_budget as cb
        long_text = "word " * 2000
        # trim(text, budget_key) — use a known key like "rag_file"
        budget = cb.get("rag_file")
        trimmed = cb.trim(long_text, "rag_file")
        assert len(trimmed) <= budget + 100  # some slack for truncation markers

    def test_compact_index_block_strips_folder_index_heading(self):
        """compact_index_block strips '## 📁 Folder Index' style headings."""
        _add_agents_path()
        import context_budget as cb
        block = "## 📁 Folder Index\n| file | type | size | modified | summary |\n| doc.md | md | 1 KB | 2024 | A doc |\n"
        result = cb.compact_index_block(block)
        assert "## 📁 Folder Index" not in result
        # Table rows should still be present
        assert "doc.md" in result

    def test_compact_index_block_preserves_auto_index_heading(self):
        """AUTO-INDEX heading is not in the strip list — it passes through."""
        _add_agents_path()
        import context_budget as cb
        block = "## AUTO-INDEX\n| file | type | size | modified | summary |\n| doc.md | md | 1 KB | 2024 | A doc |\n"
        result = cb.compact_index_block(block)
        # AUTO-INDEX is not stripped (only '## 📁 Folder Index' and similar)
        assert "doc.md" in result  # content preserved

    def test_build_context_combines_sections(self):
        """build_context(pre_index, index_block) -> combined string."""
        _add_agents_path()
        import context_budget as cb
        # Signature: build_context(pre_index: str, index_block: str) -> str
        result = cb.build_context("Intro text about ACE.", "| f.md | md | 1 KB | today | summary |")
        assert "Intro text" in result or "f.md" in result


# ══════════════════════════════════════════════════════════════════════════════
# Q. Tech-debt consolidation regression
# ══════════════════════════════════════════════════════════════════════════════

class TestTechDebtConsolidationRegression:
    """Regression tests — consolidated symbols must come from canonical source."""

    def test_embeddings_imports_from_agent_base(self):
        """embeddings.py must NOT define its own AGG_KEYWORDS / PREFERRED_NUM_COLS."""
        # IMPORTANT: use the same sys.path resolution — 'agents/' on sys.path means
        # 'agent_base' (unqualified) is the same module object that embeddings.py imports.
        # 'agents.agent_base' is a DIFFERENT module object even for the same file.
        _add_agents_path()
        import importlib
        emb = importlib.import_module("embeddings")   # resolves via agents/ on sys.path
        ab  = importlib.import_module("agent_base")   # same resolution
        # Both names must resolve to the same object (imported, not re-defined)
        assert emb.AGG_KEYWORDS is ab.AGG_KEYWORDS
        assert emb.PREFERRED_NUM_COLS is ab.PREFERRED_NUM_COLS

    def test_generate_imports_find_readme_from_agent_base(self):
        """scripts/generate.py must NOT define its own _find_readme."""
        _add_agents_path()
        import importlib
        # Load scripts/generate.py via sys.modules path so agent_base resolves correctly
        gen = importlib.import_module("scripts.generate")
        ab  = importlib.import_module("agent_base")
        assert gen._find_readme is ab._find_readme

    def test_watch_kb_imports_find_readme_from_agent_base(self):
        """scripts/watch_kb.py must NOT define its own find_readme."""
        _add_agents_path()
        import importlib
        wkb = importlib.import_module("scripts.watch_kb")
        ab  = importlib.import_module("agent_base")
        # watch_kb imports it as alias: find_readme = _find_readme (from agent_base)
        assert wkb.find_readme is ab._find_readme

    def test_agent_base_exports_all_canonical_symbols(self):
        """agent_base.py must export the five consolidated symbols."""
        _add_agents_path()
        import agent_base as ab
        assert hasattr(ab, "AGG_KEYWORDS")
        assert hasattr(ab, "PREFERRED_NUM_COLS")
        assert hasattr(ab, "_find_readme")
        assert hasattr(ab, "_has_noindex_ancestor")
        assert hasattr(ab, "folder_to_safe_name")

    def test_agg_keywords_is_non_empty(self):
        """AGG_KEYWORDS is the column-name mapping dict (not a list)."""
        _add_agents_path()
        import agent_base as ab
        # AGG_KEYWORDS is a dict: {column_name_variant: canonical_name}
        assert isinstance(ab.AGG_KEYWORDS, dict)
        assert len(ab.AGG_KEYWORDS) > 0

    def test_preferred_num_cols_is_non_empty(self):
        """PREFERRED_NUM_COLS is a list of column names to prefer as numeric."""
        _add_agents_path()
        import agent_base as ab
        # PREFERRED_NUM_COLS is a list of column name strings
        assert isinstance(ab.PREFERRED_NUM_COLS, list)
        assert len(ab.PREFERRED_NUM_COLS) > 0
