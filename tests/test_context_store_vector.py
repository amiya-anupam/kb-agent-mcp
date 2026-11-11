"""Tests for indexing context-store digests as source=digest chunks (Phase 3.8)."""
from __future__ import annotations

import hashlib
import re

import pytest

import kb_agent_mcp.vector_store as vs


class _Cfg:
    """Delegates to the current vs.cfg but pins the KB root."""

    def __init__(self, base, root):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_root", root)

    @property
    def kb_root_path(self):
        return self._root

    def __getattr__(self, name):
        return getattr(self._base, name)


def _fake_embed(text: str) -> list[float]:
    """Deterministic bag-of-words hash embedding (32 dims, L2-normalised)."""
    vec = [0.0] * 32
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 32] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = (tmp_path / "kb").resolve()
    (root / "BizOps").mkdir(parents=True)
    (root / "BizOps" / "sales.csv").write_text(
        "Region,Amount\n" + "\n".join(f"{r},{i}" for i, r in enumerate(["EMEA", "APAC"] * 20)) + "\n",
        encoding="utf-8")
    (root / "BizOps" / "notes.md").write_text("# Plan\n\nRenew annuity contracts in March.\n", encoding="utf-8")
    monkeypatch.setattr(vs, "cfg", _Cfg(vs.cfg, root))
    monkeypatch.setattr(vs, "_embed_sync", _fake_embed)
    monkeypatch.setattr(vs, "_embed_cache", vs._embed_cache.__class__())
    return root


def _chunks(domain="BizOps"):
    got = vs.get_or_create_collection(domain).get(include=["metadatas", "documents"])
    return dict(zip(got["ids"], zip(got["metadatas"], got["documents"])))


def test_tabular_file_gets_digest_chunks(kb):
    assert vs._upsert_file_sync("BizOps", kb / "BizOps" / "sales.csv") is True
    rows = _chunks()
    digest = {i: m for i, (m, _) in rows.items() if m["source"] == "digest"}
    raw = {i: m for i, (m, _) in rows.items() if m["source"] == "raw"}
    assert digest and raw
    assert all("::chunk_digest_" in i for i in digest)
    assert {m["path"] for m in digest.values()} == {"BizOps/sales.csv"}
    assert {m["name"] for m in digest.values()} == {"sales.csv"}
    assert all(m["chunk_total"] == len(digest) for m in digest.values())


def test_digest_text_describes_the_file(kb):
    vs._upsert_file_sync("BizOps", kb / "BizOps" / "sales.csv")
    text = "\n".join(d for _, (m, d) in _chunks().items() if m["source"] == "digest")
    assert "Region" in text and "Amount" in text


def test_non_digestable_file_gets_raw_chunks_only(kb):
    f = kb / "BizOps" / "data.txt"
    f.write_text('plain text content', encoding="utf-8")
    vs._upsert_file_sync("BizOps", f)
    assert {m["source"] for m, _ in _chunks().values()} == {"raw"}


def test_file_outside_kb_root_gets_raw_chunks_only(kb, tmp_path):
    f = tmp_path / "elsewhere.md"
    f.write_text("# Hello\n\nSome text.\n", encoding="utf-8")
    vs._upsert_file_sync("BizOps", f)
    assert {m["source"] for m, _ in _chunks().values()} == {"raw"}


def test_digest_failure_falls_back_to_raw(kb, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("nope")
    monkeypatch.setattr("kb_agent_mcp.context_store.sync.digest_text_for", boom)
    assert vs._upsert_file_sync("BizOps", kb / "BizOps" / "sales.csv") is True
    assert {m["source"] for m, _ in _chunks().values()} == {"raw"}


def test_delete_removes_digest_chunks(kb):
    f = kb / "BizOps" / "sales.csv"
    vs._upsert_file_sync("BizOps", f)
    vs._delete_file_sync("BizOps", f)
    assert _chunks() == {}


def test_reindex_after_change_replaces_digest_chunks(kb):
    f = kb / "BizOps" / "sales.csv"
    vs._upsert_file_sync("BizOps", f)
    f.write_text("Colour,Weight\nred,1\nblue,2\n", encoding="utf-8")
    assert vs._upsert_file_sync("BizOps", f) is True
    text = "\n".join(d for m, d in _chunks().values() if m["source"] == "digest")
    assert "Colour" in text and "Region" not in text


def test_search_on_column_names_surfaces_digest(kb):
    vs._upsert_file_sync("BizOps", kb / "BizOps" / "sales.csv")
    vs._upsert_file_sync("BizOps", kb / "BizOps" / "notes.md")
    hits = vs._search_sync("BizOps", "which columns does the sales csv have: Region and Amount", top_n=2)
    assert hits and hits[0]["path"] == "BizOps/sales.csv"
    assert "Region" in hits[0]["summary"] and "Amount" in hits[0]["summary"]


def test_unchanged_file_is_skipped_once_digest_indexed(kb):
    f = kb / "BizOps" / "sales.csv"
    assert vs._upsert_file_sync("BizOps", f) is True
    assert vs._upsert_file_sync("BizOps", f) is False


def test_pre_digest_index_is_upgraded_without_file_change(kb):
    f = kb / "BizOps" / "sales.csv"
    vs._upsert_file_sync("BizOps", f)
    col = vs.get_or_create_collection("BizOps")
    col.delete(ids=[i for i in _chunks() if "::chunk_digest_" in i])   # simulate old index
    assert vs._upsert_file_sync("BizOps", f) is True
    assert any(m["source"] == "digest" for m, _ in _chunks().values())


def test_non_digestable_unchanged_file_is_skipped(kb):
    f = kb / "BizOps" / "data.txt"
    f.write_text('plain text content', encoding="utf-8")
    assert vs._upsert_file_sync("BizOps", f) is True
    assert vs._upsert_file_sync("BizOps", f) is False
