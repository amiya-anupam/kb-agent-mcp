"""
tests/test_deep_content_indexing.py
───────────────────────────────────
Phase 2: the whole document must be searchable, not just the first
KB_BUDGET_EMBED_CHARS characters, and per-file chunk count must be capped.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from kb_agent_mcp import vector_store as vs


def _index(monkeypatch, tmp_path, content: str):
    f = tmp_path / "big.md"
    f.write_text(content, encoding="utf-8")
    col = MagicMock()
    col.get.return_value = {"metadatas": []}
    monkeypatch.setattr(vs, "get_or_create_collection", lambda d: col)
    monkeypatch.setattr(vs, "_file_hash", lambda p: "h")
    monkeypatch.setattr(vs, "_embed_sync", lambda t: [0.0] * 4)
    assert vs._upsert_file_sync("domain", f) is True
    return col.upsert.call_args.kwargs["documents"]


def test_phrase_deep_in_large_file_is_indexed(monkeypatch, tmp_path):
    phrase = "zebra-quantum-marmalade"
    content = ("lorem ipsum " * 1667)[:20_000] + phrase + (" dolor sit amet" * 2000)
    docs = _index(monkeypatch, tmp_path, content)
    assert any(phrase in d for d in docs)


def test_chunks_per_file_are_capped_and_cover_head_middle_tail(monkeypatch, tmp_path):
    monkeypatch.setattr(vs.cfg, "KB_MAX_CHUNKS_PER_FILE", 6)
    size = vs._CHUNK_SIZE
    # 30 chunks' worth of text with unique markers at the start, middle and end.
    body = "a" * (size * 30)
    content = "HEADMARK" + body[: len(body) // 2] + "MIDMARK" + body[len(body) // 2 :] + "TAILMARK"
    docs = _index(monkeypatch, tmp_path, content)
    assert len(docs) == 6
    joined = "".join(docs)
    assert "HEADMARK" in joined
    assert "MIDMARK" in joined
    assert "TAILMARK" in joined
