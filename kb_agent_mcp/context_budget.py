"""
kb_agent_mcp/context_budget.py
──────────────────────────────
Universal context compaction for the kb-agent-mcp pipeline.
Single source of truth for every token-affecting decision.

All budgets are denominated in CHARACTERS (4 chars ≈ 1 token).
Values are read from cfg (environment variables) so they can be tuned
without code changes.

Public API
----------
trim(text, budget_key)              → str
trim_summary(summary, filename)     → str
compact_index_block(block)          → str
compact_pre_index(text)             → str
build_context(pre_index, index_block) → str
get(key)                            → int
tokens(key)                         → int
COLLAPSE_RULES                      — list of (pattern, label, description_template)
"""

from __future__ import annotations

import os
import re
import pathlib

from kb_agent_mcp.config import cfg

# ── Budget registry ───────────────────────────────────────────────────────────

_BUDGETS: dict[str, int] = {
    "total":       cfg.KB_BUDGET_TOTAL,
    "index":       cfg.KB_BUDGET_INDEX,
    "full_readme": cfg.KB_BUDGET_FULL_README,
    "pre_index":   cfg.KB_BUDGET_PRE_INDEX,
    "rag_file":    cfg.KB_BUDGET_RAG_FILE,
    "history":     4,       # conversation turns (not chars)
    "summary":     cfg.KB_BUDGET_SUMMARY,
    "embed_chars": cfg.KB_BUDGET_EMBED_CHARS,
    "min_readme":  cfg.KB_MIN_README_CHARS,
    "num_ctx":     cfg.KB_NUM_CTX,
}


def get(key: str) -> int:
    """Return the character budget for a named key. Raises KeyError if unknown."""
    return _BUDGETS[key]


def tokens(key: str) -> int:
    """Rough token estimate (chars ÷ 4) for a named budget."""
    return _BUDGETS[key] // 4


# ── Core trim ─────────────────────────────────────────────────────────────────

def trim(text: str, budget_key: str) -> str:
    """
    Hard-trim *text* to the character budget for *budget_key*.
    Appends '…' only when content was actually cut.
    """
    limit = _BUDGETS[budget_key]
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    if cut < limit * 0.8:
        cut = limit
    return text[:cut] + "…"


# ── Summary compaction ────────────────────────────────────────────────────────

_USELESS_SUMMARY_PATTERNS = re.compile(
    r"^(pdf|docx|pptx|xlsx|xls|ppt|doc|png|jpg|jpeg|gif|boxnote|rtf|csv|txt)\s+file$",
    re.IGNORECASE,
)


def trim_summary(summary: str, filename: str = "") -> str:
    """
    Return a meaningful summary string within KB_BUDGET_SUMMARY chars.

    If the summary is a known-useless fallback (e.g. "PPTX file") the
    filename stem is used instead — at least it is searchable text.
    """
    s = summary.strip()
    if not s or _USELESS_SUMMARY_PATTERNS.match(s):
        if filename:
            stem = pathlib.Path(filename).stem
            s = stem.replace("-", " ").replace("_", " ").strip()
        else:
            s = ""
    limit = _BUDGETS["summary"]
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


# ── Collapse rules ────────────────────────────────────────────────────────────

def _rules_from_env() -> list[tuple[re.Pattern, str, str]]:
    """Parse KB_COLLAPSE_PATTERNS from the environment into rule tuples."""
    raw = os.environ.get("KB_COLLAPSE_PATTERNS", "").strip()
    if not raw:
        return []
    rules: list[tuple[re.Pattern, str, str]] = []
    for entry in raw.split(";;"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|", 2)
        if len(parts) != 3:
            continue
        pattern_str, label, tmpl = (p.strip() for p in parts)
        try:
            rules.append((re.compile(pattern_str, re.IGNORECASE), label, tmpl))
        except re.error:
            pass
    return rules


_BUILTIN_COLLAPSE_RULES: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"^(Thumbs\.db|\.DS_Store)$", re.IGNORECASE),
        "system files",
        "OS/system files — not knowledge content",
    ),
]

COLLAPSE_RULES: list[tuple[re.Pattern, str, str]] = (
    _rules_from_env() + _BUILTIN_COLLAPSE_RULES
)


def _collapse_label(label: str, n: int, filenames: list[str]) -> str:
    qtrs = sorted(set(re.findall(r"Q[123]\d{2,3}", " ".join(filenames))))
    q_str = ", ".join(qtrs) if qtrs else f"{n} files"
    desc = next(
        tmpl for pat, lbl, tmpl in COLLAPSE_RULES if lbl == label
    ).format(n=n, quarters=q_str)
    return trim_summary(desc)


# ── AUTO-INDEX block compaction ───────────────────────────────────────────────

_SEP_ROW = re.compile(r"^\|[-| :]+\|$")


def _is_data_row(line: str) -> bool:
    return line.strip().startswith("|") and "`" in line


def _is_subdir_row(line: str) -> bool:
    return line.strip().startswith("|") and "**📁" in line


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.split("|")[1:-1]]


