"""
tests/test_ignore_unification.py
────────────────────────────────
Task 1.4 — legacy scripts and the kb_agent_mcp package must agree on which
top-level folders are knowledge domains.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT / "agents"))

import agent_base  # noqa: E402
import generate  # noqa: E402
import watch_kb  # noqa: E402
from kb_agent_mcp.config import cfg  # noqa: E402

INFRA = [".github", ".kb_index", ".pytest_cache", "kb_agent_mcp", "scripts",
         "tests", "docs", "kb_agent_mcp.egg-info", ".git", "agents", "__pycache__"]
REAL = ["ACE Docs", "BizOps", "CP4I Docs", "skills"]


@pytest.mark.parametrize("name", INFRA)
def test_infra_folders_ignored(name):
    assert agent_base.is_ignored_folder(name) is True


@pytest.mark.parametrize("name", REAL)
def test_real_domains_not_ignored(name):
    assert agent_base.is_ignored_folder(name) is False


@pytest.mark.parametrize("name", INFRA + REAL)
def test_agrees_with_package_config(name):
    assert agent_base.is_ignored_folder(name) == cfg.is_ignored(name)


def test_user_blocklist_extension_respected():
    assert agent_base.is_ignored_folder("Private", {"private"}) is True


def test_generate_discovers_only_real_domains(tmp_path):
    for name in INFRA + REAL:
        d = tmp_path / name
        d.mkdir()
        (d / "doc.md").write_text("content")
    found = generate.discover_folders(tmp_path, generate.get_blocklist())
    assert sorted(found) == sorted(REAL)


def test_watcher_discovers_only_real_domains(tmp_path, monkeypatch):
    for name in INFRA + REAL:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(watch_kb, "WATCH_ROOT", tmp_path)
    found = [p.name for p in watch_kb.discover_knowledge_folders()]
    assert sorted(found) == sorted(REAL)
