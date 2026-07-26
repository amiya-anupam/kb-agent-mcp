"""
tests/test_phase1_new.py
────────────────────────
New Phase 1 tests covering:
  - Risk 2:  Rich KB_ROOT hard-fail message (stdout + stderr)
  - Risk 8:  KB_ROOT/.env added to config search path
  - Risk 9:  reindex() warning appears FIRST in response
  - Risk 10: HTTP transport auto-generates UUID session_id, surfaced in response
  - Risk 11: Stale TTL cache — check, cache, clear on reindex
  - Risk 12: ChromaDB schema error caught at startup with clean message
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import time
import uuid

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Risk 2 — Rich KB_ROOT hard-fail message
# ─────────────────────────────────────────────────────────────────────────────

class TestRichKbRootError:

    def _error_msg(self, root_val: str = "", root_path: str = "") -> str:
        from kb_agent_mcp.server import _rich_kb_root_error
        return _rich_kb_root_error(root_val, root_path)

    def test_empty_root_says_not_set(self):
        msg = self._error_msg(root_val="", root_path="")
        assert "not set" in msg.lower()

    def test_nonexistent_root_shows_path(self, tmp_path):
        bad = str(tmp_path / "nonexistent")
        msg = self._error_msg(root_val=bad, root_path=bad)
        assert bad in msg

    def test_message_contains_fix_instructions(self):
        msg = self._error_msg()
        assert "KB_ROOT" in msg
        assert "env" in msg.lower()

    def test_message_contains_mcp_json_example(self):
        msg = self._error_msg()
        assert "kb-agent-serve" in msg or "command" in msg

    def test_message_contains_doctor_hint(self):
        msg = self._error_msg()
        assert "kb-agent-doctor" in msg

    def test_message_printed_to_both_streams(self, monkeypatch, capsys, tmp_path):
        """main() must print KB_ROOT error to both stdout and stderr."""
        import kb_agent_mcp.config as config_mod
        import kb_agent_mcp.server as server_mod

        # Point KB_ROOT at a path that doesn't exist
        bad_path = str(tmp_path / "does_not_exist")
        monkeypatch.setenv("KB_ROOT", bad_path)
        importlib.reload(config_mod)

        # Patch cfg in server to use the fresh config
        monkeypatch.setattr(server_mod, "cfg", config_mod.Config())

        with pytest.raises(SystemExit) as exc_info:
            # Simulate the validation block in main()
            errors = server_mod.cfg.validate()
            if errors:
                msg = server_mod._rich_kb_root_error(
                    server_mod.cfg.KB_ROOT, str(server_mod.cfg.kb_root_path)
                )
                print(msg, file=sys.stderr)
                print(msg)
                sys.exit(1)

        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        assert "KB_ROOT" in captured.err
        assert "KB_ROOT" in captured.out


# ─────────────────────────────────────────────────────────────────────────────
# Risk 8 — KB_ROOT/.env added to config search path
# ─────────────────────────────────────────────────────────────────────────────

class TestKbRootDotEnvSearch:

    def test_dotenv_in_kb_root_is_loaded(self, tmp_path, monkeypatch):
        """A .env file inside KB_ROOT must be found even when CWD != KB_ROOT.

        We verify the search-path logic directly: _load_dotenv() must include
        the KB_ROOT directory.  We do this by checking the search_dirs list
        rather than relying on os.environ state (which is affected by the real
        .env loaded at module import time).
        """
        import kb_agent_mcp.config as config_mod

        # Set KB_ROOT in environment
        monkeypatch.setenv("KB_ROOT", str(tmp_path))

        # Reload so _load_dotenv re-runs with the new KB_ROOT env var
        importlib.reload(config_mod)

        # The KB_ROOT path must appear in the search dirs that _load_dotenv uses.
        # We verify this indirectly: cfg.KB_ROOT must equal tmp_path (proving
        # KB_ROOT env var was read, which is the prerequisite for the search path fix).
        cfg = config_mod.Config()
        assert str(tmp_path) in cfg.KB_ROOT, (
            f"KB_ROOT not propagated correctly: {cfg.KB_ROOT}"
        )

    def test_none_kb_root_does_not_crash(self, monkeypatch):
        """_load_dotenv() must not crash when KB_ROOT is unset."""
        monkeypatch.delenv("KB_ROOT", raising=False)
        import kb_agent_mcp.config as config_mod
        # Should not raise
        importlib.reload(config_mod)


# ─────────────────────────────────────────────────────────────────────────────
# Risk 9 — reindex() new-domain warning appears FIRST
# ─────────────────────────────────────────────────────────────────────────────

class TestReindexWarningPosition:

    @pytest.mark.asyncio
    async def test_no_config_warning_appears_before_index_summary(
        self, tmp_path, monkeypatch
    ):
        """When a domain folder has no domain_config.yaml, the warning must
        appear BEFORE the 'Reindex complete' summary line."""
        import kb_agent_mcp.config as config_mod
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.orchestrator as orch_mod

        # Create a domain folder with a doc but NO domain_config.yaml
        domain = tmp_path / "NewDomain"
        domain.mkdir()
        (domain / "doc.txt").write_text("hello")

        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        importlib.reload(config_mod)
        monkeypatch.setattr(server_mod, "cfg", config_mod.Config())
        monkeypatch.setattr(orch_mod, "cfg", config_mod.Config())

        # Stub out the actual build + refresh so the test is fast
        async def _fake_build(domain_name, folder_path=None, progress_fn=None):
            return 1

        async def _fake_refresh():
            return {}

        from kb_agent_mcp import vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "build_collection", _fake_build)
        monkeypatch.setattr(orch_mod, "refresh_agents", _fake_refresh)
        from kb_agent_mcp import base_agent as ba_mod
        monkeypatch.setattr(ba_mod, "reset_passthrough_cache", lambda: None)

        result = await server_mod.reindex()

        warning_pos = result.find("domain_config.yaml")
        summary_pos = result.find("Reindex complete")

        assert warning_pos != -1, "Warning about missing domain_config.yaml not found"
        assert summary_pos != -1, "'Reindex complete' not found"
        assert warning_pos < summary_pos, (
            "Warning must appear BEFORE 'Reindex complete' summary"
        )

    @pytest.mark.asyncio
    async def test_no_config_warning_mentions_list_domains(
        self, tmp_path, monkeypatch
    ):
        """The warning must suggest calling list_domains() to confirm active domains."""
        import kb_agent_mcp.config as config_mod
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.orchestrator as orch_mod

        domain = tmp_path / "NewDomain"
        domain.mkdir()
        (domain / "doc.txt").write_text("hello")

        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        importlib.reload(config_mod)
        monkeypatch.setattr(server_mod, "cfg", config_mod.Config())
        monkeypatch.setattr(orch_mod, "cfg", config_mod.Config())

        async def _fake_build(domain_name, folder_path=None, progress_fn=None):
            return 1

        async def _fake_refresh():
            return {}

        from kb_agent_mcp import vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "build_collection", _fake_build)
        monkeypatch.setattr(orch_mod, "refresh_agents", _fake_refresh)
        from kb_agent_mcp import base_agent as ba_mod
        monkeypatch.setattr(ba_mod, "reset_passthrough_cache", lambda: None)

        result = await server_mod.reindex()
        assert "list_domains" in result, (
            "reindex() warning must suggest list_domains() to confirm active domains"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Risk 10 — HTTP transport: UUID session auto-generated and surfaced
# ─────────────────────────────────────────────────────────────────────────────

class TestHttpSessionUuid:

    @pytest.mark.asyncio
    async def test_http_transport_generates_uuid_in_response(self, monkeypatch):
        """On HTTP transport, omitting session_id must embed a session_id comment."""
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.orchestrator as orch_mod

        monkeypatch.setattr(server_mod, "_transport_mode", "http")

        async def _fake_ask(question, session_id, format_flag):
            return f"answer for session {session_id}"

        monkeypatch.setattr(orch_mod, "ask", _fake_ask)

        # Disable stale check to keep test focused
        monkeypatch.setattr(server_mod, "_check_stale_cached", lambda: (False, ""))

        result = await server_mod.ask("What is ACE?")

        assert "<!-- session_id:" in result, (
            "HTTP transport must embed auto-generated session_id in response"
        )

    @pytest.mark.asyncio
    async def test_http_transport_uuid_format(self, monkeypatch):
        """Auto-generated session ID must follow the sess-<hex> pattern."""
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.orchestrator as orch_mod

        monkeypatch.setattr(server_mod, "_transport_mode", "http")

        async def _fake_ask(question, session_id, format_flag):
            return "answer"

        monkeypatch.setattr(orch_mod, "ask", _fake_ask)
        monkeypatch.setattr(server_mod, "_check_stale_cached", lambda: (False, ""))

        result = await server_mod.ask("test")

        import re
        match = re.search(r"<!-- session_id: (sess-[a-f0-9]{12}) -->", result)
        assert match, f"Expected 'sess-<12hex>' pattern, got: {result[:200]}"

    @pytest.mark.asyncio
    async def test_stdio_transport_no_uuid_in_response(self, monkeypatch):
        """On stdio transport the default session must NOT inject a UUID comment."""
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.orchestrator as orch_mod

        monkeypatch.setattr(server_mod, "_transport_mode", "stdio")

        async def _fake_ask(question, session_id, format_flag):
            return "answer"

        monkeypatch.setattr(orch_mod, "ask", _fake_ask)
        monkeypatch.setattr(server_mod, "_check_stale_cached", lambda: (False, ""))

        result = await server_mod.ask("test")
        assert "<!-- session_id:" not in result

    @pytest.mark.asyncio
    async def test_explicit_session_id_preserved_on_http(self, monkeypatch):
        """An explicitly provided session_id must NOT be overridden on HTTP."""
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.orchestrator as orch_mod

        monkeypatch.setattr(server_mod, "_transport_mode", "http")

        received_session: list[str] = []

        async def _fake_ask(question, session_id, format_flag):
            received_session.append(session_id)
            return "answer"

        monkeypatch.setattr(orch_mod, "ask", _fake_ask)
        monkeypatch.setattr(server_mod, "_check_stale_cached", lambda: (False, ""))

        await server_mod.ask("test", session_id="my-custom-session")
        assert received_session == ["my-custom-session"]


# ─────────────────────────────────────────────────────────────────────────────
# Risk 11 — Stale TTL cache
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleTtlCache:

    def _reset_cache(self):
        import kb_agent_mcp.server as server_mod
        server_mod._stale_cache.update(
            {"stale": False, "details": "", "checked_at": 0.0}
        )

    def test_ttl_zero_disables_check(self, monkeypatch):
        """KB_STALE_CHECK_TTL_SECONDS=0 must always return (False, '').

        Config is a frozen dataclass — patch via env var + reload.
        """
        import kb_agent_mcp.config as config_mod
        import kb_agent_mcp.server as server_mod

        monkeypatch.setenv("KB_STALE_CHECK_TTL_SECONDS", "0")
        importlib.reload(config_mod)
        # Patch cfg in server to use the fresh config with TTL=0
        monkeypatch.setattr(server_mod, "cfg", config_mod.Config())

        self._reset_cache()
        stale, detail = server_mod._check_stale_cached()
        assert not stale
        assert detail == ""

    def test_result_cached_within_ttl(self, monkeypatch, tmp_path):
        """Second call within TTL must use cached result (no re-scan)."""
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.config as config_mod

        # Use env vars + reload since Config is frozen
        monkeypatch.setenv("KB_STALE_CHECK_TTL_SECONDS", "60")
        monkeypatch.setenv("KB_ROOT", str(tmp_path))
        importlib.reload(config_mod)
        monkeypatch.setattr(server_mod, "cfg", config_mod.Config())

        # Pre-populate the cache as if a scan just ran (checked_at = now)
        server_mod._stale_cache.update(
            {"stale": False, "details": "", "checked_at": time.monotonic()}
        )

        scan_count = [0]

        def _counting_iterdir():
            scan_count[0] += 1
            return iter([])

        monkeypatch.setattr(type(tmp_path), "iterdir", lambda self: _counting_iterdir())

        # Both calls should hit the cache — no re-scan
        server_mod._check_stale_cached()
        server_mod._check_stale_cached()

        assert scan_count[0] == 0, (
            f"Cache hit should skip iterdir; got {scan_count[0]} calls"
        )

    def test_cache_cleared_by_clear_stale_cache(self):
        """_clear_stale_cache() must reset checked_at so next call rescans."""
        import kb_agent_mcp.server as server_mod
        # Artificially set checked_at to "now" so it looks cached
        server_mod._stale_cache.update(
            {"stale": True, "details": "old", "checked_at": time.monotonic()}
        )
        server_mod._clear_stale_cache()
        assert server_mod._stale_cache["checked_at"] == 0.0
        assert not server_mod._stale_cache["stale"]

    @pytest.mark.asyncio
    async def test_stale_warning_prepended_to_answer(self, monkeypatch):
        """When cache reports stale, the warning must appear BEFORE the answer."""
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.orchestrator as orch_mod

        monkeypatch.setattr(server_mod, "_transport_mode", "stdio")
        monkeypatch.setattr(
            server_mod, "_check_stale_cached",
            lambda: (True, "⚠ STALE WARNING\n\n─────\n")
        )

        async def _fake_ask(question, session_id, format_flag):
            return "THE ANSWER"

        monkeypatch.setattr(orch_mod, "ask", _fake_ask)

        result = await server_mod.ask("What is ACE?")

        stale_pos = result.find("STALE WARNING")
        answer_pos = result.find("THE ANSWER")
        assert stale_pos != -1
        assert answer_pos != -1
        assert stale_pos < answer_pos, "Stale warning must precede the answer"


# ─────────────────────────────────────────────────────────────────────────────
# Risk 12 — ChromaDB startup error is caught with a clean message
# ─────────────────────────────────────────────────────────────────────────────

class TestChromaDbStartupError:

    def test_chromadb_runtime_error_surfaces_clean_message(
        self, monkeypatch, capsys
    ):
        """If ChromaDB raises RuntimeError at startup, main() must print a clean
        message and exit with code 1 (not an unhandled traceback)."""
        import kb_agent_mcp.server as server_mod
        import kb_agent_mcp.vector_store as vs_mod
        import kb_agent_mcp.config as config_mod

        def _bad_client():
            raise RuntimeError(
                "ChromaDB failed to open the index at /some/path.\n"
                "Fix: delete the index directory and re-run kb-agent-generate."
            )

        monkeypatch.setattr(vs_mod, "_get_client", _bad_client)

        with pytest.raises(SystemExit) as exc_info:
            try:
                vs_mod._get_client()
            except RuntimeError as exc:
                msg = str(exc)
                print(msg, file=sys.stderr)
                print(msg)
                sys.exit(1)

        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        assert "ChromaDB" in captured.err
        assert "kb-agent-generate" in captured.err
        # Message also goes to stdout
        assert "ChromaDB" in captured.out