def _filename_from_row(line: str) -> str:
    m = re.search(r"`([^`]+)`", line)
    return m.group(1) if m else ""


def compact_index_block(block: str) -> str:
    """
    Apply all compaction rules to a raw AUTO-INDEX markdown block.

    Rules applied in order:
      1. Strip heading boilerplate
      2. Strip size annotations  (list format)
      3. Normalise multi-column table → 2-column (File | Summary)
      4. Detect and collapse repeated-version file groups
      5. Truncate per-row summaries to KB_BUDGET_SUMMARY
      6. Clean up consecutive blank lines

    Returns the compacted block as a string.
    """
    lines = block.splitlines()

    # 1. Strip heading boilerplate
    cleaned = []
    for line in lines:
        s = line.strip()
        if s.startswith("## 📁 Folder Index"):
            continue
        if s.startswith("## Documents in this Folder"):
            continue
        if s.startswith("> **") and ("files" in s or "file" in s) and (
            "Last indexed" in s or "Auto-indexed" in s or "Indexed" in s
        ):
            continue
        if re.match(r"^_Indexed:\s", s):
            continue
        cleaned.append(line)
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    lines = cleaned

    # 2. Strip size annotations
    lines = [
        re.sub(r"\s+&nbsp;\s+_[A-Z]+_\s+&nbsp;\s+[\d.]+\s+[KMG]B", "", l)
        for l in lines
    ]

    # 3. Normalise table to 2 columns (File | Summary)
    header_idx = next(
        (i for i, l in enumerate(lines) if re.match(r"^\|\s*File\s*\|", l.strip())),
        None,
    )
    if header_idx is not None:
        cells = _cells(lines[header_idx])
        if len(cells) > 2:
            summary_col = len(cells) - 1
            out = []
            for line in lines:
                if not _is_table_row(line):
                    out.append(line)
                    continue
                c = _cells(line)
                if len(c) > 2:
                    if all(re.match(r"^-+$", x) for x in c if x):
                        out.append("|---|---|")
                    elif any("**📁" in x for x in c):
                        out.append(f"| {c[0]} | |")
                    else:
                        out.append(f"| {c[0]} | {c[summary_col]} |")
                else:
                    out.append(line)
            lines = out

    # 4. Collapse repeated-version file groups
    groups: dict[str, dict] = {}
    for i, line in enumerate(lines):
        if not _is_data_row(line):
            continue
        fname = _filename_from_row(line)
        if not fname:
            continue
        for pat, label, _ in COLLAPSE_RULES:
            if pat.search(fname):
                if label not in groups:
                    groups[label] = {"files": [], "first_idx": i}
                groups[label]["files"].append(fname)
                break

    if groups:
        emitted: set[str] = set()
        subdir_before: list[int] = []
        new_lines: list[str | None] = list(lines)

        for i, line in enumerate(new_lines):
            if line is None:
                continue
            if _is_subdir_row(line):
                subdir_before = [i]
                continue
            if not _is_data_row(line):
                subdir_before = []
                continue
            fname = _filename_from_row(line)
            matched_label = next(
                (lbl for pat, lbl, _ in COLLAPSE_RULES if pat.search(fname)),
                None,
            )
            if matched_label is None:
                subdir_before = []
                continue
            info = groups[matched_label]
            if matched_label not in emitted:
                n = len(info["files"])
                desc = _collapse_label(matched_label, n, info["files"])
                new_lines[i] = f"| _{matched_label}_ | {desc} |"
                emitted.add(matched_label)
            else:
                new_lines[i] = None
                for si in subdir_before:
                    new_lines[si] = None
            subdir_before = []

        lines = [l for l in new_lines if l is not None]

    # 5. Truncate per-row summaries
    out = []
    for line in lines:
        if _is_data_row(line):
            c = _cells(line)
            if len(c) >= 2:
                summary = trim_summary(c[1], _filename_from_row(line))
                line = f"| {c[0]} | {summary} |"
        out.append(line)
    lines = out

    # 6. Clean up consecutive blank lines
    result, prev_blank = [], False
    for l in lines:
        is_blank = not l.strip()
        if is_blank and prev_blank:
            continue
        result.append(l)
        prev_blank = is_blank

    return "\n".join(result).strip()


# ── Pre-index section compaction ──────────────────────────────────────────────

def compact_pre_index(text: str) -> str:
    """Trim the hand-written README intro to KB_BUDGET_PRE_INDEX chars."""
    return trim(text.strip(), "pre_index")


# ── Final context assembly ────────────────────────────────────────────────────

def build_context(pre_index: str, index_block: str) -> str:
    """
    Assemble the final context string from the pre-index narrative and the
    compacted AUTO-INDEX block. Total is capped at KB_BUDGET_INDEX chars.
    """
    pre = compact_pre_index(pre_index) if pre_index else ""
    index = compact_index_block(index_block)
    combined = (pre + "\n\n" + index) if pre else index
    return trim(combined, "index")
