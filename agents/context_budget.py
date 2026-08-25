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
trim_summary(summary, filename)         → str
compact_index_block(block)              → str
compact_pre_index(text)                 → str
build_context(pre_index, index_block)   → str
get(key)                                → int
tokens(key)                             → int
COLLAPSE_RULES                          — list of (pattern, label, description_template)
"""

import os
import pathlib
import sys as _sys
import functools

# ── Load .env ─────────────────────────────────────────────────────────────────
# Delegate to agent_base so there is a single canonical loader.

_sys.path.insert(0, str(pathlib.Path(__file__).parent))
from agent_base import _load_env  # noqa: E402
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

# ── Pure compaction logic (shared with kb_agent_mcp/context_budget.py) ───────
# Each function in _context_budget_logic takes `budgets` as its first argument.
# We bind our local _BUDGETS here via partial so callers see the clean API.

import _context_budget_logic as _logic  # noqa: E402

COLLAPSE_RULES = _logic.COLLAPSE_RULES

get                = functools.partial(_logic.get,                _BUDGETS)
tokens             = functools.partial(_logic.tokens,             _BUDGETS)
trim               = functools.partial(_logic.trim,               _BUDGETS)
trim_summary       = functools.partial(_logic.trim_summary,       _BUDGETS)
compact_index_block = functools.partial(_logic.compact_index_block, _BUDGETS)
compact_pre_index  = functools.partial(_logic.compact_pre_index,  _BUDGETS)
build_context      = functools.partial(_logic.build_context,      _BUDGETS)
