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

from fastmcp import FastMCP

from kb_agent_mcp.config import cfg
from kb_agent_mcp import __version__

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
                    Default "default" is shared across all callers.

    Returns:
        Markdown-formatted answer string.
    """
    from kb_agent_mcp.orchestrator import ask as _ask
    return await _ask(
        question=question,
        session_id=session_id,
        format_flag=format or None,
    )


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
    if not domains:
        return (
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

    lines = [f"Reindex complete — KB_ROOT: {kb_root}"]
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

def main() -> None:
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

    errors = cfg.validate()
    if errors:
        print("Configuration errors:", file=sys.stderr)
        for e in errors:
            print(f"  • {e}", file=sys.stderr)
        sys.exit(1)

    if args.transport == "http":
        mcp.run(transport="sse", host="0.0.0.0", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
