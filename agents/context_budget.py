#!/usr/bin/env python3
"""
context_budget.py — Universal context compaction for the KnowledgeBase agent
-----------------------------------------------------------------------------
Single source of truth for every token-affecting decision in the pipeline.
Used by both agent_base.py (query-time) and watch_kb.py (index-time).

The budget is denominated in CHARACTERS (4 chars ≈ 1 token).  All limits are
read from environment variables so they can be tuned without touching code.

Environment variables (all optional — sensible defaults provided):
  KB_BUDGET_TOTAL        Hard ceiling on any context sent to an LLM (chars).
                         Default: 24000  (~6000 tokens)
  KB_BUDGET_INDEX        Max chars for README index (simple-query) context.
                         Default: 8000   (~2000 tokens)
  KB_BUDGET_FULL_README  Max chars for full-README (complex-query) context.
                         Default: 24000  (~6000 tokens)
  KB_BUDGET_PRE_INDEX    Max chars from the hand-written README intro prepended
                         to the index block.  Default: 2000  (~500 tokens)
  KB_BUDGET_RAG_FILE     Max chars extracted per file in RAG fallback.
                         Default: 4000   (~1000 tokens)
  KB_BUDGET_SUMMARY      Max chars for a single file summary in the index.
                         Default: 100    (~25 tokens)
  KB_BUDGET_HISTORY      Max conversation history turns sent with each request.
                         Default: 4      (turns, not chars)
  KB_BUDGET_EMBED_CHARS  Max chars of text sent to the embedding model per file.
                         Default: 8000   (~2000 tokens)
  KB_MIN_README_CHARS    Min hand-written README chars required to use README-first
                         strategy (below this threshold falls back to RAG).
                         Default: 200
  KB_NUM_CTX             Ollama context window size passed as num_ctx.
                         Default: 32768  (set lower for smaller GPUs, e.g. 8192)

Public API
----------
trim(text, budget_key)                  → str
    Trim text to the named budget.  Hard-truncates at char limit.

trim_summary(summary, filename)         → str
    Trim a file summary, stripping known useless fallback text first.

compact_index_block(block)              → str
    Apply all compaction rules to a complete AUTO-INDEX markdown block:
      1. Strip heading boilerplate  (## 📁 Folder Index, count line)
      2. Strip non-summary columns  (Type, Size, Last Modified if present)
      3. Strip size annotations     (&nbsp; _PDF_ &nbsp; 3.3 MB)
      4. Collapse repeated-version file groups  (EPM, screenshots, etc.)
      5. Truncate individual summaries to KB_BUDGET_SUMMARY
      6. Strip subdir rows that repeat the parent path in every cell

compact_pre_index(text)                 → str
    Trim the hand-written README intro to KB_BUDGET_PRE_INDEX.

build_context(pre_index, index_block)   → str
    Assemble final context string within KB_BUDGET_INDEX.

COLLAPSE_RULES
    Exportable list of (pattern, label, description_template) tuples.
    watch_kb.py imports this so the same grouping logic runs at index time.
"""

import os
import re
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

# ── Budget registry ───────────────────────────────────────────────────────────

_BUDGETS: dict[str, int] = {
    # ── Query-time ──────────────────────────────────────────────────────────
    "total":        int(os.environ.get("KB_BUDGET_TOTAL",       "24000")),
    "index":        int(os.environ.get("KB_BUDGET_INDEX",        "8000")),
    "full_readme":  int(os.environ.get("KB_BUDGET_FULL_README", "24000")),
    "pre_index":    int(os.environ.get("KB_BUDGET_PRE_INDEX",    "2000")),
    "rag_file":     int(os.environ.get("KB_BUDGET_RAG_FILE",     "4000")),
    "history":      int(os.environ.get("KB_BUDGET_HISTORY",         "4")),  # turns
    # ── Index-time ──────────────────────────────────────────────────────────
    "summary":      int(os.environ.get("KB_BUDGET_SUMMARY",       "500")),
    # ── Embedding ───────────────────────────────────────────────────────────
    "embed_chars":  int(os.environ.get("KB_BUDGET_EMBED_CHARS",  "3500")),
    # ── LLM runtime ─────────────────────────────────────────────────────────
    "min_readme":   int(os.environ.get("KB_MIN_README_CHARS",     "200")),
    "num_ctx":      int(os.environ.get("KB_NUM_CTX",            "32768")),
}


def get(key: str) -> int:
    """Return the character budget for a named key.  Raises KeyError if unknown."""
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
    # Try to break at a newline near the limit to avoid mid-sentence cuts
    cut = text.rfind("\n", 0, limit)
    if cut < limit * 0.8:   # no nearby newline — just hard cut
        cut = limit
    return text[:cut] + "…"


