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

Named sessions / workspaces
────────────────────────────
A session is just a named file under session_memory/.  Giving a session a
meaningful name (e.g. "ace-renewal-review") makes it bookmarkable and
resumable across server restarts without re-querying.

    • list_sessions_sync() / list_sessions()
          Return a list of all persisted sessions with their turn count,
          last-active timestamp, and expiry status — sorted newest-first.

    • get_history_sync("ace-renewal-review")
          Resume the session by name.

Answer compression
──────────────────
Before a long answer is persisted in memory a one-shot LLM summarisation call
is attempted (Tier 1).  This preserves key conclusions far better than a hard
character truncation.  A three-tier fallback ensures the operation never blocks
or fails even in fully offline environments:

  Tier 1 – LLM summarisation  (temperature=0, 8 s wall-clock timeout)
      Skipped when KB_LLM_PROVIDER=passthrough or KB_MEMORY_COMPRESS=false.

  Tier 2 – Sentence-boundary truncation
      Cuts at the last complete sentence within KB_SESSION_MAX_ANSWER_CHARS.

  Tier 3 – Hard character truncation  (original behaviour, final safety net)
"""

from __future__ import annotations

import json
import logging
import re
import time
import asyncio
from pathlib import Path
from typing import NamedTuple

from kb_agent_mcp.config import cfg

# Sentence-boundary splitter used by Tier-2 truncation
_SENT_END_RE = re.compile(r'(?<=[.!?])\s+')

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────────────

_SAFE_SESSION_RE = re.compile(r"[^a-zA-Z0-9_\-]")

# ── In-memory session cache ────────────────────────────────────────────────────
# Keeps the most-recently-used session dict in memory so repeated queries in
# the same conversation don't hit disk on every call.
# Entry: { session_id: (data_dict, loaded_at_timestamp) }
# Evicted when the session is saved (refreshed) or when it expires.
_SESSION_CACHE: dict[str, tuple[dict, float]] = {}
_SESSION_CACHE_TTL = 300.0  # seconds — evict idle entries after 5 min


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
    """Load a session — from in-memory cache if warm, else from disk."""
    now = time.time()

    # Check in-memory cache first
    if session_id in _SESSION_CACHE:
        cached_data, cached_at = _SESSION_CACHE[session_id]
        # Evict if TTL exceeded or session itself has expired
        elapsed_session = now - cached_data.get("last_active", 0)
        if (now - cached_at) < _SESSION_CACHE_TTL and elapsed_session <= cfg.KB_SESSION_TIMEOUT_HOURS * 3600:
            return cached_data
        else:
            del _SESSION_CACHE[session_id]

    # Cache miss — load from disk
    path = _session_file(session_id)
    if not path.exists():
        return _empty_session()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        elapsed = now - data.get("last_active", 0)
        if elapsed > cfg.KB_SESSION_TIMEOUT_HOURS * 3600:
            return _empty_session()
        _SESSION_CACHE[session_id] = (data, now)
        return data
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning("Failed to load session %r (%s); starting fresh", session_id, exc)
        return _empty_session()


def _save_sync(session_id: str, data: dict) -> None:
    """Write a session to disk and refresh the in-memory cache."""
    data["last_active"] = time.time()
    path = _session_file(session_id)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Keep cache in sync with what was just written
    _SESSION_CACHE[session_id] = (data, time.time())


# ── Answer compression ─────────────────────────────────────────────────────────

def _sentence_truncate_sync(text: str, max_chars: int) -> str:
    """Tier 2: cut at the last complete sentence boundary within max_chars.

    Falls back to a hard character cut (Tier 3) when no sentence boundary is
    found.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    sentences = _SENT_END_RE.split(window)
    if len(sentences) <= 1:
        return window.rstrip() + "…"
    return " ".join(sentences[:-1]).rstrip() + "…"


