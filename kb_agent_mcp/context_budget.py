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

import sys
import pathlib
import functools

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

# ── Pure compaction logic (shared with agents/context_budget.py) ──────────────
# The logic module lives in agents/ which is on the repo root path.
# We insert the agents/ dir so the shared module is importable without making
# agents/ a formal package dependency of kb_agent_mcp.
# Each function takes `budgets` as its first argument; we bind _BUDGETS via partial.

_agents_dir = str(pathlib.Path(__file__).parent.parent / "agents")
if _agents_dir not in sys.path:
    sys.path.insert(0, _agents_dir)

import _context_budget_logic as _logic  # noqa: E402

COLLAPSE_RULES = _logic.COLLAPSE_RULES

get                 = functools.partial(_logic.get,                 _BUDGETS)
tokens              = functools.partial(_logic.tokens,              _BUDGETS)
trim                = functools.partial(_logic.trim,                _BUDGETS)
trim_summary        = functools.partial(_logic.trim_summary,        _BUDGETS)
compact_index_block = functools.partial(_logic.compact_index_block, _BUDGETS)
compact_pre_index   = functools.partial(_logic.compact_pre_index,   _BUDGETS)
build_context       = functools.partial(_logic.build_context,       _BUDGETS)
