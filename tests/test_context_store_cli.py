"""Tests for `kb-agent context` CLI, the kb_context MCP tool and the hook wiring."""
from __future__ import annotations

import asyncio
import sys

import pytest


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / "BizOps").mkdir(parents=True)
    (root / "BizOps" / "notes.md").write_text(
        "# Plan\n\nRenew the annuity contracts in March.\n", encoding="utf-8")
    (root / "BizOps" / "sales.csv").write_text("Region,Amount\nEMEA,10\nAPAC,20\n", encoding="utf-8")
    # Resolve at call time: other tests importlib.reload() the config module.
    from kb_agent_mcp.config import cfg
    monkeypatch.setattr(type(cfg), "kb_root_path", property(lambda self: root))
    return root


def _run_cli(monkeypatch, *argv):
    from kb_agent_mcp.cli import context
    monkeypatch.setattr(sys, "argv", ["kb-agent context", *argv])
    with pytest.raises(SystemExit) as exc:
        context.main()
    return exc.value.code


def test_cli_build_then_refresh(kb, monkeypatch, capsys):
    assert _run_cli(monkeypatch, "build") == 0
    out = capsys.readouterr().out
    assert "2 built" in out
    ctx = kb / ".kb_index" / "context"
    assert (ctx / "MANIFEST.md").is_file()

    assert _run_cli(monkeypatch, "refresh") == 0
    assert "0 built, 2 unchanged" in capsys.readouterr().out

    assert _run_cli(monkeypatch, "build", "--force") == 0
    assert "2 built" in capsys.readouterr().out


def test_cli_unknown_domain_fails(kb, monkeypatch, capsys):
    assert _run_cli(monkeypatch, "build", "--domain", "Nope") == 1
    assert "No such domain" in capsys.readouterr().err


def test_cli_registered_in_main():
    from kb_agent_mcp.cli import main
    assert main._SUBCOMMANDS["context"] == ("kb_agent_mcp.cli.context", "main")
    assert "context" in main._SUBCOMMAND_HELP


def test_kb_context_tool_walks_manifest_index_digest(kb):
    from kb_agent_mcp import server
    from kb_agent_mcp.context_store.sync import sync

    # Before the store exists: a readable error, not an exception
    assert "kb context build" in asyncio.run(server.kb_context("manifest")) or \
           "build" in asyncio.run(server.kb_context("manifest"))

    sync(kb)
    manifest = asyncio.run(server.kb_context("manifest"))
    assert "BizOps" in manifest
    index = asyncio.run(server.kb_context("index", domain="BizOps"))
    assert "notes.md" in index
    digest = asyncio.run(server.kb_context("digest", path="BizOps/notes.md"))
    assert "annuity" in digest
    assert asyncio.run(server.kb_context("digest", path="../../etc/passwd")).startswith("❌")
    assert asyncio.run(server.kb_context("bogus")).startswith("❌")
