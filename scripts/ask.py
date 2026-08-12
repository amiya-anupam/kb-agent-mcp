#!/usr/bin/env python3
"""
scripts/ask.py — offline-capable CLI wrapper for the KnowledgeBase Agent
-------------------------------------------------------------------------
Use this instead of calling agent_knowledgebase.py directly.  It handles
the passthrough case so the full question→answer round-trip works even when
Ollama is not running and there is no internet connection.

How it works
------------
1. Run agent_knowledgebase.py as a subprocess, capturing stdout.
2. If the output contains NO <<<KB_PASSTHROUGH>>> blocks (Ollama answered
   normally), just print the answer.
3. If passthrough blocks ARE present, extract question + context from them,
   build a prompt, and send it to Ollama directly (localhost:11434).
4. If Ollama is also unreachable, print the retrieved context as-is so the
   user at least has the raw document excerpts.

Usage
-----
  python3 scripts/ask.py "your question"
  python3 scripts/ask.py "your question" --format bullets
  python3 scripts/ask.py --clear
  python3 scripts/ask.py --check-drift
  python3 scripts/ask.py --help

Environment variables (same as agent_base.py)
---------------------------------------------
  KB_MODEL          Ollama model name (default: qwen3:14b)
  KB_LLM_BASE_URL   Ollama base URL   (default: http://localhost:11434)
"""

import os
import re
import sys
import json
import pathlib
import subprocess
import textwrap
import datetime

# ── Resolve paths ─────────────────────────────────────────────────────────────

SCRIPT_DIR  = pathlib.Path(__file__).parent.resolve()
REPO_ROOT   = SCRIPT_DIR.parent
AGENT       = REPO_ROOT / "agents" / "agent_knowledgebase.py"
ENV_FILE    = REPO_ROOT / ".env"

# ── Load .env so KB_MODEL / KB_LLM_BASE_URL are available ────────────────────

def _load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

OLLAMA_URL = os.environ.get("KB_LLM_BASE_URL", "http://localhost:11434")
MODEL      = os.environ.get("KB_MODEL", "qwen3:14b")

# ── Passthrough block markers (must match agent_base.py) ─────────────────────

