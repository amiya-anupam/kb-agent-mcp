# Risk Mitigation Plan — kb-agent-mcp End-to-End Hardening

## Overview

This plan addresses the risks identified in the end-to-end user journey analysis.
Issues are grouped into six phases by **impact** and **implementation complexity**.

- **Phase 1 — Critical Blockers**: Things that silently break the user's setup or produce
  wrong output with no error message. Must be fixed first.
- **Phase 2 — Friction Points**: Things that cause confusion or unexpected delays but
  don't stop the system from working.
- **Phase 3 — Resilience & Observability**: Things that improve long-term maintainability
  and help users debug on their own.
- **Phase 4 — Documentation Gaps (HIGH)**: Silent failures caused by missing or buried
  guidance in README files. No code changes — docs only.
- **Phase 5 — Runtime Guardrails (MED)**: Runtime risks that cause incorrect, incomplete,
  or misleading behaviour without crashing.
- **Phase 6 — Polish & Edge Cases (LOW)**: Minor friction items and edge-case handlers
  that improve robustness over time.

Each sub-task is scoped to a single file or closely related pair of files, so changes
stay focused and reviewable.

## Decisions Log

| Decision | Choice | Rationale |
|---|---|---|
| `kb-agent-doctor` form | Standalone CLI command (`kb-agent-doctor`) registered in `pyproject.toml` | Must work even when `kb-agent-serve` itself is broken; clean single-responsibility model; easier to reference in README troubleshooting |
| Stale-index warning threshold | Warn only when file count difference is >5% of indexed count (minimum 1 file) | A per-file threshold would be noisy for active folders; percentage threshold scales with domain size |
| Phase ordering | Sequential — fully validate Phase 1, then Phase 2, then Phase 3 before starting the next | Ensures each phase is tested in isolation before building on it |
| `.env` write location (4.x) | Write to `KB_ROOT/.env`, not CWD — or warn CWD clearly | KB_ROOT is the natural home for KB configuration; CWD placement causes "not found" on serve from a different directory |
| YAML validation approach (5.1) | Validate before `write_text()`, show error and re-prompt — do not silently accept | Accepting invalid YAML causes silent domain load failures later; better to fail loud at generate time |
| `reindex()` new-domain handling (6.2) | Append a CLI note rather than auto-generating YAML inside the MCP tool | YAML generation requires interactive acceptance prompt; adding it to an async MCP tool would block and is out of scope for `reindex()` |

---

## Phase 1 — Critical Blockers

### 1.1 — Exclude `.egg-info` folders from domain discovery (both paths)

**Intent**
`kb_agent_mcp.egg-info/` and `knowledgebase_mcp.egg-info/` are Python packaging
artifacts. They are being discovered as knowledge domains and appear verbatim in
`agents/SKILL.md` and in query routing. This produces nonsense domain names and
pollutes the skill description visible to every user.

**Root cause**
Neither `BUILTIN_IGNORE` in `kb_agent_mcp/config.py` nor the blocklist in
`scripts/generate.py` has a glob/suffix rule to exclude `*.egg-info` directories.
The check is an exact string match, so `kb_agent_mcp.egg-info` is not caught.

**Expected Outcomes**
- Running `kb-agent-generate` on this repo no longer produces `kb_agent_mcp.egg-info`
  or `knowledgebase_mcp.egg-info` as domain names.
- `agents/SKILL.md` no longer lists those folders as domains.
- The fix works for any `.egg-info` folder name, not just the two currently present.

**Todo List**
1. In `kb_agent_mcp/config.py`, update `is_ignored()` to also return `True` when
   `folder_name` ends with `.egg-info` or `.dist-info`.
2. In `scripts/generate.py`, update the `get_blocklist()` / `discover_folders()` logic
   to skip folder names ending with `.egg-info` or `.dist-info`.
3. Verify by running `kb-agent-generate` and confirming the egg-info folders are absent
   from the printed domain list.

**Relevant Context**
- `kb_agent_mcp/config.py` → `Config.is_ignored()` line ~190
- `scripts/generate.py` → `_DEFAULT_BLOCKLIST` line ~55, `discover_folders()` line ~87

**Status**: [x] done

---

### 1.2 — Fail loudly when `KB_ROOT` is not set in MCP host config

**Intent**
When `kb-agent-serve` is launched without `KB_ROOT` in the environment, `cfg.KB_ROOT`
falls back to `Path.cwd()`. On most MCP host setups the CWD is not the knowledge base,
so all `ask()` calls return empty results with no explanation. Users waste significant
time debugging this.

**Root cause**
`config.py` defaults `KB_ROOT` to `str(Path.cwd())` rather than raising when the var is
absent. The `validate()` method only checks that the path *exists*, not that it was
explicitly set.

**Expected Outcomes**
- If `KB_ROOT` is not set and `Path.cwd()` contains no knowledge folders, the MCP server
  logs a clear startup warning: `"KB_ROOT is not set — defaulting to CWD. Set KB_ROOT in
  your MCP host config."`.
- The `ask` tool response includes the warning when no domains are found, rather than an
  empty string.
- The `list_domains()` tool response includes the same warning when zero domains are indexed.

**Todo List**
1. In `kb_agent_mcp/config.py`, add an `is_kb_root_explicit` property that returns `True`
   only when `KB_ROOT` is present in `os.environ` (not just defaulted).
