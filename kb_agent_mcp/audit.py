"""
kb_agent_mcp/audit.py
─────────────────────
Append-only audit log for all ask() calls.

Each turn is written as a single JSON object on its own line (JSONL format)
to {KB_ROOT}/.kb_index/audit.jsonl.

Schema per entry:
    {
        "ts":          <unix float>,
        "iso":         "2026-07-28T14:32:01.123Z",
        "session_id":  "user-session-1",
        "question":    "What is the Q3 ACE renewal status?",
        "domains":     ["BizOps"],
        "files_cited": ["BizOps/Renewal Tracking/Q3 Deals.xlsx"],
        "answer_hash": "a3f2c1",   # first 8 chars of sha256(answer)
        "blocked":     false,       # true when security gate blocked the answer
        "latency_ms":  342
    }

Rotation: when the file exceeds KB_AUDIT_MAX_MB, it is renamed to
audit.jsonl.1 (previous .1 is overwritten) and a fresh audit.jsonl starts.
At most two files are kept — the current log and one rotated archive.

Public API
----------
log_turn(session_id, question, domains, files_cited, answer, blocked, latency_ms)
    Append one entry. Silently swallows all I/O errors so a log failure
    never breaks a query response.

read_log(limit, session_id) -> list[dict]
    Return the last *limit* entries, optionally filtered by session_id.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from kb_agent_mcp.config import cfg

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _audit_path() -> Path:
    p = cfg.kb_index_path / "audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.encode()).hexdigest()[:8]


def _rotate_if_needed(path: Path) -> None:
    """Rename audit.jsonl → audit.jsonl.1 when size exceeds KB_AUDIT_MAX_MB."""
    max_bytes = cfg.KB_AUDIT_MAX_MB * 1024 * 1024
    try:
        if path.exists() and path.stat().st_size >= max_bytes:
            archive = path.with_suffix(".jsonl.1")
            path.rename(archive)
    except OSError as exc:
        logger.warning("Audit log rotation failed: %s", exc)


# ── Public API ─────────────────────────────────────────────────────────────────

def log_turn(
    session_id: str,
    question: str,
    domains: Sequence[str],
    files_cited: Sequence[str],
    answer: str,
    blocked: bool = False,
    latency_ms: int = 0,
) -> None:
    """
    Append one audit entry. Never raises — I/O errors are logged and swallowed
    so an audit failure never impacts query responses.
    """
    if not cfg.KB_AUDIT_ENABLED:
        return

    now = time.time()
    entry = {
        "ts":          now,
        "iso":         datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "session_id":  session_id,
        "question":    question[:500],      # cap at 500 chars to keep log compact
        "domains":     list(domains),
        "files_cited": list(files_cited),
        "answer_hash": _answer_hash(answer),
        "blocked":     blocked,
        "latency_ms":  latency_ms,
    }

    try:
        path = _audit_path()
        _rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Audit log write failed: %s", exc)


def read_log(
    limit: int = 50,
    session_id: str | None = None,
) -> list[dict]:
    """
    Return the last *limit* audit entries from disk, newest-last order.
    Optionally filter to a single session_id.
    Never raises.
    """
    path = _audit_path()
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Audit log read failed: %s", exc)
        return []

    entries: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if session_id and entry.get("session_id") != session_id:
            continue
        entries.append(entry)
        if len(entries) >= limit:
            break

    return list(reversed(entries))  # return in chronological order


def summarise_log(days: int = 30) -> dict:
    """
    Compute usage analytics from the audit log over the last *days* days.

    Returns a dict with:
        period_days       - the requested window
        total_queries     - total entries in the window
        blocked_queries   - entries where blocked=True
        failure_rate_pct  - blocked / total * 100 (or 0 when total=0)
        avg_latency_ms    - mean latency across all entries in window
        top_questions     - list of {"question": ..., "count": ...} for top 10
        domain_counts     - dict mapping domain name to query count (sorted desc)
        busiest_domain    - domain with the highest query count (or None)
        no_data           - True when the log is empty or does not exist
    """
    import time as _time
    from collections import Counter

    cutoff = _time.time() - days * 86400
    path = _audit_path()

    # Read both the current log and the rotated archive so the window can
    # span a rotation boundary without losing data.
    all_lines: list[str] = []
    for candidate in (path, path.with_suffix(".jsonl.1")):
        if candidate.exists():
            try:
                all_lines.extend(candidate.read_text(encoding="utf-8").splitlines())
            except OSError as exc:
                logger.warning("Audit summarise read failed (%s): %s", candidate, exc)

    entries: list[dict] = []
    for line in all_lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("ts", 0) >= cutoff:
            entries.append(e)

    if not entries:
        return {
            "period_days": days,
            "total_queries": 0,
            "blocked_queries": 0,
            "failure_rate_pct": 0.0,
            "avg_latency_ms": 0.0,
            "top_questions": [],
            "domain_counts": {},
            "busiest_domain": None,
            "no_data": True,
        }

    total = len(entries)
    blocked = sum(1 for e in entries if e.get("blocked"))
    failure_rate = round(blocked / total * 100, 1) if total else 0.0
    avg_latency = round(sum(e.get("latency_ms", 0) for e in entries) / total, 1)

    question_counter: Counter = Counter(e.get("question", "") for e in entries)
    top_questions = [
        {"question": q, "count": c}
        for q, c in question_counter.most_common(10)
        if q
    ]

    domain_counter: Counter = Counter()
    for e in entries:
        for d in e.get("domains", []):
            domain_counter[d] += 1
    domain_counts = dict(domain_counter.most_common())
    busiest = domain_counter.most_common(1)[0][0] if domain_counter else None

    return {
        "period_days": days,
        "total_queries": total,
        "blocked_queries": blocked,
        "failure_rate_pct": failure_rate,
        "avg_latency_ms": avg_latency,
        "top_questions": top_questions,
        "domain_counts": domain_counts,
        "busiest_domain": busiest,
        "no_data": False,
    }
