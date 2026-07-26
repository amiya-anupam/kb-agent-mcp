"""
tests/test_audit_fixes.py
─────────────────────────
Regression tests for all 6 bugs identified in the install-to-execution audit.

  BUG-1 — domain_agent._pre_rank(): swapped args to vector_store.search()
  BUG-2 — vector_store.build_collection(): indexed_at stored as float only; now adds indexed_at_iso
  BUG-3 — status._get_indexed_file_hashes(): wrong metadata key ("file_hash" vs "hash")
  BUG-4 — watch.py: import re placed after the function that uses it
  BUG-5 — setup._patch_env_key(): duplicate key when both commented and real form exist
  BUG-6 — requirements.txt: missing core packages
"""
from __future__ import annotations

import datetime
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# BUG-1 — Correct arg order to vector_store.search()
# ══════════════════════════════════════════════════════════════════════════════

class TestBug1PreRankArgOrder:
    """_pre_rank must call search(domain, query, …) not search(query, domain, …)."""

    @pytest.mark.asyncio
    async def test_pre_rank_passes_folder_name_as_first_arg(self):
        """Verify _pre_rank calls search(folder_name, question, top_n=…)."""
        from kb_agent_mcp.domain_agent import DomainAgent, _default_config
        import kb_agent_mcp.vector_store as vs_mod

        folder_name = "TestDomain"
        question    = "What is the SLA policy?"
        captured: list[tuple] = []

        async def fake_search(domain, query, top_n=4):
            captured.append((domain, query, top_n))
            return []

        original = vs_mod.search
        vs_mod.search = fake_search
        try:
            agent = DomainAgent.__new__(DomainAgent)
            agent.folder_name = folder_name
            agent.config = _default_config(folder_name)
            # Ensure no pin/boost so we avoid the thread-pool call
            agent.config = _default_config(folder_name)
            agent.config.pin_files = []
            agent.config.boost_keywords = []
            await agent._pre_rank(question)
        finally:
            vs_mod.search = original

        assert len(captured) == 1, "search() should be called exactly once"
        called_domain, called_query, _ = captured[0]
        assert called_domain == folder_name, (
            f"First arg must be domain ('{folder_name}'), got '{called_domain}'"
        )
        assert called_query == question, (
            f"Second arg must be query ('{question}'), got '{called_query}'"
        )


# ══════════════════════════════════════════════════════════════════════════════
# BUG-2 — build_collection writes both indexed_at (float) and indexed_at_iso (ISO)
# ══════════════════════════════════════════════════════════════════════════════

class TestBug2IndexedAtStorage:
    """build_collection must store both indexed_at (float) and indexed_at_iso (ISO)."""

    @pytest.mark.asyncio
    async def test_build_collection_stores_indexed_at_iso(self, tmp_path):
        """indexed_at_iso must be a parseable timezone-aware ISO datetime string."""
        import kb_agent_mcp.vector_store as vs

        written: dict = {}

        def fake_set_meta(domain, meta):
            written.update(meta)

        fake_col = MagicMock()
        fake_col.count.return_value = 0
        fake_col.get.return_value = {"ids": [], "metadatas": [], "documents": []}

        # build_collection(domain, folder_path, progress_fn=None)
        with (
            patch.object(vs, "get_or_create_collection", return_value=fake_col),
            patch.object(vs, "set_domain_metadata", side_effect=fake_set_meta),
            patch.object(vs, "upsert_file", new=AsyncMock(return_value=False)),
        ):
            await vs.build_collection("TestDomain", str(tmp_path))

        assert "indexed_at" in written, "indexed_at (float) must be written"
        assert "indexed_at_iso" in written, "indexed_at_iso (ISO string) must be written"
        assert isinstance(written["indexed_at"], float)
        parsed = datetime.datetime.fromisoformat(written["indexed_at_iso"])
        assert parsed.tzinfo is not None, "indexed_at_iso must be timezone-aware"

    def test_status_domain_row_reads_indexed_at_iso(self):
        """_domain_row: when indexed_at_iso present, no crash, returns 'today'."""
        from kb_agent_mcp.cli.status import _domain_row
        import kb_agent_mcp.vector_store as vs_mod

        fake_col = MagicMock()
        fake_col.count.return_value = 5
        iso_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        fake_col.get.return_value = {
            "metadatas": [{"indexed_at_iso": iso_now, "indexed_at": 9999999999.0}]
        }

        with (
            patch.object(vs_mod, "get_or_create_collection", return_value=fake_col),
            patch.object(vs_mod, "_get_client", return_value=MagicMock()),
        ):
            row = _domain_row("TestDomain", Path("/kb"))

        assert row is not None
        assert row.get("indexed_str") == "today"

    def test_status_domain_row_falls_back_to_float_indexed_at(self):
        """_domain_row: when only float indexed_at present, no crash, returns 'today'."""
        from kb_agent_mcp.cli.status import _domain_row
        import kb_agent_mcp.vector_store as vs_mod

        fake_col = MagicMock()
        fake_col.count.return_value = 3
        fake_col.get.return_value = {
            "metadatas": [{"indexed_at": time.time()}]
        }

        with (
            patch.object(vs_mod, "get_or_create_collection", return_value=fake_col),
            patch.object(vs_mod, "_get_client", return_value=MagicMock()),
        ):
            row = _domain_row("TestDomain", Path("/kb"))

        assert row is not None
        assert row.get("indexed_str") == "today"


