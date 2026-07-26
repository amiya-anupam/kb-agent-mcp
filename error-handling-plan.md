# Error Handling Improvement Plan

> **Design decisions (confirmed):**
> - **Task 4 scope:** CLI logger calls cover *error paths only* (`except` blocks). No `logger.info()` added to success paths — Rich/print already handles those for the user.
> - **`_search_sync()` returning `[]`:** Keep `[]` as the return value so callers' graceful degradation is preserved. Add `logger.warning()` with domain + query + exc so an operator can distinguish "DB broken" from "genuinely empty" in logs.

## Overview

The codebase has inconsistent error handling across its modules. Two critical runtime crashes exist from logger references that were added without the logger being defined. Beyond that, several library modules silently swallow exceptions and return empty/null values with no trace of what went wrong. The goal is to ensure every error path either propagates a descriptive exception or logs the reason before returning a fallback — no silent failures, no mystery `None`/`[]`/`False` returns.

**Scope:** All files under `kb_agent_mcp/` — both library modules and CLI tools.
**Non-goal:** Changing any user-visible behaviour, return types, or public API signatures. Error paths keep their current fallback values; they just stop being silent.

---

## Sub-Tasks

---

### Task 1 — Fix critical runtime crashes (missing logger definitions)

**Status:** `[ ] pending`

**Intent:**
Two files use `logger.warning()` / `logger.debug()` that were added in the previous audit pass but the `logger` variable was never defined. These will raise `NameError` the first time either error path is hit at runtime.

**Expected Outcomes:**
- `base_agent.py` and `orchestrator.py` each have `import logging` and `logger = logging.getLogger(__name__)` at module level.
- Running the tests still passes (≥ 306).
- The NameError is no longer reachable.

**Todo List:**
1. Add `import logging` to the stdlib imports block in `kb_agent_mcp/base_agent.py`.
2. Add `logger = logging.getLogger(__name__)` after the imports in `base_agent.py`.
3. Add `import logging` to the stdlib imports block in `kb_agent_mcp/orchestrator.py`.
4. Add `logger = logging.getLogger(__name__)` after the imports in `orchestrator.py`.
5. Run `python3 -m pytest tests/ -q --tb=short` — confirm ≥ 306 pass.

**Relevant Context:**
- `kb_agent_mcp/base_agent.py` line 65: `logger.debug("Ollama reachability check failed (%s); treating as passthrough", exc)` — logger undefined.
- `kb_agent_mcp/orchestrator.py` line 239: `logger.warning("LLM domain-routing failed (%s); falling back to keywords", exc)` — logger undefined.
- `kb_agent_mcp/memory.py` and `kb_agent_mcp/vector_store.py` already have correct logger setup (added in previous session) — use those as the reference pattern.

---

### Task 2 — Add logging to silent swallowers in library modules

**Status:** `[ ] pending`

**Intent:**
Several library modules catch exceptions and return empty/null values with no log output. Callers have no way to distinguish a real empty result from an error. This task adds a `logger.warning()` before every such fallback return so the failure is traceable.

**Expected Outcomes:**
- Every `except` block that returns `None`, `[]`, `{}`, `False`, or calls `pass` now logs the exception and relevant context before doing so.
- Return values are not changed — callers continue to receive the same fallback.
- Running tests still passes (≥ 306).

**Todo List:**

**domain_agent.py** (no logger exists — add it first):
1. Add `import logging` and `logger = logging.getLogger(__name__)` at module level.
2. Line ~142: `stale_file_count()` catches bare `Exception` and returns `(0, 0)` — add `logger.warning("stale_file_count for %r failed (%s); returning (0, 0)", domain, exc)`.

**vector_store.py** (logger already defined):
3. Line ~140: `collection_exists()` catches bare `Exception` and returns `False` — add `logger.warning(...)` with domain name and exception.
4. Line ~182: `set_domain_metadata()` silent fallback to `get_or_create` — add `logger.debug(...)` noting the metadata update failed and a create is being attempted.
5. Line ~199–203: `get_domain_metadata()` silent JSON parse failure + returns `None` — add `logger.warning(...)` with domain name and exc.
6. Line ~211: `delete_collection()` silent `pass` — add `logger.warning(...)` with domain name and exc.
7. Line ~264: `_delete_file_sync()` silent `pass` — add `logger.warning(...)` with file path and exc.
8. Line ~282: `_search_sync()` returns `[]` on ChromaDB error — add `logger.warning(...)` with domain, query, and exc.

**file_parser.py** (logger already defined):
9. Line ~177: Silent XLSX `workbook.xml` parse error — add `logger.debug(...)` with path and exc.
10. Line ~185: Silent `_rels/workbook.xml.rels` parse error — add `logger.debug(...)`.
11. Line ~196: Silent `sharedStrings.xml` parse error — add `logger.debug(...)`.

**domain_rules.py** (no logger exists — add it first):
12. Add `import logging` and `logger = logging.getLogger(__name__)` at module level.
13. Line ~119: `_parse_yaml()` catches `Exception` and returns `{}` — add `logger.warning(...)` with file path and exc.
14. Line ~142: `load_domain_config()` catches `Exception` and returns `None` — add `logger.warning(...)` with domain/path and exc.
15. Line ~211: `apply_pin_rules()` silent `rglob` error — add `logger.debug(...)` with domain and exc.

16. Run `python3 -m pytest tests/ -q --tb=short` — confirm ≥ 306 pass.

**Relevant Context:**
- Existing good pattern: `vector_store.py` lines 236–237 and 320–322 (added last session) — use same style.
- `file_parser.py` line 441–446 already has good logging for file extraction — match that style.
- `domain_agent.py` imports block: `kb_agent_mcp/domain_agent.py` lines 1–20.
- `domain_rules.py` imports block: `kb_agent_mcp/domain_rules.py` lines 1–50.

