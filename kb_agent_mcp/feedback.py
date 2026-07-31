"""
kb_agent_mcp/feedback.py
────────────────────────
Per-answer feedback / rating store.

Each rating is written as a single JSON object on its own line (JSONL)
to {KB_ROOT}/.kb_index/feedback.jsonl.

Schema per entry:
    {
        "ts":          <unix float>,
        "iso":         "2026-07-31T14:32:01.123Z",
        "session_id":  "user-session-1",
        "question":    "What is the Q3 ACE renewal status?",   (first 500 chars)
        "rating":      4,           # 1–5 (1 = bad, 5 = excellent)
        "comment":     "...",       # optional free-text
        "answer_hash": "a3f2c1"     # sha256[:8] of the answer that was rated
    }

Public API
----------
record(session_id, question, answer, rating, comment) → None
    Append one feedback entry. Silently swallows I/O errors.

read_feedback(limit, session_id, min_rating, max_rating) → list[dict]
    Return the last *limit* entries, optionally filtered.
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

# Valid rating range
RATING_MIN = 1
RATING_MAX = 5


# ── Helpers ────────────────────────────────────────────────────────────────────

def _feedback_path() -> Path:
    p = cfg.kb_index_path / "feedback.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.encode()).hexdigest()[:8]


# ── Public API ─────────────────────────────────────────────────────────────────

def record(
    session_id: str,
    question: str,
    answer: str,
    rating: int,
    comment: str = "",
) -> None:
    """
    Append one feedback entry.  Never raises — I/O errors are logged and
    swallowed so a feedback failure never impacts query responses.

    Args:
        session_id: The session the answer was delivered in.
        question:   The question that was asked (capped to 500 chars).
        answer:     The answer text (used only to derive a hash for correlation).
        rating:     Integer 1–5.  Values outside this range are clamped.
        comment:    Optional free-text note from the user.
    """
    rating = max(RATING_MIN, min(RATING_MAX, int(rating)))
    now = time.time()
    entry = {
        "ts":          now,
        "iso":         datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "session_id":  session_id,
        "question":    question[:500],
        "rating":      rating,
        "comment":     comment[:1000] if comment else "",
        "answer_hash": _answer_hash(answer),
    }
    try:
        path = _feedback_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Feedback write failed: %s", exc)


def read_feedback(
    limit: int = 50,
    session_id: str | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
) -> list[dict]:
    """
    Return the last *limit* feedback entries from disk (newest-last order).
    Optionally filter by session_id and/or rating range.
    Never raises.
    """
    path = _feedback_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Feedback read failed: %s", exc)
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
        r = entry.get("rating", 0)
        if min_rating is not None and r < min_rating:
            continue
        if max_rating is not None and r > max_rating:
            continue
        entries.append(entry)
        if len(entries) >= limit:
            break

    return list(reversed(entries))  # chronological order
