"""
tests/test_path_a.py
─────────────────────
Tests for the three Path-A CLI improvements:

  A1 — kb-agent-status --diff  (status.py: _diff_domain, print_diff, --diff flag)
  A2 — clipboard copy helper   (setup.py: _copy_to_clipboard)
  A3 — Rich keyword editor     (setup.py: _kw_editor_prompt, interactive_keyword_editor)
"""
from __future__ import annotations

import sys
import types
import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# A1 — --diff flag and diff logic
# ══════════════════════════════════════════════════════════════════════════════

class TestDiffDomain:
    """Unit tests for _diff_domain() in status.py."""

    def _setup(self, tmp_path, monkeypatch, hashes=None, indexed_at_offset_days=-1):
        """
        Create a single domain folder with one file and patch ChromaDB.

        hashes: dict of {abs_path_str: hash} to return from _get_indexed_file_hashes.
                Pass None to simulate no index (empty dict).
        indexed_at_offset_days: days *before* now for the indexed_at timestamp.
                                Negative = in the past. None = no timestamp.
        """
        domain_dir = tmp_path / "TestDomain"
        domain_dir.mkdir()
        doc = domain_dir / "notes.md"
        doc.write_text("hello")

        # Build indexed_at timestamp
        indexed_at: str | None = None
        if indexed_at_offset_days is not None:
            dt = (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=indexed_at_offset_days)
            )
            indexed_at = dt.isoformat()

        # Patch get_indexed_file_hashes
        if hashes is None:
            fake_hashes: dict = {}
        else:
            fake_hashes = hashes

        from kb_agent_mcp.cli import status as status_mod
        monkeypatch.setattr(status_mod, "_get_indexed_file_hashes", lambda _: fake_hashes)

        # Patch get_or_create_collection for indexed_at lookup
        col = MagicMock()
        if indexed_at:
            col.get.return_value = {"metadatas": [{"indexed_at": indexed_at}]}
        else:
            col.get.return_value = {"metadatas": [{}]}

        import kb_agent_mcp.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "get_or_create_collection", lambda _: col)

        return domain_dir, doc

    def test_no_index_all_files_missing(self, tmp_path, monkeypatch):
        from kb_agent_mcp.cli.status import _diff_domain
        domain_dir, doc = self._setup(tmp_path, monkeypatch, hashes=None)

        result = _diff_domain("TestDomain", tmp_path)

        assert result["no_index"] is True
        assert doc in result["missing"]
        assert result["stale"] == []
        assert result["ok"] == 0

    def test_file_in_index_is_ok(self, tmp_path, monkeypatch):
        from kb_agent_mcp.cli.status import _diff_domain
        # indexed_at = 1 day in the future → file mtime is always before it → ok
        domain_dir, doc = self._setup(tmp_path, monkeypatch,
                                      hashes=None,
                                      indexed_at_offset_days=1)
        import kb_agent_mcp.cli.status as status_mod
        monkeypatch.setattr(status_mod, "_get_indexed_file_hashes",
                            lambda _: {str(doc.resolve()): "abc123"})

        result = _diff_domain("TestDomain", tmp_path)

        assert result["no_index"] is False
        assert result["missing"] == []
        assert result["stale"] == []
        assert result["ok"] == 1

    def test_file_not_in_index_is_missing(self, tmp_path, monkeypatch):
        from kb_agent_mcp.cli.status import _diff_domain
        # Hashes contain a different path — doc is not indexed
        domain_dir, doc = self._setup(tmp_path, monkeypatch,
                                      hashes={"/some/other/file.md": "xyz"},
                                      indexed_at_offset_days=-1)

        result = _diff_domain("TestDomain", tmp_path)

        assert doc in result["missing"]
        assert result["stale"] == []

    def test_file_modified_after_index_is_stale(self, tmp_path, monkeypatch):
        from kb_agent_mcp.cli.status import _diff_domain
        domain_dir, doc = self._setup(tmp_path, monkeypatch,
                                      hashes=None,
                                      # indexed_at is 2 days ago
                                      indexed_at_offset_days=-2)
        import kb_agent_mcp.cli.status as status_mod
        monkeypatch.setattr(status_mod, "_get_indexed_file_hashes",
                            lambda _: {str(doc.resolve()): "abc"})

        # Touch the file so mtime > indexed_at
        import os, time
        future_mtime = time.time() + 10   # set mtime 10 s in the future relative to now
        os.utime(doc, (future_mtime, future_mtime))

        result = _diff_domain("TestDomain", tmp_path)

        assert doc in result["stale"]
        assert result["missing"] == []
        assert result["ok"] == 0


