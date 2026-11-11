# Phase 5.1 - Duplicate function inventory (agents/ vs kb_agent_mcp/)

Inventory only. No code was refactored. Compiled by AST-matching module-level
functions and class methods with the same name across `agents/` and `kb_agent_mcp/`,
then diffing the bodies by hand.

## How the "26" was counted

The figure 26 appears only in the plan title; no source document lists the 26
functions. The AST match finds **26 same-named pairs that are real or
near-duplicates, plus 4 `main` entry points and the `ask` / `list_sessions`
collisions that are not duplicates** (listed under "False duplicates"). The exact
set behind the plan's 26 cannot be reproduced; this table is the reconciled list.

Only **1** pair is byte-identical (`_apply_format_instruction`). All others have
diverged in body, signature, or sync/async shape.

Convention: `agents/` versions are synchronous; `kb_agent_mcp/` versions are mostly
`async` (`call_llm`, `search`, memory functions). Canonical pick = the
`kb_agent_mcp/` version, per the plan.

## Same-name pairs

| # | Function | agents/ location (lines) | kb_agent_mcp/ location (lines) | Status | What differs | Canonical |
|---|----------|--------------------------|--------------------------------|--------|--------------|-----------|
| 1 | `_apply_format_instruction` | agent_base.py:214 | domain_agent.py:38 | IDENTICAL | nothing | package |
| 2 | `_has_noindex_ancestor` | agent_base.py (25 L) | file_parser.py (17 L) | DIVERGED | package reads root from `cfg`; agents uses `KB_ROOT` and swallows exceptions | package |
| 3 | `should_skip` | agent_base.py | file_parser.py | DIVERGED (constants only) | same logic, different `SKIP_PATTERNS` constants | package |
| 4 | `_stream_xlsx_aggregate` | agent_base.py | file_parser.py | NEAR-IDENTICAL | both 5-line delegators to `agents/_xlsx_stream.py` | package |
| 5 | `_find_readme` | agent_base.py (43 L) | base_agent.py (31 L) | DIVERGED | package version shorter | package |
| 6 | `_non_index_chars` | agent_base.py (9 L) | base_agent.py (9 L) | DIVERGED (minor) | small body difference | package |
| 7 | `_get_readme_context` | agent_base.py (46 L) | base_agent.py (29 L) | DIVERGED | package version shorter | package |
| 8 | `call_llm` | agent_base.py (13 L, sync, `LLM_PROVIDER` dispatch) | base_agent.py:312 (8 L, async, `_LLM_REGISTRY`) | DIVERGED (sync vs async) | dispatch mechanism and async | package |
| 9 | `format_confidence_footer` | agent_base.py (46 L) | base_agent.py (16 L) | DIVERGED | package version much shorter | package |
| 10 | `ask` | agent_base.py (214 L) | base_agent.py (268 L) | DIVERGED | package is the flag-gated tiered/Chroma pipeline | package |
| 11 | `_embed_ollama` | embeddings.py (9 L) | embeddings.py (11 L) | DIVERGED (minor) | | package |
| 12 | `_embed_openai` | embeddings.py (14 L) | embeddings.py (16 L) | DIVERGED (minor) | | package |
| 13 | `_embed_sentence_transformers` | embeddings.py (24 L) | embeddings.py (3 L) | DIVERGED | package calls `_load_st_model` | package |
| 14 | `search` | embeddings.py:515 (65 L, sync) | vector_store.py:895 (10 L, async wrapper over `_search_sync`) | DIVERGED | different backends (flat index vs Chroma) | package |
| 15 | `_session_file` | memory.py (16 L) | memory.py (6 L) | DIVERGED | agents keeps legacy single-file path for "default"; package uses `.kb_index/session_memory/` | package |
| 16 | `get_history` | memory.py | memory.py | DIVERGED | package = async wrapper over `*_sync` | package |
| 17 | `add_turn` | memory.py (19 L) | memory.py (7 L) | DIVERGED | as above | package |
| 18 | `clear` | memory.py | memory.py | DIVERGED | as above | package |
| 19 | `summary` | memory.py | memory.py | DIVERGED | as above | package |
| 20 | `list_sessions` | memory.py (47 L) | memory.py (3 L) | DIVERGED | as above | package |
| 21 | `detect_format_intent` | agent_knowledgebase.py (30 L) | orchestrator.py (20 L) | DIVERGED | | package |
| 22 | `_keyword_confidence` | agent_knowledgebase.py (35 L) | orchestrator.py (27 L) | DIVERGED | | package |
| 23 | `_tokens` | content_gate.py:113 | tiered.py:78 | FALSE DUPLICATE | different tokenizers, different purposes | keep both |
| 24 | `AGG_KEYWORDS` / `_AGG_KEYWORDS` (constant) | agent_base.py:83 | file_parser.py:60 | DUPLICATE CONSTANT | also re-imported by agents/embeddings.py | package |
| 25 | `PREFERRED_NUM_COLS` / `_PREFERRED_NUM_COLS` (constant) | agent_base.py:114 | file_parser.py:85 | DUPLICATE CONSTANT | | package |
| 26 | `context_budget` (whole module) | agents/context_budget.py (91 L) | kb_agent_mcp/context_budget.py | DUPLICATE MODULE | both delegate to `agents/_context_budget_logic.py` | package |