_PT_START = "<<<KB_PASSTHROUGH>>>"
_PT_END   = "<<<KB_PASSTHROUGH_END>>>"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _color(code: str, text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

def _dim(t):  return _color("2",    t)
def _bold(t): return _color("1",    t)
def _grn(t):  return _color("32",   t)
def _red(t):  return _color("31",   t)
def _cyn(t):  return _color("36",   t)


def _extract_passthrough_blocks(output: str) -> list[dict]:
    """
    Pull every <<<KB_PASSTHROUGH>>> … <<<KB_PASSTHROUGH_END>>> block from
    stdout and parse it into a dict with keys: agent, question, source,
    system_prompt, context.
    """
    blocks = []
    for raw in re.findall(
        re.escape(_PT_START) + r"(.*?)" + re.escape(_PT_END),
        output, re.DOTALL
    ):
        b: dict = {}
        # AGENT:
        m = re.search(r"^AGENT:\s*(.+)$", raw, re.MULTILINE)
        b["agent"] = m.group(1).strip() if m else "KnowledgeBase"
        # QUESTION:
        m = re.search(r"^QUESTION:\s*(.+)$", raw, re.MULTILINE)
        b["question"] = m.group(1).strip() if m else ""
        # SOURCE:
        m = re.search(r"^SOURCE:\s*(.+)$", raw, re.MULTILINE)
        b["source"] = m.group(1).strip() if m else ""
        # SYSTEM_PROMPT: (everything between that line and ---CONTEXT---)
        m = re.search(r"^SYSTEM_PROMPT:\n(.*?)^---CONTEXT---",
                      raw, re.DOTALL | re.MULTILINE)
        b["system_prompt"] = m.group(1).strip() if m else ""
        # CONTEXT: (everything after ---CONTEXT---)
        m = re.search(r"^---CONTEXT---\n(.*)$", raw, re.DOTALL | re.MULTILINE)
        b["context"] = m.group(1).strip() if m else raw.strip()
        blocks.append(b)
    return blocks


def _call_ollama(system: str, user: str) -> str | None:
    """
    POST to Ollama /api/chat with the assembled prompt.
    Returns the answer string, or None if Ollama is unreachable.
    """
    try:
        import urllib.request
        payload = json.dumps({
            "model":    MODEL,
            "stream":   False,
            "messages": [
                {"role": "system",    "content": system},
                {"role": "user",      "content": user},
            ],
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data["message"]["content"]
    except Exception:
        return None


def _answer_from_blocks(blocks: list[dict], question: str) -> None:
    """
    Given parsed passthrough blocks, build one combined prompt and send
    it to Ollama.  Falls back to printing raw context if Ollama is down.
    """
    # Merge context from all matched domains into one prompt
    context_sections = []
    system_parts     = []
    for b in blocks:
        if b["context"]:
            context_sections.append(
                f"[{b['agent']} — source: {b['source']}]\n{b['context']}"
            )
        if b["system_prompt"] and b["system_prompt"] not in system_parts:
            system_parts.append(b["system_prompt"])

    combined_context = "\n\n---\n\n".join(context_sections)
    system_prompt    = "\n\n".join(system_parts) or (
        "You are a helpful knowledge-base assistant. "
        "Answer only from the provided context. "
        "If the context does not contain the answer, say so."
    )
    user_prompt = (
        f"Context from the knowledge base:\n\n{combined_context}"
        f"\n\n---\n\nQuestion: {question}"
    )

    print(_dim(f"\n[ask.py] Ollama is handling the answer ({MODEL})…\n"))
    answer = _call_ollama(system_prompt, user_prompt)

    if answer:
        print(answer)
    else:
        # Ollama also unreachable — print raw context so user still has something
        print(_red("[ask.py] Ollama unreachable. Printing retrieved context instead:\n"))
        for b in blocks:
            print(_bold(f"─── {b['agent']} (source: {b['source']}) ───"))
            print(textwrap.fill(b["context"][:3000], width=100))
            print()


# ── Drift check ───────────────────────────────────────────────────────────────

def _check_drift() -> int:
    """
    Compare the live folder state against the last audit.jsonl entry.

    Returns:
        0  — index is current (or audit not yet populated — run generate.py first)
        1  — drift detected (files added/removed since last index run)
    """
    audit_path = REPO_ROOT / ".kb_index" / "audit.jsonl"

    # Discover folders using the same blocklist as generate.py
    _DEFAULT_BLOCKLIST = {
        "agents", ".git", "__pycache__", ".ds_store", "node_modules",
        ".venv", "venv", "env", ".bob", ".idea", ".vscode", "dist", "build",
        ".kb_index", "kb_agent_mcp", "kb_agent_mcp.egg-info", "node_modules",
        "scripts", "tests",
    }
    _INCLUDE_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt",
                     ".csv", ".boxnote", ".ppt", ".doc", ".png", ".jpg", ".jpeg"}
    _SKIP = {"readme", ".ds_store"}

    def _count_files(root: pathlib.Path) -> dict[str, int]:
        counts: dict[str, int] = {}
        for folder in sorted(root.iterdir()):
            if not folder.is_dir():
                continue
            if folder.name.lower() in _DEFAULT_BLOCKLIST:
                continue
            n = sum(
                1 for f in folder.rglob("*")
                if f.is_file()
                and f.suffix.lower() in _INCLUDE_EXTS
                and not any(p in f.name.lower() for p in _SKIP)
            )
            if n > 0:
                counts[folder.name] = n
        return counts

    live = _count_files(REPO_ROOT)
    live_total = sum(live.values())

    print(_bold("\n📊  KnowledgeBase Drift Check"))
    print(_dim(f"  KB root: {REPO_ROOT}"))
    print()

    if not audit_path.exists() or audit_path.stat().st_size == 0:
        print(_dim("  ⚠  No audit log found. Run `python3 scripts/generate.py` first."))
        print()
        print(_bold("  Live file counts:"))
        for folder, n in sorted(live.items()):
            print(f"    {folder}: {n} file(s)")
        print(f"\n  Total: {live_total} file(s) across {len(live)} domain(s)")
        return 0

    # Read the last audit entry
    last_entry: dict = {}
    try:
        lines = [l for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        last_entry = json.loads(lines[-1])
    except Exception as e:
        print(_red(f"  ✗ Could not read audit log: {e}"))
        return 1

    indexed_total = last_entry.get("files", 0)
    indexed_ts    = last_entry.get("ts", "unknown")
    indexed_domains = last_entry.get("domains", [])

    # Calculate drift
    drift_folders: list[str] = []
    new_folders   = [f for f in live if f not in indexed_domains]
    gone_folders  = [f for f in indexed_domains if f not in live]

    # Check mtime: any file newer than the audit timestamp = possible unindexed change
    try:
        audit_dt = datetime.datetime.fromisoformat(indexed_ts)
        audit_ts = audit_dt.timestamp()
    except Exception:
        audit_ts = 0

    recent_files: list[str] = []
    for folder in sorted(REPO_ROOT.iterdir()):
        if not folder.is_dir() or folder.name.lower() in _DEFAULT_BLOCKLIST:
            continue
        for f in folder.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in _INCLUDE_EXTS:
                continue
            if any(p in f.name.lower() for p in _SKIP):
                continue
            try:
                if f.stat().st_mtime > audit_ts:
                    recent_files.append(f"{folder.name}/{f.name}")
            except OSError:
                continue

    total_drift = (live_total - indexed_total) if indexed_total else 0
    has_drift   = bool(new_folders or gone_folders or recent_files)

    if not has_drift:
        print(_grn("  ✅  Index is current — no drift detected."))
        print(_dim(f"  Last indexed: {indexed_ts}  ({indexed_total} files, {len(indexed_domains)} domain(s))"))
        return 0

    print(_red("  ⚠️   Drift detected — index may be out of date!"))
    print(_dim(f"  Last indexed: {indexed_ts}"))
    print()

    if new_folders:
        print(_bold("  New folders not yet indexed:"))
        for f in new_folders:
            print(f"    + {f}/  ({live.get(f, 0)} file(s))")
        print()

    if gone_folders:
        print(_bold("  Folders removed since last index:"))
        for f in gone_folders:
            print(f"    - {f}/")
        print()

    if recent_files:
        shown = recent_files[:15]
        print(_bold(f"  Files modified after last index run ({len(recent_files)} total):"))
        for fname in shown:
            print(f"    ~ {fname}")
        if len(recent_files) > 15:
            print(f"    … and {len(recent_files) - 15} more")
        print()

    if total_drift != 0:
        direction = f"+{total_drift}" if total_drift > 0 else str(total_drift)
        print(_dim(f"  File count delta: {direction} (indexed: {indexed_total}, live: {live_total})"))
        print()

    print(_bold("  Fix:  python3 scripts/generate.py"))
    print(_bold("     or restart the watcher:  python3 scripts/watch_kb.py"))
    print()
    return 1


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not AGENT.exists():
        print(_red(f"Agent not found: {AGENT}"))
        print("Run: python3 scripts/setup.py")
        sys.exit(1)

    # Handle --check-drift before passing args to the agent
    if "--check-drift" in sys.argv:
        sys.exit(_check_drift())

    # Pass all args straight through to agent_knowledgebase.py
    agent_args = sys.argv[1:]

    # Run the agent, capturing stdout while also streaming stderr live
    proc = subprocess.run(
        [sys.executable, str(AGENT)] + agent_args,
        capture_output=True,
        text=True,
    )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # Always surface stderr (progress messages, errors) to the user
    if stderr.strip():
        print(stderr, file=sys.stderr, end="")

    # ── Does stdout contain passthrough blocks? ───────────────────────────────
    if _PT_START in stdout:
        blocks = _extract_passthrough_blocks(stdout)
        if blocks:
            # Derive the question from the first block (they all share the same Q)
            question = blocks[0]["question"] or " ".join(
                a for a in agent_args if not a.startswith("--")
            )
            _answer_from_blocks(blocks, question)
            return

    # ── Normal path: agent answered directly (Ollama was running) ────────────
    print(stdout, end="")

    if proc.returncode != 0:
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