class TestPrintDiff:
    """Integration tests for print_diff() output."""

    def _fake_cfg(self, tmp_path, monkeypatch):
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            is_ignored=lambda n: n.startswith("."),
        )
        import kb_agent_mcp.config as config_mod
        monkeypatch.setattr(config_mod, "cfg", fake_cfg)
        return fake_cfg

    def test_empty_root_prints_no_domains(self, tmp_path, monkeypatch):
        from rich.console import Console
        from kb_agent_mcp.cli.status import print_diff
        self._fake_cfg(tmp_path, monkeypatch)

        console = Console(no_color=True, file=StringIO())
        print_diff(tmp_path, console)
        out = console.file.getvalue()
        assert "No domains found" in out or "kb-agent-generate" in out

    def test_clean_domain_shows_checkmark(self, tmp_path, monkeypatch):
        from rich.console import Console
        from kb_agent_mcp.cli.status import print_diff

        domain_dir = tmp_path / "CleanDomain"
        domain_dir.mkdir()
        (domain_dir / "doc.md").write_text("data")

        self._fake_cfg(tmp_path, monkeypatch)

        # Patch _diff_domain to return clean result
        import kb_agent_mcp.cli.status as status_mod
        monkeypatch.setattr(
            status_mod, "_diff_domain",
            lambda name, root: {"missing": [], "stale": [], "ok": 1, "no_index": False},
        )

        console = Console(no_color=True, file=StringIO())
        print_diff(tmp_path, console)
        out = console.file.getvalue()
        assert "CleanDomain" in out
        assert "all files indexed" in out

    def test_missing_files_listed(self, tmp_path, monkeypatch):
        from rich.console import Console
        from kb_agent_mcp.cli.status import print_diff

        domain_dir = tmp_path / "PartialDomain"
        domain_dir.mkdir()
        missing_file = domain_dir / "new.md"
        missing_file.write_text("new content")

        self._fake_cfg(tmp_path, monkeypatch)

        import kb_agent_mcp.cli.status as status_mod
        monkeypatch.setattr(
            status_mod, "_diff_domain",
            lambda name, root: {
                "missing": [missing_file], "stale": [], "ok": 0, "no_index": False
            },
        )

        console = Console(no_color=True, file=StringIO())
        print_diff(tmp_path, console)
        out = console.file.getvalue()
        assert "new.md" in out
        assert "not indexed" in out.lower()

    def test_diff_flag_accepted_by_argparse(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--diff", action="store_true")
        args = parser.parse_args(["--diff"])
        assert args.diff is True

    def test_diff_mode_calls_print_diff(self, tmp_path, monkeypatch):
        """--diff flag should route to print_diff and return without rendering a table."""
        import kb_agent_mcp.config as config_mod
        fake_cfg = types.SimpleNamespace(
            kb_root_path=tmp_path,
            is_ignored=lambda n: n.startswith("."),
        )
        monkeypatch.setattr(config_mod, "cfg", fake_cfg)

        called = []
        import kb_agent_mcp.cli.status as status_mod
        monkeypatch.setattr(status_mod, "print_diff", lambda root, console: called.append(True))

        with patch.object(sys, "argv", ["kb-agent-status", "--diff"]):
            status_mod.main()

        assert called == [True], "print_diff should have been called once"


# ══════════════════════════════════════════════════════════════════════════════
# A2 — clipboard helper
# ══════════════════════════════════════════════════════════════════════════════

class TestCopyToClipboard:

    def test_returns_true_when_command_succeeds(self, monkeypatch):
        from kb_agent_mcp.cli.setup import _copy_to_clipboard
        import shutil as _shutil

        monkeypatch.setattr(_shutil, "which", lambda cmd: "/usr/bin/pbcopy" if cmd == "pbcopy" else None)

        import subprocess as _sp
        monkeypatch.setattr(_sp, "run", lambda *a, **kw: MagicMock(returncode=0))

        assert _copy_to_clipboard("hello") is True

    def test_returns_false_when_no_command_available(self, monkeypatch):
        from kb_agent_mcp.cli.setup import _copy_to_clipboard
        import shutil as _shutil

        monkeypatch.setattr(_shutil, "which", lambda _: None)

        assert _copy_to_clipboard("hello") is False

    def test_falls_through_to_next_on_error(self, monkeypatch):
        """If pbcopy fails, tries xclip; if xclip succeeds, returns True."""
        from kb_agent_mcp.cli.setup import _copy_to_clipboard
        import shutil as _shutil, subprocess as _sp

        # pbcopy and xclip both present
        monkeypatch.setattr(_shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd in ("pbcopy", "xclip") else None)

        call_count = [0]
        def fake_run(cmd, **kw):
            call_count[0] += 1
            if cmd[0] == "pbcopy":
                raise OSError("device busy")
            return MagicMock(returncode=0)
        monkeypatch.setattr(_sp, "run", fake_run)

        result = _copy_to_clipboard("test text")
        assert result is True
        assert call_count[0] == 2  # pbcopy tried + xclip tried


# ══════════════════════════════════════════════════════════════════════════════
# A3 — Rich keyword editor
# ══════════════════════════════════════════════════════════════════════════════

class TestKwEditorPrompt:

    def test_returns_keyword_list_on_input(self, tmp_path, monkeypatch):
        from kb_agent_mcp.cli.setup import _kw_editor_prompt

        # Patch Prompt.ask to return a fixed string
        monkeypatch.setattr(
            "rich.prompt.Prompt.ask",
            lambda *a, **kw: "revenue, quota, deals",
        )

        result = _kw_editor_prompt("Sales", ["old_kw"])
        assert result == ["revenue", "quota", "deals"]

    def test_returns_none_on_empty_input(self, monkeypatch):
        from kb_agent_mcp.cli.setup import _kw_editor_prompt

        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: "")

        result = _kw_editor_prompt("Sales", [])
        assert result is None

    def test_returns_none_on_keyboard_interrupt(self, monkeypatch):
        from kb_agent_mcp.cli.setup import _kw_editor_prompt

        def _raise(*a, **kw):
            raise KeyboardInterrupt

        monkeypatch.setattr("rich.prompt.Prompt.ask", _raise)

        result = _kw_editor_prompt("Sales", [])
        assert result is None

    def test_strips_whitespace_from_keywords(self, monkeypatch):
        from kb_agent_mcp.cli.setup import _kw_editor_prompt

        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: "  foo ,  bar , baz  ")

        result = _kw_editor_prompt("Docs", [])
        assert result == ["foo", "bar", "baz"]