---

### Task 3 — Add logging to silent swallowers in base_agent.py

**Status:** `[ ] pending`

**Intent:**
`base_agent.py` has three `except` blocks in its README-context helpers that silently swallow errors and return `None`/`(None, "")`. Since `base_agent.py` is the core agent runtime, these silent failures make it impossible to diagnose why an agent has no system prompt context.

**Expected Outcomes:**
- All three except blocks in `base_agent.py` log the failure reason before returning.
- Return values are unchanged.
- Tests pass (≥ 306).

**Todo List:**
1. Line ~141: `_find_readme()` catches `Exception` during `iterdir()` and returns `None` implicitly — add `logger.debug(...)` with folder path and exc.
2. Line ~157: `_find_readme()` catches `Exception` on individual file reads during the loop and does `continue` — add `logger.debug(...)` with candidate path and exc.
3. Line ~196: `_get_readme_context()` catches `Exception` and returns `(None, "")` — add `logger.debug(...)` with path and exc.
4. Run `python3 -m pytest tests/ -q --tb=short` — confirm ≥ 306 pass.

**Relevant Context:**
- Logger will be defined in Task 1 — this task depends on Task 1 being complete first.
- `kb_agent_mcp/base_agent.py` functions `_find_readme()` ~line 135 and `_get_readme_context()` ~line 190.

---

### Task 4 — Add Python logging to CLI tools

**Status:** `[ ] pending`

**Intent:**
CLI tools currently use only Rich/print output. Per the user's preference, all error paths should also emit a Python log entry so errors appear in log files when the tools are run in non-interactive / automated contexts (e.g. cron, CI). Rich output to the terminal is kept as-is.

**Expected Outcomes:**
- Each CLI module (`setup.py`, `generate.py`, `watch.py`, `doctor.py`, `status.py`) has `import logging` and `logger = logging.getLogger(__name__)` at module level.
- Every `except` block that currently only prints or is silent also calls `logger.error(...)` or `logger.warning(...)` with the exception and relevant context.
- Terminal output is unchanged (Rich/print calls stay in place).
- Tests pass (≥ 306).

**Todo List:**

**cli/watch.py** (already has a named logger — verify it logs all exceptions, add any missing):
1. Scan all `except` blocks in `watch.py` — the three currently-logged ones are fine. Confirm no additional bare handlers.

**cli/setup.py**:
2. Add `import logging` and `logger = logging.getLogger(__name__)` at module level.
3. Identify every `except` block that only prints or is silent — add `logger.error(...)` or `logger.warning(...)` alongside the existing print/Rich call.

**cli/generate.py**:
4. Add `import logging` and `logger = logging.getLogger(__name__)` at module level.
5. Add `logger.error(...)` to each `except` block that currently only prints or is silent.

**cli/doctor.py**:
6. Add `import logging` and `logger = logging.getLogger(__name__)` at module level.
7. Add `logger.error(...)` to each `except` block.

**cli/status.py**:
8. Add `import logging` and `logger = logging.getLogger(__name__)` at module level.
9. Add `logger.error(...)` to each `except` block.

10. Run `python3 -m pytest tests/ -q --tb=short` — confirm ≥ 306 pass.

**Relevant Context:**
- `cli/watch.py` line 33: `logger = logging.getLogger("kb-agent-watch")` — already done; use as pattern.
- CLI tools use a mix of `rich.console.Console` and plain `print()` for user-facing output — do not replace those, only add the parallel `logger` call.
- CLI modules are typically run as entry points, not imported — but adding a module logger is still correct for library-consistency and automation use.

---

### Task 5 — Final validation and commit

**Status:** `[ ] pending`

**Intent:**
Run the full test suite, verify all 306+ tests pass with no new warnings, then commit and push the complete error-handling improvement as a single commit.

**Expected Outcomes:**
- `python3 -m pytest tests/ -q --tb=short` shows ≥ 306 passed, 0 failed.
- `git push origin main` succeeds.
- Commit message summarises all four tasks.

**Todo List:**
1. Run `python3 -m pytest tests/ -q --tb=short` — confirm ≥ 306 pass.
2. Stage all changed files.
3. Commit with message: `fix: add missing logger definitions and improve error handling across all modules`.
4. Push to `main`.

---

## File Change Summary

| File | Changes |
|------|---------|
| `kb_agent_mcp/base_agent.py` | Add `import logging` + `logger`; add debug logs to 3 silent except blocks |
| `kb_agent_mcp/orchestrator.py` | Add `import logging` + `logger` |
| `kb_agent_mcp/domain_agent.py` | Add `import logging` + `logger`; log in `stale_file_count()` |
| `kb_agent_mcp/vector_store.py` | Log in 5 silent except blocks |
| `kb_agent_mcp/file_parser.py` | Log in 3 silent XLSX XML parse blocks |
| `kb_agent_mcp/domain_rules.py` | Add `import logging` + `logger`; log in 3 silent except blocks |
| `kb_agent_mcp/cli/setup.py` | Add `import logging` + `logger`; add parallel `logger` calls to except blocks |
| `kb_agent_mcp/cli/generate.py` | Add `import logging` + `logger`; add parallel `logger` calls to except blocks |
| `kb_agent_mcp/cli/doctor.py` | Add `import logging` + `logger`; add parallel `logger` calls to except blocks |
| `kb_agent_mcp/cli/status.py` | Add `import logging` + `logger`; add parallel `logger` calls to except blocks |
| `kb_agent_mcp/cli/watch.py` | Verify existing logging is complete — no changes expected |
