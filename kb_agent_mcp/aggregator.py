"""
kb_agent_mcp/aggregator.py
──────────────────────────
Cross-domain answer aggregation (Feature 6).

When the orchestrator receives results from multiple domain agents, this
module produces a single unified answer instead of the raw
"### From <Domain>" concatenation.

Strategy (offline-first, no LLM required)
------------------------------------------
1. Single domain → pass through unchanged (no aggregation needed).
2. Multiple domains, passthrough mode → pass through unchanged
   (the passthrough block already interleaves all context for the host AI).
3. Multiple domains, LLM mode → aggregate:
   a. Extract key facts from each domain answer (sentence-level split).
   b. Detect cross-domain conflicts (same named entity, contradictory numbers).
   c. Detect complementary information (unique facts per domain).
   d. Render a single unified **Summary** section followed by
      per-domain **Detail** sections that preserve full answer fidelity.

Public API
----------
aggregate(results, question) → str | None
    Returns an aggregated answer string, or None to signal the caller
    should fall back to the default _merge_answers() output.
"""

from __future__ import annotations

import re
from typing import Sequence


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sentences(text: str) -> list[str]:
    """Split *text* into non-empty sentences (rough but fast)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 20]


def _strip_footer(text: str) -> str:
    """Remove confidence footer / source block appended by base_agent."""
    # Footers start with a markdown HR then emoji
    text = re.sub(r"\n\n---\n[🎯📄].*", "", text, flags=re.DOTALL)
    return text.strip()


def _domain_label(result: dict) -> str:
    return result.get("agent", "Unknown")


def _is_numeric_sentence(sentence: str) -> bool:
    """True when the sentence contains a number (likely a data point)."""
    return bool(re.search(r"\b\d[\d,%.]*\b", sentence))


def _detect_conflicts(answers: list[tuple[str, list[str]]]) -> list[str]:
    """
    Lightweight conflict detector: look for the same numeric token appearing
    with different values across domains for the same subject noun.

    Returns a list of human-readable conflict notes (may be empty).
    """
    # Collect (number, context_snippet, domain) tuples
    num_re = re.compile(r"([\w\s]{0,25})\b(\$?[\d,]+(?:\.\d+)?%?)\b([\w\s]{0,25})")
    buckets: dict[str, list[tuple[str, str]]] = {}  # normalised key → [(value, domain)]

    for domain, sents in answers:
        for sent in sents:
            for m in num_re.finditer(sent):
                pre, val, post = m.group(1).strip(), m.group(2), m.group(3).strip()
                # Use last 2 words before number as the subject key
                subject_words = pre.split()[-2:]
                key = " ".join(subject_words).lower()
                if len(key) < 3:
                    continue
                buckets.setdefault(key, [])
                buckets[key].append((val, domain))

    conflicts: list[str] = []
    for key, occurrences in buckets.items():
        if len(occurrences) < 2:
            continue
        # Check if values differ between domains
        vals = [v for v, _ in occurrences]
        if len(set(vals)) > 1:
            parts = " vs ".join(f"`{v}` ({d})" for v, d in occurrences[:4])
            conflicts.append(f"**{key}**: {parts}")

    return conflicts[:5]  # cap to avoid noise


# ── Public API ─────────────────────────────────────────────────────────────────

def aggregate(
    results: Sequence[dict],
    question: str = "",
) -> str | None:
    """
    Produce a unified cross-domain answer from *results*.

    Returns:
        A synthesised markdown string, or ``None`` when aggregation is not
        applicable (single domain, passthrough mode, or no found results).
        The caller should use ``_merge_answers()`` output when None is returned.
    """
    found = [r for r in results if r.get("found")]

    # ── Guard: only aggregate 2+ non-passthrough LLM results ─────────────────
    if len(found) < 2:
        return None
    if any(r.get("passthrough") for r in found):
        return None

    # ── Collect per-domain answer text (footer stripped) ─────────────────────
    domain_answers: list[tuple[str, str]] = []
    for r in found:
        raw = r.get("answer", "")
        footer = r.get("confidence_footer") or ""
        clean = _strip_footer(raw + footer)
        if clean:
            domain_answers.append((_domain_label(r), clean))

    if not domain_answers:
        return None

    # ── Build sentence inventory per domain ───────────────────────────────────
    domain_sentences: list[tuple[str, list[str]]] = [
        (domain, _sentences(text))
        for domain, text in domain_answers
    ]

    # ── Conflict detection ────────────────────────────────────────────────────
    conflicts = _detect_conflicts(domain_sentences)

    # ── Complementary fact extraction ────────────────────────────────────────
    # A fact is "unique" to a domain when its key tokens don't appear in any
    # other domain's answer text.
    complementary: list[tuple[str, str]] = []  # (domain, sentence)
    all_texts = [text for _, text in domain_answers]
    for domain, sents in domain_sentences:
        other_texts = " ".join(t for d, t in domain_answers if d != domain).lower()
        for sent in sents:
            # Heuristic: sentence is complementary when ≥3 of its content
            # words don't appear in any other domain's answer.
            words = [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", sent)]
            unique_words = [w for w in words if w not in other_texts]
            if len(unique_words) >= 3:
                complementary.append((domain, sent))
                break  # one headline complementary sentence per domain is enough

    # ── Build unified answer ──────────────────────────────────────────────────
    parts: list[str] = []

    # Header
    n = len(domain_answers)
    domain_names = " · ".join(f"**{d}**" for d, _ in domain_answers)
    parts.append(f"*Aggregated answer from {n} domains: {domain_names}*\n")

    # Conflict callout (if any)
    if conflicts:
        parts.append("---\n\n> ⚠️ **Conflicting data detected across domains:**")
        for c in conflicts:
            parts.append(f"> - {c}")
        parts.append("")

    # Complementary highlights (if any)
    if complementary:
        parts.append("---\n\n**Key cross-domain highlights**\n")
        for domain, sent in complementary:
            parts.append(f"- **{domain}:** {sent}")
        parts.append("")

    # Full per-domain answers preserved
    parts.append("---\n")
    for domain, text in domain_answers:
        parts.append(f"### {domain}\n\n{text}")

    return "\n".join(parts)