def _compress_answer_sync(answer: str) -> str:
    """
    Compress a long answer for memory storage (sync, called from a thread).

    Three-tier fallback — never raises, never blocks the caller for more than
    ~8 seconds:

      Tier 1 – LLM summarisation  (temperature=0, 8 s wall-clock timeout)
          Skipped when KB_MEMORY_COMPRESS=false or provider is passthrough.

      Tier 2 – Sentence-boundary truncation within KB_SESSION_MAX_ANSWER_CHARS.

      Tier 3 – Hard character truncation  (original behaviour, safety net).
    """
    max_chars = cfg.KB_SESSION_MAX_ANSWER_CHARS

    if len(answer) <= max_chars:
        return answer  # short enough — store verbatim

    tier2 = _sentence_truncate_sync(answer, max_chars)

    # Respect KB_MEMORY_COMPRESS=false (pure offline mode)
    compress_enabled = cfg.KB_MEMORY_COMPRESS
    if not compress_enabled:
        return tier2

    # Skip Tier 1 in passthrough mode (no local LLM available)
    if cfg.KB_LLM_PROVIDER == "passthrough":
        return tier2

    try:
        # Re-use the same sync LLM helpers that base_agent already uses so we
        # share the connection pool and don't introduce a new HTTP client.
        from kb_agent_mcp.base_agent import (
            _call_ollama_sync,
            _call_openai_compat_sync,
            _call_anthropic_sync,
        )

        def _raw_call() -> str:
            provider = cfg.KB_LLM_PROVIDER.lower()
            if provider == "anthropic":
                return _call_anthropic_sync(messages, 0.0)
            if provider in ("openai", "custom"):
                return _call_openai_compat_sync(messages, 0.0)
            return _call_ollama_sync(messages, 0.0)

        prompt = (
            "Summarise the following answer in at most 100 words. "
            "Preserve the key conclusions, findings, and any named entities "
            "(products, numbers, dates, names). "
            "Reply with ONLY the summary — no preamble, no explanation.\n\n"
            f"ANSWER:\n{answer[:4000]}"
        )
        messages = [
            {"role": "system", "content": "You are a concise summariser."},
            {"role": "user",   "content": prompt},
        ]

        import threading as _threading
        result_holder: list[str] = []
        error_holder:  list[BaseException] = []

        def _worker():
            try:
                result_holder.append(_raw_call())
            except BaseException as exc:  # noqa: BLE001
                error_holder.append(exc)

        t = _threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=8.0)

        if t.is_alive() or error_holder or not result_holder:
            logger.debug(
                "Memory compression Tier-1 unavailable (%s); falling back to sentence truncation",
                error_holder[0] if error_holder else "timeout",
            )
            return tier2

        summary_text = result_holder[0].strip()
        if not summary_text:
            return tier2

        logger.debug("Memory compression: stored LLM summary (%d chars)", len(summary_text))
        return f"[summary] {summary_text}"

    except Exception as exc:
        logger.debug("Memory compression Tier-1 import/call error (%s); using Tier 2", exc)
        return tier2


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

    Long answers are compressed before persisting via _compress_answer_sync():
      - LLM summarisation when available (≤100 words, preserves conclusions)
      - Sentence-boundary truncation when LLM is unavailable or slow
      - Hard char truncation as a final safety net

    The full answer was already returned to the caller; the compressed form is
    only used for multi-turn routing context on subsequent questions.
    """
    data = _load_sync(session_id)
    stored = _compress_answer_sync(assistant_message)
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


# ── Session listing ─────────────────────────────────────────────────────────────

def list_sessions_sync() -> list[dict]:
    """Return metadata for all persisted sessions, sorted newest-first.

    Each entry contains:
        session_id   str   — the session name (filename without .json)
        turns        int   — number of conversation turns stored
        last_active  float — Unix timestamp of last activity
        expired      bool  — True when the session has exceeded the timeout
    """
    now = time.time()
    mem_dir = cfg.kb_index_path / "session_memory"
    if not mem_dir.exists():
        return []

    sessions: list[dict] = []
    for path in mem_dir.glob("*.json"):
        session_id = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        last_active = data.get("last_active", 0)
        turns = len(data.get("messages", [])) // 2
        expired = (now - last_active) > cfg.KB_SESSION_TIMEOUT_HOURS * 3600
        sessions.append({
            "session_id":  session_id,
            "turns":       turns,
            "last_active": last_active,
            "expired":     expired,
        })

    # Newest-first
    sessions.sort(key=lambda s: s["last_active"], reverse=True)
    return sessions


async def list_sessions() -> list[dict]:
    """Return metadata for all persisted sessions, sorted newest-first (async)."""
    return await asyncio.to_thread(list_sessions_sync)