# ══════════════════════════════════════════════════════════════════════════════
# BUG-3 — _get_indexed_file_hashes uses key "hash" not "file_hash"
# ══════════════════════════════════════════════════════════════════════════════

class TestBug3FileHashKey:
    """_get_indexed_file_hashes must read the 'hash' key, not 'file_hash'."""

    def test_returns_hash_when_metadata_uses_hash_key(self):
        from kb_agent_mcp.cli.status import _get_indexed_file_hashes
        import kb_agent_mcp.vector_store as vs_mod

        fake_col = MagicMock()
        fake_col.get.return_value = {
            "metadatas": [
                {"path": "/kb/Docs/file.md",  "hash": "abc123"},
                {"path": "/kb/Docs/other.md", "hash": "def456"},
            ]
        }

        with patch.object(vs_mod, "get_or_create_collection", return_value=fake_col):
            result = _get_indexed_file_hashes("Docs")

        assert result.get("/kb/Docs/file.md") == "abc123"
        assert result.get("/kb/Docs/other.md") == "def456"

    def test_returns_empty_string_for_metadata_with_no_hash(self):
        """Missing hash key should yield '' (falsy) not raise KeyError."""
        from kb_agent_mcp.cli.status import _get_indexed_file_hashes
        import kb_agent_mcp.vector_store as vs_mod

        fake_col = MagicMock()
        fake_col.get.return_value = {
            "metadatas": [{"path": "/kb/Docs/file.md"}]
        }

        with patch.object(vs_mod, "get_or_create_collection", return_value=fake_col):
            result = _get_indexed_file_hashes("Docs")

        assert result.get("/kb/Docs/file.md") == ""

    def test_old_file_hash_key_returns_empty_not_hash(self):
        """Verify old 'file_hash' key is NOT read (confirming the bug was real)."""
        from kb_agent_mcp.cli.status import _get_indexed_file_hashes
        import kb_agent_mcp.vector_store as vs_mod

        fake_col = MagicMock()
        fake_col.get.return_value = {
            "metadatas": [{"path": "/kb/Docs/file.md", "file_hash": "SHOULD_NOT_READ"}]
        }

        with patch.object(vs_mod, "get_or_create_collection", return_value=fake_col):
            result = _get_indexed_file_hashes("Docs")

        # file_hash is the OLD wrong key — should come back as ""
        assert result.get("/kb/Docs/file.md") == ""


# ══════════════════════════════════════════════════════════════════════════════
# BUG-4 — watch.py: import re at top; _purge_domain works without NameError
# ══════════════════════════════════════════════════════════════════════════════

class TestBug4WatchReImport:
    """'re' must be a top-level import; _purge_domain must not raise NameError."""

    def test_re_is_imported_at_module_level(self):
        """'re' must appear in the watch module namespace after import."""
        import kb_agent_mcp.cli.watch as watch_mod
        assert "re" in vars(watch_mod), (
            "'re' should be a top-level name in watch.py (not deferred)"
        )

    @pytest.mark.asyncio
    async def test_purge_domain_calls_delete_collection_no_name_error(self):
        """_purge_domain must call vector_store.delete_collection without NameError."""
        import kb_agent_mcp.cli.watch as watch_mod
        import kb_agent_mcp.vector_store as vs_mod

        deleted: list[str] = []

        def fake_delete(domain):
            deleted.append(domain)

        with patch.object(vs_mod, "delete_collection", side_effect=fake_delete):
            with patch("kb_agent_mcp.orchestrator.refresh_agents", new=AsyncMock()):
                watcher = watch_mod._KBWatcher.__new__(watch_mod._KBWatcher)
                await watcher._purge_domain("MyDomain")

        assert "MyDomain" in deleted