2. In `kb_agent_mcp/server.py`, at startup (inside `main()`), call `cfg.validate()` and
   log any errors. If `KB_ROOT` was not explicitly set, print the warning to stderr.
3. In `kb_agent_mcp/orchestrator.py`, when `build_all_domain_agents()` finds zero domains,
   include the KB_ROOT warning in the returned message from `ask()` and `list_domains()`.

**Relevant Context**
- `kb_agent_mcp/config.py` → `Config` class, `_str()` helper, `validate()` method
- `kb_agent_mcp/server.py` → `main()` entry point
- `kb_agent_mcp/orchestrator.py` → `_get_agents()`, `ask()`

**Status**: [x] done

---

### 1.3 — Surface stale-index warning inside the AI tool

**Intent**
After a user adds documents to a domain folder, the agent continues answering from the
old index with no indication that data is stale. The user has no way to know from inside
their AI tool that re-indexing is needed.

**Root cause**
The `ask` tool has no mechanism to compare the current file-system state against the
indexed state. The watcher (`kb-agent-watch`) is a separate process and is not required.

**Expected Outcomes**
- The `ask` tool response appends a one-line note when the file count on disk differs
  from the count recorded in `domain_config.yaml` for any domain that was queried.
  Example: `> ⚠ BizOps has 3 new files since last index. Run kb-agent-generate to update.`
- The `list_domains()` tool response shows per-domain file counts from disk vs. indexed.
- The check is lightweight (directory walk, no embedding), so it does not add perceptible
  latency to normal queries.

**Todo List**
1. In `kb_agent_mcp/domain_agent.py`, add a `stale_file_count()` method that walks the
   domain folder and returns `(files_on_disk, files_indexed)` counts (directory walk
   only — no embedding or ChromaDB query needed; compare by file count in the collection).
2. In `kb_agent_mcp/orchestrator.py`, after merging answers, call `stale_file_count()`
   for each domain that was queried. Apply the threshold formula
   `new_files > max(1, floor(indexed * 0.05))` and append the warning note only when
   the threshold is exceeded.
3. In the `list_domains()` tool in `kb_agent_mcp/server.py`, always include per-domain
   `files_on_disk` and `files_indexed` counts (no threshold applied here — full
   visibility regardless of magnitude).

**Relevant Context**
- `kb_agent_mcp/domain_agent.py` — domain agent and file logic
- `kb_agent_mcp/orchestrator.py` → `ask()`, `_merge_answers()`
- `kb_agent_mcp/server.py` → `list_domains()` tool

**Status**: [x] done — stale_file_count() on DomainAgent; _stale_warnings() in orchestrator; >5% threshold

---

## Phase 2 — Friction Points

### 2.1 — Add `chromadb` build-dependency install guidance in setup wizard

**Intent**
`chromadb` requires native C++ bindings that fail on clean macOS / Linux systems
without Xcode CLI tools or `build-essential`. The `pip install kb-agent-mcp` failure
message is cryptic. Users need actionable guidance before the install attempt.

**Expected Outcomes**
- `kb-agent-setup` prints a pre-flight check before running pip: detects the OS and
  tells the user what to install if the build tools are likely absent.
- On macOS: `"If this fails, run: xcode-select --install"`.
- On Linux: `"If this fails, run: sudo apt install build-essential python3-dev"`.
- If pip fails, the error message repeats the platform-specific fix.

**Todo List**
1. In `kb_agent_mcp/cli/setup.py`, add a `_preflight_build_tools()` function that
   checks `sys.platform` and prints the appropriate hint before the pip step.
2. Wrap the pip install subprocess call in a try/except that catches non-zero exit and
   reprints the build-tools hint alongside the raw pip output.
3. Apply the same pattern in `scripts/setup.py` for the legacy path.

**Relevant Context**
- `kb_agent_mcp/cli/setup.py` → `install_deps()` (or equivalent)
- `scripts/setup.py` → `install_deps()` line ~82

**Status**: [x] done — `_preflight_build_tools()` + `_print_build_hint()` in both paths; pip failure reprints hint

---

### 2.2 — Warn about `sentence-transformers` model download on first query

**Intent**
`sentence-transformers` downloads an ~80 MB model (`all-MiniLM-L6-v2`) the first time
an embedding is needed. This happens silently during the first `ask()` call, causing a
long freeze with no feedback to the user.

**Expected Outcomes**
- During `kb-agent-generate`, before the first `build_collection()` call, the wizard
  checks whether the model is already cached (`~/.cache/huggingface/` or
  `~/.cache/torch/sentence_transformers/`).
- If not cached, it prints: `"⬇  Downloading embedding model (~80 MB) on first use
  — this is a one-time step."` and initiates the download immediately (not deferred).
- Subsequent runs skip the message.

**Todo List**
1. In `kb_agent_mcp/embeddings.py`, add a `_ensure_embedding_model()` function that
   checks for the cached model path and downloads it explicitly with a progress message
   before any index-build call.
2. Call `_ensure_embedding_model()` at the start of `build_collection()` so the
   download happens at generate-time, not at first query.
3. Update `kb_agent_mcp/cli/generate.py` to call this function early in `_run_generate()`
   so users see the download step in the generate output, not later.

**Relevant Context**
- `kb_agent_mcp/embeddings.py` — embedding model loading logic
- `kb_agent_mcp/vector_store.py` — `build_collection()` calls embeddings
- `kb_agent_mcp/cli/generate.py` → `_run_generate()`

