"""Tests for context store sync (incremental regeneration) and read_context."""
from __future__ import annotations

from pathlib import Path

import pytest

from kb_agent_mcp.context_store import sync as cs
from kb_agent_mcp.context_store.frontmatter import parse_front_matter


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / "kb"
    (root / "BizOps" / "Revenue").mkdir(parents=True)
    (root / "Guides").mkdir()
    (root / "BizOps" / "Revenue" / "sales.csv").write_text(
        "Region,Amount\nEMEA,10\nAPAC,20\nEMEA,5\n", encoding="utf-8")
    (root / "BizOps" / "notes.md").write_text(
        "# Plan\n\nWe will renew the annuity contracts in March.\n", encoding="utf-8")
    (root / "Guides" / "how-to.md").write_text(
        "# Setup\n\nInstall the tool before running the first import.\n", encoding="utf-8")
    (root / "BizOps" / "logo.png").write_bytes(b"\x89PNG\r\n")
    return root


def test_first_sync_builds_everything(kb):
    res = cs.sync(kb)
    assert sorted(res.built) == ["BizOps/Revenue/sales.csv", "BizOps/notes.md", "Guides/how-to.md"]
    ctx = kb / ".kb_index" / "context"
    assert (ctx / "bizops" / "Revenue" / "sales.csv.md").is_file()
    assert (ctx / "bizops" / "INDEX.md").is_file() and (ctx / "MANIFEST.md").is_file()
    assert "1 not digested" in (ctx / "MANIFEST.md").read_text()
    assert res.failed == {} and res.changed


def test_second_sync_is_a_noop(kb):
    cs.sync(kb)
    res = cs.sync(kb)
    assert res.built == [] and res.removed == [] and res.unchanged == 3
    assert res.indexes_changed == 0 and not res.changed


def test_only_changed_file_is_rebuilt(kb):
    cs.sync(kb)
    (kb / "BizOps" / "notes.md").write_text("# Plan\n\nWe will cancel everything.\n", encoding="utf-8")
    res = cs.sync(kb)
    assert res.built == ["BizOps/notes.md"] and res.unchanged == 2
    text = (kb / ".kb_index" / "context" / "bizops" / "notes.md.md").read_text()
    assert "cancel everything" in text


def test_touching_without_changing_content_does_not_rebuild(kb):
    cs.sync(kb)
    p = kb / "BizOps" / "notes.md"
    p.write_bytes(p.read_bytes())
    assert cs.sync(kb).built == []


def test_deleted_source_removes_digest_and_index_entry(kb):
    cs.sync(kb)
    (kb / "BizOps" / "Revenue" / "sales.csv").unlink()
    res = cs.sync(kb)
    assert res.removed == ["bizops/Revenue/sales.csv.md"]
    ctx = kb / ".kb_index" / "context"
    assert not (ctx / "bizops" / "Revenue").exists()
    assert "Revenue/" not in (ctx / "bizops" / "INDEX.md").read_text()


def test_deleted_domain_folder_removes_its_digests(kb):
    import shutil
    cs.sync(kb)
    shutil.rmtree(kb / "Guides")
    cs.sync(kb)
    ctx = kb / ".kb_index" / "context"
    assert not (ctx / "guides").exists()
    assert "Guides" not in (ctx / "MANIFEST.md").read_text()


def test_hand_written_markdown_in_context_dir_survives(kb):
    cs.sync(kb)
    mine = kb / ".kb_index" / "context" / "bizops" / "MY_NOTES.md"
    mine.write_text("# mine\n", encoding="utf-8")
    cs.sync(kb)
    assert mine.exists()


def test_force_rebuilds_all(kb):
    cs.sync(kb)
    res = cs.sync(kb, force=True)
    assert len(res.built) == 3
    assert res.indexes_changed == 0                     # identical output


def test_domain_filter(kb):
    res = cs.sync(kb, domains=["Guides"])
    assert res.built == ["Guides/how-to.md"]
    assert not (kb / ".kb_index" / "context" / "bizops").exists()


def test_one_bad_file_does_not_stop_the_run(kb, monkeypatch):
    real = cs.build_digest_for

    def flaky(path, root=None):
        if Path(path).name == "notes.md":
            raise RuntimeError("boom")
        return real(path, root)

    monkeypatch.setattr(cs, "build_digest_for", flaky)
    res = cs.sync(kb)
    assert "BizOps/notes.md" in res.failed and "boom" in res.failed["BizOps/notes.md"]
    assert len(res.built) == 2


def test_digest_front_matter_matches_source(kb):
    cs.sync(kb)
    fm = parse_front_matter((kb / ".kb_index" / "context" / "bizops" / "notes.md.md").read_text())
    assert fm["path"] == "BizOps/notes.md" and fm["type"] == "md"


def test_read_context(kb):
    cs.sync(kb)
    ctx = kb / ".kb_index" / "context"
    assert "Knowledge base manifest" in cs.read_context("manifest", ctx)
    assert "# BizOps" in cs.read_context("index", ctx, domain="BizOps")
    assert "BizOps / Revenue" in cs.read_context("index", ctx, domain="BizOps", path="Revenue")
    assert "sales.csv" in cs.read_context("digest", ctx, path="BizOps/Revenue/sales.csv")
    with pytest.raises(FileNotFoundError):
        cs.read_context("digest", ctx, path="BizOps/missing.xlsx")
    with pytest.raises(ValueError):
        cs.read_context("digest", ctx, path="BizOps/../../etc/passwd")
    with pytest.raises(ValueError):
        cs.read_context("index", ctx)
    with pytest.raises(ValueError):
        cs.read_context("bogus", ctx)


def test_same_size_edit_is_detected(kb):
    """A same-length edit with a newer mtime must still be re-digested (sha256 decides)."""
    import os
    cs.sync(kb)
    p = kb / "BizOps" / "notes.md"
    old = p.read_text(encoding="utf-8")
    p.write_text(old.replace("March", "April"), encoding="utf-8")   # March -> April changes length; pad
    p.write_text(old.replace("renew", "cease"), encoding="utf-8")   # same length
    assert len(p.read_bytes()) == len(old.encode())
    future = p.stat().st_mtime + 10
    os.utime(p, (future, future))
    assert cs.sync(kb).built == ["BizOps/notes.md"]


def test_safe_sync_never_raises(tmp_path):
    msgs: list[str] = []
    assert cs.safe_sync(tmp_path / "does-not-exist", log=msgs.append) is None
    assert msgs and "failed" in msgs[0]


def test_safe_sync_logs_only_when_something_changed(kb):
    msgs: list[str] = []
    assert cs.safe_sync(kb, log=msgs.append).built
    assert len(msgs) == 1 and "context store:" in msgs[0]
    cs.safe_sync(kb, log=msgs.append)
    assert len(msgs) == 1
