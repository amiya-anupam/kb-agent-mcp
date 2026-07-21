#!/usr/bin/env python3
"""
memory.py — Conversation Memory
---------------------------------
Stores multi-turn conversation history for the KnowledgeBase Agent.
Persists to disk so context survives between Bob invocations in the same session.

Session resets automatically after KB_SESSION_TIMEOUT_HOURS of inactivity.

Environment variables (all optional — sensible defaults provided):
  KB_SESSION_TIMEOUT_HOURS  Hours of inactivity before session resets.  Default: 2
  KB_SESSION_MAX_TURNS      Max conversation turns kept in memory.       Default: 20
  KB_SESSION_MAX_ANSWER_CHARS
                            Max chars of an assistant answer stored in memory.
                            Long answers are truncated before persisting so they
                            don't inflate the history context sent to the LLM on
                            every subsequent turn.  Default: 400  (~100 tokens)
"""

import os
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

MEMORY_FILE      = pathlib.Path(__file__).parent / "vector_store" / "session_memory.json"
TIMEOUT_HOURS    = float(os.environ.get("KB_SESSION_TIMEOUT_HOURS", "2"))
MAX_TURNS        = int(os.environ.get("KB_SESSION_MAX_TURNS", "20"))
MAX_ANSWER_CHARS = int(os.environ.get("KB_SESSION_MAX_ANSWER_CHARS", "400"))

# ── Memory operations ─────────────────────────────────────────────────────────

def _load() -> dict:
    """Load memory from disk. Returns empty session if missing or expired."""
    if not MEMORY_FILE.exists():
        return {"messages": [], "last_active": time.time()}
    try:
        data = json.loads(MEMORY_FILE.read_text())
        # Check for timeout
        if time.time() - data.get("last_active", 0) > TIMEOUT_HOURS * 3600:
            return {"messages": [], "last_active": time.time()}
        return data
    except Exception:
        return {"messages": [], "last_active": time.time()}


def _save(data: dict):
    """Save memory to disk."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["last_active"] = time.time()
    MEMORY_FILE.write_text(json.dumps(data, indent=2))


def get_history() -> list[dict]:
    """Return the current conversation history (list of message dicts)."""
    return _load().get("messages", [])


def add_turn(user_message: str, assistant_message: str):
    """Append a user + assistant turn to memory.

    The assistant answer is truncated to MAX_ANSWER_CHARS before persisting.
    The full answer was already shown to the user; only a summary is needed
    for follow-up routing and context.  This prevents previous long answers
    from inflating the history tokens sent on every subsequent LLM call.
    """
    data = _load()
    stored_answer = assistant_message[:MAX_ANSWER_CHARS]
    if len(assistant_message) > MAX_ANSWER_CHARS:
        stored_answer += "…"
    data["messages"].append({"role": "user",      "content": user_message})
    data["messages"].append({"role": "assistant",  "content": stored_answer})
    # Trim to MAX_TURNS (keep most recent)
    if len(data["messages"]) > MAX_TURNS * 2:
        data["messages"] = data["messages"][-(MAX_TURNS * 2):]
    _save(data)


def clear():
    """Clear all conversation history (start fresh session)."""
    _save({"messages": [], "last_active": time.time()})
    print("Session memory cleared.")


def summary() -> str:
    """Return a brief summary of the current session state."""
    data = _load()
    msgs = data.get("messages", [])
    turns = len(msgs) // 2
    if turns == 0:
        return "No conversation history yet."
    last_active = data.get("last_active", 0)
    mins_ago = int((time.time() - last_active) / 60)
    return f"{turns} turn(s) in memory · last active {mins_ago} min ago"


# ── Standalone: inspect / clear session ──────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        clear()
    else:
        print(f"Session: {summary()}")
        history = get_history()
        if history:
            print("\nConversation history:")
            for i, msg in enumerate(history):
                role  = msg["role"].upper()
                text  = msg["content"][:120].replace("\n", " ")
                print(f"  [{i+1}] {role}: {text}...")