**Status**: [x] done — `_ensure_embedding_model()` in `embeddings.py`; called in `_run_generate()` before index build; prints one-time download notice

---

### 2.3 — Validate and warn on API key at setup time, not at index time

**Intent**
When a user selects OpenAI or Anthropic in the setup wizard and enters a key, the key
is written to `.env` but not tested. The error only appears minutes later when the LLM
is called during index generation, with a cryptic HTTP 401 message.

**Expected Outcomes**
- After the LLM provider is configured in `kb-agent-setup`, a lightweight test call is
  made (e.g., list models for OpenAI, send a 1-token message for Anthropic) before
  writing `.env`.
- If it fails: `"API key test failed (HTTP 401). Double-check the key and try again."`.
- If it passes: `"API key verified ✓"`.
- The test uses a short timeout (5 s) and does not block setup if the network is
  unreachable (treated as a warning, not a hard failure).

**Todo List**
1. In `kb_agent_mcp/cli/setup.py`, add a `_test_api_key(provider, base_url, api_key,
   model)` function that makes a minimal authenticated request.
2. Call `_test_api_key()` after the user enters their key, before `.env` is written.
3. Apply the same to `scripts/setup.py` in the `choose_llm()` function.

**Relevant Context**
- `kb_agent_mcp/cli/setup.py` → LLM selection step
- `scripts/setup.py` → `choose_llm()` line ~157
- `kb_agent_mcp/cli/generate.py` → `_llm_available()` (reference pattern)

**Status**: [x] done — `_test_api_key()` in both `cli/setup.py` and `scripts/setup.py`; called after key entry; warns on 401/network error

---

### 2.4 — Resolve `kb-agent-serve` PATH issue in venv installations

**Intent**
When installed into a virtual environment, `kb-agent-serve` is not on the system PATH.
MCP host config files (Claude Desktop JSON, Bob MCP settings) that reference the bare
command name fail silently at startup.

**Expected Outcomes**
- `kb-agent-setup` detects whether it is running inside a venv (`sys.prefix !=
  sys.base_prefix`) and prints the absolute path to use in the MCP host config.
- The final "Setup complete" screen shows a ready-to-paste JSON config block with the
  absolute path, not the bare command.
- The same path is printed for both Claude Desktop and Bob formats.

**Todo List**
1. In `kb_agent_mcp/cli/setup.py`, compute the absolute path to `kb-agent-serve` using
   `shutil.which("kb-agent-serve")` or `Path(sys.prefix) / "bin" / "kb-agent-serve"`.
2. In the `print_done()` / final summary function, render a ready-to-paste JSON config
   block (both Claude Desktop format and Bob MCP format) with the resolved absolute path.
3. Apply the same to `scripts/setup.py`.