# ── Summary compaction ────────────────────────────────────────────────────────

# Summaries that carry no information — generated when the LLM was unavailable
# or the file type is binary/image.
_USELESS_SUMMARY_PATTERNS = re.compile(
    r"^(pdf|docx|pptx|xlsx|xls|ppt|doc|png|jpg|jpeg|gif|boxnote|rtf|csv|txt)\s+file$",
    re.IGNORECASE,
)

def trim_summary(summary: str, filename: str = "") -> str:
    """
    Return a meaningful summary string within KB_BUDGET_SUMMARY chars.

    If the summary is a known-useless fallback (e.g. "PPTX file") the
    filename stem is used instead — at least it's searchable text.
    """
    s = summary.strip()

    if not s or _USELESS_SUMMARY_PATTERNS.match(s):
        if filename:
            stem = pathlib.Path(filename).stem
            s    = stem.replace("-", " ").replace("_", " ").strip()
        else:
            s = ""

    limit = _BUDGETS["summary"]
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


# ── Collapse rules ────────────────────────────────────────────────────────────
# Each rule: (compiled regex, display label, description template)
#
# The regex is matched against the *filename* (not path).
# The description template may use {n} (file count) and {quarters} (extracted
# quarter codes like Q126, Q226 found in the filenames).
#
# Rules are evaluated in order; first match wins.
#
# TWO WAYS TO ADD RULES:
#
# 1. Environment variable KB_COLLAPSE_PATTERNS (recommended — no code changes)
#    Format: pipe-separated triples  pattern|label|description_template
#    Multiple rules: separate with  ;;
#    Example in .env:
#      KB_COLLAPSE_PATTERNS=EPM2-004|EPM weekly snapshots|Weekly files for {quarters} ({n} files);;^Screenshot|screenshots|Snapshot images ({n} files)
#
# 2. Extend COLLAPSE_RULES in code below (for rules you want to share with
#    everyone who clones the repo — only add truly universal patterns here).
#
# Both watch_kb.py (index-time) and compact_index_block() (query-time) import
# this list, so one entry covers both paths automatically.

def _rules_from_env() -> list[tuple[re.Pattern, str, str]]:
    """Parse KB_COLLAPSE_PATTERNS from the environment into rule tuples."""
    raw = os.environ.get("KB_COLLAPSE_PATTERNS", "").strip()
    if not raw:
        return []
    rules = []
    for entry in raw.split(";;"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|", 2)
        if len(parts) != 3:
            continue  # silently skip malformed entries
        pattern_str, label, tmpl = (p.strip() for p in parts)
        try:
            rules.append((re.compile(pattern_str, re.IGNORECASE), label, tmpl))
        except re.error:
            pass  # silently skip bad regex
    return rules


# Built-in rules — universal patterns that apply to any knowledge base.
# Keep this list small and truly cross-domain.
_BUILTIN_COLLAPSE_RULES: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"^(Thumbs\.db|\.DS_Store)$", re.IGNORECASE),
        "system files",
        "OS/system files — not knowledge content",
    ),
]

# Final list: env-var rules first (user's own patterns take priority),
# then built-in universal rules.
COLLAPSE_RULES: list[tuple[re.Pattern, str, str]] = (
    _rules_from_env() + _BUILTIN_COLLAPSE_RULES
)


def _collapse_label(label: str, n: int, filenames: list[str]) -> str:
    qtrs = sorted(set(re.findall(r"Q[123]\d{2,3}", " ".join(filenames))))
    q_str = ", ".join(qtrs) if qtrs else f"{n} files"
    desc  = next(
        tmpl for pat, lbl, tmpl in COLLAPSE_RULES if lbl == label
    ).format(n=n, quarters=q_str)
    return trim_summary(desc)


# ── AUTO-INDEX block compaction ───────────────────────────────────────────────

# Markdown table separator pattern
_SEP_ROW = re.compile(r"^\|[-| :]+\|$")

def _is_data_row(line: str) -> bool:
    return line.strip().startswith("|") and "`" in line

def _is_subdir_row(line: str) -> bool:
    return line.strip().startswith("|") and "**📁" in line

def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")

def _cells(line: str) -> list[str]:
    """Split a markdown table row into cell strings (strips outer pipes)."""
    return [c.strip() for c in line.split("|")[1:-1]]

def _filename_from_row(line: str) -> str:
    m = re.search(r"`([^`]+)`", line)
    return m.group(1) if m else ""


