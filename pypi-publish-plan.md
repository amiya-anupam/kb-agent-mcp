# PyPI Publishing Plan: `knowledgebase-mcp`

## Overview

Publish `kb_agent_mcp/` to PyPI under the name **`knowledgebase-mcp`** so customers can install with:

```
pip install knowledgebase-mcp
```

The legacy `agents/` and `scripts/` directories stay in the repo untouched — they are excluded from the published package via the existing `[tool.setuptools.packages.find]` configuration.

A GitHub Actions workflow triggers on every merge to `main`, builds the distribution, and publishes to PyPI automatically using Trusted Publishing (no long-lived secrets needed).

**Scope:** `pyproject.toml` rename + README update + CI/CD pipeline + PyPI project registration. No code changes to `kb_agent_mcp/`.

---

## Sub-Tasks

---

### Sub-task 1 — Rename the package to `knowledgebase-mcp` in `pyproject.toml`

**Intent:** Change the published PyPI name from `kb-agent-mcp` to `knowledgebase-mcp`. The internal Python module name (`kb_agent_mcp`) and all CLI entry points stay the same — only the distribution name changes.

**Expected Outcomes:**
- `pyproject.toml` `[project].name` is `knowledgebase-mcp`
- `[project].description` is updated to reference the new name
- `README-MCP.md` Quick Start section updated to show `pip install knowledgebase-mcp` (and extras: `knowledgebase-mcp[openai]`, etc.)
- Comments in `pyproject.toml` reflecting the old name are updated
- The internal module import path (`kb_agent_mcp`) is unchanged

**Todo List:**
1. In `pyproject.toml` line 6: change `name = "kb-agent-mcp"` → `name = "knowledgebase-mcp"`
2. In `pyproject.toml` optional-deps comments (lines 44, 47, 50): update `pip install kb-agent-mcp[...]` → `pip install knowledgebase-mcp[...]`
3. In `README-MCP.md`: update every occurrence of `pip install kb-agent-mcp` → `pip install knowledgebase-mcp`
4. Verify `[tool.setuptools.packages.find]` still includes only `kb_agent_mcp*` (it should — this is unrelated to the distribution name)

**Relevant Context:**
- [`pyproject.toml`](pyproject.toml:6) — line 6 is the `name` field
- [`README-MCP.md`](README-MCP.md:27) — Quick Start and Installation sections reference the old name
- The `[tool.setuptools.packages.find]` at line 67–69 already correctly excludes `agents/` and `scripts/`

**Status:** `[x] done`

---

### Sub-task 2 — Prepare PyPI Trusted Publishing (no secrets required)

**Intent:** Configure PyPI to trust GitHub Actions as a publisher. This uses OIDC (OpenID Connect) — no `PYPI_TOKEN` secret in GitHub is needed. The workflow proves its identity via the GitHub Actions JWT.

**Expected Outcomes:**
- A PyPI project named `knowledgebase-mcp` exists under your PyPI account
- PyPI Trusted Publishing is configured for:
  - Repository owner: `<your GitHub username/org>`
  - Repository name: `KnowledgeBase` (or whatever the repo is named on GitHub)
  - Workflow filename: `publish.yml`
  - Environment name: `pypi` (optional but recommended)
- No `PYPI_TOKEN` secret needed in the GitHub repo settings

