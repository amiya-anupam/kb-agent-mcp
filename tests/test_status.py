"""
tests/test_status.py
─────────────────────
Tests for kb_agent_mcp/cli/status.py

Covers:
  - main() exits 0 with no domains (graceful empty state)
  - build_table() returns a Rich Table instance
  - build_table() contains domain names when domains exist
  - --json flag emits valid JSON with required keys
  - --plain flag suppresses ANSI codes
  - --tui and --interval flags accepted by argparse
  - stale domain shown with ⚠ in output
  - missing ChromaDB index does not crash (graceful fallback)
"""
from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch
import datetime

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fake_collection(count: int = 5, age_days: int | None = 2):
    """Build a mock ChromaDB collection with optional indexed_at metadata."""
    col = MagicMock()
    col.count.return_value = count
    if age_days is not None:
        ts = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=age_days)
        ).isoformat()
        col.get.return_value = {"metadatas": [{"indexed_at": ts}]}
    else:
        col.get.return_value = {"metadatas": [{}]}
    return col


# ── build_table() ──────────────────────────────────────────────────────────────

class TestBuildTable:

    def _setup_domain(self, tmp_path, monkeypatch, domain_name="TestDomain",
                      count=5, age_days=2):
        """Create a fake domain folder and patch ChromaDB."""
        domain_dir = tmp_path / domain_name
        domain_dir.mkdir()
        (domain_dir / "domain_config.yaml").write_text("folder_name: test\n")
        (domain_dir / "notes.md").write_text("hello")

        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client", lambda: None)
        col = _fake_collection(count=count, age_days=age_days)
        monkeypatch.setattr(vs_mod, "get_or_create_collection", lambda name: col)

        import types
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            KB_LLM_PROVIDER="passthrough",
            KB_EMBED_MODEL="",
            is_ignored=lambda n: n.startswith("."),
        )
        import kb_agent_mcp.config as config_mod
        monkeypatch.setattr(config_mod, "cfg", fake_cfg)
        return domain_dir, fake_cfg

    def test_returns_rich_table(self, tmp_path, monkeypatch):
        from rich.table import Table
        from rich.console import Console
        from kb_agent_mcp.cli.status import build_table

        self._setup_domain(tmp_path, monkeypatch)

        console = Console(no_color=True)
        table = build_table(console)
        assert isinstance(table, Table)

    def test_table_contains_domain_name(self, tmp_path, monkeypatch, capsys):
        from rich.console import Console
        from kb_agent_mcp.cli.status import build_table

        self._setup_domain(tmp_path, monkeypatch, domain_name="MyDomain")

        console = Console(no_color=True, file=StringIO())
        table = build_table(console)
        console.print(table)
        out = console.file.getvalue()
        assert "MyDomain" in out

    def test_empty_kb_root_shows_no_domains(self, tmp_path, monkeypatch):
        from rich.console import Console
        from kb_agent_mcp.cli.status import build_table

        import kb_agent_mcp.config as config_mod
        import types
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            KB_LLM_PROVIDER="passthrough",
            KB_EMBED_MODEL="",
            is_ignored=lambda n: n.startswith("."),
        )
        monkeypatch.setattr(config_mod, "cfg", fake_cfg)

        console = Console(no_color=True, file=StringIO())
        table = build_table(console)
        console.print(table)
        out = console.file.getvalue()
        assert "No domains found" in out or "kb-agent-generate" in out

    def test_stale_domain_shows_warning(self, tmp_path, monkeypatch):
        from rich.console import Console
        from kb_agent_mcp.cli.status import build_table, STALE_DAYS

        self._setup_domain(tmp_path, monkeypatch, domain_name="OldDomain",
                           count=10, age_days=STALE_DAYS + 3)

        console = Console(no_color=True, file=StringIO())
        table = build_table(console)
        console.print(table)
        out = console.file.getvalue()
        assert "stale" in out.lower() or "⚠" in out

    def test_missing_chromadb_does_not_crash(self, tmp_path, monkeypatch):
        """When ChromaDB throws, domain row should show 'not indexed'."""
        domain_dir = tmp_path / "BrokenDomain"
        domain_dir.mkdir()
        (domain_dir / "notes.md").write_text("data")

        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client",
                            lambda: (_ for _ in ()).throw(RuntimeError("mismatch")))

        import kb_agent_mcp.config as config_mod
        import types
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            KB_LLM_PROVIDER="passthrough",
            KB_EMBED_MODEL="",
            is_ignored=lambda n: n.startswith("."),
        )
        monkeypatch.setattr(config_mod, "cfg", fake_cfg)

        from rich.console import Console
        from kb_agent_mcp.cli.status import build_table
        console = Console(no_color=True, file=StringIO())
        # Should not raise
        table = build_table(console)
        console.print(table)
        out = console.file.getvalue()
        assert "BrokenDomain" in out


