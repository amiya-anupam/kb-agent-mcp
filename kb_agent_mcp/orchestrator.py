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
  6. Merge results → final answer string
  7. Persist turn in session memory

Thread-safe: all async; DomainAgent.run() calls are gathered concurrently.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from kb_agent_mcp.config import cfg
from kb_agent_mcp.domain_agent import DomainAgent, build_all_domain_agents
from kb_agent_mcp.memory import (
    get_history_sync,
    add_turn_sync,
)


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
    except Exception:
        kw_matches, _ = _keyword_confidence(question, agents)
        return {
            "domains":                kw_matches or ([fallback] if fallback else []),
            "needs_clarification":    False,
            "clarification_question": "",
        }


# ── Answer merger ──────────────────────────────────────────────────────────────

def _merge_answers(
    results: list[dict],
    agents: dict[str, DomainAgent],
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

    # Passthrough: return combined passthrough blocks
    if any(r.get("passthrough") for r in found):
        return "\n".join(
            r.get("passthrough_block", r["answer"])
            for r in found
            if r.get("passthrough")
        )

    if len(found) == 1:
        r = found[0]
        return r["answer"] + (r.get("confidence_footer") or "")

    merged = []
    for r in found:
        footer = r.get("confidence_footer") or ""
        merged.append(f"### From {r['agent']}\n\n{r['answer']}{footer}")
    return "\n\n---\n\n".join(merged)


# ── Main orchestrator function ─────────────────────────────────────────────────

async def ask(
    question: str,
    session_id: str = "default",
    format_flag: str | None = None,
) -> str:
    """
    Full async pipeline: detect format → route → dispatch → merge → persist.

    Args:
        question:   The user's question (may contain natural-language format phrases).
        session_id: Conversation session identifier for multi-turn memory.
        format_flag: Explicit format name (table/bullets/oneline/paragraph/numbered/json)
                     or None for auto-detection from the question text.

    Returns:
        The final answer string (markdown).
    """
    agents = await _get_agents()

    if not agents:
        return (
            "No knowledge domains found. Run `kb-agent-generate` first to "
            "discover folders and build the knowledge index.\n"
            f"  KB_ROOT: {cfg.kb_root_path}"
        )

    # Detect format intent
    question, format_instruction = detect_format_intent(question, explicit_flag=format_flag)

    # Load conversation history (sync — fast disk read)
    history = get_history_sync(session_id)

    # Fast keyword pre-filter
    kw_domains, kw_confident = _keyword_confidence(question, agents)

    if kw_confident:
        domain_names = kw_domains
    else:
        classification = await _classify_intent(question, history, agents)
        domain_names   = classification["domains"] or kw_domains or [list(agents.keys())[0]]

        # Clarification needed?
        if classification.get("needs_clarification") and classification.get("clarification_question"):
            cq = classification["clarification_question"]
            # Persist clarification exchange in session memory (sync, fast)
            add_turn_sync(question, cq, session_id)
            return cq

    # Dispatch to selected domain agents in parallel
    tasks = [
        agents[name].run(question, history, format_instruction)
        for name in domain_names
        if name in agents
    ]
    if not tasks:
        return f"No matching domain agents for: {domain_names}"

    results = await asyncio.gather(*tasks, return_exceptions=False)

    final_answer = _merge_answers(list(results), agents)
    add_turn_sync(question, final_answer, session_id)
    return final_answer


# ── list_domains helper ────────────────────────────────────────────────────────

async def list_domains() -> list[dict]:
    """Return a list of {folder_name, agent_name, description} for all domains."""
    agents = await _get_agents()
    return [
        {
            "folder_name": name,
            "agent_name":  agent.config.agent_name,
            "description": agent.config.description,
        }
        for name, agent in agents.items()
    ]
