"""
kb_agent_mcp/orchestrator.py
─────────────────────────────
Top-level orchestrator: routing, parallel domain dispatch, answer merge.

Pipeline per `ask()` call:
  1. Detect format intent from natural-language phrases in the question
  2. Fast keyword pre-filter (≥2 keyword hits → skip LLM routing)
  3. LLM classifier (when keyword routing is ambiguous or has 0 hits)
  4. Clarification response (when classifier signals needs_clarification)
  5. Parallel DomainAgent.run() across selected domains
  6. Merge / aggregate results → final answer string
     (Feature 6: cross-domain aggregation via aggregator.aggregate())
  7. Persist turn in session memory

Thread-safe: all async; DomainAgent.run() calls are gathered concurrently.

Passthrough mode (no local LLM):
  When KB_LLM_PROVIDER=passthrough or Ollama is unreachable, base_agent returns
  a raw <<<KB_PASSTHROUGH>>> block instead of an LLM answer.  _merge_answers()
  detects this and converts the block into clean markdown so the MCP client
  (Claude, Bob, Cursor, etc.) receives readable retrieved context it can answer
  from — rather than an unformatted marker string.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from typing import Any

from kb_agent_mcp.base_agent import AgentResult, is_data_question as _is_data_q
from kb_agent_mcp.config import cfg
from kb_agent_mcp.domain_agent import DomainAgent, build_all_domain_agents
from kb_agent_mcp.memory import (
    get_history_sync,
    add_turn_sync,
)


logger = logging.getLogger(__name__)


# ── Orchestrator singleton (loaded lazily, refreshed by reindex) ───────────────

_agents: dict[str, DomainAgent] | None = None
_agents_lock = asyncio.Lock()


async def _get_agents() -> dict[str, DomainAgent]:
    global _agents
    if _agents is None:
        async with _agents_lock:
            if _agents is None:
                _agents = await build_all_domain_agents()
    return _agents


async def refresh_agents() -> dict[str, DomainAgent]:
    """Rebuild all domain agents from disk (called after reindex)."""
    global _agents
    async with _agents_lock:
        _agents = await build_all_domain_agents()
    return _agents


# ── Format intent detection ────────────────────────────────────────────────────

_FORMAT_INSTRUCTIONS: dict[str, str] = {
    "table":     "Format your entire answer as a Markdown table with clear column headers. "
                 "Do not use prose paragraphs — the response must be a table.",
    "bullets":   "Format your entire answer as a concise Markdown bullet list. "
                 "Use short, scannable bullet points. Do not use prose paragraphs.",
    "oneline":   "Answer in exactly ONE sentence. Be direct and specific. "
                 "Do not add any explanation, preamble, or follow-up.",
    "paragraph": "Write your answer as clear prose paragraphs. "
                 "Do not use bullet points or tables.",
    "numbered":  "Format your entire answer as a numbered Markdown list. "
                 "Each item should be a concise, self-contained point.",
    "json":      "Return your answer as valid JSON only. No markdown fences, no prose. "
                 "Choose a sensible structure (array of objects or flat object) for the content.",
}

_FORMAT_ALIASES: dict[str, str] = {
    "bullet":         "bullets",
    "bullet-points":  "bullets",
    "list":           "bullets",
    "1line":          "oneline",
    "one-line":       "oneline",
    "one-liner":      "oneline",
    "1liner":         "oneline",
    "prose":          "paragraph",
    "paragraphs":     "paragraph",
    "num":            "numbered",
    "numbered-list":  "numbered",
}

_FORMAT_PHRASE_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(as a table|in (a )?table (format|form)?|give me a table|show (it|that|results?) as a table)\b", re.IGNORECASE), "table"),
    (re.compile(r"\b(as bullet[- ]?points?|in bullet[- ]?points?|bullet[- ]?point (format|form|list)?|as a (bullet )?list)\b", re.IGNORECASE), "bullets"),
    (re.compile(r"\b(in one sentence|as one sentence|one[- ]liner|one[- ]line (answer|summary)?|in a single sentence)\b", re.IGNORECASE), "oneline"),
    (re.compile(r"\b(as a numbered list|in a numbered list|number (the |each )?(items?|points?|steps?))\b", re.IGNORECASE), "numbered"),
    (re.compile(r"\b(as (valid )?json|in json( format)?|return (as )?json)\b", re.IGNORECASE), "json"),
    (re.compile(r"\b(as (prose )?paragraphs?|in paragraph (format|form)?)\b", re.IGNORECASE), "paragraph"),
]


def detect_format_intent(
    question: str,
    explicit_flag: str | None = None,
) -> tuple[str, str]:
    """
    Detect the desired answer format.

    Returns:
        (question, format_instruction)  — question is returned unchanged.
        format_instruction is "" when no format is requested.
    """
    if explicit_flag:
        key = _FORMAT_ALIASES.get(explicit_flag.strip().lower(), explicit_flag.strip().lower())
        return question, _FORMAT_INSTRUCTIONS.get(key, "")

    for pattern, fmt_key in _FORMAT_PHRASE_MAP:
        if pattern.search(question):
            return question, _FORMAT_INSTRUCTIONS[fmt_key]

    return question, ""


# ── Keyword router ─────────────────────────────────────────────────────────────

def _keyword_hit_counts(
    question: str,
    agents: dict[str, DomainAgent],
) -> dict[str, int]:
    q = question.lower()
    return {
        name: sum(1 for kw in agent.config.keywords if kw.lower() in q)
        for name, agent in agents.items()
    }


def _keyword_confidence(
    question: str,
    agents: dict[str, DomainAgent],
) -> tuple[list[str], bool]:
    """
    Return (matched_domain_names, is_confident).

    Confident routing:
      - Exactly 1 domain matched with ≥2 keyword hits, OR
      - Top domain has ≥3× more hits than any other matched domain
    """
    counts = {k: v for k, v in _keyword_hit_counts(question, agents).items() if v > 0}
    matched = list(counts.keys())

    if not matched:
        return matched, False

    if len(matched) == 1 and counts[matched[0]] >= 2:
        return matched, True

    top_name = max(counts, key=counts.__getitem__)
    top_hits = counts[top_name]
    others   = [v for k, v in counts.items() if k != top_name]
    if top_hits >= 2 and others and top_hits >= 3 * max(others):
        return [top_name], True

    return matched, False


# ── LLM intent classifier ──────────────────────────────────────────────────────

async def _classify_intent(
    question: str,
    history: list[dict],
    agents: dict[str, DomainAgent],
) -> dict[str, Any]:
    """
    Use the LLM to classify which domain(s) the question belongs to.
    Falls back to keyword routing when passthrough mode is active.
    """
    from kb_agent_mcp.base_agent import call_llm, is_passthrough

    if not agents:
        return {"domains": [], "needs_clarification": False, "clarification_question": ""}

    valid_names = list(agents.keys())
    fallback    = valid_names[0] if valid_names else ""

    # Build domain descriptions including keywords
    desc_lines = []
    for name, agent in agents.items():
        kws = ", ".join(agent.config.keywords[:12])
        line = f'- "{name}": {agent.config.description}'
        if kws:
            line += f"\n  Keywords: {kws}"
        desc_lines.append(line)
    domain_descriptions = "\n".join(desc_lines)

    system_prompt = (
        "You are a routing agent for a KnowledgeBase system with these domains:\n"
        f"{domain_descriptions}\n\n"
        "Respond ONLY with valid JSON:\n"
        '{\n  "domains": ["Domain Name"],\n'
        '  "needs_clarification": false,\n'
        '  "clarification_question": ""\n}\n\n'
        "Rules:\n"
        f"- domains must be one or more of: {', '.join(valid_names)}\n"
        "- Set needs_clarification true only if the question is completely ambiguous\n"
        "- Return ONLY the JSON object"
    )

    # Passthrough: no local LLM available — keyword fallback
    if await is_passthrough():
        kw_matches, _ = _keyword_confidence(question, agents)
        return {
            "domains":                kw_matches or ([fallback] if fallback else []),
            "needs_clarification":    False,
            "clarification_question": "",
        }

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-4:])
    messages.append({"role": "user", "content": question})

    try:
        raw   = await call_llm(messages, temperature=0.0)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data  = json.loads(match.group()) if match else {}

        valid_set     = set(valid_names)
        domains_found = [d for d in data.get("domains", []) if d in valid_set]
        return {
            "domains":                domains_found or [fallback],
            "needs_clarification":    data.get("needs_clarification", False),
            "clarification_question": data.get("clarification_question", ""),
        }
    except Exception as exc:
        logger.warning("LLM domain-routing failed (%s); falling back to keywords", exc)
        kw_matches, _ = _keyword_confidence(question, agents)
        return {
            "domains":                kw_matches or ([fallback] if fallback else []),
            "needs_clarification":    False,
            "clarification_question": "",
        }


# ── Passthrough context budget helpers (Risk 14) ──────────────────────────────

def _estimate_context_size(n_domains: int, top_n: int, max_chars_per_domain: int) -> int:
    """
    Estimate total passthrough context chars before retrieval.

    Formula: each domain can contribute up to (top_n * max_chars_per_domain) chars.
    """
    return n_domains * top_n * max_chars_per_domain


def _adjusted_top_n(
    n_domains: int,
    top_n: int,
    max_chars_per_domain: int,
) -> tuple[int, str]:
    """
    Return (adjusted_top_n, budget_status).

    budget_status:
      ""          — within budget, no change
      "narrowed"  — top_n was reduced to fit within threshold
      "truncated" — even top_n=1 is over threshold (cannot help, warn user)
    """
    threshold = int(cfg.KB_BUDGET_PASSTHROUGH_THRESHOLD * cfg.KB_BUDGET_TOTAL)
    estimated = _estimate_context_size(n_domains, top_n, max_chars_per_domain)

    if estimated <= threshold:
        return top_n, ""

    # Try reducing top_n until we fit under threshold
    for reduced in range(top_n - 1, 0, -1):
        if _estimate_context_size(n_domains, reduced, max_chars_per_domain) <= threshold:
            return reduced, "narrowed"

    # Even top_n=1 is over threshold — can't reduce further
    return 1, "truncated"


# ── Passthrough block parser ───────────────────────────────────────────────────

_PT_START = "<<<KB_PASSTHROUGH>>>"
_PT_END   = "<<<KB_PASSTHROUGH_END>>>"


def _unwrap_passthrough_blocks(raw: str, budget_status: str = "") -> str:
    """
    Convert one or more <<<KB_PASSTHROUGH>>> blocks into clean markdown.

    Each block is parsed for AGENT, SOURCE, and the ---CONTEXT--- section.
    The result is formatted as readable markdown so any MCP client (Claude,
    Bob, Cursor, etc.) can answer the question directly from the context —
    without needing to parse marker strings.

    Falls back to returning `raw` unchanged if no blocks are found.
    """
    blocks = re.findall(
        re.escape(_PT_START) + r"(.*?)" + re.escape(_PT_END),
        raw, re.DOTALL,
    )
    if not blocks:
        return raw

    # Header instruction block — explicit so any host AI model acts on it
    header_parts = [
        "**Instructions for the AI reading this:** "
        "The user's KnowledgeBase MCP server is in passthrough mode (no local LLM). "
        "The retrieved context below is the authoritative source of information. "
        "Please read it carefully and answer the user's question directly, "
        "citing the source where relevant. Do not say the context is unavailable.\n"
    ]

    # Two-tier budget warning (Risk 14)
    if budget_status == "narrowed":
        header_parts.append(
            "> ⚠ **Context narrowed:** Retrieved results were reduced to fit within "
            "the passthrough context budget. For broader results, raise "
            "`KB_BUDGET_TOTAL` or `KB_BUDGET_PASSTHROUGH_THRESHOLD` in your `.env`.\n"
        )
    elif budget_status == "truncated":
        header_parts.append(
            "> ⚠ **Context truncated:** Even with the minimum retrieval depth, the "
            "estimated context exceeds the passthrough budget. Results may be incomplete. "
            "Raise `KB_BUDGET_TOTAL` in your `.env` for better coverage.\n"
        )

    sections: list[str] = ["\n".join(header_parts)]

    for block in blocks:
        # Extract AGENT
        m = re.search(r"^AGENT:\s*(.+)$", block, re.MULTILINE)
        agent = m.group(1).strip() if m else "KnowledgeBase"

        # Extract SOURCE
        m = re.search(r"^SOURCE:\s*(.+)$", block, re.MULTILINE)
        source = m.group(1).strip() if m else ""

        # Extract CONTEXT (everything after ---CONTEXT--- marker)
        m = re.search(r"^---CONTEXT---\n(.*)$", block, re.DOTALL | re.MULTILINE)
        context = m.group(1).strip() if m else block.strip()

        heading = f"### {agent}"
        if source:
            heading += f"\n*Source: {source}*"
        sections.append(f"{heading}\n\n{context}")

    return "\n\n---\n\n".join(sections)


# ── Answer merger ──────────────────────────────────────────────────────────────

def _merge_answers(
    results: list[dict],
    agents: dict[str, DomainAgent],
    question: str = "",
    budget_status: str = "",
) -> str:
    found = [r for r in results if r.get("found")]

    if not found:
        domain_hints = "\n".join(
            f"  - {name}: {agent.config.description}"
            for name, agent in agents.items()
        )
        return (
            "I couldn't find relevant information to answer your question.\n\n"
            "Try rephrasing, or add more context. Available domains:\n"
            + domain_hints
        )

    # Passthrough: unwrap raw marker blocks → clean markdown context
    if any(r.get("passthrough") for r in found):
        combined_raw = "\n".join(
            r.get("passthrough_block", r["answer"])
            for r in found
            if r.get("passthrough")
        )
        return _unwrap_passthrough_blocks(combined_raw, budget_status=budget_status)

    if len(found) == 1:
        r = found[0]
        answer = r["answer"] + (r.get("confidence_footer") or "")
        if r.get("truncated") and _is_data_q(question):
            answer += (
                "\n\n> ⚠ **Note:** Source context was truncated to fit the budget. "
                "For complete data, open the source file directly."
            )
        return answer

    merged = []
    for r in found:
        footer = r.get("confidence_footer") or ""
        answer = r["answer"] + footer
        if r.get("truncated") and _is_data_q(question):
            answer += (
                "\n\n> ⚠ **Note:** Source context was truncated to fit the budget. "
                "For complete data, open the source file directly."
            )
        merged.append(f"### From {r['agent']}\n\n{answer}")
    return "\n\n---\n\n".join(merged)


# ── Minimal-keyword routing notice ────────────────────────────────────────────

def _minimal_keyword_notice(domain_names: list[str], agents: dict) -> str:
    """
    Return a one-line notice when ANY routed domain has ≤1 keyword configured.

    ≤1 keyword means the domain was generated without an LLM (minimal defaults)
    and routing is essentially a guess.  The notice nudges the user to enrich
    their domain config without being alarming about the answer itself.

    Returns "" when all routed domains have ≥2 keywords — no noise in normal use.
    """
    thin_domains = [
        name
        for name in domain_names
        if name in agents and len(agents[name].config.keywords) <= 1
    ]
    if not thin_domains:
        return ""
    plural = "s" if len(thin_domains) > 1 else ""
    names  = ", ".join(f"**{n}**" for n in thin_domains)
    return (
        f"\n\n---\n\n"
        f"> 💡 **Routing quality note:** Domain{plural} {names} "
        f"{'have' if len(thin_domains) > 1 else 'has'} minimal keyword config "
        f"(generated without an LLM). "
        f"Routing accuracy may be lower than expected.\n"
        f"> To improve: run `kb-agent-generate --force` with an LLM configured, "
        f"or edit `<domain>/domain_config.yaml` → `keywords:` section manually."
    )


# ── Stale-index warning ────────────────────────────────────────────────────────

def _stale_warnings(domain_names: list[str], agents: dict) -> str:
    """
    Check queried domains for new unindexed files and return a warning string.

    Threshold: warn only when new_files > max(1, floor(indexed * 0.05)).
    This avoids noise on active folders while still alerting on meaningful growth.

    Returns "" when everything is up-to-date — safe to append unconditionally.
    """
    warnings: list[str] = []
    for name in domain_names:
        agent = agents.get(name)
        if agent is None:
            continue
        on_disk, indexed = agent.stale_file_count()
        new_files = on_disk - indexed
        threshold = max(1, math.floor(indexed * 0.05))
        if new_files > threshold:
            warnings.append(
                f"⚠  **{name}**: {new_files} new file(s) detected since last index "
                f"({indexed} → {on_disk}). Run `kb-agent-generate` to update."
            )
    if not warnings:
        return ""
    return "\n\n---\n\n" + "\n\n".join(warnings)


# ── Pipeline helpers (SRP: each function owns exactly one stage) ───────────────

async def _resolve_domains(
    question: str,
    history: list[dict],
    agents: dict[str, DomainAgent],
) -> tuple[list[str], str | None]:
    """
    Route the question to one or more domain names.

    Returns:
        (domain_names, clarification_question)
        When clarification_question is not None, the caller should return it
        directly to the user without dispatching to any domain.
    """
    kw_domains, kw_confident = _keyword_confidence(question, agents)

    if kw_confident:
        return kw_domains, None

    classification = await _classify_intent(question, history, agents)
    domain_names   = classification["domains"] or kw_domains or [list(agents.keys())[0]]

    if classification.get("needs_clarification") and classification.get("clarification_question"):
        return domain_names, classification["clarification_question"]

    return domain_names, None


async def _compute_passthrough_budget(
    domain_names: list[str],
    agents: dict[str, DomainAgent],
) -> tuple[int | None, str]:
    """
    When in passthrough mode, compute a reduced top_n that fits the context budget.

    Returns:
        (top_n_override, budget_status)
        top_n_override is None when no reduction is needed (or not passthrough mode).
        budget_status is "" | "narrowed" | "truncated".
    """
    from kb_agent_mcp.base_agent import is_passthrough as _is_passthrough
    if not await _is_passthrough():
        return None, ""

    selected = [agents[n] for n in domain_names if n in agents]
    if not selected:
        return None, ""

    avg_top_n     = max(1, round(sum(a.config.top_n    for a in selected) / len(selected)))
    avg_max_chars = max(1, round(sum(a.config.max_chars for a in selected) / len(selected)))
    adjusted, budget_status = _adjusted_top_n(
        n_domains=len(selected),
        top_n=avg_top_n,
        max_chars_per_domain=avg_max_chars,
    )
    top_n_override = adjusted if budget_status else None
    return top_n_override, budget_status


async def _dispatch_domains(
    question: str,
    history: list[dict],
    format_instruction: str,
    domain_names: list[str],
    agents: dict[str, DomainAgent],
    top_n_override: int | None,
    session_id: str,
) -> list[AgentResult] | None:
    """
    Dispatch to selected domain agents in parallel and normalise results.

    Returns:
        A list of AgentResult dicts, or None when no tasks were created (no
        matching agents) — the caller should return an error message in that case.
    """
    tasks = [
        agents[name].run(
            question, history, format_instruction,
            top_n_override=top_n_override,
            session_id=session_id,
        )
        for name in domain_names
        if name in agents
    ]
    if not tasks:
        return None

    # return_exceptions=True so a single failing domain never cancels the others.
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[AgentResult] = []
    for name, outcome in zip([n for n in domain_names if n in agents], raw):
        if isinstance(outcome, BaseException):
            logger.warning("Domain agent %r failed: %s", name, outcome)
            results.append(AgentResult(
                agent=name,
                answer=f"[{name}: retrieval failed — {outcome}]",
                sources=[],
                found=False,
                passthrough=False,
            ))
        else:
            results.append(outcome)
    return results


def _build_sources_block(results: list[AgentResult]) -> str:
    """
    Build the deduplicated **Sources** footer from all domain results.

    Returns "" when all results are passthrough (they embed their own source
    labels) or when no sources were collected.
    """
    if any(r.get("passthrough") for r in results):
        return ""

    seen_paths: set[str] = set()
    all_sources: list[dict] = []
    for r in results:
        for s in r.get("sources", []):
            p = s.get("path", "")
            if p and p not in seen_paths:
                seen_paths.add(p)
                all_sources.append(s)

    if not all_sources:
        return ""

    all_sources.sort(key=lambda s: -s.get("score", 0.0))
    lines = ["\n\n---\n\n**Sources**"]
    for s in all_sources:
        name  = s.get("name", s.get("path", "unknown"))
        score = s.get("score", 0.0)
        lock  = " 🔒" if s.get("confidential") else ""
        lines.append(f"- `{name}`{lock} *(relevance: {score:.2f})*")
    return "\n".join(lines)


def _assemble_answer(
    results: list[AgentResult],
    agents: dict[str, DomainAgent],
    question: str,
    domain_names: list[str],
    budget_status: str,
) -> str:
    """
    Aggregate/merge domain results then append stale warnings, routing notices,
    and source citations.
    """
    from kb_agent_mcp.aggregator import aggregate as _aggregate

    aggregated = _aggregate(list(results), question=question)
    answer = aggregated if aggregated is not None else _merge_answers(
        list(results), agents, question=question, budget_status=budget_status
    )

    answer += _stale_warnings(domain_names, agents)
    answer += _minimal_keyword_notice(domain_names, agents)
    answer += _build_sources_block(results)
    return answer


# ── Main orchestrator function ─────────────────────────────────────────────────

async def ask(
    question: str,
    session_id: str = "default",
    format_flag: str | None = None,
) -> str:
    """
    Full async pipeline: detect format → route → dispatch → merge → persist.

    Args:
        question:    The user's question (may contain natural-language format phrases).
        session_id:  Conversation session identifier for multi-turn memory.
        format_flag: Explicit format name (table/bullets/oneline/paragraph/numbered/json)
                     or None for auto-detection from the question text.

    Returns:
        The final answer string (markdown).
    """
    agents = await _get_agents()

    if not agents:
        kb_root_hint = (
            "\n\n⚠  **KB_ROOT may not be set correctly.**\n"
            f"  Currently resolving to: `{cfg.kb_root_path}`\n"
            "  If this is not your knowledge base, add `KB_ROOT` to your MCP "
            "host config env block:\n"
            '  `"env": { "KB_ROOT": "/absolute/path/to/your/KnowledgeBase" }`'
            if not cfg.kb_root_is_explicit else
            f"\n  KB_ROOT: `{cfg.kb_root_path}`"
        )
        return (
            "No knowledge domains found. Run `kb-agent-generate` first to "
            "discover folders and build the knowledge index."
            + kb_root_hint
        )

    question, format_instruction = detect_format_intent(question, explicit_flag=format_flag)
    history      = get_history_sync(session_id)

    domain_names, clarification = await _resolve_domains(question, history, agents)
    if clarification:
        add_turn_sync(question, clarification, session_id)
        return clarification

    top_n_override, budget_status = await _compute_passthrough_budget(domain_names, agents)

    results = await _dispatch_domains(
        question, history, format_instruction,
        domain_names, agents, top_n_override, session_id,
    )
    if results is None:
        return f"No matching domain agents for: {domain_names}"

    if all(not r.get("found") and "retrieval failed" in r.get("answer", "") for r in results):
        failed_names = ", ".join(r["agent"] for r in results)
        return f"All domain agents failed to respond ({failed_names}). Check your LLM connection or run `reindex()`."

    final_answer = _assemble_answer(results, agents, question, domain_names, budget_status)

    add_turn_sync(question, final_answer, session_id)
    return final_answer


# ── list_domains helper ────────────────────────────────────────────────────────

async def list_domains() -> list[dict]:
    """Return a list of {folder_name, agent_name, description} for all domains.

    When no domains exist, returns a single entry with a diagnostic message
    so the caller (server.py list_domains tool) can surface the KB_ROOT hint.
    """
    agents = await _get_agents()
    if not agents:
        return [{
            "folder_name": "_no_domains",
            "agent_name":  "—",
            "description": (
                "No domains indexed yet. Run `kb-agent-generate` to discover "
                "knowledge folders under your KB_ROOT. "
                + (
                    f"KB_ROOT is currently defaulting to `{cfg.kb_root_path}` "
                    "(not explicitly set — add KB_ROOT to your MCP host config env block)."
                    if not cfg.kb_root_is_explicit else
                    f"KB_ROOT: `{cfg.kb_root_path}`"
                )
            ),
        }]
    return [
        {
            "folder_name": name,
            "agent_name":  agent.config.agent_name,
            "description": agent.config.description,
        }
        for name, agent in agents.items()
    ]