def compact_index_block(block: str) -> str:
    """
    Apply all compaction rules to a raw AUTO-INDEX markdown block.

    Rules applied in order:
      1. Strip heading boilerplate
      2. Strip size annotations  (CP4I list format)
      3. Normalise multi-column table → 2-column (File | Summary)
      4. Detect and collapse repeated-version file groups
      5. Truncate per-row summaries to KB_BUDGET_SUMMARY
      6. Strip redundant subdir rows whose content is all-empty

    Returns the compacted block as a string (no leading/trailing blank lines).
    """
    lines = block.splitlines()

    # ── 1. Strip heading boilerplate ─────────────────────────────────────────
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

    # Drop leading blank lines
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    lines = cleaned

    # ── 2. Strip size annotations (list format: &nbsp; _PDF_ &nbsp; X KB) ───
    lines = [
        re.sub(r"\s+&nbsp;\s+_[A-Z]+_\s+&nbsp;\s+[\d.]+\s+[KMG]B", "", l)
        for l in lines
    ]

    # ── 3. Normalise table to 2 columns (File | Summary) ─────────────────────
    # Detect header row — if it has >2 cells, rewrite everything
    header_idx = next(
        (i for i, l in enumerate(lines) if re.match(r"^\|\s*File\s*\|", l.strip())),
        None,
    )
    if header_idx is not None:
        cells = _cells(lines[header_idx])
        if len(cells) > 2:
            # Identify which column index is "Summary" (last non-empty)
            summary_col = len(cells) - 1
            out = []
            for line in lines:
                if not _is_table_row(line):
                    out.append(line)
                    continue
                c = _cells(line)
                if len(c) > 2:
                    # separator row
                    if all(re.match(r"^-+$", x) for x in c if x):
                        out.append("|---|---|")
                    # subdir placeholder row  | **📁 ...** | | | | |
                    elif any("**📁" in x for x in c):
                        out.append(f"| {c[0]} | |")
                    else:
                        out.append(f"| {c[0]} | {c[summary_col]} |")
                else:
                    out.append(line)
            lines = out

    # ── 4. Collapse repeated-version file groups ──────────────────────────────
    # Pass 1: collect groups
    groups: dict[str, dict] = {}   # label → {files, order_first}
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

    # Pass 2: rewrite lines, replacing first occurrence with collapsed row,
    # removing subsequent occurrences and their adjacent subdir headers
    if groups:
        emitted: set[str] = set()
        subdir_before: list[int] = []   # track subdir row indices for deletion
        new_lines: list[str | None] = list(lines)  # None = deleted

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
                # Replace this row with the collapsed summary
                n      = len(info["files"])
                desc   = _collapse_label(matched_label, n, info["files"])
                new_lines[i] = f"| _{matched_label}_ | {desc} |"
                emitted.add(matched_label)
            else:
                # Delete this row and any immediately preceding subdir header
                new_lines[i] = None
                for si in subdir_before:
                    new_lines[si] = None

            subdir_before = []

        lines = [l for l in new_lines if l is not None]

    # ── 5. Truncate per-row summaries ─────────────────────────────────────────
    limit = _BUDGETS["summary"]
    out   = []
    for line in lines:
        if _is_data_row(line):
            c = _cells(line)
            if len(c) >= 2:
                summary = trim_summary(c[1], _filename_from_row(line))
                line    = f"| {c[0]} | {summary} |"
        out.append(line)
    lines = out

    # ── 6. Strip all-empty subdir rows  (| **📁 sub/** | | or | **📁 sub/** |  |) ─
    lines = [
        l for l in lines
        if not (_is_subdir_row(l) and all(
            c.strip() in ("", "|") for c in _cells(l)[1:]
        ) and False)  # actually keep subdir rows — they provide structure
    ]
    # Note: we keep subdir rows because they help the LLM understand folder
    # structure. Only collapse *repeated* subdir rows (from deleted file rows).

    # Clean up consecutive blank lines introduced by deletions
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
    """
    Trim the hand-written README section (before the AUTO-INDEX marker)
    to KB_BUDGET_PRE_INDEX chars, breaking at a paragraph boundary.
    """
    return trim(text.strip(), "pre_index")


# ── Final context assembly ────────────────────────────────────────────────────

def build_context(pre_index: str, index_block: str) -> str:
    """
    Assemble the final context string from the pre-index narrative and the
    compacted AUTO-INDEX block.  Total is capped at KB_BUDGET_INDEX chars.

    If pre_index is empty, returns just the index block (trimmed to budget).
    """
    pre   = compact_pre_index(pre_index) if pre_index else ""
    index = compact_index_block(index_block)

    if pre:
        combined = pre + "\n\n" + index
    else:
        combined = index

    return trim(combined, "index")
