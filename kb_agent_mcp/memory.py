"""
kb_agent_mcp/memory.py
──────────────────────
Multi-session conversation memory with disk persistence.

Each session is identified by a `session_id` string (default "default").
Data is stored as a flat JSON file per session:

    {KB_ROOT}/.kb_index/session_memory/<session_id>.json

Session schema:
    {
        "messages": [{"role": "user"|"assistant", "content": "…"}, …],
        "last_active": <unix timestamp float>
    }

Sessions expire after KB_SESSION_TIMEOUT_HOURS of inactivity and reset
automatically on the next access.
"""

from __future__ import annotations

import json
import logging
import re
import time
import asyncio
from pathlib import Path

from kb_agent_mcp.config import cfg

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────────────

_SAFE_SESSION_RE = re.compile(r"[^a-zA-Z0-9_\-]")


def _session_file(session_id: str) -> Path:
    """Return the disk path for a given session_id."""
    safe = _SAFE_SESSION_RE.sub("_", session_id)
    mem_dir = cfg.kb_index_path / "session_memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir / f"{safe}.json"


def _empty_session() -> dict:
    return {"messages": [], "last_active": time.time()}


# ── Sync I/O (used by async wrappers via asyncio.to_thread) ────────────────────

def _load_sync(session_id: str) -> dict:
    """Load a session from disk. Returns a fresh session if missing or expired."""
    path = _session_file(session_id)
    if not path.exists():
        return _empty_session()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        elapsed = time.time() - data.get("last_active", 0)
        if elapsed > cfg.KB_SESSION_TIMEOUT_HOURS * 3600:
            return _empty_session()
        return data
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning("Failed to load session %r (%s); starting fresh", session_id, exc)
        return _empty_session()


def _save_sync(session_id: str, data: dict) -> None:
    """Write a session to disk."""
    data["last_active"] = time.time()
    path = _session_file(session_id)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Public sync API (used internally by orchestrator) ──────────────────────────

def get_history_sync(session_id: str = "default") -> list[dict]:
    """Return the conversation history for a session (sync)."""
    return _load_sync(session_id).get("messages", [])


def add_turn_sync(
    user_message: str,
    assistant_message: str,
    session_id: str = "default",
) -> None:
    """Append a user + assistant turn to memory (sync).

    The assistant answer is truncated to KB_SESSION_MAX_ANSWER_CHARS before
    persisting — the full answer was already returned to the caller; only a
    summary is needed for follow-up routing context.
    """
    data = _load_sync(session_id)
    stored = assistant_message[: cfg.KB_SESSION_MAX_ANSWER_CHARS]
    if len(assistant_message) > cfg.KB_SESSION_MAX_ANSWER_CHARS:
        stored += "…"
    data["messages"].append({"role": "user", "content": user_message})
    data["messages"].append({"role": "assistant", "content": stored})
    # Keep only the most recent KB_SESSION_MAX_TURNS turns
    max_msgs = cfg.KB_SESSION_MAX_TURNS * 2
    if len(data["messages"]) > max_msgs:
        data["messages"] = data["messages"][-max_msgs:]
    _save_sync(session_id, data)


def clear_sync(session_id: str = "default") -> None:
    """Clear the conversation history for a session (sync)."""
    _save_sync(session_id, _empty_session())


def summary_sync(session_id: str = "default") -> str:
    """Return a one-line status summary for a session (sync)."""
    data = _load_sync(session_id)
    msgs = data.get("messages", [])
    turns = len(msgs) // 2
    if turns == 0:
        return f"Session '{session_id}': no history."
    mins_ago = int((time.time() - data.get("last_active", 0)) / 60)
    return f"Session '{session_id}': {turns} turn(s) · last active {mins_ago} min ago"


# ── Public async API (used by MCP server tools) ─────────────────────────────────

async def get_history(session_id: str = "default") -> list[dict]:
    """Return the conversation history for a session (async)."""
    return await asyncio.to_thread(get_history_sync, session_id)


async def add_turn(
    user_message: str,
    assistant_message: str,
    session_id: str = "default",
) -> None:
    """Append a user + assistant turn to memory (async)."""
    await asyncio.to_thread(add_turn_sync, user_message, assistant_message, session_id)


async def clear(session_id: str = "default") -> None:
    """Clear the conversation history for a session (async)."""
    await asyncio.to_thread(clear_sync, session_id)


async def summary(session_id: str = "default") -> str:
    """Return a one-line status summary for a session (async)."""
    return await asyncio.to_thread(summary_sync, session_id)
