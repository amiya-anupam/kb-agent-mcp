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