**Todo List:**
1. Log in to [pypi.org](https://pypi.org) (create account if needed)
2. Go to **Publishing** → **Add a new pending publisher**
3. Fill in: PyPI project name = `knowledgebase-mcp`, GitHub owner, repo name, workflow filename = `publish.yml`
4. Save — PyPI will auto-create the project on first publish

> Note: This is a one-time manual step. Document the exact PyPI project URL once created.

**Relevant Context:**
- PyPI Trusted Publishing docs: https://docs.pypi.org/trusted-publishers/
- No files to edit — this is a PyPI web UI step

**Status:** `[x] done`

---

### Sub-task 3 — Add GitHub Actions publish workflow

**Intent:** Create `.github/workflows/publish.yml` that runs on every merge to `main`, builds the wheel + sdist, and publishes to PyPI via Trusted Publishing.

**Expected Outcomes:**
- `.github/workflows/publish.yml` exists
- On merge to `main`, the workflow:
  1. Checks out the repo
  2. Builds `dist/knowledgebase_mcp-*.whl` and `dist/knowledgebase_mcp-*.tar.gz`
  3. Publishes both to PyPI using `pypa/gh-action-pypi-publish` with OIDC
- The workflow does NOT publish if tests fail (test job is a required dependency)
- `agents/` and `scripts/` are never included in the built wheel (already excluded by `pyproject.toml`)

**Todo List:**
1. Create `.github/workflows/` directory
2. Create `.github/workflows/publish.yml` with:
   - Trigger: `push` to `main` branch
   - Job 1 `test`: install `.[dev]`, run `pytest tests/ -q` — fail fast
   - Job 2 `publish`: depends on `test` job passing, uses `pypa/gh-action-pypi-publish@release/v1` with `permissions: id-token: write`
   - Python version: 3.11 (stable, matches classifiers)
   - Build step: `python -m build` (produces both wheel and sdist)
3. Verify the workflow file passes `yamllint` or GitHub Actions schema validation (mental check)

**Relevant Context:**
- `pyproject.toml` already has `build` in `[dev]` extras — the CI `pip install ".[dev]"` picks it up
- `pyproject.toml` `[tool.pytest.ini_options]` testpaths = `["tests"]` — no extra args needed
- Reference: https://docs.pypi.org/trusted-publishers/using-a-publisher/

**Status:** `[x] done`

---

### Sub-task 4 — Add version auto-bump on merge (optional but recommended)

**Intent:** Currently `version = "0.1.0"` is hardcoded. Every merge to `main` will publish — so we need version uniqueness or a strategy to avoid PyPI rejecting duplicate versions.

**Strategy: Auto-bump patch version on every merge to `main`.**

The CI workflow reads the current version from `pyproject.toml`, increments the patch segment (e.g. `0.1.0` → `0.1.1`), commits and pushes the bump back to `main` before building and publishing. This means every merge produces a unique, monotonically increasing version on PyPI with no developer action required.

**Expected Outcomes:**
- On every merge to `main`, the version in `pyproject.toml` is automatically incremented (patch segment only)
- The version bump commit is pushed back to `main` by the CI bot before the wheel is built
- The published wheel version matches the bumped value in `pyproject.toml`
- Developers never manually touch the version field for routine releases
- A `## Releasing` section in `README-MCP.md` explains the flow

**Todo List:**
1. In `.github/workflows/publish.yml`, add a `bump-version` step before the build step:
   - Parse `version = "X.Y.Z"` from `pyproject.toml` using `sed` or a small Python one-liner
   - Increment the patch component: `Z` → `Z+1`
   - Write the new version back to `pyproject.toml` in-place
   - `git config` bot identity (`github-actions[bot]`)
   - `git commit -am "chore: bump version to X.Y.Z+1 [skip ci]"` — the `[skip ci]` tag prevents the commit from re-triggering the workflow
   - `git push`
2. Add a `## Releasing` section to `README-MCP.md`:
   - "Merge to `main` → CI auto-bumps patch, builds, and publishes to PyPI automatically"
   - "For a minor or major bump, manually edit `version` in `pyproject.toml` in your PR before merging"

**Relevant Context:**
- [`pyproject.toml`](pyproject.toml:7) line 7: `version = "0.1.0"`

**Status:** `[x] done`

---

### Sub-task 5 — Smoke-test the build locally before first publish

**Intent:** Verify the wheel builds cleanly, contains only `kb_agent_mcp/` files, and installs correctly — before the first CI-triggered publish hits PyPI.

**Expected Outcomes:**
- `python -m build` completes without errors
- `dist/knowledgebase_mcp-0.1.0-py3-none-any.whl` exists
- `unzip -l dist/knowledgebase_mcp-*.whl` shows only `kb_agent_mcp/` and metadata — no `agents/`, `scripts/`, `ACE Docs/`, `BizOps/`, etc.
- `pip install dist/knowledgebase_mcp-*.whl` in a fresh venv succeeds
- `kb-agent-serve --version` and `kb-agent-setup --help` run without import errors

**Todo List:**
1. Run `pip install ".[dev]"` to ensure `build` is available
2. Run `python -m build`
3. Inspect wheel contents: `unzip -l dist/knowledgebase_mcp-*.whl | grep -v kb_agent_mcp`
4. Create a fresh venv: `python -m venv /tmp/test-venv && source /tmp/test-venv/bin/activate`
5. Install the local wheel: `pip install dist/knowledgebase_mcp-0.1.0-py3-none-any.whl`
6. Test CLIs: `kb-agent-serve --version`, `kb-agent-setup --help`
7. Deactivate and clean up the test venv

**Relevant Context:**
- [`pyproject.toml`](pyproject.toml:67-69) `[tool.setuptools.packages.find]` — `include = ["kb_agent_mcp*"]` already excludes legacy dirs

**Status:** `[x] done`

---

## Sequencing

```
Sub-task 1 (rename pyproject.toml + README)
    ↓
Sub-task 5 (local smoke-test — verify build is clean)
    ↓
Sub-task 2 (PyPI Trusted Publishing — manual web UI step)
    ↓
Sub-task 3 (GitHub Actions publish workflow)
    ↓
Sub-task 4 (document release convention)
```

Sub-tasks 2 and 3 can be done in parallel once Sub-task 1 is confirmed clean.

---

## Out of Scope (future phases)

- Native installer (`.dmg`, `.exe`) — deferred
- Version auto-bump automation
- TestPyPI staging environment
- `CHANGELOG.md` generation
