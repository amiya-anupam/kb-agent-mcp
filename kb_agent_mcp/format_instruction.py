"""
kb_agent_mcp/format_instruction.py
──────────────────────────────────
Single definition of apply_format_instruction(); dependency-free so both
kb_agent_mcp.domain_agent and agents/agent_base.py can import it cheaply.
"""

from __future__ import annotations

import re


def apply_format_instruction(system_prompt: str, format_instruction: str) -> str:
    """Append a format instruction to a system prompt (no-op when empty)."""
    if not format_instruction:
        return system_prompt
    return (
        system_prompt
        + f"\n\n**OUTPUT FORMAT DIRECTIVE (highest priority):**\n{format_instruction}"
    )


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
    (re.compile(r"\b(in one sentence|as one sentence|one[- ]liner|one[- ]line (answer|summary)?|in a single sentence|briefly in one sentence|give me (a )?(quick |short )?one[- ]?liner)\b", re.IGNORECASE), "oneline"),
    (re.compile(r"\b(as a numbered list|in a numbered list|number (the |each )?(items?|points?|steps?))\b", re.IGNORECASE), "numbered"),
    (re.compile(r"\b(as (valid )?json|in json( format)?|return (as )?json)\b", re.IGNORECASE), "json"),
    (re.compile(r"\b(as (prose )?paragraphs?|in paragraph (format|form)?)\b", re.IGNORECASE), "paragraph"),
]


def detect_format_intent_key(
    question: str,
    explicit_flag: str | None = None,
) -> tuple[str, str]:
    """Return (format_key, instruction) — ("", "") when no format is requested."""
    if explicit_flag:
        key = explicit_flag.strip().lower()
        key = _FORMAT_ALIASES.get(key, key)
        return key, _FORMAT_INSTRUCTIONS.get(key, "")
    for pattern, fmt_key in _FORMAT_PHRASE_MAP:
        if pattern.search(question):
            return fmt_key, _FORMAT_INSTRUCTIONS[fmt_key]
    return "", ""