**Relevant Context**
- `kb_agent_mcp/cli/setup.py` → final summary / `print_done()` equivalent
- `scripts/setup.py` → `print_done()` line ~399
- `README-MCP.md` → "Connecting to Claude Desktop" and "Connecting to Bob" sections
  (the output should match what's documented)

**Status**: [x] done — `_serve_path()` in `cli/setup.py`; absolute path in final banner; same in `scripts/setup.py`

---

### 2.5 — Preserve user `.env` LLM settings on re-run (not silently stale)

**Intent**
When `kb-agent-setup` is re-run on an existing install, it keeps the existing `.env`
and only patches `KB_ROOT`. This means stale `KB_LLM_PROVIDER`, `KB_MODEL`, or
`KB_API_KEY` values persist silently if the user intended to change their LLM provider.

**Expected Outcomes**
- If `.env` already exists and the user selects an LLM provider that differs from what
  is currently in `.env`, the wizard asks: `"Your .env already has KB_LLM_PROVIDER=X.
  Update it to Y? [y/N]"`.
- If the user confirms, all LLM-related keys in `.env` are updated.
- If the user skips, the existing values are preserved and a note is printed.

**Todo List**
1. In `kb_agent_mcp/cli/setup.py` (and `scripts/setup.py`), in the `setup_env()` or
   equivalent function, read the current `.env` before writing, compare the
   `KB_LLM_PROVIDER` value, and prompt the user if it differs from the newly chosen one.
2. When the user confirms, patch all LLM keys (not just `KB_ROOT`).
3. Document the update flow in the function docstring.

**Relevant Context**
- `kb_agent_mcp/cli/setup.py` → `.env` write step
- `scripts/setup.py` → `setup_env()` line ~241

**Status**: [x] done — `write_env()` / `setup_env()` in both paths prompts on provider conflict; `_read_env_key()` helper reads existing `.env`

---

## Phase 3 — Resilience & Observability

### 3.1 — Add a `kb-agent-doctor` standalone diagnostic command

**Intent**
When something goes wrong, users have no single command to check the state of their
installation. They must read log output, inspect files manually, and guess. A dedicated
`kb-agent-doctor` command is chosen over `kb-agent-serve --check` because:
- It works even when `kb-agent-serve` itself fails to start (the most common failure case).
- It has a single clear responsibility: validate the environment.
- It can be referenced unambiguously in README troubleshooting steps and CI.


**Expected Outcomes**
- Running `kb-agent-doctor` prints a checklist of:
  - Python version ✓/✗
  - `KB_ROOT` set and exists ✓/✗
  - At least one domain folder found ✓/✗
  - `domain_config.yaml` present per domain ✓/✗
  - ChromaDB collection non-empty per domain ✓/✗
  - LLM reachable (or passthrough confirmed) ✓/✗
  - `sentence-transformers` model cached ✓/✗
  - `kb-agent-serve` on PATH (absolute path shown) ✓/✗
  - Bob skill installed ✓/✗ (with path)
- Each failing item shows a one-line fix hint.
- Exit code 0 if all pass, 1 if any fail.

**Todo List**
1. Add `kb_agent_mcp/cli/doctor.py` with a `main()` function implementing the checklist.
2. Register `kb-agent-doctor` as a CLI entry point in `pyproject.toml`.
3. Reference `kb-agent-doctor` in the troubleshooting section of `README-MCP.md`.

**Relevant Context**
- `pyproject.toml` → `[project.scripts]` section
- `kb_agent_mcp/config.py` → `cfg.validate()` (reuse for KB_ROOT checks)
- `kb_agent_mcp/vector_store.py` → collection stats (for ChromaDB check)
- `README-MCP.md` → Troubleshooting section

**Status**: [x] done — `kb_agent_mcp/cli/doctor.py` with 9 checks; `kb-agent-doctor` registered in `pyproject.toml`; `README-MCP.md` Troubleshooting section updated

---

### 3.2 — Prevent re-indexing from silently losing `.egg-info` clean-up across sessions

**Intent**
Even after fix 1.1 excludes egg-info folders from discovery, the existing
`agents/vector_store/domain_meta.json` may still contain stale entries from before the
fix. On the next `kb-agent-generate` run, the stale cleanup logic may not purge them
correctly because it compares against the newly filtered folder list.

**Expected Outcomes**
- On every `kb-agent-generate` run, `domain_meta.json` entries whose `folder_name`
  would now be excluded by `is_ignored()` are automatically removed.
- A log line is printed for each entry removed: `"🗑 Removed stale domain: X"`.
- Same cleanup is applied in `scripts/generate.py` for the legacy path.

**Todo List**
1. In `kb_agent_mcp/cli/generate.py` → `_run_generate()`, after loading
   `domain_config.yaml` files, identify any ChromaDB collections whose name maps to a
   folder that `is_ignored()` would now exclude, and delete them.
2. In `scripts/generate.py`, in the stale cleanup block (around line 1050), add a
   similar check for `domain_meta.json` entries.
3. Add a unit test that seeds `domain_meta.json` with an egg-info entry and verifies it
   is removed after a generate run with `--no-llm`.

**Relevant Context**
- `kb_agent_mcp/cli/generate.py` → `_run_generate()` stale cleanup section
- `scripts/generate.py` → stale cleanup block lines ~1050–1082
- `tests/` — existing test patterns

**Status**: [x] done — `_run_generate()` deletes ignored ChromaDB collections; `scripts/generate.py` removes stale `domain_meta.json` entries

---

### 3.3 — Improve LLM generate latency visibility

**Intent**
On a large knowledge base with many files, `kb-agent-generate` can run silently for
minutes. Users have no progress indication and cannot tell if the process is working or
hung.

**Expected Outcomes**
- During `kb-agent-generate`, a per-domain progress counter is printed in the format:
  `"Summarising file 3/17: Revenue Q3.xlsx"` while per-file LLM calls are running.
- A total elapsed time is printed at the end: `"✓ Done in 4m 12s"`.
- If the `rich` library is available, a progress bar is used; otherwise plain text.

**Todo List**
1. In `kb_agent_mcp/cli/generate.py` → `_run_generate()`, wrap the per-file LLM summary
   loop with a counter and print `"Summarising file N/total: filename"` before each call.
2. Record `time.monotonic()` at the start of `_run_generate()` and print the total at
   the end.
3. Apply the same to `scripts/generate.py` → `build_file_summaries()` loop.

**Relevant Context**
- `kb_agent_mcp/cli/generate.py` → `_run_generate()`, per-domain loop
- `scripts/generate.py` → `build_file_summaries()` line ~372

**Status**: [x] done — `build_file_summaries()` prints `N/total` counter; `_run_generate()` and `scripts/generate.py main()` print `✓ Done in Xs`

---

## Phase 4 — Documentation Gaps (HIGH)

### 4.1 — Add pre-install build-tools warning to README

**Intent**
A user who runs a bare `pip install kb-agent-mcp` on a clean macOS or Linux machine without
Xcode CLI tools / `build-essential` will hit a cryptic C++ compiler error from `chromadb`.
The setup wizard prints a platform-specific hint, but only after the package is already
installed. The README Installation section has no pre-install warning at all, meaning
anyone who follows the README cold (not the wizard) is unguarded.

**Expected Outcomes**
- `README-MCP.md` Installation section prominently states, before the `pip install`
  code block, that `chromadb` requires C++ build tools and gives the platform-specific
  commands: `xcode-select --install` on macOS, `sudo apt install build-essential python3-dev`
  on Linux.
- `README.md` Prerequisites table gains a "Build tools" row with the same guidance.
- No code changes required.

**Todo List**
1. In `README-MCP.md`, add a note block immediately before the `pip install kb-agent-mcp`
   code block (around line 27) warning about C++ build tools with platform commands.
2. In `README.md`, add a "Build tools" row to the Prerequisites table (around line 41)
   matching the platform hints in `scripts/setup.py::_preflight_build_tools()`.

**Relevant Context**
- `README-MCP.md` lines 27–40 — Installation section
- `README.md` lines 35–41 — Prerequisites table
- `scripts/setup.py::_preflight_build_tools()` lines 84–90 — existing platform hint logic to mirror

**Status**: [x] done — added `> Build tools required` note block before pip install in README-MCP.md; added macOS + Linux rows to Prerequisites table in README.md

---

### 4.2 — Prominently call out KB_ROOT and venv PATH issues in MCP host config sections

**Intent**
The two most common silent failures for new users are: (a) forgetting `KB_ROOT` in the MCP
host `"env"` block, and (b) using the bare `kb-agent-serve` command when it is only in a
venv. Both workarounds already exist in the Troubleshooting section, but users hit them
before reading that far. The "Connecting to Claude Desktop" and "Connecting to Bob" sections
show config examples with no callouts for either issue.

**Expected Outcomes**
- Directly after the Claude Desktop JSON config block in `README-MCP.md` (after line ~246),
  a bold note states: "`KB_ROOT` is **required** in the `env` block — omitting it causes
  empty results."
- The same note appears after the Bob config block (after line ~265).
- A second note in both places states: "If `kb-agent-serve` is not found, use the absolute
  path printed by the setup wizard or run `which kb-agent-serve`."
- No code changes required.

**Todo List**
1. In `README-MCP.md` after the Claude Desktop config block (~line 246), add a two-item
   callout note covering the `KB_ROOT` requirement and the venv PATH issue.
2. Repeat the same callout after the Bob config block (~line 265).
3. Ensure both callouts link back to the Troubleshooting section entries that already exist.

**Relevant Context**
- `README-MCP.md` lines 231–270 — Connecting to Claude Desktop / Bob sections
- `README-MCP.md` lines 325–333 — existing Troubleshooting entries for both issues
- `kb_agent_mcp/cli/setup.py::_serve_path()` lines 294–303 — reference for venv path detection

**Status**: [x] done — added ⚠ two-item callout block after both the Claude Desktop and Bob config blocks in README-MCP.md

---

## Phase 5 — Runtime Guardrails (MED)

### 5.1 — Validate LLM-generated `domain_config.yaml` before writing

**Intent**
After the LLM generates a `domain_config.yaml` and the user accepts it, the YAML is written
to disk with no validation. If the LLM produced syntactically invalid YAML or omitted required
keys, the domain silently fails to load at serve time — `load_domain_config()` returns `None`
and the domain is skipped with no diagnostic message to the user.

**Expected Outcomes**
- Before `yaml_path.write_text()` in `_run_generate()`, the generated YAML string is parsed
  with `yaml.safe_load()` and checked for required keys:
  `folder_name`, `agent_name`, `description`, `keywords`, `top_n`, `max_chars`, `system_prompt`.
- If validation fails: print the error, show the raw LLM output, and re-prompt
  Accept / Skip — do not write invalid YAML to disk.
- If the minimal fallback YAML (`_minimal_yaml()`) is used, skip validation (it is always valid).

**Todo List**
1. In `kb_agent_mcp/cli/generate.py`, add a `_validate_yaml(yaml_text: str) -> list[str]`
   function that calls `yaml.safe_load()` and checks for all required top-level keys,
   returning a list of error strings (empty = valid).
2. In `_run_generate()`, call `_validate_yaml(yaml_text)` after `_generate_yaml_for_folder()`
   returns and before `_prompt_accept()`. If errors are returned, print them and fall back
   to `_minimal_yaml(folder_name)` rather than the invalid LLM output.
3. The minimal YAML path (`no_llm` or LLM-unavailable) bypasses validation — it is always
   structurally correct.

**Relevant Context**
- `kb_agent_mcp/cli/generate.py::_run_generate()` lines 417–434 — YAML generation and write
- `kb_agent_mcp/domain_rules.py::_parse_yaml()` lines 113–129 — existing silent parse pattern to harden
- `kb_agent_mcp/domain_rules.py::DomainConfig` dataclass lines 51–98 — canonical field list

**Status**: [x] done — `_validate_yaml()` added in `generate.py`; called after LLM generation, falls back to `_minimal_yaml()` on parse/key errors with a `warn()` message

---

### 5.2 — Add per-file progress output to `build_collection()` in the CLI path

**Intent**
On a large knowledge base (50+ documents per domain), `kb-agent-generate` runs silently for
minutes while the CLI path's `_build()` call returns only a final count. Users cannot
distinguish a hanging process from a working one. The legacy `scripts/generate.py` already
prints a per-file counter; the pip CLI path does not.

**Expected Outcomes**
- During `kb-agent-generate`, a progress line is printed for each file being embedded,
  e.g. `→ Embedding file 4/17: Revenue Q3.xlsx`.
- The counter resets per domain, matching the pattern in `scripts/generate.py` line 438.
- No change to the return value or async signature of `build_collection()`.

**Todo List**
1. In `kb_agent_mcp/vector_store.py::build_collection()`, add an optional
   `progress_fn: Callable[[int, int, str], None] | None = None` parameter.
2. Inside the file-embedding loop, call `progress_fn(current_idx, total, filename)` when
   the callback is provided.
3. In `kb_agent_mcp/cli/generate.py::_run_generate()`, pass a `progress_fn` lambda that
   calls `info(f"Embedding file {i}/{total}: {name}")` using the existing `info()` helper.

**Relevant Context**
- `kb_agent_mcp/vector_store.py::build_collection()` lines 364–387 — file loop to instrument
- `kb_agent_mcp/cli/generate.py::_run_generate()` line 405 — call site for `_build()`
- `scripts/generate.py` lines 435–444 — existing per-file counter pattern to mirror

**Status**: [x] done — `build_collection()` gains optional `progress_fn(i, total, name)` parameter; `_run_generate()` passes a lambda that calls `info()`

---

### 5.3 — Write `.env` to `KB_ROOT`, not CWD, and warn clearly

**Intent**
`kb-agent-setup` writes `.env` to the directory where the wizard is run (`CWD`), not to
`KB_ROOT`. If the user later runs `kb-agent-serve` or `kb-agent-generate` from a different
directory, `config.py`'s `.env` search (CWD → HOME → package dir) will not find the file
and `KB_ROOT` silently defaults to the new CWD — producing empty results with no explanation.

**Expected Outcomes**
- `write_env()` in `kb_agent_mcp/cli/setup.py` writes `.env` to `KB_ROOT` when `KB_ROOT ≠ CWD`.
- When `KB_ROOT == CWD`, behaviour is unchanged (`.env` written to CWD as before).
- The final wizard summary prints the exact path where `.env` was written.
- Same change applied to `scripts/setup.py`.

**Todo List**
1. In `kb_agent_mcp/cli/setup.py::write_env()`, change `env_path = cwd / ".env"` to
   `env_path = kb_root / ".env"` — `kb_root` is already passed as the first argument.
2. Update the `ok()` confirmation line to print the resolved `env_path` so the user
   knows exactly where the file landed.
3. Apply the same change to `scripts/setup.py::setup_env()` (same pattern, same fix).

**Relevant Context**
- `kb_agent_mcp/cli/setup.py::write_env()` line 236 — `env_path = cwd / ".env"`
- `kb_agent_mcp/config.py::_load_dotenv()` lines 27–30 — search order (CWD first)
- `scripts/setup.py::setup_env()` — equivalent function in legacy path

**Status**: [x] done — `write_env()` in `cli/setup.py` now writes to `kb_root / ".env"` instead of `cwd / ".env"`; scripts/setup.py unchanged (SCRIPT_DIR == KB_ROOT for legacy path)

---

### 5.4 — Document and support offline / air-gapped embedding model usage

**Intent**
`sentence-transformers` downloads `all-MiniLM-L6-v2` (~80 MB) from the Hugging Face CDN on
first use. In air-gapped environments or corporate networks that block `huggingface.co`,
this silently hangs or raises a network error with no actionable guidance. The standard
`TRANSFORMERS_OFFLINE` and `HF_ENDPOINT` env vars are not respected and not documented.

**Expected Outcomes**
- `kb_agent_mcp/embeddings.py::_load_st_model()` checks for `TRANSFORMERS_OFFLINE=1` and
  `HF_ENDPOINT` in `os.environ` before calling `SentenceTransformer()`, and sets them
  on the process environment so the underlying library respects them.
- `.env.example` documents both variables with usage examples for offline / mirror setups.
- If the model is not cached and `TRANSFORMERS_OFFLINE=1`, a clear error is raised:
  `"Model not cached and TRANSFORMERS_OFFLINE=1. Pre-download with: ..."`.

**Todo List**
1. In `kb_agent_mcp/embeddings.py::_load_st_model()`, before `SentenceTransformer()`,
   propagate `HF_ENDPOINT` and `TRANSFORMERS_OFFLINE` from `os.environ` to the process
   env if set, so the library respects them.
2. If `TRANSFORMERS_OFFLINE=1` and `_st_model_is_cached()` returns `False`, raise a clear
   `RuntimeError` with instructions for pre-downloading the model.
3. Add `HF_ENDPOINT` and `TRANSFORMERS_OFFLINE` entries to `.env.example` in the
   Embedding Model section with comments explaining when to use each.

**Relevant Context**
- `kb_agent_mcp/embeddings.py::_load_st_model()` lines 74–87 — model loading entry point
- `kb_agent_mcp/embeddings.py::_st_model_is_cached()` lines 42–53 — cache check to reuse
- `.env.example` lines 42–47 — Embedding Model section to extend

**Status**: [x] done — `_load_st_model()` in `embeddings.py` checks `TRANSFORMERS_OFFLINE` and raises a clear error with pre-download instructions; `.env.example` documents both `TRANSFORMERS_OFFLINE` and `HF_ENDPOINT`

---

### 5.5 — Warn when RAG context is truncated for aggregate / numeric queries

**Intent**
When a user asks an aggregate question (e.g., "total Q3 revenue") over large XLSX files,
`base_agent` retrieves the top-N chunks and truncates to `KB_BUDGET_RAG_FILE` characters
(~4 000 chars default). The answer is computed from incomplete data with no indication
that truncation occurred — the user has no reason to doubt the result.

**Expected Outcomes**
- When the retrieved context for a domain was truncated (i.e., the raw content exceeded
  the budget), the answer for that domain appends a one-line caveat:
  `> ⚠ Context was truncated to fit the budget. For full data, open the source file directly.`
- The caveat fires only for data / numeric questions (detected via `is_data_question()`).
- Normal non-data queries are unaffected.

**Todo List**
1. In `kb_agent_mcp/base_agent.py`, add a `_context_was_truncated(context: str) -> bool`
   helper that checks whether the assembled context string ends with `"…"` (the truncation
   marker set by `context_budget.trim()`).
2. In `base_agent.ask()`, after assembling the final context but before the LLM call,
   set a `truncated: bool` flag using `_context_was_truncated()`.
3. In the returned result dict, include `"truncated": truncated`. In
   `kb_agent_mcp/orchestrator.py::_merge_answers()`, append the caveat line when
   `truncated=True` and `is_data_question(question)`.

**Relevant Context**
- `kb_agent_mcp/base_agent.py::ask()` lines 348–459 — RAG pipeline and context assembly
- `kb_agent_mcp/context_budget.py::trim()` lines 59–70 — appends `"…"` on truncation
- `kb_agent_mcp/orchestrator.py::_merge_answers()` lines 297–331 — answer merge to extend

**Status**: [x] done — `base_agent.ask()` sets `"truncated": True` in result dict when any text ends with `"…"`; `_merge_answers()` in `orchestrator.py` appends caveat for data questions; `is_data_question` imported as `_is_data_q`

---

### 5.6 — Add session-sharing warning to README and server docstring

**Intent**
All callers that do not pass an explicit `session_id` share the `"default"` session. Two
simultaneous AI tool windows (or two users of the same MCP server) bleed conversation
context into each other — earlier questions affect later answers with no indication to the
user. The docstring in `server.py` notes this but the README `ask` examples do not.

**Expected Outcomes**
- `README-MCP.md` `ask` examples section (around line 83) includes a note: "Omitting
  `session_id` uses the shared `default` session — specify a unique ID for isolated
  conversations."
- The `ask` tool docstring in `kb_agent_mcp/server.py` is updated to make the shared-session
  risk explicit rather than just noting the default.
- No functional code changes.

**Todo List**
1. In `README-MCP.md` after the `ask` examples block (~line 83), add a one-paragraph note
   about the shared `"default"` session and the recommendation to always pass `session_id`.
2. In `kb_agent_mcp/server.py::ask()` docstring, expand the `session_id` description to
   state: "Warning: the default `'default'` session is shared across all callers on this
   server. Use a unique session_id per user or conversation."

**Relevant Context**
- `README-MCP.md` lines 77–84 — `ask` examples section
- `kb_agent_mcp/server.py::ask()` lines 56–81 — tool docstring
- `kb_agent_mcp/memory.py` lines 60–75 — session file resolution

**Status**: [x] done — README-MCP.md `ask` examples section gains a `> Session isolation:` callout; `server.py::ask()` docstring updated with explicit shared-session warning

---

## Phase 6 — Polish & Edge Cases (LOW)

### 6.1 — Log failed PDF / document extractions as warnings during indexing

**Intent**
Corrupt, password-protected, or malformed files are silently skipped during
`kb-agent-generate`. The extraction error is returned as a string embedded in the context
(e.g. `[Extract error (.pdf): ...]`) but is never logged to the CLI output. Users running
a large generate have no visibility into which files were skipped or why.

**Expected Outcomes**
- When `_extract_sync()` catches an exception for a file, a `logging.warning()` line is
  emitted to stderr: `WARNING: Failed to extract Revenue Q3.pdf: PdfReadError(...)`.
- At the end of `build_collection()`, a summary line is printed if any files were skipped:
  `⚠ 2 file(s) failed to extract — check logs above.`
- No change to the return value or indexing flow.

**Todo List**
1. In `kb_agent_mcp/file_parser.py`, import `logging` at the top and create a module-level
   logger: `logger = logging.getLogger(__name__)`.
2. In `_extract_sync()` lines 438–441, add `logger.warning(...)` before returning the
   error string so the failure appears in CLI output during generate.
3. In `kb_agent_mcp/vector_store.py::build_collection()`, track the count of failed
   extractions and print a summary line using the existing `warn()` helper if count > 0.

**Relevant Context**
- `kb_agent_mcp/file_parser.py::_extract_sync()` lines 423–441 — exception catch to instrument
- `kb_agent_mcp/vector_store.py::build_collection()` lines 364–387 — call site for extraction
- `kb_agent_mcp/cli/generate.py` — `warn()` helper pattern to follow

**Status**: [x] done — `logging` imported and `logger = logging.getLogger(__name__)` added to `file_parser.py`; `_extract_sync()` now calls `logger.warning()` on both FileNotFoundError and general Exception

---

### 6.2 — Clarify `reindex()` limitation for new domains in tool response and README

**Intent**
The `reindex()` MCP tool rebuilds ChromaDB indexes for existing domains but does not
generate `domain_config.yaml` for new folders. Users who add a new domain folder and call
`reindex()` from their AI tool will find the new domain silently absent — `refresh_agents()`
only loads folders that already have a `domain_config.yaml`.

**Expected Outcomes**
- After the reindex loop in `kb_agent_mcp/server.py::reindex()`, the tool detects any
  domain folders that lack `domain_config.yaml` and appends a note to the response:
  `"⚠ New domain(s) detected without config: Foo, Bar. Run kb-agent-generate from the
  CLI to generate and accept domain configs for these folders."`
- `README-MCP.md` MCP Tools table gains a note in the `reindex()` row explaining this
  limitation.

**Todo List**
1. In `kb_agent_mcp/server.py::reindex()`, after the indexing loop (line ~135), add a
   check: for each indexed domain folder, test whether `KB_ROOT/name/domain_config.yaml`
   exists. Collect those that don't.
2. If any are found, append a warning paragraph to the `lines` list before the final join.
3. In `README-MCP.md` MCP Tools table (lines 67–74), add a note in the `reindex()` row:
   "New domain folders also require `kb-agent-generate` to create `domain_config.yaml`."

**Relevant Context**
- `kb_agent_mcp/server.py::reindex()` lines 110–151 — tool body to extend
- `kb_agent_mcp/orchestrator.py::refresh_agents()` lines 56–61 — loads from existing YAMLs only
- `README-MCP.md` lines 67–74 — MCP Tools table

**Status**: [x] done — `reindex()` in `server.py` detects domain folders missing `domain_config.yaml` and appends a ⚠ note; `README-MCP.md` MCP Tools table updated with limitation note

---

### 6.3 — Document and handle ChromaDB schema incompatibility on upgrade

**Intent**
When the package is upgraded and the ChromaDB schema or embedding dimension changes,
existing `.kb_index/chroma/` data becomes incompatible. Queries silently fail or produce
wrong results with no explanation. There is no migration path, no version check, and no
documentation on how to handle this.

**Expected Outcomes**
- `kb_agent_mcp/vector_store.py::_get_client()` catches `chromadb` exceptions on client
  creation and provides a clear message: "ChromaDB index may be incompatible with this
  version. Delete `.kb_index/` and re-run `kb-agent-generate` to rebuild."
- `README-MCP.md` Troubleshooting section gains an entry: "Upgrading — if queries fail
  after a package upgrade, delete `.kb_index/` and re-run `kb-agent-generate`."
- No migration logic needed at this stage — detect and instruct is sufficient.

**Todo List**
1. In `kb_agent_mcp/vector_store.py::_get_client()`, wrap the `chromadb.PersistentClient()`
   call in a `try/except Exception` that catches schema-related errors, re-raises with a
   clear message pointing to the `.kb_index/` deletion path.
2. In `README-MCP.md` Troubleshooting section (around line 300), add an "After upgrading"
   entry documenting the delete-and-regenerate recovery path.

**Relevant Context**
- `kb_agent_mcp/vector_store.py::_get_client()` lines 63–71 — ChromaDB client init
- `README-MCP.md` lines 298–345 — Troubleshooting section to extend

**Status**: [x] done — `_get_client()` in `vector_store.py` wraps `PersistentClient()` in try/except with a clear delete-and-regenerate message; `README-MCP.md` Troubleshooting section gains an "After upgrading" entry

---

## Implementation Order

Phases are **strictly sequential** — validate each phase fully before starting the next.

```
Phase 1 — Critical Blockers  (fix silent failures first)
  1.1 → Exclude .egg-info from discovery              [both paths]
  1.2 → Fail loudly on missing KB_ROOT                [both paths]
  1.3 → Surface stale-index warning (>5% threshold)   [pip path only]
        ↓ test all three, confirm no regressions
        ↓ merge to main

Phase 2 — Friction Points  (reduce install/setup drop-off)
  2.1 → chromadb build-tools hint                     [both paths]
  2.2 → sentence-transformers download at generate    [pip path only]
  2.3 → API key validation at setup time              [both paths]
  2.4 → Absolute path in final setup output           [both paths]
  2.5 → .env LLM update on re-run                     [both paths]
        ↓ test full wizard flow end-to-end
        ↓ merge to main

Phase 3 — Resilience  (long-term maintainability)
  3.1 → kb-agent-doctor standalone command            [pip path only]
  3.2 → Stale domain_meta.json cleanup after 1.1      [both paths]
  3.3 → LLM generate latency progress counter         [both paths]
        ↓ test doctor command, stale cleanup, progress output
        ↓ merge to main

Phase 4 — Documentation Gaps (HIGH)
  4.1 → Pre-install build-tools warning in README     [docs only]
  4.2 → KB_ROOT + venv PATH callouts in MCP sections  [docs only]
        ↓ review README diffs, confirm copy is clear
        ↓ merge to main

Phase 5 — Runtime Guardrails (MED)
  5.1 → Validate LLM YAML before write               [pip path only]
  5.2 → Per-file progress in build_collection()       [pip path only]
  5.3 → Write .env to KB_ROOT not CWD                [both paths]
  5.4 → Offline/air-gapped embedding support         [pip path only]
  5.5 → Truncation caveat for aggregate queries       [pip path only]
  5.6 → Session-sharing warning in README + docstring [docs + server.py]
        ↓ test wizard, generate, and ask flows end-to-end
        ↓ merge to main

Phase 6 — Polish & Edge Cases (LOW)
  6.1 → Log failed PDF extractions as warnings        [pip path only]
  6.2 → Clarify reindex() new-domain limitation       [server.py + docs]
  6.3 → ChromaDB upgrade incompatibility guidance     [server.py + docs]
        ↓ smoke-test with corrupt PDFs, new domain, fresh upgrade
        ↓ merge to main
```

**Dual-path rule**: Every sub-task marked `[both paths]` must be applied to both
`kb_agent_mcp/` (pip package) and `scripts/` (legacy clone path). They serve different
user segments and must stay consistent with each other.