Rows 23-26 are not same-named functions of the first kind; they are listed to
reconcile toward the plan's 26.

## Related near-duplicates (different names)

| Function | Locations | Note |
|----------|-----------|------|
| `folder_to_safe_name` | agents/agent_base.py:194 | same slug logic as the next two |
| `domain_slug` | kb_agent_mcp/context_store/paths.py:29 | |
| `_safe_name` | kb_agent_mcp/vector_store.py:341 | |
| `discover_folders` | agents/embeddings.py:80, scripts/generate.py:82 | |
| `should_skip` | scripts/watch_kb.py:221 | third copy of skip logic |

## False duplicates (name collision only)

- `main` x3: agent entry points vs `server.main`.
- `ask`: `agents/agent_base.ask` / `base_agent.ask` are related (row 10); `orchestrator.ask` and `server.ask` are separate layers.
- `list_sessions`: `server.list_sessions` is an MCP tool wrapper, not a copy.

## Reverse dependency (RESOLVED in 5.2: both modules now live in `kb_agent_mcp/`)

`kb_agent_mcp` imports shared logic **from** `agents/` via `sys.path` insertion:

- `kb_agent_mcp/file_parser.py:258-266` imports `_xlsx_stream`
- `kb_agent_mcp/context_budget.py:48-56` imports `_context_budget_logic`

Before 5.2 can make `kb_agent_mcp` canonical, `agents/_xlsx_stream.py` and
`agents/_context_budget_logic.py` must move into `kb_agent_mcp/` (agents/ then
re-exports them).

## Callers that import from agents/ (bare module names, sys.path based)

- **scripts**
  - `scripts/generate.py:55-66,451-456,520,970` - `agent_base` (`folder_to_safe_name`, `KB_ROOT`, `VECTOR_STORE`, `ask`), `embeddings` (`extract_text_snippet`, `search`, `build_index`), `content_gate`
  - `scripts/watch_kb.py:55-60,313,868,1020,1032` - `context_budget`, `agent_base`, `embeddings`
- **agents themselves**
  - `agents/agent_{bizops,ace_docs,cp4i_docs}.py` - `agent_base`, `memory`, `embeddings`
  - `agents/agent_knowledgebase.py:48,49,142,528` - `memory`, `agent_base`, `embeddings`
  - `agents/embeddings.py:46`, `agents/memory.py:64,193`, `agents/context_budget.py:55` - `agent_base`
- **tests**
  - `tests/test_tech_debt_duplicates.py` (imports `agent_base` and `embeddings`; asserts the copies of `folder_to_safe_name`, `AGG_KEYWORDS`, etc. agree - must be kept green or updated in 5.2)
  - `test_noindex_guard.py`, `test_ignore_unification.py`, `test_e2e_new_customer.py`, `test_image_ocr.py`, `test_content_gate.py`

## File sizes (agents/)

`agent_base.py` 1,229 L; `agent_knowledgebase.py` 774; `embeddings.py` 701;
`content_gate.py` 407; `memory.py` 369; `_context_budget_logic.py` 297;
`_xlsx_stream.py` 207; `agent_bizops.py` 124.

## Suggested order for 5.2 (not started)

1. DONE: moved `_xlsx_stream` and `_context_budget_logic` into `kb_agent_mcp/` (breaks the reverse dependency).
2. Collapse the byte-identical and constant duplicates (rows 1, 3, 4, 24, 25, 26) - lowest risk.
3. Unify slug helpers.
4. Memory and embeddings pairs (sync/async shape differences need thin sync wrappers in agents/).
5. `ask` / `call_llm` last; they carry behavioural divergence.