class TestInteractiveKeywordEditor:

    def test_yes_mode_skips_editor(self, tmp_path, capsys):
        from kb_agent_mcp.cli.setup import interactive_keyword_editor

        (tmp_path / "D").mkdir()
        interactive_keyword_editor(["D"], tmp_path, yes=True)

        out = capsys.readouterr().out
        # --yes mode: just a warning, no interactive prompts
        assert "manually" in out or "minimal" in out

    def test_no_minimal_domains_is_noop(self, tmp_path, capsys):
        from kb_agent_mcp.cli.setup import interactive_keyword_editor

        interactive_keyword_editor([], tmp_path, yes=False)
        out = capsys.readouterr().out
        assert out == ""

    def test_writes_keywords_to_yaml(self, tmp_path, monkeypatch):
        import yaml
        from kb_agent_mcp.cli.setup import interactive_keyword_editor

        domain_dir = tmp_path / "BizOps"
        domain_dir.mkdir()
        yaml_path  = domain_dir / "domain_config.yaml"
        yaml_path.write_text("folder_name: BizOps\nkeywords:\n- bizops\n")

        # Patch _confirm → True (user says yes)
        monkeypatch.setattr("kb_agent_mcp.cli.setup._confirm", lambda *a, **kw: True)
        # Patch _kw_editor_prompt → return new keywords
        monkeypatch.setattr(
            "kb_agent_mcp.cli.setup._kw_editor_prompt",
            lambda name, current: ["revenue", "quota"],
        )

        interactive_keyword_editor(["BizOps"], tmp_path, yes=False)

        data = yaml.safe_load(yaml_path.read_text())
        assert data["keywords"] == ["revenue", "quota"]

    def test_skip_domain_on_none_from_prompt(self, tmp_path, monkeypatch):
        """If _kw_editor_prompt returns None, YAML should not be modified."""
        import yaml
        from kb_agent_mcp.cli.setup import interactive_keyword_editor

        domain_dir = tmp_path / "ACE"
        domain_dir.mkdir()
        yaml_path  = domain_dir / "domain_config.yaml"
        original   = "folder_name: ACE\nkeywords:\n- ace\n"
        yaml_path.write_text(original)

        monkeypatch.setattr("kb_agent_mcp.cli.setup._confirm", lambda *a, **kw: True)
        monkeypatch.setattr(
            "kb_agent_mcp.cli.setup._kw_editor_prompt",
            lambda name, current: None,  # user skipped
        )

        interactive_keyword_editor(["ACE"], tmp_path, yes=False)

        assert yaml_path.read_text() == original
