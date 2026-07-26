# Code Quality, Packaging & Security Audit Plan — kb-agent-mcp

## Overview

Full audit of `kb_agent_mcp/` across three axes: code quality (PEP 8/257, best
practices), packaging hygiene, and security. Every finding is grounded in a
verified source line. False alarms from the sub-agent scan have been ruled out.

Issues are grouped into 4 independent sub-tasks ordered by impact.

---

## Confirmed Findings

### HIGH — Must fix

| # | File | Line | Issue |
|---|------|------|-------|
| H1 | `base_agent.py` | 420 | Same swapped-args bug as BUG-1: `_vs_search(question, folder_name, …)` but `vector_store.search()` signature is `(domain, query, …)`. Strategy-2 RAG fallback always searches the wrong collection. |

### MEDIUM — Should fix

| # | File | Line | Issue |
|---|------|------|-------|
| M1 | `cli/doctor.py` | 528 | `import argparse` placed **after** `main()` (same pattern as BUG-4 in watch.py). Marked `# noqa: E402` but is a NameError risk and violates PEP 8. |
| M2 | `base_agent.py`, `cli/generate.py`, `cli/setup.py` | 291, 142, 180 | `"anthropic-version": "2023-06-01"` hardcoded in three separate files. Should be a single named constant. |
| M3 | `orchestrator.py` | 238 | Bare `except Exception:` after JSON parse — silently falls back to keyword routing without logging *what* went wrong (LLM unreachable vs bad JSON vs timeout). Should log at WARNING level. |
| M4 | `pyproject.toml` | — | Missing `[project.urls]` table (Homepage, Repository) — standard PyPI metadata; makes the package page on PyPI sparse. |
| M5 | `pyproject.toml` | 14-22 | Missing `License :: OSI Approved :: MIT License` classifier — `license = "MIT"` sets the SPDX field but not the trove classifier. |

### LOW — Nice to fix

| # | File | Lines | Issue |
|---|------|-------|-------|
| L1 | `cli/doctor.py` | 528 | `import argparse` after function definition — move to top (same fix as M1 but noting separately as style) |
| L2 | `vector_store.py` | 232, 279, 317 | Three `except Exception:` blocks with no log output — silent failures make debugging impossible |
| L3 | `base_agent.py` | 64, 140, 195 | Three `except Exception:` blocks silently swallow passthrough-detection and context-extraction errors |
| L4 | `memory.py` | 62 | `except Exception:` swallows JSON parse error on session file load — should catch `json.JSONDecodeError` |
| L5 | `.gitignore` | 78-80 | References `risk-mitigation-plan.md` and `pypi-publish-plan.md` — both are gone; dead gitignore entries (cosmetic) |

---

## Sub-Tasks

---

### Task 1 — Fix HIGH: Swapped args in `base_agent.py` Strategy-2 RAG

**Intent:** `base_agent.py:420` calls `_vs_search(question, folder_name, …)` but
`vector_store.search(domain, query, …)` expects domain first. This is the same
class of bug as BUG-1 (already fixed in `domain_agent.py`). When `pre_ranked_results`
is `None` — i.e., every non-data, non-README-first query — Strategy 2 searches
using the question text as the domain name, returning empty results silently.

**Relevant Context:**
- `kb_agent_mcp/base_agent.py`, line 420
- `kb_agent_mcp/vector_store.py`, line 362 — `async def search(domain, query, top_n)`
- `kb_agent_mcp/domain_agent.py`, line 155 — already-fixed identical pattern for reference

**Expected Outcomes:**
- Line 420 passes `folder_name` as first arg, `question` as second
- New regression test in `tests/test_audit_fixes.py` (or a new file) verifies
  the call order in the Strategy-2 path

**Todo List:**
- [ ] Edit `base_agent.py:420`: `_vs_search(question, folder_name, …)` → `_vs_search(folder_name, question, …)`
- [ ] Add test: mock `_vs_search`, call `base_agent.ask()` with no README and `pre_ranked_results=None`, assert domain arg is `folder_name`
- [ ] Run `pytest tests/ -q`

**Status:** `[ ] pending`

---

### Task 2 — Fix MEDIUM: Move `import argparse` to top of `doctor.py`

**Intent:** `import argparse` is placed at line 528, after `main()` which uses it at
line 516. This is the same anti-pattern as BUG-4 (watch.py), though the risk is lower
because `main()` is only called at startup. Still violates PEP 8 E402 and creates
a NameError risk if `main()` is ever called in a test before Python reaches line 528.

**Relevant Context:**
- `kb_agent_mcp/cli/doctor.py`, lines 515-528
- All other CLI files (`watch.py`, `setup.py`, `generate.py`, `status.py`, `server.py`)
  already import `argparse` at the top — doctor.py is the sole outlier

**Expected Outcomes:**
- `import argparse` is the first or among the first imports in `doctor.py`
- The `# noqa: E402` comment is removed (no longer needed)
- Existing tests still pass

**Todo List:**
- [ ] Move `import argparse` to the top of `doctor.py` with other stdlib imports
- [ ] Remove `# noqa: E402` comment and the `if __name__ == "__main__": main()` block at bottom (entry point is `pyproject.toml`, not `__main__`)
- [ ] Run `pytest tests/ -q`

**Status:** `[ ] pending`

---

### Task 3 — Fix MEDIUM: Extract repeated Anthropic version header constant