## 5.2 progress

Done (each its own commit, suite 940 passed after each):

- Reverse dependency removed: `_xlsx_stream` and `_context_budget_logic` now live in `kb_agent_mcp/`; agents/ imports them from there.
- Rows 24, 25: `AGG_KEYWORDS` / `PREFERRED_NUM_COLS` defined once in `kb_agent_mcp/_xlsx_stream.py`; `agents/agent_base.py` re-exports the legacy names, `file_parser` aliases them.
- Row 1: `apply_format_instruction` defined once in `kb_agent_mcp/format_instruction.py`; both old names remain as aliases.
- Row 26 / row 4: the two `context_budget` modules and the two `_stream_xlsx_aggregate` wrappers now share the package logic; the thin per-layer wrappers stay because each binds its own budgets/constants.

Deliberately NOT merged yet (behaviour differs, not a pure move):

- Rows 2-3 (`_has_noindex_ancestor`, `should_skip`): different skip-pattern sets (`watch_kb` in agents) and root source (`KB_ROOT` vs `cfg`); tests monkeypatch each.
- Slug helpers: `folder_to_safe_name` collapses runs of non-alphanumerics, `domain_slug`/`_safe_name` do not (and `_safe_name` pads/truncates). Unifying would change output.
- Rows 8, 10 (`call_llm`, `ask`): sync + `LLM_PROVIDER` dispatch (agents, monkeypatched by `tests/test_routing_and_passthrough.py`) vs async `_LLM_REGISTRY` (package). Left separate on purpose.

Also done (migration order memory -> embeddings -> content_gate -> routing/base; suite 940 passed after each):

- memory: `agents/memory.py` is a shim over `kb_agent_mcp.memory` (`_trim_messages`, `_session_record`, keyword overrides on `_compress_answer_sync`). Kept divergence: the agents default session still lives in `agents/vector_store/session_memory.json`, separate from the package's `.kb_index/session_memory/default.json`.
- embeddings: `agents/embeddings.py` re-exports `_embed_ollama`, `_embed_openai`, `_embed_sentence_transformers`, `_embed_sync as get_embedding`. The package reads `cfg` (not import-time env vars) and gates its fallback on `KB_PASSTHROUGH_FALLBACK`.
- content_gate: no package twin. The only same-name pair, `_tokens` (content_gate vs `tiered._tokens`), is a false duplicate (different tokenizers). Nothing to merge.
- routing/base: `_find_readme`, `_non_index_chars`, `format_confidence_footer` are imported from `kb_agent_mcp.base_agent`; the format tables and a new `detect_format_intent_key` live in `kb_agent_mcp/format_instruction.py` (orchestrator and agents both use it; agents keeps its CLI `print`); `_keyword_confidence` shares `kb_agent_mcp.orchestrator.confidence_from_counts` (hit counting stays per-layer).
- Divergence reconciled: the agents one-liner phrase regex was wider (`briefly in one sentence`, `give me a quick one-liner`); the canonical table now uses the wider one, so the package also recognises those phrases.
- `_get_readme_context` stays in agents: it reads `KB_ROOT` and the module-level `_cb` budget, which tests patch.


## 5.4 progress: single source of truth for domain metadata

- `domain_config.yaml` (per knowledge folder) is canonical. `kb_agent_mcp.domain_rules.overlay_domain_config` returns a legacy meta entry with `agent_name`, `description`, `keywords`, `top_n`, `max_chars` and `system_prompt` taken from the yaml.
- `agents/vector_store/domain_meta.json` is now a derived cache: `scripts/generate.py` overlays the yaml before writing it, and `agents/agent_knowledgebase.load_domain_meta()` overlays it again on read, so a stale cache can no longer override the yaml. The package itself never reads this file.
- `<domain>_index.json` files are still required by the legacy embeddings/keyword path (`agents/embeddings.py`, `agent_base.py`, `domain_runner.py`, `watch_kb.py`, `generate.py`); not removable.
- `docs_index.json` was a stale watcher artefact (a long-running watcher with an older `INFRA_FOLDERS` indexed `docs/`). It is deleted; `generate.py` orphan cleanup removes it, and restarting the watcher stops it reappearing.
