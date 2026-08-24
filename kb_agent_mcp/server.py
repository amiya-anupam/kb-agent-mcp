"""
kb_agent_mcp/server.py
──────────────────────
FastMCP server exposing sixteen tools:

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

  resume_session(session_id)
    → Show conversation history for a named session (for resuming across restarts).

  list_sessions()
    → List all named sessions / workspaces with turn count and last-active time.

  rate_answer(rating, session_id, comment)
    → Submit a 1–5 star rating for the most recent answer.

  update_document(rel_path, content, mode)
    → Write or append content to a file in KB_ROOT and re-index it immediately.

  ── Data Analyst tools ──────────────────────────────────────────────────────

  analyze_file(path)
    → Profile any file and return a DataCard (schema, grain, themes, summary).

  suggest_questions(path)
    → Return analytical questions grouped by theme based on the DataCard.

  query_data(path, question, session_id)
    → Ask clarifying questions OR return answer + reasoning.

  refine_query(session_id, feedback)
    → Re-run the last query with updated parameters from user feedback.

  compare_data(path_a, path_b, question, session_id, metric_col, time_col)
    → Compare two files side-by-side; emits a period × diff table (B − A).

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
from kb_agent_mcp.audit import log_turn as _audit_log, read_log as _audit_read

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
    #
    # Feature 12 (short-term) — KB_DEFAULT_SESSION_ID: when the caller passes
    # the generic "default" and a named default is configured, substitute it so
    # all conversation history accumulates under a stable personal session that
    # survives server restarts.
    effective_session = session_id
    generated_session: str | None = None
    if session_id == "default" and cfg.KB_DEFAULT_SESSION_ID:
        effective_session = cfg.KB_DEFAULT_SESSION_ID
    elif _transport_mode == "http" and session_id == "default":
        effective_session = f"sess-{uuid.uuid4().hex[:12]}"
        generated_session = effective_session

    from kb_agent_mcp.orchestrator import ask as _ask, _agents as _loaded_agents

    # Security gate — refuse to answer when confidential files have been
    # detected but the user has not yet acknowledged them with the token.
    # is_gate_acknowledged() is a fast local dict lookup; no I/O on the
    # happy path once the session is acknowledged.
    if cfg.KB_SECURITY_GATE_ENABLED:
        from kb_agent_mcp.security_gate import is_gate_acknowledged, load_gate_session
        if not is_gate_acknowledged(effective_session):
            sess = load_gate_session(effective_session)
            if sess is not None and sess.status == "blocked":
                files_list = "\n".join(
                    f"  🔒 {e['relative_path']}  ({e['reason']})"
                    for e in sess.confidential_files
                )
                return (
                    "⛔ **Security gate is active for this session.**\n\n"
                    "Confidential files were detected:\n"
                    f"{files_list}\n\n"
                    "Call `check_confidential()` to see the acknowledgement token, "
                    "then call `acknowledge_gate()` with that token to proceed."
                )

    # Cat 4 — Cold-start sentinel: agents haven't been loaded yet for this process.
    # The first ask() call triggers ChromaDB + sentence-transformers loading (1–3s).
    # We can't stream a "loading…" message before the call returns in stdio/MCP, but
    # we can prepend a brief note to the ANSWER so the user sees it was a cold start
    # and understands why the first response takes longer.
    _cold_start = _loaded_agents is None

    # Risk 11 — prepend stale-index warning when TTL cache detects new files.
    stale, stale_detail = _check_stale_cached()
    _t0 = time.monotonic()
    answer = await _ask(
        question=question,
        session_id=effective_session,
        format_flag=format or None,
    )
    _latency_ms = int((time.monotonic() - _t0) * 1000)

    if _cold_start:
        answer = (
            "*⏱ Cold start — indexes loaded for the first time this session.*\n\n"
            + answer
        )

    if stale:
        answer = stale_detail + answer

    # Surface the auto-generated session ID as a hidden comment so callers
    # can extract and reuse it without polluting the visible markdown.
    if generated_session:
        answer = f"<!-- session_id: {generated_session} -->\n\n" + answer

    # ── Feature 4: Audit log ──────────────────────────────────────────────────
    # Detect whether the gate blocked the answer (doesn't touch gate machinery).
    _blocked = answer.startswith("⛔ **Security gate is active")
    # Extract cited file paths from the orchestrator result via sources in the
    # answer text (heuristic: lines matching the source label pattern).
    # A lightweight parse — source paths are already in the answer footer.
    import re as _re
    _files_cited = _re.findall(r"\*Source: ([^\n*]+)\*", answer)
    # Determine which domains were queried from the orchestrator's agent map.
    try:
        from kb_agent_mcp.orchestrator import _agents as _agt
        _domains = list(_agt.keys()) if _agt else []
    except Exception:
        _domains = []
    _audit_log(
        session_id=effective_session,
        question=question,
        domains=_domains,
        files_cited=_files_cited,
        answer=answer,
        blocked=_blocked,
        latency_ms=_latency_ms,
    )

    return answer


# ── Tool: check_confidential ───────────────────────────────────────────────────

@mcp.tool()
async def check_confidential(session_id: str = "default") -> str:
    """
    Scan all knowledge domains for confidential-flagged files and activate
    the security gate when any are found.

    If confidential files exist, a one-time acknowledgement token is generated
    and returned.  You must pass this token to acknowledge_gate() before ask()
    will answer questions that touch those files.

    The token is generated fresh on every call — it cannot be pre-planted
    in any document, because it did not exist when the document was indexed.

    Args:
        session_id: The session to gate. Use the same session_id as your ask()
                    calls so the gate state is shared.

    Returns:
        A report of confidential files found, or a "clear" status when none exist.
    """
    if not cfg.KB_SECURITY_GATE_ENABLED:
        return "ℹ Security gate is disabled (KB_SECURITY_GATE_ENABLED=false)."

    from kb_agent_mcp.security_gate import (
        scan_all_domains,
        generate_ack_token,
        GateSession,
        save_gate_session,
    )
    import asyncio as _asyncio

    entries = await _asyncio.to_thread(scan_all_domains)

    if not entries:
        from kb_agent_mcp.security_gate import GateSession, save_gate_session
        clear_sess = GateSession(
            session_id=session_id,
            status="clear",
            ack_token="",
            confidential_files=[],
        )
        await _asyncio.to_thread(save_gate_session, clear_sess)
        return (
            "✅ **Security gate: clear.**\n\n"
            "No confidential-flagged files found. You can call `ask()` freely."
        )

    token = generate_ack_token()
    sess = GateSession(
        session_id=session_id,
        status="blocked",
        ack_token=token,
        confidential_files=[
            {"domain": e.domain, "relative_path": e.relative_path,
             "filename": e.filename, "reason": e.reason}
            for e in entries
        ],
    )
    await _asyncio.to_thread(save_gate_session, sess)

    files_list = "\n".join(
        f"  🔒 {e.relative_path}\n     ↳ Reason: {e.reason}"
        for e in entries
    )
    return (
        "⛔ **Security gate activated.**\n\n"
        f"The following {len(entries)} file(s) contain confidentiality signals:\n\n"
        f"{files_list}\n\n"
        "─────────────────────────────────────────────────────\n"
        f"**Acknowledgement token: `{token}`**\n\n"
        "Type this token yourself — do not copy it from a document.\n"
        "Call `acknowledge_gate()` with this token to proceed.\n\n"
        "> ⚠ This token expires when you call `check_confidential()` again.\n"
        "> Once acknowledged, confidential file content will be included in answers\n"
        "> with a 🔒 prefix on every citation."
    )


# ── Tool: acknowledge_gate ────────────────────────────────────────────────────

@mcp.tool()
async def acknowledge_gate(session_id: str, token: str) -> str:
    """
    Acknowledge the security gate for a session by providing the token
    printed by check_confidential().

    The token must be typed by a live user — it cannot come from document
    content, because it was generated after all documents were indexed.

    Args:
        session_id: The session to unlock (must match the session_id used in
                    check_confidential()).
        token:      The acknowledgement token shown by check_confidential().

    Returns:
        Confirmation message on success, or an error with instructions to
        call check_confidential() again for a fresh token on failure.
    """
    if not cfg.KB_SECURITY_GATE_ENABLED:
        return "ℹ Security gate is disabled (KB_SECURITY_GATE_ENABLED=false)."

    import asyncio as _asyncio
    from kb_agent_mcp.security_gate import (
        load_gate_session,
        validate_ack_token,
        save_gate_session,
    )

    sess = await _asyncio.to_thread(load_gate_session, session_id)

    if sess is None:
        return (
            "❌ No active gate session found for this session_id.\n\n"
            "Call `check_confidential()` first to scan for confidential files "
            "and receive an acknowledgement token."
        )

    if sess.status == "clear":
        return "✅ No confidential files were detected. No acknowledgement needed."

    if sess.status == "acknowledged":
        return "✅ Gate already acknowledged for this session."

    # Validate the token (constant-time compare)
    if not validate_ack_token(sess.ack_token, token):
        return (
            "❌ **Wrong token.** The token you provided does not match.\n\n"
            "Call `check_confidential()` again to generate a new token.\n"
            "> Tip: tokens are case-insensitive (e.g. `b7e2` and `B7E2` both work)."
        )

    # Token correct — mark acknowledged
    sess.status = "acknowledged"
    sess.acknowledged_at = time.time()
    await _asyncio.to_thread(save_gate_session, sess)

    file_count = len(sess.confidential_files)
    return (
        f"✅ **Gate cleared for session `{session_id}`.**\n\n"
        f"{file_count} confidential file(s) are now included in answers.\n"
        "All citations from these files will be prefixed with 🔒."
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

    # Security gate — clear all gate sessions after reindex.
    # New files may have been added that contain confidential signals;
    # every session must re-run check_confidential() against the fresh index.
    if cfg.KB_SECURITY_GATE_ENABLED:
        from kb_agent_mcp.security_gate import clear_all_gate_sessions
        clear_all_gate_sessions()

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


# ── Tool: analyze_file ────────────────────────────────────────────────────────

@mcp.tool()
async def analyze_file(path: str) -> str:
    """
    Profile any file and return a DataCard — a structured description of what
    the file contains, its schema, data types, grain, and analytical themes.

    Works with: .xlsx, .xls, .csv, .json, .jsonl, .pdf, .docx, .pptx, .txt, .md

    Args:
        path: Path to the file. Can be absolute or relative to KB_ROOT.

    Returns:
        JSON string containing the DataCard profile.
    """
    import json as _json
    from pathlib import Path as _Path
    from kb_agent_mcp.analyst.inspector import inspect_file as _inspect, data_card_to_dict

    file_path = _Path(path)
    if not file_path.is_absolute():
        file_path = cfg.kb_root_path / path

    if not file_path.exists():
        return _json.dumps({"error": f"File not found: {path}"})

    card = await _inspect(str(file_path))
    return _json.dumps(data_card_to_dict(card), indent=2, default=str)


# ── Tool: suggest_questions ────────────────────────────────────────────────────

@mcp.tool()
async def suggest_questions(path: str) -> str:
    """
    Return analytical questions the AI can answer for a given file, grouped
    by theme (revenue, attrition, growth, concentration, anomaly, summary).

    Args:
        path: Path to the file. Can be absolute or relative to KB_ROOT.

    Returns:
        JSON string mapping theme → list of questions with clarification metadata.
    """
    import json as _json
    from pathlib import Path as _Path
    from kb_agent_mcp.analyst.inspector import inspect_file as _inspect, data_card_to_dict
    from kb_agent_mcp.analyst.planner import suggest_questions as _suggest

    file_path = _Path(path)
    if not file_path.is_absolute():
        file_path = cfg.kb_root_path / path

    if not file_path.exists():
        return _json.dumps({"error": f"File not found: {path}"})

    card = await _inspect(str(file_path))
    menu = await _suggest(card)
    return _json.dumps(menu, indent=2, default=str)


# ── Tool: query_data ──────────────────────────────────────────────────────────

@mcp.tool()
async def query_data(
    path: str,
    question: str,
    session_id: str = "",
) -> str:
    """
    Ask a data computation question about a file.

    The tool will:
      1. Profile the file (schema, columns, data types).
      2. Ask clarifying questions if needed (e.g. which time period, which metric).
      3. Run the computation and return the answer with full reasoning.

    Works with: .xlsx, .xls, .csv, .json, .jsonl and document formats.

    Args:
        path:       Path to the file (absolute or relative to KB_ROOT).
        question:   Natural-language question, e.g.:
                    "What are the top 10 customers by revenue in FY2025?"
                    "How many customers churned compared to last year?"
        session_id: Optional session ID for multi-turn conversations.
                    If blank, a new session is created automatically.

    Returns:
        JSON string with keys: status, session_id, answer, reasoning,
        suggested_followups, clarifications (when clarification is needed),
        and chart_data (null or an object with keys: type, labels, datasets,
        csv, mermaid).  Use chart_data["csv"] to save the data as a file,
        chart_data["mermaid"] to render a chart inline (single-dataset only),
        or chart_data["datasets"] to drive a custom visualisation.
    """
    import json as _json
    from kb_agent_mcp.analyst.engine import query_data as _query

    result = await _query(path=path, question=question, session_id=session_id or None)
    return _json.dumps(result, indent=2, default=str)


# ── Tool: refine_query ────────────────────────────────────────────────────────

@mcp.tool()
async def refine_query(session_id: str, feedback: str) -> str:
    """
    Refine the last data query based on user feedback.

    Use this to:
      • Answer a clarifying question (e.g. "Use FY2025" or "Rev Act @ PC")
      • Correct an assumption (e.g. "Actually just Q4 data")
      • Adjust output (e.g. "Show top 20 instead")
      • Ask a follow-up (e.g. "Now group by geography")

    Args:
        session_id: The session ID returned by a previous query_data call.
        feedback:   Your correction or follow-up in natural language.

    Returns:
        JSON string with the updated answer + reasoning.
    """
    import json as _json
    from kb_agent_mcp.analyst.engine import refine_query as _refine

    result = await _refine(session_id=session_id, feedback=feedback)
    return _json.dumps(result, indent=2, default=str)


# ── Tool: compare_data ────────────────────────────────────────────────────────

@mcp.tool()
async def compare_data(
    path_a: str,
    path_b: str,
    question: str = "",
    session_id: str = "",
    metric_col: str = "",
    time_col: str = "",
) -> str:
    """
    Compare two tabular data files side-by-side.

    Loads both files, aggregates each by time period (quarter, year, etc.),
    aligns the periods, and returns a diff table showing:
      • Value in file A for each period
      • Value in file B for each period
      • Absolute change (B − A) per period
      • Percentage change (B − A) / A per period
      • A grand-total row when multiple periods exist

    Typical use: "compare Q3 vs Q4 renewal trackers",
                 "how does this year's pipeline compare to last year's?"

    Works with: .xlsx, .xls, .csv, .json, .jsonl

    Args:
        path_a:     First file  — the baseline  (A).
                    Absolute path or relative to KB_ROOT.
        path_b:     Second file — the comparison (B).
                    Absolute path or relative to KB_ROOT.
        question:   Optional natural-language description to guide column
                    selection, e.g. "compare revenue by quarter".
        session_id: Optional session ID for multi-turn follow-up via
                    refine_query(). Auto-generated when blank.
        metric_col: Explicit metric column to use in both files.
                    Leave blank to auto-detect from the DataCard.
        time_col:   Explicit time / period column to group by.
                    Leave blank to auto-detect.

    Returns:
        JSON string with keys: status, session_id, question, answer,
        reasoning, suggested_followups, warnings, file_a, file_b,
        and chart_data (grouped bar — two datasets, one per file).
        chart_data["csv"] contains both series as a CSV attachment.
        chart_data["mermaid"] is omitted for multi-dataset comparisons
        (use chart_data["datasets"] to drive a custom chart instead).
        (plus "error" when status == "error")
    """
    import json as _json
    from kb_agent_mcp.analyst.engine import compare_data as _compare

    result = await _compare(
        path_a=path_a,
        path_b=path_b,
        question=question,
        session_id=session_id or None,
        metric_col=metric_col,
        time_col=time_col,
    )
    return _json.dumps(result, indent=2, default=str)


# ── Tool: domain_status ────────────────────────────────────────────────────────

@mcp.tool()
async def domain_status() -> str:
    """
    Return a health card for all indexed knowledge domains.

    For each domain shows:
      • Files on disk vs files indexed in the vector store
      • Last indexed timestamp
      • Number of unindexed (new) files
      • Overall status: ✅ current | ⚠ stale (new files) | ❌ not indexed

    Use this to verify your knowledge base is up-to-date after adding files.
    If 'new files' > 0, run reindex() or restart the watcher to pick them up.
    """
    import datetime as _dt
    from kb_agent_mcp.orchestrator import _get_agents
    from kb_agent_mcp.vector_store import get_domain_metadata

    agents = await _get_agents()

    if not agents:
        return (
            "No knowledge domains found. "
            "Run `kb-agent-generate` first to build the knowledge index."
        )

    rows: list[str] = []
    rows.append("| Domain | On disk | Indexed | New files | Last indexed | Status |")
    rows.append("|--------|---------|---------|-----------|--------------|--------|")

    for name, agent in sorted(agents.items()):
        on_disk, indexed = agent.stale_file_count()
        new_files = max(0, on_disk - indexed)

        meta = get_domain_metadata(name) or {}
        ts = meta.get("indexed_at_iso") or meta.get("indexed_at")
        if ts:
            try:
                # Parse ISO string and format as readable local time
                dt = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                last_indexed = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                last_indexed = str(ts)[:16]
        else:
            last_indexed = "never"

        if last_indexed == "never":
            status = "❌ not indexed"
        elif new_files > 0:
            status = f"⚠ {new_files} new"
        else:
            status = "✅ current"

        rows.append(
            f"| **{name}** | {on_disk} | {indexed} "
            f"| {new_files if new_files else '—'} "
            f"| {last_indexed} | {status} |"
        )

    summary_lines = ["\n".join(rows)]

    # Append a hint when any domain has unindexed files
    stale_domains = [
        name for name, agent in agents.items()
        if max(0, agent.stale_file_count()[0] - agent.stale_file_count()[1]) > 0
    ]
    if stale_domains:
        summary_lines.append(
            f"\n> ⚠ **{len(stale_domains)} domain(s) have new unindexed files:** "
            f"{', '.join(stale_domains)}.\n"
            "> Call `reindex()` to update, or the watcher will pick them up automatically."
        )

    return "\n".join(summary_lines)


# ── Tool: read_audit ──────────────────────────────────────────────────────────

@mcp.tool()
async def read_audit(
    limit: int = 50,
    session_id: str = "",
) -> str:
    """
    Return recent audit log entries showing what questions were asked,
    which domains were queried, which files were cited, and response latency.

    Args:
        limit:      Maximum number of entries to return (default 50, max 500).
        session_id: Optional — filter to a specific session. Leave blank for all.

    Returns:
        Markdown table of audit entries, newest first.
    """
    import asyncio as _asyncio

    effective_limit = max(1, min(limit, 500))
    entries = await _asyncio.to_thread(
        _audit_read,
        effective_limit,
        session_id or None,
    )

    if not entries:
        msg = "No audit entries found"
        if session_id:
            msg += f" for session '{session_id}'"
        return msg + "."

    rows = ["| Time (UTC) | Session | Question | Domains | Files cited | Latency | Blocked |"]
    rows.append("|------------|---------|----------|---------|-------------|---------|---------|")

    for e in reversed(entries):  # newest first
        ts = e.get("iso", "")[:19].replace("T", " ")
        sess = e.get("session_id", "")[:12]
        q = e.get("question", "")[:60].replace("|", "\\|")
        if len(e.get("question", "")) > 60:
            q += "…"
        domains = ", ".join(e.get("domains", [])) or "—"
        files = e.get("files_cited", [])
        files_str = str(len(files)) + " file(s)" if files else "—"
        latency = f"{e.get('latency_ms', 0)}ms"
        blocked = "🔒 yes" if e.get("blocked") else "no"
        rows.append(
            f"| {ts} | {sess} | {q} | {domains} | {files_str} | {latency} | {blocked} |"
        )

    total = len(entries)
    header = f"**Audit log** — {total} entr{'y' if total == 1 else 'ies'}"
    if session_id:
        header += f" for session `{session_id}`"
    return header + "\n\n" + "\n".join(rows)


# ── Tool: resume_session ──────────────────────────────────────────────────────

@mcp.tool()
async def resume_session(session_id: str = "default") -> str:
    """
    Show the conversation history for a named session, so you can pick up
    where you left off after a server restart or reconnect.

    Args:
        session_id: The session to inspect. Leave blank to use the configured
                    default session (KB_DEFAULT_SESSION_ID if set, else "default").

    Returns:
        A formatted transcript of the session's turns, oldest first, or a
        message indicating the session is empty.
    """
    import asyncio as _asyncio
    from kb_agent_mcp.memory import get_history as _get_history

    eff = session_id
    if eff == "default" and cfg.KB_DEFAULT_SESSION_ID:
        eff = cfg.KB_DEFAULT_SESSION_ID

    messages = await _get_history(eff)

    if not messages:
        return (
            f"Session `{eff}` has no history.\n\n"
            "Start a conversation with `ask()` — history is automatically saved."
        )

    turns = len(messages) // 2
    lines = [f"**Session `{eff}`** — {turns} turn(s)\n"]
    for i, msg in enumerate(messages):
        role = "🧑 You" if msg["role"] == "user" else "🤖 KB"
        content = msg["content"]
        # Show first 300 chars of each message to keep the output scannable
        preview = content[:300] + ("…" if len(content) > 300 else "")
        lines.append(f"**{role}:** {preview}")
        if msg["role"] == "assistant" and i < len(messages) - 1:
            lines.append("")  # blank line between turns
    return "\n".join(lines)


# ── Tool: list_sessions ───────────────────────────────────────────────────────

@mcp.tool()
async def list_sessions() -> str:
    """
    List all named sessions / workspaces with their turn count, last-active
    time, and expiry status.

    Named sessions let you bookmark and resume deep investigations across
    server restarts without re-querying.  Pass the session name as
    `session_id` to `ask()`, `resume_session()`, or `clear_memory()`.

    Returns:
        A Markdown table of sessions sorted newest-first, or a message
        when no sessions have been created yet.
    """
    import asyncio as _asyncio
    import datetime as _dt
    from kb_agent_mcp.memory import list_sessions as _list

    sessions = await _list()

    if not sessions:
        return (
            "No named sessions found.\n\n"
            "Create one by passing `session_id='<name>'` to `ask()`, e.g.\n"
            '`ask("What is ACE?", session_id="ace-renewal-review")`\n\n'
            "The session persists across server restarts and can be resumed "
            "at any time with `resume_session(session_id='ace-renewal-review')`."
        )

    now = _dt.datetime.now(_dt.timezone.utc)
    rows = ["| Session ID | Turns | Last active | Status |"]
    rows.append("|------------|-------|-------------|--------|")

    for s in sessions:
        la_ts = s["last_active"]
        if la_ts:
            la_dt = _dt.datetime.fromtimestamp(la_ts, tz=_dt.timezone.utc)
            delta = now - la_dt
            mins  = int(delta.total_seconds() // 60)
            if mins < 60:
                la_str = f"{mins}m ago"
            elif mins < 1440:
                la_str = f"{mins // 60}h ago"
            else:
                la_str = f"{delta.days}d ago"
        else:
            la_str = "unknown"

        status = "⚠ expired" if s["expired"] else "✓ active"
        rows.append(
            f"| `{s['session_id']}` | {s['turns']} | {la_str} | {status} |"
        )

    total = len(sessions)
    header = f"**{total} session(s)**\n\n"
    return header + "\n".join(rows)


# ── Tool: rate_answer ─────────────────────────────────────────────────────────

@mcp.tool()
async def rate_answer(
    rating: int,
    session_id: str = "default",
    comment: str = "",
) -> str:
    """
    Submit a 1–5 star rating for the most recent answer in this session.
    Use this after `ask()` to record whether the answer was helpful.

    Args:
        rating:     Star rating from 1 (poor) to 5 (excellent).
        session_id: Session whose last answer is being rated. Defaults to the
                    configured default session (KB_DEFAULT_SESSION_ID if set).
        comment:    Optional free-text note (what was good/bad, what you expected).

    Returns:
        Confirmation message.
    """
    import asyncio as _asyncio
    from kb_agent_mcp.feedback import record as _fb_record, RATING_MIN, RATING_MAX
    from kb_agent_mcp.memory import get_history as _get_history

    eff = session_id
    if eff == "default" and cfg.KB_DEFAULT_SESSION_ID:
        eff = cfg.KB_DEFAULT_SESSION_ID

    # Clamp rating to valid range before fetching history (fail-fast feedback)
    if not (RATING_MIN <= rating <= RATING_MAX):
        return (
            f"⚠ Rating must be between {RATING_MIN} and {RATING_MAX}. "
            f"Got: {rating}"
        )

    # Retrieve the last question + answer from session history
    messages = await _get_history(eff)
    # Messages are stored as alternating user/assistant pairs
    last_question = ""
    last_answer   = ""
    for msg in reversed(messages):
        if msg["role"] == "assistant" and not last_answer:
            last_answer = msg["content"]
        elif msg["role"] == "user" and not last_question and last_answer:
            last_question = msg["content"]
            break

    if not last_answer:
        return (
            f"No answer found in session `{eff}` to rate.\n\n"
            "Call `ask()` first, then rate the response."
        )

    await _asyncio.to_thread(
        _fb_record,
        eff,
        last_question,
        last_answer,
        rating,
        comment,
    )

    stars = "⭐" * rating + "☆" * (RATING_MAX - rating)
    msg_out = f"✅ Feedback recorded — {stars} ({rating}/{RATING_MAX})"
    if comment:
        msg_out += f"\n> {comment}"
    return msg_out


# ── Tool: update_document ─────────────────────────────────────────────────────

@mcp.tool()
async def update_document(
    rel_path: str,
    content: str,
    mode: str = "overwrite",
) -> str:
    """
    Write or update a document in the knowledge base and immediately re-index it.

    Use this to capture notes, update summaries, or create new markdown files
    directly inside your KB_ROOT without leaving the conversation.  The file is
    re-embedded in the vector store right away so `ask()` can find the new
    content on the very next query.

    Args:
        rel_path: Path relative to KB_ROOT, e.g. "BizOps/notes.md".
                  Parent directories are created automatically.
                  Path traversal outside KB_ROOT is rejected for safety.
        content:  Text content to write (plain text or markdown).
        mode:     How to write the content:
                  • "overwrite" — replace the entire file (default).
                  • "append"    — add *content* to the end of the existing file.
                  • "prepend"   — insert *content* at the top of the existing file.

    Returns:
        A status message indicating success or failure, the domain the file
        belongs to, and whether the vector index was updated.

    Examples:
        update_document("BizOps/Q3_notes.md", "## Key risks\\n- Renewal delays")
        update_document("BizOps/Q3_notes.md", "\\n- Late payment risk", mode="append")
    """
    from kb_agent_mcp.writeback import write_document as _write

    result = await _write(rel_path, content, mode)

    if not result["ok"]:
        return f"❌ {result['message']}"

    domain_hint = f" (domain: `{result['domain']}`)" if result["domain"] else ""
    reindex_hint = " · ✓ re-indexed" if result["reindexed"] else " · ⚠ not re-indexed (unsupported format or outside a domain)"
    return (
        f"✅ **Document updated**{domain_hint}{reindex_hint}\n\n"
        f"Path: `{result['path']}`\n"
        f"Mode: `{mode}`"
    )


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