**Intent:** The string `"anthropic-version": "2023-06-01"` appears identically in
three files. If Anthropic updates their API version, all three must be changed by
hand — a classic DRY violation. One named constant in `config.py` or a new
`_constants.py` eliminates the drift risk.

**Relevant Context:**
- `kb_agent_mcp/base_agent.py`, line 291
- `kb_agent_mcp/cli/generate.py`, line 142
- `kb_agent_mcp/cli/setup.py`, line 180
- `kb_agent_mcp/config.py` — already the home of shared config values

**Expected Outcomes:**
- A single `ANTHROPIC_API_VERSION = "2023-06-01"` constant defined in `config.py`
- All three files import and reference the constant instead of the string literal
- Tests still pass

**Todo List:**
- [ ] Add `ANTHROPIC_API_VERSION = "2023-06-01"` to `config.py`
- [ ] Replace the string literal in `base_agent.py:291`, `generate.py:142`, `setup.py:180`
- [ ] Run `pytest tests/ -q`

**Status:** `[ ] pending`

---

### Task 4 — Fix MEDIUM: Add `[project.urls]` and missing license classifier to `pyproject.toml`

**Intent:** The PyPI package page for `kb-agent-mcp` currently has no homepage,
source, or documentation links, and is missing the trove license classifier.
Both are standard PyPI metadata that improve discoverability and make the package
page complete.

**Relevant Context:**
- `pyproject.toml`, the `[project]` table
- Current classifiers: lines 14-22 (missing `License :: OSI Approved :: MIT License`)
- No `[project.urls]` table exists

**Expected Outcomes:**
- `[project.urls]` added with `Homepage`, `Repository`, and `Documentation` keys
- `License :: OSI Approved :: MIT License` added to classifiers
- `pytest tests/ -q` still passes (no runtime impact)

**Todo List:**
- [ ] Add `[project.urls]` table with correct GitHub repo URL
- [ ] Add `License :: OSI Approved :: MIT License` to `classifiers`
- [ ] Run `pytest tests/ -q`

**Status:** `[ ] pending`

---

### Task 5 — Fix LOW: Add WARNING logs to silent `except Exception:` blocks

**Intent:** 65 `except Exception:` blocks exist across the codebase. Most are
intentional resilience patterns (fallback to keyword search, return empty, skip file).
However, the ones that swallow errors *without any log output* make production
debugging very hard — a user sees empty results with no indication why.

Scope is limited to the highest-impact silent swallows only:

| File | Line | What is silently swallowed |
|------|------|---------------------------|
| `orchestrator.py` | 238 | LLM classification failure (JSON parse, timeout, bad response) |
| `vector_store.py` | 317 | Embedding failure causing fallback to keyword search |
| `vector_store.py` | 232 | Hash verification failure on upsert |
| `memory.py` | 62 | JSON parse error on session file load |
| `base_agent.py` | 64 | Ollama reachability check failure |

All others (file extraction errors, watchdog errors, clipboard errors) are
already acceptable UX-level silences.

**Relevant Context:**
- `kb_agent_mcp/orchestrator.py:238`
- `kb_agent_mcp/vector_store.py:232,317`
- `kb_agent_mcp/memory.py:62`
- `kb_agent_mcp/base_agent.py:64`
- Each module already has a `logger = logging.getLogger(...)` — just needs `logger.warning()`

**Expected Outcomes:**
- Each of the 5 blocks above logs a `WARNING` with the exception repr
- No change to fallback behaviour — same control flow, just with a log line
- Tests still pass

**Todo List:**
- [ ] `orchestrator.py:238` — add `logger.warning("LLM classification failed, using keyword fallback: %s", exc)` (need to capture exc first: `except Exception as exc:`)
- [ ] `vector_store.py:317` — add `logger.warning("Embedding failed, falling back to keyword search: %s", exc)`
- [ ] `vector_store.py:232` — add `logger.warning("Hash check failed for %s: %s", …, exc)`
- [ ] `memory.py:62` — change to `except (json.JSONDecodeError, ValueError)` and log
- [ ] `base_agent.py:64` — add `logger.debug("Ollama reachability check failed: %s", exc)`
- [ ] Run `pytest tests/ -q`

**Status:** `[ ] pending`

---

### Task 6 — Fix LOW: Remove stale gitignore entries

**Intent:** `.gitignore` references two files — `risk-mitigation-plan.md` and
`pypi-publish-plan.md` — that were deleted in a previous commit. Dead entries
create confusion ("is this file supposed to exist?"). Two lines to delete.

**Relevant Context:**
- `.gitignore`, lines 78-80

**Expected Outcomes:**
- Two stale entries removed
- `.gitignore` still covers all real cases (verified by review)
- No staged file changes beyond `.gitignore`

**Todo List:**
- [ ] Remove `risk-mitigation-plan.md` and `pypi-publish-plan.md` lines from `.gitignore`

**Status:** `[ ] pending`

---

## Out of Scope (ruled out)

- The 60 remaining `except Exception:` blocks — all are either intentional UX
  resilience (file extraction skip, clipboard fallback, watchdog debounce) or
  already log the exception. Changing all of them would produce noise without value.
- SSL verification on httpx calls — Python's default SSL context is secure; no
  explicit `verify=False` found anywhere.
- `eval()` / `exec()` — none found.
- `shell=True` subprocess — none found.
- API key leakage in error messages — verified safe; key never interpolated into
  log strings.
- Version pinning strategy — `>=` pins are intentional for a library package to
  avoid over-constraining consumer environments.
