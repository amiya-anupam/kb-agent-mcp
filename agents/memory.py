#!/usr/bin/env python3
"""
memory.py — Conversation Memory
---------------------------------
Stores multi-turn conversation history for the KnowledgeBase Agent.
Persists to disk so context survives between Bob invocations in the same session.

Named sessions / workspaces
────────────────────────────
Each session is stored as a separate JSON file:

    {KB_ROOT}/.kb_index/session_memory/<session_id>.json   (preferred)
    agents/vector_store/session_<session_id>.json           (legacy fallback)

The default session ("default") uses the legacy path for backward compatibility.
Named sessions use the .kb_index directory co-located with the knowledge base.

Session resets automatically after KB_SESSION_TIMEOUT_HOURS of inactivity.

Answer compression
──────────────────
When storing a long answer, instead of hard-truncating at MAX_ANSWER_CHARS the
module attempts a one-shot LLM summarisation call to produce a ≤100-word digest
that preserves key conclusions.  A three-tier fallback chain handles every
possible environment:

  Tier 1 – LLM summarisation
      A cheap, temperature-0 call with a tight 8-second timeout.
      Only attempted when KB_LLM_PROVIDER is NOT "passthrough" AND the
      answer is longer than MAX_ANSWER_CHARS.

  Tier 2 – Sentence-boundary truncation
      If the LLM is unreachable, returns a timeout / error, or the
      feature is disabled (KB_MEMORY_COMPRESS=false), the text is
      split on sentence endings and cut at the last complete sentence
      that fits in MAX_ANSWER_CHARS.  Never splits mid-sentence.

  Tier 3 – Hard character truncation (original behaviour)
      Ultimate safety net — used only when sentence splitting also fails.

Set KB_MEMORY_COMPRESS=false to skip Tier 1 entirely (pure offline mode).

Environment variables (all optional — sensible defaults provided):
  KB_SESSION_TIMEOUT_HOURS  Hours of inactivity before session resets.  Default: 2
  KB_SESSION_MAX_TURNS      Max conversation turns kept in memory.       Default: 20
  KB_SESSION_MAX_ANSWER_CHARS
                            Max chars of an assistant answer stored in memory.
                            Default: 400  (~100 tokens)
  KB_MEMORY_COMPRESS        Enable LLM summarisation before storage.     Default: true
                            Set to "false" to use sentence truncation only (offline).
"""

import os
import re
import json
import time
import pathlib

# ── Load .env if present ──────────────────────────────────────────────────────

def _load_env():
    for candidate in [
        pathlib.Path(os.environ.get("KB_ROOT", "")) / ".env",
        pathlib.Path(__file__).parent.parent / ".env",
    ]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
            break

_load_env()

# ── Config ────────────────────────────────────────────────────────────────────

# Legacy single-file path (kept for the implicit "default" session)
_LEGACY_MEMORY_FILE = pathlib.Path(__file__).parent / "vector_store" / "session_memory.json"

TIMEOUT_HOURS    = float(os.environ.get("KB_SESSION_TIMEOUT_HOURS", "2"))
MAX_TURNS        = int(os.environ.get("KB_SESSION_MAX_TURNS", "20"))
MAX_ANSWER_CHARS = int(os.environ.get("KB_SESSION_MAX_ANSWER_CHARS", "400"))
_COMPRESS        = os.environ.get("KB_MEMORY_COMPRESS", "true").strip().lower() not in ("false", "0", "no", "off")

# Regex to sanitise arbitrary session names into safe filenames
_SAFE_RE = re.compile(r"[^a-zA-Z0-9_\-]")

# Sentence-boundary splitter: split after ., !, ? followed by whitespace or end
_SENT_END_RE = re.compile(r'(?<=[.!?])\s+')

# Module-level active session (set via set_session() or the CLI --session flag)
_active_session: str = "default"


def set_session(name: str) -> None:
    """Switch the active session for all subsequent memory operations."""
    global _active_session
    _active_session = name.strip() or "default"


def _session_file(session_id: str) -> pathlib.Path:
    """Return the disk path for a given session_id.

    The "default" session uses the legacy single-file path so existing history
    is preserved.  All other names use .kb_index/session_memory/<safe>.json,
    which mirrors the kb_agent_mcp layer and makes the files visible to
    `kb-agent-status --sessions`.
    """
    if session_id == "default":
        return _LEGACY_MEMORY_FILE

    safe = _SAFE_RE.sub("_", session_id)
    kb_root = pathlib.Path(os.environ.get("KB_ROOT", "")) or pathlib.Path(__file__).parent.parent
    mem_dir = kb_root / ".kb_index" / "session_memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir / f"{safe}.json"


