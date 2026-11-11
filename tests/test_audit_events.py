"""
tests/test_audit_events.py
──────────────────────────
Phase 5.5 — every audit.jsonl line carries an ``event`` field, and repeated
generate_complete lines are coalesced instead of flooding the log.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT / "agents"))

from kb_agent_mcp import audit as audit_mod  # noqa: E402


def _lines(p: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_log_event_has_event_ts_and_iso(tmp_path):
    p = tmp_path / "audit.jsonl"
    audit_mod.log_event("reindex_complete", path=p, domain="D", files=3)
    (e,) = _lines(p)
    assert e["event"] == "reindex_complete"
    assert isinstance(e["ts"], float) and e["iso"]
    assert e["domain"] == "D" and e["files"] == 3


def test_coalesce_collapses_identical_repeat(tmp_path):
    p = tmp_path / "audit.jsonl"
    for _ in range(3):
        audit_mod.log_event("generate_complete", path=p, coalesce=True,
                            reason="manual", domains=["A"], files=5)
    (e,) = _lines(p)
    assert e["count"] == 3


def test_coalesce_keeps_changed_detail_and_other_events(tmp_path):
    p = tmp_path / "audit.jsonl"
    audit_mod.log_event("generate_complete", path=p, coalesce=True, domains=["A"], files=5)
    audit_mod.log_event("generate_complete", path=p, coalesce=True, domains=["A"], files=6)
    audit_mod.log_event("reindex_complete", path=p, coalesce=True, domains=["A"], files=6)
    assert [e["event"] for e in _lines(p)] == [
        "generate_complete", "generate_complete", "reindex_complete"]


def test_non_coalesced_events_always_append(tmp_path):
    p = tmp_path / "audit.jsonl"
    for _ in range(2):
        audit_mod.log_event("reindex_complete", path=p, domain="D", files=1)
    assert len(_lines(p)) == 2


def test_every_writer_output_has_event(tmp_path, monkeypatch):
    """log_turn, log_event and the watcher's _write_audit all stamp ``event``."""
    import watch_kb
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(watch_kb, "AUDIT_LOG_PATH", p)
    watch_kb._write_audit("reindex_complete", {"domain": "D", "files": 2})

    from kb_agent_mcp.config import cfg  # noqa: F401
    monkeypatch.setattr(audit_mod, "_audit_path", lambda: p)
    audit_mod.log_turn("s", "q", ["D"], [], "a", False, 5)

    entries = _lines(p)
    assert [e["event"] for e in entries] == ["reindex_complete", "query"]


def test_summarise_ignores_non_query_and_string_ts(tmp_path, monkeypatch):
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_mod, "_audit_path", lambda: p)
    import time
    p.write_text("\n".join(json.dumps(x) for x in [
        {"event": "generate_complete", "ts": time.time(), "files": 1},
        {"event": "generate_complete", "ts": "2026-11-11T18:06:14", "files": 1},  # legacy ISO ts
        {"ts": time.time(), "question": "legacy no event", "domains": ["D"], "latency_ms": 10},
        {"event": "query", "ts": time.time(), "question": "q", "domains": ["D"], "latency_ms": 20},
    ]) + "\n")
    s = audit_mod.summarise_log(days=1)
    assert s["total_queries"] == 2
    assert s["domain_counts"] == {"D": 2}


def test_drift_check_uses_last_indexing_event_not_query(tmp_path, monkeypatch):
    """_warn_if_drift reads the last indexing event; query lines do not reset it."""
    import agent_knowledgebase as akb
    import time
    audit = tmp_path / ".kb_index" / "audit.jsonl"
    audit.parent.mkdir()
    old = time.time() - 1000
    audit.write_text("\n".join(json.dumps(x) for x in [
        {"event": "reindex_complete", "ts": old, "domain": "Dom", "files": 1},
        {"event": "query", "ts": time.time(), "question": "q"},
    ]) + "\n")
    dom = tmp_path / "Dom"
    dom.mkdir()
    (dom / "new.md").write_text("changed after last index")
    monkeypatch.setattr(akb, "AUDIT_PATH", audit)

    started: list[str] = []
    import threading
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self.name or "t"))
    akb._warn_if_drift()
    assert started, "stale index should trigger a background reindex"