# ══════════════════════════════════════════════════════════════════════════════
# BUG-5 — _patch_env_key must not produce duplicate keys
# ══════════════════════════════════════════════════════════════════════════════

class TestBug5PatchEnvKeyNoDuplicates:
    """_patch_env_key must replace only one occurrence and produce exactly one key."""

    def test_simple_replacement(self, tmp_path):
        from kb_agent_mcp.cli.setup import _patch_env_key
        env = tmp_path / ".env"
        env.write_text("FOO=old\nBAR=keep\n")
        _patch_env_key(env, "FOO", "new")
        lines = env.read_text().splitlines()
        assert lines.count("FOO=new") == 1
        assert "BAR=keep" in lines

    def test_commented_key_replaced_when_no_live_key(self, tmp_path):
        from kb_agent_mcp.cli.setup import _patch_env_key
        env = tmp_path / ".env"
        env.write_text("# FOO=/path/to/old\n")
        _patch_env_key(env, "FOO", "/new/path")
        lines = env.read_text().splitlines()
        assert lines.count("FOO=/new/path") == 1

    def test_no_duplicate_when_both_commented_and_live_form_present(self, tmp_path):
        """Core regression: both commented and uncommented form → exactly one output line."""
        from kb_agent_mcp.cli.setup import _patch_env_key
        env = tmp_path / ".env"
        env.write_text(
            "# KB_ROOT=/old/path\n"
            "SOME_OTHER=value\n"
            "KB_ROOT=/live/path\n"
        )
        _patch_env_key(env, "KB_ROOT", "/new/path")
        content = env.read_text()
        lines = content.splitlines()
        kb_lines = [l for l in lines if l.startswith("KB_ROOT=")]
        assert len(kb_lines) == 1, (
            f"Expected exactly 1 KB_ROOT= line, got {len(kb_lines)}: {lines}"
        )
        assert kb_lines[0] == "KB_ROOT=/new/path"
        # The commented form should have been dropped
        assert not any("# KB_ROOT=" in l for l in lines)
        # Unrelated key preserved
        assert "SOME_OTHER=value" in lines

    def test_key_appended_when_not_found(self, tmp_path):
        from kb_agent_mcp.cli.setup import _patch_env_key
        env = tmp_path / ".env"
        env.write_text("EXISTING=yes\n")
        _patch_env_key(env, "NEW_KEY", "hello")
        assert "NEW_KEY=hello" in env.read_text()

    def test_only_live_key_replaced_when_no_comment(self, tmp_path):
        """When only a live key exists (no comment), it is replaced exactly once."""
        from kb_agent_mcp.cli.setup import _patch_env_key
        env = tmp_path / ".env"
        env.write_text("A=1\nKB_ROOT=/old\nB=2\n")
        _patch_env_key(env, "KB_ROOT", "/new")
        lines = env.read_text().splitlines()
        assert lines.count("KB_ROOT=/new") == 1
        assert "A=1" in lines
        assert "B=2" in lines


# ══════════════════════════════════════════════════════════════════════════════
# BUG-6 — requirements.txt must contain all core packages
# ══════════════════════════════════════════════════════════════════════════════

class TestBug6RequirementsTxt:
    """requirements.txt must list every package in pyproject.toml dependencies."""

    REQUIRED_PACKAGES = [
        "fastmcp",
        "chromadb",
        "python-docx",
        "rich",
        "pyyaml",
        # packages present before the fix
        "httpx",
        "numpy",
        "scikit-learn",
        "watchdog",
        "pypdf",
        "python-pptx",
        "openpyxl",
        "sentence-transformers",
    ]

    def _read_requirements(self) -> str:
        req = Path(__file__).parent.parent / "requirements.txt"
        assert req.exists(), "requirements.txt not found"
        return req.read_text().lower()

    @pytest.mark.parametrize("pkg", REQUIRED_PACKAGES)
    def test_package_present(self, pkg):
        content = self._read_requirements()
        assert pkg.lower() in content, (
            f"'{pkg}' is missing from requirements.txt"
        )
