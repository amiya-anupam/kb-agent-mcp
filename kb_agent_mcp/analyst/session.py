"""
kb_agent_mcp/analyst/session.py
─────────────────────────────────
Analyst session state — separate from the KB conversation memory.

Each analyst session records:
  • the file that was loaded
  • the original question
  • any clarifying questions that were returned to the caller
  • the parameter values collected so far
  • the last computed answer + reasoning
  • the raw conversation context (for refinement)

Storage location:
    {KB_ROOT}/.kb_index/analyst_sessions/<session_id>.json

Sessions expire after KB_SESSION_TIMEOUT_HOURS (reuses the same env var
as conversation memory).  A fresh AnalystSession is returned if the
persisted file is missing, unreadable, or expired.
"""

from __future__ import annotations

import json
import logging
import re
import time
import asyncio
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from kb_agent_mcp.config import cfg

logger = logging.getLogger(__name__)


# ── Session schema ─────────────────────────────────────────────────────────────

@dataclass
class AnalystSession:
    """All state for a single data-analyst conversation."""

    session_id: str

    # File context
    file_path: str = ""
    data_card: dict[str, Any] = field(default_factory=dict)

    # Question + parameters
    original_question: str = ""
    # Keys are clarifying-question IDs, values are the collected answers
    params: dict[str, Any] = field(default_factory=dict)

    # Pending clarification round (empty → no clarification needed)
    pending_clarifications: list[dict[str, Any]] = field(default_factory=list)

    # Last computed result
    last_answer: str = ""
    last_reasoning: str = ""
    # Suggested follow-up questions after the last answer
    suggested_followups: list[str] = field(default_factory=list)

    # Conversation turns  [{"role": "user"|"analyst", "content": "…"}, …]
    turns: list[dict[str, str]] = field(default_factory=list)

    last_active: float = field(default_factory=time.time)


# ── In-memory cache ────────────────────────────────────────────────────────────

_SESSION_CACHE: dict[str, tuple[AnalystSession, float]] = {}
_CACHE_TTL = 300.0  # 5 min hot cache


# ── Helpers ────────────────────────────────────────────────────────────────────

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_\-]")


def _session_dir() -> Path:
    d = cfg.kb_index_path / "analyst_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_file(session_id: str) -> Path:
    safe = _SAFE_RE.sub("_", session_id)
    return _session_dir() / f"{safe}.json"


def _timeout_seconds() -> float:
    return cfg.KB_SESSION_TIMEOUT_HOURS * 3600


# ── Sync I/O ───────────────────────────────────────────────────────────────────

def _load_sync(session_id: str) -> AnalystSession:
    now = time.time()

    # Hot cache hit
    if session_id in _SESSION_CACHE:
        cached, cached_at = _SESSION_CACHE[session_id]
        age = now - cached.last_active
        if (now - cached_at) < _CACHE_TTL and age <= _timeout_seconds():
            return cached
        del _SESSION_CACHE[session_id]

    path = _session_file(session_id)
    if not path.exists():
        return AnalystSession(session_id=session_id)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        age = now - raw.get("last_active", 0)
        if age > _timeout_seconds():
            return AnalystSession(session_id=session_id)
        sess = AnalystSession(**raw)
        _SESSION_CACHE[session_id] = (sess, now)
        return sess
    except (json.JSONDecodeError, TypeError, OSError) as exc:
        logger.warning("analyst session %r unreadable (%s); starting fresh", session_id, exc)
        return AnalystSession(session_id=session_id)


def _save_sync(session_id: str, sess: AnalystSession) -> None:
    sess.last_active = time.time()
    path = _session_file(session_id)
    path.write_text(json.dumps(asdict(sess), indent=2), encoding="utf-8")
    _SESSION_CACHE[session_id] = (sess, time.time())


# ── Public sync API ────────────────────────────────────────────────────────────

def load_session_sync(session_id: str) -> AnalystSession:
    return _load_sync(session_id)


def save_session_sync(sess: AnalystSession) -> None:
    _save_sync(sess.session_id, sess)


def clear_session_sync(session_id: str) -> None:
    _save_sync(session_id, AnalystSession(session_id=session_id))
    if session_id in _SESSION_CACHE:
        del _SESSION_CACHE[session_id]


def add_turn_sync(
    sess: AnalystSession,
    role: str,
    content: str,
) -> None:
    """Append a turn to the session and persist."""
    sess.turns.append({"role": role, "content": content})
    # Keep a rolling window of the last 20 turns (10 exchanges)
    if len(sess.turns) > 20:
        sess.turns = sess.turns[-20:]
    _save_sync(sess.session_id, sess)


# ── Public async API ───────────────────────────────────────────────────────────

async def load_session(session_id: str) -> AnalystSession:
    return await asyncio.to_thread(load_session_sync, session_id)


async def save_session(sess: AnalystSession) -> None:
    await asyncio.to_thread(save_session_sync, sess)


async def clear_session(session_id: str) -> None:
    await asyncio.to_thread(clear_session_sync, session_id)


async def add_turn(sess: AnalystSession, role: str, content: str) -> None:
    await asyncio.to_thread(add_turn_sync, sess, role, content)
