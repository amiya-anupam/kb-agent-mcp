"""Tests for the context store INDEX.md / MANIFEST.md generator and path mapping."""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from kb_agent_mcp.context_store import index as ix
from kb_agent_mcp.context_store.frontmatter import parse_front_matter
from kb_agent_mcp.context_store.paths import (
    INDEX_NAME, MANIFEST_NAME, digest_path, domain_slug,
)


def _digest(ctx: Path, slug: str, rel_under_domain: str, domain: str, *, typ="xlsx",
            rows=10, period="", partial=False, empty=False, kws=("alpha", "beta")) -> Path:
    p = ctx / slug / (rel_under_domain + ".md")
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"path: {domain}/{rel_under_domain}", "sha256: " + "0" * 64, f"type: {typ}",
          f"rows: {rows}" if typ == "xlsx" else f"slides: {rows}"]
    if period:
        fm.append(f"period: {period}")
    fm += [f"extraction: {'empty' if empty else 'ok'}", f"partial: {'true' if partial else 'false'}",
           "keywords: [" + ", ".join(f'"{k}"' for k in kws) + "]", "---", "", "# body", ""]
    p.write_text("\n".join(fm), encoding="utf-8")
    return p


@pytest.fixture
def ctx(tmp_path):
    c = tmp_path / "ctx"
    _digest(c, "bizops", "Revenue/a.xlsx", "BizOps", rows=1234, period="2026Q1 to 2026Q2")
    _digest(c, "bizops", "Revenue/b.xlsx", "BizOps", partial=True)
    _digest(c, "bizops", "notes.pptx", "BizOps", typ="pptx", rows=7)
    _digest(c, "ace_docs", "guide.pptx", "ACE Docs", typ="pptx", empty=True)
    return c


def test_domain_slug_and_digest_path(tmp_path):
    assert domain_slug("ACE Docs") == "ace_docs"
    assert domain_slug("CP4I Docs") == "cp4i_docs"
    root = tmp_path / "kb"
    src = root / "BizOps" / "Revenue" / "a.xlsx"
    assert digest_path(tmp_path / "c", root, src) == tmp_path / "c" / "bizops" / "Revenue" / "a.xlsx.md"
    with pytest.raises(ValueError):
        digest_path(tmp_path / "c", root, root / "loose.xlsx")


def test_build_creates_indexes_and_manifest(ctx):
    changed = ix.build_indexes(ctx)
    assert ctx / MANIFEST_NAME in changed
    top = (ctx / "bizops" / INDEX_NAME).read_text()
    assert "# BizOps" in top and "3 digested files (1 here, 2 in sub-folders)" in top
    assert "[Revenue/](Revenue/INDEX.md) — 2 files (2 xlsx)" in top
    assert "[notes.pptx](notes.pptx.md) — pptx, 7 slides; alpha, beta" in top
    sub = (ctx / "bizops" / "Revenue" / INDEX_NAME).read_text()
    assert "[a.xlsx](a.xlsx.md) — xlsx, 1,234 rows, 2026Q1 to 2026Q2; alpha, beta" in sub
    assert "partial" in sub
    assert parse_front_matter(top)["domain"] == "BizOps"


def test_manifest_one_line_per_domain(ctx):
    ix.build_indexes(ctx, {"bizops": Counter({".png": 2})})
    text = (ctx / MANIFEST_NAME).read_text()
    lines = [l for l in text.splitlines() if l.startswith("- ")]
    assert len(lines) == 2
    biz = next(l for l in lines if "BizOps" in l)
    assert "3 digests (2 xlsx, 1 pptx)" in biz and "1 partial" in biz and "2 not digested" in biz
    assert "bizops/INDEX.md" in biz and "updated 20" in biz
    ace = next(l for l in lines if "ACE Docs" in l)
    assert "1 unreadable" in ace
    assert "Not digested" in (ctx / "bizops" / INDEX_NAME).read_text()


def test_rebuild_is_stable_and_reports_no_change(ctx):
    ix.build_indexes(ctx)
    before = {p: p.read_bytes() for p in ctx.rglob("*.md")}
    assert ix.build_indexes(ctx) == []
    assert before == {p: p.read_bytes() for p in ctx.rglob("*.md")}


def test_deleted_digests_update_and_prune_indexes(ctx):
    ix.build_indexes(ctx)
    for f in (ctx / "bizops" / "Revenue").glob("*.md"):
        if f.name != INDEX_NAME:
            f.unlink()
    ix.build_indexes(ctx)
    assert not (ctx / "bizops" / "Revenue" / INDEX_NAME).exists()
    assert "Revenue/" not in (ctx / "bizops" / INDEX_NAME).read_text()
    for f in (ctx / "ace_docs").glob("*.pptx.md"):
        f.unlink()
    ix.build_indexes(ctx)
    assert not (ctx / "ace_docs" / INDEX_NAME).exists()
    assert "ACE Docs" not in (ctx / MANIFEST_NAME).read_text()


def test_non_digest_markdown_is_ignored(ctx):
    (ctx / "bizops" / "NOTES.md").write_text("# hand written\n", encoding="utf-8")
    ix.build_indexes(ctx)
    assert "NOTES" not in (ctx / "bizops" / INDEX_NAME).read_text()
    assert (ctx / "bizops" / "NOTES.md").exists()


def test_large_folder_fits_budget(tmp_path):
    c = tmp_path / "ctx"
    for i in range(400):
        _digest(c, "big", f"Quarterly report number {i:04d} for the region.xlsx", "Big",
                kws=("revenue", "attrition", "renewal"))
    ix.build_indexes(c)
    text = (c / "big" / INDEX_NAME).read_text()
    assert len(text.encode()) <= ix.INDEX_BUDGET
    assert "400 digested files" in text


def test_manifest_budget_with_many_domains(tmp_path):
    c = tmp_path / "ctx"
    for i in range(60):
        _digest(c, f"domain_{i:02d}", "f.xlsx", f"Domain {i:02d}", kws=tuple(f"kw{j}" for j in range(10)))
    ix.build_indexes(c)
    assert len((c / MANIFEST_NAME).read_bytes()) <= ix.MANIFEST_BUDGET


def test_missing_context_dir_is_noop(tmp_path):
    assert ix.build_indexes(tmp_path / "nope") == []