# ── Memory operations ─────────────────────────────────────────────────────────

def _load(session_id: str | None = None) -> dict:
    """Load memory from disk. Returns empty session if missing or expired."""
    sid = session_id or _active_session
    path = _session_file(sid)
    if not path.exists():
        return {"messages": [], "last_active": time.time()}
    try:
        data = json.loads(path.read_text())
        # Check for timeout
        if time.time() - data.get("last_active", 0) > TIMEOUT_HOURS * 3600:
            return {"messages": [], "last_active": time.time()}
        return data
    except Exception:
        return {"messages": [], "last_active": time.time()}


def _save(data: dict, session_id: str | None = None):
    """Save memory to disk."""
    sid = session_id or _active_session
    path = _session_file(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_active"] = time.time()
    path.write_text(json.dumps(data, indent=2))


def get_history(session_id: str | None = None) -> list[dict]:
    """Return the current conversation history (list of message dicts)."""
    return _load(session_id).get("messages", [])


# ── Answer compression ────────────────────────────────────────────────────────

def _sentence_truncate(text: str, max_chars: int) -> str:
    """Tier 2: truncate at the last complete sentence boundary within max_chars.

    Splits on sentence-ending punctuation followed by whitespace, then walks
    backward to find the longest prefix that fits.  Falls back to a hard cut
    (Tier 3) when no sentence boundary is found within the limit.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    sentences = _SENT_END_RE.split(window)
    if len(sentences) <= 1:
        # No sentence boundary found — hard cut (Tier 3)
        return window.rstrip() + "…"
    # Drop the last (potentially incomplete) sentence fragment
    result = " ".join(sentences[:-1]).rstrip()
    return result + "…"


def _compress_answer(answer: str) -> str:
    """
    Compress a long answer for memory storage using a three-tier fallback:

      Tier 1: LLM summarisation  (fast, temperature=0, 8 s timeout)
      Tier 2: Sentence-boundary truncation
      Tier 3: Hard character truncation  (original behaviour, safety net)

    Returns the compressed string.  Never raises.
    """
    if len(answer) <= MAX_ANSWER_CHARS:
        return answer  # short enough — store verbatim

    # ── Tier 2 is always ready as the fallback ────────────────────────────────
    tier2 = _sentence_truncate(answer, MAX_ANSWER_CHARS)

    # ── Tier 1: skip when compression is disabled or we are in passthrough ────
    if not _COMPRESS:
        return tier2

    try:
        # Import at call time to avoid a hard dependency at module import;
        # agent_base is only available when running inside the agents/ context.
        import sys as _sys
        import pathlib as _pathlib
        _agents_dir = str(_pathlib.Path(__file__).parent)
        if _agents_dir not in _sys.path:
            _sys.path.insert(0, _agents_dir)

        from agent_base import call_llm, _PASSTHROUGH  # type: ignore[import]

        if _PASSTHROUGH:
            # passthrough mode: no local LLM — skip to Tier 2
            return tier2

        prompt = (
            "Summarise the following answer in at most 100 words. "
            "Preserve the key conclusions, findings, and any named entities "
            "(products, numbers, dates, names). "
            "Reply with ONLY the summary — no preamble, no explanation.\n\n"
            f"ANSWER:\n{answer[:4000]}"   # cap input to keep the call cheap
        )
        messages = [
            {"role": "system", "content": "You are a concise summariser."},
            {"role": "user",   "content": prompt},
        ]

        # Override the default 120 s timeout with a tight 8 s budget so a slow
        # or unavailable LLM never meaningfully delays the caller.
        try:
            # agent_base uses httpx directly; we can't pass a custom timeout
            # through call_llm(), so we wrap it in a threading.Timer guard.
            import threading as _threading
            result_holder: list[str] = []
            error_holder:  list[Exception] = []

            def _do_call():
                try:
                    result_holder.append(call_llm(messages, temperature=0.0))
                except Exception as exc:
                    error_holder.append(exc)

            t = _threading.Thread(target=_do_call, daemon=True)
            t.start()
            t.join(timeout=8.0)  # hard 8-second wall-clock limit

            if t.is_alive() or error_holder:
                # LLM timed out or errored — Tier 2
                return tier2

            summary_text = result_holder[0].strip() if result_holder else ""
            if not summary_text:
                return tier2

            # Tag so callers can tell a compressed entry from a verbatim one
            return f"[summary] {summary_text}"

        except Exception:
            return tier2

    except ImportError:
        # agent_base not on path (e.g. called from the MCP layer) — Tier 2
        return tier2
    except Exception:
        return tier2


def add_turn(user_message: str, assistant_message: str, session_id: str | None = None):
    """Append a user + assistant turn to memory.

    Long answers are compressed before persisting via _compress_answer():
      - LLM summarisation when available (≤100 words, preserves conclusions)
      - Sentence-boundary truncation when LLM is unavailable or slow
      - Hard char truncation as a final safety net

    The full answer was already shown to the user; the compressed form is
    only used for multi-turn routing context on subsequent questions.
    """
    data = _load(session_id)
    stored_answer = _compress_answer(assistant_message)
    data["messages"].append({"role": "user",      "content": user_message})
    data["messages"].append({"role": "assistant",  "content": stored_answer})
    # Trim to MAX_TURNS (keep most recent)
    if len(data["messages"]) > MAX_TURNS * 2:
        data["messages"] = data["messages"][-(MAX_TURNS * 2):]
    _save(data, session_id)


def clear(session_id: str | None = None):
    """Clear all conversation history (start fresh session)."""
    sid = session_id or _active_session
    _save({"messages": [], "last_active": time.time()}, sid)
    label = f"'{sid}'" if sid != "default" else "default"
    print(f"Session {label} memory cleared.")


def summary(session_id: str | None = None) -> str:
    """Return a brief summary of the current session state."""
    sid = session_id or _active_session
    data = _load(sid)
    msgs = data.get("messages", [])
    turns = len(msgs) // 2
    label = f"'{sid}'" if sid != "default" else "default"
    if turns == 0:
        return f"Session {label}: no history yet."
    last_active = data.get("last_active", 0)
    mins_ago = int((time.time() - last_active) / 60)
    return f"Session {label}: {turns} turn(s) in memory · last active {mins_ago} min ago"


def list_sessions() -> list[dict]:
    """Return metadata for all persisted sessions, sorted newest-first.

    Scans both the legacy vector_store/ directory and .kb_index/session_memory/
    so sessions created by either the agents layer or the MCP layer are included.

    Each entry contains:
        session_id   str   — the session name
        turns        int   — number of conversation turns stored
        last_active  float — Unix timestamp of last activity
        expired      bool  — True when the session has exceeded the timeout
    """
    now = time.time()
    seen: set[str] = set()
    sessions: list[dict] = []

    def _record(path: pathlib.Path, session_id: str) -> None:
        if session_id in seen:
            return
        seen.add(session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        last_active = data.get("last_active", 0)
        turns = len(data.get("messages", [])) // 2
        expired = (now - last_active) > TIMEOUT_HOURS * 3600
        sessions.append({
            "session_id":  session_id,
            "turns":       turns,
            "last_active": last_active,
            "expired":     expired,
        })

    # Legacy single-file default session
    if _LEGACY_MEMORY_FILE.exists():
        _record(_LEGACY_MEMORY_FILE, "default")

    # Per-session files in .kb_index/session_memory/
    kb_root = pathlib.Path(os.environ.get("KB_ROOT", "")) or pathlib.Path(__file__).parent.parent
    mem_dir = kb_root / ".kb_index" / "session_memory"
    if mem_dir.exists():
        for p in sorted(mem_dir.glob("*.json")):
            _record(p, p.stem)

    sessions.sort(key=lambda s: s["last_active"], reverse=True)
    return sessions


# ── Standalone: inspect / clear session ──────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        clear()
    elif len(sys.argv) > 1 and sys.argv[1] == "--sessions":
        rows = list_sessions()
        if not rows:
            print("No sessions found.")
        else:
            print(f"{'Session':<30}  {'Turns':>5}  {'Last active':>12}  Status")
            print("-" * 60)
            for s in rows:
                la = int((time.time() - s["last_active"]) // 60)
                la_str = f"{la}m ago" if la < 60 else f"{la // 60}h ago"
                status = "expired" if s["expired"] else "active"
                print(f"{s['session_id']:<30}  {s['turns']:>5}  {la_str:>12}  {status}")
    else:
        print(f"Session: {summary()}")
        history = get_history()
        if history:
            print("\nConversation history:")
            for i, msg in enumerate(history):
                role  = msg["role"].upper()
                text  = msg["content"][:120].replace("\n", " ")
                print(f"  [{i+1}] {role}: {text}...")