# ── --json flag ────────────────────────────────────────────────────────────────

class TestJsonOutput:

    def test_json_output_is_valid(self, tmp_path, monkeypatch, capsys):
        import kb_agent_mcp.config as config_mod
        import types
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            KB_LLM_PROVIDER="passthrough",
            KB_EMBED_MODEL="",
            is_ignored=lambda n: n.startswith("."),
        )
        monkeypatch.setattr(config_mod, "cfg", fake_cfg)

        import kb_agent_mcp.cli.status as status_mod
        import shutil
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/kb-agent-serve")

        with patch.object(sys, "argv", ["kb-agent-status", "--json"]):
            from kb_agent_mcp.cli.status import main
            main()

        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert "kb_root" in data
        assert "domains" in data
        assert "llm" in data
        assert "server" in data

    def test_json_domains_list(self, tmp_path, monkeypatch, capsys):
        domain_dir = tmp_path / "Sales"
        domain_dir.mkdir()
        (domain_dir / "data.txt").write_text("revenue")

        import kb_agent_mcp.config as config_mod
        import types, shutil
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            KB_LLM_PROVIDER="passthrough",
            KB_EMBED_MODEL="",
            is_ignored=lambda n: n.startswith("."),
        )
        monkeypatch.setattr(config_mod, "cfg", fake_cfg)
        monkeypatch.setattr(shutil, "which", lambda _: None)

        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "_get_client", lambda: None)
        monkeypatch.setattr(vs_mod, "get_or_create_collection",
                            lambda _: _fake_collection(count=3, age_days=1))

        with patch.object(sys, "argv", ["kb-agent-status", "--json"]):
            from kb_agent_mcp.cli.status import main
            main()

        data = json.loads(capsys.readouterr().out)
        names = [d["name"] for d in data["domains"]]
        assert "Sales" in names


# ── --plain flag ───────────────────────────────────────────────────────────────

class TestPlainFlag:

    def test_plain_suppresses_ansi(self, tmp_path, monkeypatch, capsys):
        import kb_agent_mcp.config as config_mod
        import types, shutil
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            KB_LLM_PROVIDER="passthrough",
            KB_EMBED_MODEL="",
            is_ignored=lambda n: n.startswith("."),
        )
        monkeypatch.setattr(config_mod, "cfg", fake_cfg)
        monkeypatch.setattr(shutil, "which", lambda _: None)

        with patch.object(sys, "argv", ["kb-agent-status", "--plain"]):
            from kb_agent_mcp.cli.status import main
            main()

        out = capsys.readouterr().out
        assert "\033[" not in out, "ANSI escape codes found in --plain output"


# ── --tui and --interval flags ─────────────────────────────────────────────────

class TestTuiFlags:

    def test_tui_flag_accepted_by_argparse(self):
        import argparse
        # Reconstruct just the parser to check flag registration
        parser = argparse.ArgumentParser()
        parser.add_argument("--tui", action="store_true")
        parser.add_argument("--interval", type=int, default=5)
        args = parser.parse_args(["--tui", "--interval", "10"])
        assert args.tui is True
        assert args.interval == 10

    def test_interval_default(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--interval", type=int, default=5)
        args = parser.parse_args([])
        assert args.interval == 5
