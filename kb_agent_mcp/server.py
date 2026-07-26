"""
kb_agent_mcp/server.py
──────────────────────
FastMCP server exposing five tools:

  ask(question, format, session_id)
    → Query all relevant knowledge domains and return an answer.

  list_domains()
    → Return the names and descriptions of all indexed domains.

  reindex()
    → Re-scan KB_ROOT and rebuild the vector index for all domains.

  clear_memory(session_id)
    → Delete the conversation history for a session.

  show_memory(session_id)
    → Return a summary of the current session state.

Transport:
  Default (stdio):  kb-agent-serve
  HTTP/SSE:         kb-agent-serve --transport http [--port 8765]

Usage:
  kb-agent-serve                          # stdio
  kb-agent-serve --transport http         # HTTP on port 8765
  kb-agent-serve --transport http --port 9000
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid

from fastmcp import FastMCP

from kb_agent_mcp.config import cfg
from kb_agent_mcp import __version__

# ── Stale-index TTL cache (Risk 11) ───────────────────────────────────────────
# _stale_cache holds the last scan result and the monotonic timestamp it was taken.
# Cleared by reindex() so the next ask() sees a fresh scan.
_stale_cache: dict = {"stale": False, "details": "", "checked_at": 0.0}


def _check_stale_cached() -> tuple[bool, str]:
    """
    Return (is_stale, detail_string).

    Runs a lightweight mtime scan across all domain folders.  The result is
    cached for KB_STALE_CHECK_TTL_SECONDS seconds to avoid per-query I/O.
    TTL=0 disables the check entirely.
    """
    ttl = cfg.KB_STALE_CHECK_TTL_SECONDS
    if ttl == 0:
        return False, ""

    now = time.monotonic()
    if now - _stale_cache["checked_at"] < ttl:
        return _stale_cache["stale"], _stale_cache["details"]

    # Perform the scan
    kb_root = cfg.kb_root_path
    stale_domains: list[str] = []

    try:
        from kb_agent_mcp.vector_store import get_domain_metadata
        for entry in sorted(kb_root.iterdir()):
            if not entry.is_dir() or cfg.is_ignored(entry.name):
                continue
            meta = get_domain_metadata(entry.name) or {}
            last_indexed = float(meta.get("indexed_at", 0))
            if last_indexed == 0:
                continue  # never indexed — skip (generate hasn't run yet)
            for f in entry.rglob("*"):
                if f.is_file() and f.stat().st_mtime > last_indexed:
                    stale_domains.append(entry.name)
                    break  # one new file is enough to flag the domain
    except Exception:
        # Scan failure is non-fatal — don't block the answer
        _stale_cache.update({"stale": False, "details": "", "checked_at": now})
        return False, ""

    if stale_domains:
        detail = (
            f"⚠ Index may be stale — files modified since last index in: "
            f"{', '.join(stale_domains)}.\n"
            f"  Fix: call `reindex()` here, or run `kb-agent-generate` in your terminal.\n\n"
            f"─────────────────────────────────────────────────────────────────\n"
        )
        _stale_cache.update({"stale": True, "details": detail, "checked_at": now})
        return True, detail

    _stale_cache.update({"stale": False, "details": "", "checked_at": now})
    return False, ""


def _clear_stale_cache() -> None:
    """Reset the stale cache — called by reindex() after index rebuild."""
    _stale_cache.update({"stale": False, "details": "", "checked_at": 0.0})

# ── FastMCP application ────────────────────────────────────────────────────────

mcp = FastMCP(
    name="kb-agent-mcp",
    version=__version__,
    instructions=(
        "Multi-agent knowledge base MCP server. "
        "Indexes any folder of documents and answers questions via RAG."
    ),
)


# ── Tool: ask ─────────────────────────────────────────────────────────────────

# ── Transport mode (set at startup, used by ask() for HTTP session auto-UUID) ─
_transport_mode: str = "stdio"


@mcp.tool()
async def ask(
    question: str,
    format: str = "",
    session_id: str = "default",
) -> str:
    """
    Query the knowledge base and return an answer.

    Args:
        question:   Your question (natural language). May include format phrases
                    like "as a table" or "in bullet points".
        format:     Optional explicit output format. Supported values:
                    table | bullets | oneline | paragraph | numbered | json
        session_id: Conversation session ID for multi-turn context.
                    Use the same ID across calls to maintain history.
                    On HTTP transport, a unique session_id is auto-generated
                    when the default "default" is used — the generated ID is
                    embedded in the response as <!-- session_id: <id> --> so
                    callers can reuse it across reconnects for continuity.
                    On stdio (Claude Desktop / Bob) the default session is safe
                    because the transport is always single-user.

    Returns:
        Markdown-formatted answer string.
    """
    # Risk 10 — HTTP transport: auto-generate a UUID session to prevent
    # conversation bleed between independent callers on the same server.
    # The generated ID is surfaced in the response so callers can resume.
    effective_session = session_id
    generated_session: str | None = None
    if _transport_mode == "http" and session_id == "default":
        effective_session = f"sess-{uuid.uuid4().hex[:12]}"
        generated_session = effective_session

    from kb_agent_mcp.orchestrator import ask as _ask

    # Risk 11 — prepend stale-index warning when TTL cache detects new files.
    stale, stale_detail = _check_stale_cached()
    answer = await _ask(
        question=question,
        session_id=effective_session,
        format_flag=format or None,
    )

    if stale:
        answer = stale_detail + answer

    # Surface the auto-generated session ID as a hidden comment so callers
    # can extract and reuse it without polluting the visible markdown.
    if generated_session:
        answer = f"<!-- session_id: {generated_session} -->\n\n" + answer

    return answer


# ── Tool: list_domains ─────────────────────────────────────────────────────────

@mcp.tool()
async def list_domains() -> str:
    """
    List all indexed knowledge domains.

    Returns a newline-separated list of domain names and descriptions,
    one per line in the format:  <folder_name>: <description>
    """
    from kb_agent_mcp.orchestrator import list_domains as _list

    domains = await _list()
    # orchestrator returns a single sentinel entry when no real domains exist
    if not domains or (len(domains) == 1 and domains[0]["folder_name"] == "_no_domains"):
        return domains[0]["description"] if domains else (
            "No domains indexed yet. Run `kb-agent-generate` to discover "
            f"knowledge folders under {cfg.kb_root_path}"
        )
    lines = [f"**{d['folder_name']}** ({d['agent_name']}): {d['description']}" for d in domains]
    return "\n".join(lines)


# ── Tool: reindex ──────────────────────────────────────────────────────────────

@mcp.tool()
async def reindex() -> str:
    """
    Re-scan the knowledge base root and rebuild vector indexes for all domains.

    Use this after adding new files or creating new knowledge folders.
    Returns a summary of what was indexed.
    """
    from kb_agent_mcp.vector_store import build_collection as _build
    from kb_agent_mcp.orchestrator import refresh_agents
    from kb_agent_mcp.base_agent import reset_passthrough_cache

    kb_root = cfg.kb_root_path
    if not kb_root.exists():
        return f"KB_ROOT does not exist: {kb_root}"

    indexed_domains: list[str] = []
    errors: list[str] = []

    for entry in sorted(kb_root.iterdir()):
        if not entry.is_dir() or cfg.is_ignored(entry.name):
            continue
        try:
            count = await _build(entry.name)
            indexed_domains.append(f"  ✓ {entry.name}: {count} files")
        except Exception as e:
            errors.append(f"  ✗ {entry.name}: {e}")

    # Refresh in-memory agent registry after reindex
    await refresh_agents()
    reset_passthrough_cache()

    # Risk 11 — clear stale cache so next ask() sees fresh state
    _clear_stale_cache()

    # Risk 9 — new domains without domain_config.yaml: surface warning FIRST
    # so users see the actionable message before the index summary.
    no_config = [
        entry.name
        for entry in sorted(kb_root.iterdir())
        if entry.is_dir()
        and not cfg.is_ignored(entry.name)
        and not (entry / "domain_config.yaml").exists()
    ]

    lines: list[str] = []
    if no_config:
        lines.append(
            "⚠ New domain folder(s) detected without `domain_config.yaml`:\n"
            "  " + ", ".join(no_config) + "\n"
            "  These folders are indexed in ChromaDB but NOT yet queryable.\n"
            "  Run `kb-agent-generate` from your terminal to generate configs,\n"
            "  then call `list_domains()` to confirm they are active.\n"
        )

    lines.append(f"Reindex complete — KB_ROOT: {kb_root}")
    if indexed_domains:
        lines.append("\nIndexed domains:")
        lines.extend(indexed_domains)
    if errors:
        lines.append("\nErrors:")
        lines.extend(errors)
    if not indexed_domains and not errors:
        lines.append("No indexable domains found.")

    return "\n".join(lines)


# ── Tool: clear_memory ─────────────────────────────────────────────────────────

@mcp.tool()
async def clear_memory(session_id: str = "default") -> str:
    """
    Clear the conversation history for a session.

    Args:
        session_id: The session to clear. Defaults to "default".

    Returns:
        Confirmation message.
    """
    from kb_agent_mcp.memory import clear as _clear
    await _clear(session_id)
    return f"Session '{session_id}' memory cleared."


# ── Tool: show_memory ──────────────────────────────────────────────────────────

@mcp.tool()
async def show_memory(session_id: str = "default") -> str:
    """
    Show the current conversation history for a session.

    Args:
        session_id: The session to inspect. Defaults to "default".

    Returns:
        Summary and recent conversation turns.
    """
    from kb_agent_mcp.memory import get_history as _history, summary as _summary

    status  = await _summary(session_id)
    history = await _history(session_id)

    if not history:
        return status

    lines = [status, ""]
    for i in range(0, len(history), 2):
        user_msg = history[i]["content"][:200].replace("\n", " ")
        asst_msg = (history[i + 1]["content"][:200].replace("\n", " ") if i + 1 < len(history) else "")
        turn = (i // 2) + 1
        lines.append(f"[{turn}] User: {user_msg}")
        lines.append(f"     Bot:  {asst_msg}")
    return "\n".join(lines)


# ── Entry point ────────────────────────────────────────────────────────────────

def _rich_kb_root_error(root_val: str, root_path: str) -> str:
    """Return a human-readable KB_ROOT error message for both stdout and stderr."""
    if not root_val:
        problem = "KB_ROOT is not set."
    else:
        problem = f"KB_ROOT does not exist or is not a directory: {root_path}"

    return (
        f"\n✗ {problem}\n\n"
        "  The kb-agent-mcp server requires KB_ROOT to point to your\n"
        "  knowledge base folder.\n\n"
        "  Fix: add KB_ROOT to your MCP host config env block:\n\n"
        '    "kb-agent-mcp": {\n'
        '      "command": "/absolute/path/to/kb-agent-serve",\n'
        '      "env": {\n'
        '        "KB_ROOT": "/absolute/path/to/your/KnowledgeBase"\n'
        '      }\n'
        '    }\n\n'
        "  Then restart your MCP host (Claude Desktop / Bob / Cursor).\n"
        "  Run `kb-agent-doctor` for a full health check.\n"
    )


def main() -> None:
    global _transport_mode

    parser = argparse.ArgumentParser(
        prog="kb-agent-serve",
        description="Start the kb-agent-mcp MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="HTTP port when --transport http (default: 8765)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit",
    )
    args = parser.parse_args()

    if args.version:
        print(f"kb-agent-mcp {__version__}")
        sys.exit(0)

    # Risk 2 — Hard fail when KB_ROOT is missing or invalid.
    # Print to BOTH stdout and stderr: some MCP hosts capture one but not the other.
    errors = cfg.validate()
    if errors:
        msg = _rich_kb_root_error(cfg.KB_ROOT, str(cfg.kb_root_path))
        print(msg, file=sys.stderr)
        print(msg)  # also stdout so MCP hosts that only read stdout see it
        sys.exit(1)

    # Risk 2 — Soft warning when KB_ROOT is not explicitly set (fell back to CWD).
    # This is the most common silent failure — print to stderr for log visibility.
    if not cfg.kb_root_is_explicit:
        warn_msg = (
            "⚠  KB_ROOT is not set — defaulting to current working directory "
            f"({cfg.kb_root_path}).\n"
            "   Add KB_ROOT to your MCP host config env block:\n"
            '     "env": { "KB_ROOT": "/absolute/path/to/your/KnowledgeBase" }'
        )
        print(warn_msg, file=sys.stderr)

    # Risk 12 — Catch ChromaDB schema incompatibility at startup.
    # Importing the client here triggers the error early with a clean message.
    try:
        from kb_agent_mcp.vector_store import _get_client
        _get_client()
    except RuntimeError as exc:
        msg = str(exc)
        print(msg, file=sys.stderr)
        print(msg)
        sys.exit(1)

    _transport_mode = args.transport

    # Risk 10 — HTTP transport: warn about shared default session.
    if args.transport == "http":
        print(
            "⚠  HTTP transport: multiple callers share the \"default\" session.\n"
            "   Pass a unique session_id per user to isolate conversation history.\n"
            "   When session_id is omitted, a UUID is auto-generated per call and\n"
            "   returned as <!-- session_id: <id> --> in the response.",
            file=sys.stderr,
        )
        mcp.run(transport="sse", host="0.0.0.0", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
