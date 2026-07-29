# Architecture: kb-agent-mcp

This document describes the internal structure of the `kb-agent-mcp` package.
It covers every module, the two main pipelines (setup and query), and the data flows between them.

---

## System overview

![kb-agent-mcp routing diagram](architecture%20flow%20diagram.png)

*User question → Router agent splits into: Doc question (sub-agent → Vector index) or Data question (Data Analyst ✨ NEW → Schema Inspector + Query Engine → Raw files / Answer + Reasoning)*

---

## Package layout

```
kb_agent_mcp/
├── server.py            MCP server — exposes 9 tools via FastMCP
├── orchestrator.py      Top-level query pipeline: route → dispatch → merge
├── domain_agent.py      Per-domain RAG wrapper
├── base_agent.py        README-first RAG pipeline + LLM calls
├── vector_store.py      ChromaDB client, upsert, search, metadata
├── embeddings.py        Embedding backends with fallback chain
├── file_parser.py       Multi-format text extractor
├── domain_rules.py      domain_config.yaml loader + retrieval rule application
├── memory.py            Multi-session conversation memory (disk-persisted JSON)
├── context_budget.py    Character budget registry + context compaction engine
├── config.py            Configuration singleton (env vars + .env file)
├── analyst/             Data Analyst capability add-on (live file computation)
│   ├── __init__.py      Exposes 4 entry points consumed by server.py
│   ├── inspector.py     Schema profiler → DataCard (columns, types, grain, themes)
│   ├── planner.py       DataCard → themed analytical question menu
│   ├── engine.py        Query engine: clarify → load → compute → answer + reasoning
│   └── session.py       Analyst session state (separate from KB conversation memory)
└── cli/
    ├── main.py          Unified `kb-agent` root command (dispatches all subcommands)
    ├── setup.py         Interactive setup wizard (kb-agent-setup / kb-agent setup)
    ├── generate.py      Index builder + domain YAML generator (kb-agent-generate / kb-agent generate)
    ├── watch.py         Filesystem watcher (kb-agent-watch / kb-agent watch)
    ├── doctor.py        Health checklist with auto-fix (kb-agent-doctor / kb-agent doctor)
    └── status.py        Per-domain status table (kb-agent-status / kb-agent status)

scripts/
└── setup.py             Compatibility shim → delegates to kb_agent_mcp.cli.setup
```

---

## Module responsibilities

### `config.py`
A frozen dataclass (`Config`) that reads every tunable value from environment
variables (or a `.env` file auto-discovered in CWD → `$HOME` → `KB_ROOT`).
Exposes derived paths (`kb_root_path`, `kb_index_path`, `session_memory_path`)
and a `validate()` method used at server startup and by the CLI.
A module-level singleton `cfg` is imported everywhere else.

### `server.py`
The FastMCP application. Registers nine MCP tools:

| Tool | What it does |
|---|---|
| `ask` | Full query pipeline via `orchestrator.ask()` |
| `list_domains` | Returns indexed domain names and descriptions |
| `reindex` | Rebuilds ChromaDB collections for all domains |
| `clear_memory` | Deletes a session's conversation history |
| `show_memory` | Returns a session's turn history |
| `analyze_file` | Profiles any file; returns a DataCard (JSON) |
| `suggest_questions` | Returns themed analytical questions for a file |
| `query_data` | Asks clarifying questions then computes answer + reasoning |
| `refine_query` | Re-runs the last query with updated params from user feedback |

The five core tools delegate to `orchestrator.ask()`. The four analyst tools
delegate to `kb_agent_mcp.analyst` and are self-contained (no ChromaDB, no
vector index — raw file computation only).

Also owns the stale-index TTL cache: a lightweight mtime scan runs at most
once per `KB_STALE_CHECK_TTL_SECONDS` seconds and prepends a `⚠` banner to
answers when new files are detected. At startup, validates `KB_ROOT` and the
ChromaDB client; exits immediately with a human-readable error if either fails.

### `orchestrator.py`
Coordinates the full query pipeline for every `ask()` call:

1. **Format intent detection** — regex phrases in the question (`"as a table"`,
   `"in bullet points"`) are mapped to explicit format instructions passed to
   every domain agent.
2. **Keyword pre-filter** — each `DomainAgent`'s keyword list is scored against
   the question. A confident match (≥2 hits in one domain, or 3× lead over
   others) skips the LLM classifier entirely.
3. **LLM intent classifier** — when keyword routing is ambiguous, an LLM call
   returns a JSON `{ domains, needs_clarification, clarification_question }`.
   In passthrough mode, keyword matching is used as a fallback (no LLM
   available for routing).
4. **Passthrough budget check** — before dispatch, estimates total context size
   (`n_domains × top_n × max_chars`) against `KB_BUDGET_PASSTHROUGH_THRESHOLD`.
   Reduces `top_n` if the estimate would overflow, and emits a warning in the
   response.
5. **Parallel dispatch** — calls `DomainAgent.run()` for each selected domain
   concurrently via `asyncio.gather()`.
6. **Answer merge** — if a single domain matched, returns its answer directly.
   Multiple domains are joined with `---` separators. Passthrough blocks are
   unwrapped into clean markdown with an instruction header for the host AI.
7. **Memory persistence** — the question + answer are appended to the session
   file (sync disk write, negligible latency).

### `domain_agent.py`
A thin per-domain wrapper around `base_agent.ask()`. On each `run()` call:

- Resolves `effective_top_n` (may be overridden by orchestrator for budget control).
- Checks whether the question matches domain-specific `data_patterns` or the
  global `is_data_question()` classifier; if so, bypasses README-first and calls
  `_pre_rank()` first (vector search + pin/boost rules).
- Otherwise delegates directly to `base_agent.ask()`.
- `stale_file_count()` does a cheap `rglob` + ChromaDB `count()` comparison to
  feed the orchestrator's stale-index warning.

### `base_agent.py`
The README-first RAG pipeline. For each domain:

**Strategy 1 — README-first:**
- Looks for a README (`.md` file in the domain folder, priority cascade).
  Result is cached in `_README_CACHE` (5-min TTL via `_get_readme_cached()`) — the
  filesystem is not re-read on every query.
- Simple question → extracts the `<!-- KB:AUTO-INDEX:START -->` block and
  the pre-index intro; compacts them via `context_budget.build_context()`.
- Complex question (matches `_COMPLEX_QUESTION_RE`) → uses the full README
  up to `KB_BUDGET_FULL_README` chars.
- Data question (matches `_DATA_QUESTION_RE`) → skips README entirely.

**Strategy 2 — Raw-file RAG fallback:**
- Used when README is absent/thin, or the question is a data query.
- Calls `vector_store.search()` for top-N results.
- Extracts text from each matched file concurrently via `file_parser.extract()`.
- Assembles a context block with source labels and relevance scores.

In both strategies, if `is_passthrough()` is true, a structured
`<<<KB_PASSTHROUGH>>>…<<<KB_PASSTHROUGH_END>>>` block is returned instead of
an LLM answer. The orchestrator unwraps this into readable markdown.

Also owns all LLM call implementations (Ollama, OpenAI-compatible, Anthropic),
and the `is_passthrough()` cache (checked once per process against Ollama;
reset by `reindex()`).

All outbound HTTP calls (LLM providers) reuse a shared `httpx.Client` singleton
returned by `_get_http_client()`. The client is created once per process with
connection pooling, saving 100–500 ms per call compared to a per-request client.

### `vector_store.py`
ChromaDB persistence layer. One collection per domain, stored under
`{KB_ROOT}/.kb_index/chroma/`. Each file is stored with its MD5 hash;
`_upsert_file_sync()` skips files whose hash hasn't changed (incremental
indexing). Embeddings are computed via `embeddings._embed_sync()`.

Embedding calls are deduplicated by a 128-entry SHA-1-keyed LRU cache
(`_embed_cache` / `_embed_cached()`): the same query text is never re-embedded
within a process lifetime.

Search uses `col.query(n_results=top_n)` — ChromaDB's native ANN retrieval.
This is faster and avoids loading the entire collection into memory. A full-scan
fallback (sklearn `cosine_similarity` over all embeddings) is retained and
triggered only when `col.query()` raises an exception.
Falls back to keyword matching if embeddings are missing entirely.

`set_domain_metadata()` / `get_domain_metadata()` store domain config and two
timestamps as ChromaDB collection metadata (flat key-value, JSON-serialised for
lists/dicts):

- `indexed_at` — Unix float; used by the server's stale-index TTL cache to
  compare against file `mtime` values.
- `indexed_at_iso` — ISO 8601 string (timezone-aware); used by `kb-agent-status`
  and `kb-agent-doctor` for human-readable age display.

Both keys are written together by `build_collection()`. Old indexes that predate
this change only have `indexed_at`; the CLI tools fall back to converting it.

### `embeddings.py`
Embedding backend with a three-tier fallback chain:

1. **Configured provider** (Ollama `/api/embeddings`, OpenAI-compatible
   `/embeddings`) — used when `KB_LLM_PROVIDER` is `ollama`, `openai`,
   `anthropic`, or `custom`.
2. **sentence-transformers** (`all-MiniLM-L6-v2`, ~80 MB, 384-dim) — used
   directly when `KB_LLM_PROVIDER=passthrough`, or as a fallback when the
   primary provider is unreachable and `KB_PASSTHROUGH_FALLBACK=true`.

`_st_model_is_cached()` checks both the HuggingFace hub cache and the legacy
torch cache before attempting a download. `_ensure_embedding_model()` is called
at generate-time to front-load the download with a visible progress message.

When `TRANSFORMERS_OFFLINE=1` is set and the model is not cached, a clear
`RuntimeError` is raised with pre-cache instructions rather than hanging.

### `file_parser.py`
Synchronous text extractors (run in thread pool via `asyncio.to_thread()`):

| Format | Extractor |
|---|---|
| `.txt` `.md` `.csv` | UTF-8 read |
| `.docx` | XML extraction from zip (`word/document.xml`) |
| `.pdf` | `pypdf` page iteration |
| `.pptx` `.ppt` | `python-pptx` shape text |
| `.xlsx` `.xls` < 50 MB | `openpyxl` with smart aggregation for sheets > 200 rows |
| `.xlsx` `.xls` ≥ 50 MB | Streaming XML `iterparse` — never loads full workbook |
| `.boxnote` | Recursive JSON tree walk |

Large XLSX files use a streaming aggregation strategy: the sheet is walked once
with `iterparse`, numeric columns are summed by detected group-by dimensions
(product, geography, quarter, etc.), and a compact markdown summary is returned
instead of raw rows. This keeps context tokens small while preserving all
analytically relevant information.

### `domain_rules.py`
Loads and validates `domain_config.yaml` for each knowledge folder into a
`DomainConfig` dataclass. Compiles `data_patterns` and `complex_patterns` as
`re.Pattern` objects on first use (lazy). Applies `pin_files` (glob-forced
inclusion) and `boost_keywords` (filename-based sort boost) to vector search
results via `apply_pin_rules()`.

### `memory.py`
Session memory with an in-memory cache layer. Each session is persisted as a
JSON file at `{KB_ROOT}/.kb_index/session_memory/<session_id>.json` containing
a message list and a `last_active` timestamp.

An in-process `_SESSION_CACHE` dict (5-min TTL) acts as a first-read layer:
`_load_sync()` returns the cached value on warm reads and only hits disk on cold
start or after the TTL expires. `_save_sync()` writes to both cache and disk.
This avoids repeated disk I/O for sessions that receive multiple turns in quick
succession.

Sessions expire automatically after `KB_SESSION_TIMEOUT_HOURS` hours of
inactivity. Only the last `KB_SESSION_MAX_TURNS` turns are retained; assistant
answers are truncated to `KB_SESSION_MAX_ANSWER_CHARS` before storage (the full
answer was already returned to the caller).

### `analyst/` — Data Analyst capability add-on

A self-contained sub-package that enables **live computation** over raw files.
It does not use the vector index; it loads actual file data and aggregates,
filters, or compares it to answer data questions that RAG cannot handle.

**`analyst/inspector.py`** — Schema profiler

Reads any supported file and returns a `DataCard`: a structured description of
columns, data types, grain (what one row represents), data themes, and quality
warnings. Column classification (`metric`, `id`, `entity`, `time`,
`categorical`, `text`) is driven by name-hint dictionaries and value statistics
(numeric ratio, cardinality). Large XLSX files use a sparse-row cell-reference
parser (handles files > 50 MB without loading the full workbook). DataCards are
cached per `(path, mtime)` with a 5-minute TTL — repeated calls do not re-read
the file.

**`analyst/planner.py`** — Question planner

Takes a `DataCard` and returns a `QuestionMenu`: a dict keyed by theme
(`revenue`, `attrition`, `growth`, `concentration`, `anomaly`, `summary`,
`document`). Each question carries a `clarifications` list — the parameters
that must be collected before the computation can run. The planner is pure logic
(no I/O) and intentionally over-inclusive: it suggests everything the data
*could* answer.

**`analyst/engine.py`** — Query engine

`query_data(path, question, session_id)`:

1. Calls `inspect_file()` to get or retrieve the cached `DataCard`.
2. Calls `_needs_clarification()` — checks for metric ambiguity and unknown
   time ranges; returns clarifying questions if any params are missing.
3. Loads the file into `list[dict]` using `_load_rows()` (supports xlsx, csv,
   json/jsonl; handles sparse-row xlsx encoding).
4. Applies time and entity filters, then calls `_build_answer()`.
5. `_build_answer()` dispatches to the right computation branch based on
   keywords in the question: attrition pivot, total/sum, top-N ranking,
   group-by breakdown, or summary/data quality.
6. Returns a structured dict: `{status, session_id, answer, reasoning, suggested_followups}`.

`refine_query(session_id, feedback)` parses free-text feedback, updates
`sess.params` (time range, metric column, top_n, pending clarification
answers), then re-runs `query_data()` against the same file and original
question.

**`analyst/session.py`** — Analyst session state

Separate from `memory.py`. Stores file path, DataCard, original question,
collected params, pending clarifications, last answer/reasoning, and a rolling
20-turn conversation window. Persisted as JSON under
`{KB_ROOT}/.kb_index/analyst_sessions/<session_id>.json`. Uses the same
in-memory 5-minute TTL cache pattern as `memory.py`.

### `context_budget.py`
Central registry of all character budgets (read from `cfg`). Provides:
- `trim(text, key)` — hard-trim with newline-aware cut point.
- `compact_index_block(block)` — strips boilerplate headings, normalises
  multi-column tables to two columns (File | Summary), collapses repeated-
  version file groups, truncates per-row summaries.
- `build_context(pre_index, index_block)` — assembles the compacted README
  context for simple questions.
- `COLLAPSE_RULES` — extensible via `KB_COLLAPSE_PATTERNS` env var.

---

## Module responsibilities (CLI)

### `cli/main.py`
Unified entry point (`kb-agent`). Parses the first positional argument as a
subcommand and delegates to the appropriate CLI module in-process (no subprocess
fork). Registered subcommands: `init`, `setup`, `generate`, `serve`, `watch`,
`doctor`, `status`.

`kb-agent init` is the recommended first-time path: it calls `run_setup()`,
`run_generate()`, and `run_doctor()` in sequence within a single process, giving
the user a guided setup → index-build → health-check flow in one command.

### `cli/setup.py`
The canonical interactive setup wizard (`kb-agent-setup`). Guides a new user through:
Python check → build-tools pre-flight → venv recommendation → KB_ROOT selection →
LLM configuration (two-question design: Q&A mode + optional API key for generate) →
`.env` write → `kb-agent-generate` invocation → interactive keyword editor for domains
that received minimal YAML (no LLM available during generate).

`scripts/setup.py` at the repo root is a **thin shim** (~12 lines) that delegates
entirely to this module via `python -m kb_agent_mcp.cli.setup`. It exists only for
backward compatibility with cloned-repo users and the `knowledgebase-install` skill.

### `cli/generate.py`
Index builder and domain YAML generator (`kb-agent-generate`). Discovers top-level
knowledge folders, upserts changed files into ChromaDB (hash-delta incremental), calls
the configured LLM to generate `domain_config.yaml`, validates the output, and installs
the Bob skill. Flags: `--force`, `--no-llm`, `--domain <name>`, `--yes`.

### `cli/watch.py`
Filesystem watcher (`kb-agent-watch`). Backed by `watchdog`, debounced at 5 s. Handles:
file add/modify/delete → upsert/delete from ChromaDB; new top-level folder → trigger
generate flow; folder deleted → purge collection. `--no-prompt` auto-accepts new domains
for CI/headless use.

### `cli/doctor.py`
Health checklist (`kb-agent-doctor`). Runs 9 checks and prints a `✓`/`✗`/`⚠` report.
Exit code 0 = healthy, 1 = failures remain.

Each check returns a `CheckResult(label, passed, fix_fn)` NamedTuple. When `--fix` is
passed, the doctor calls `fix_fn()` for every failing check that has one, then re-runs
all checks to show the final state. Auto-fixable failures:

| Failure | Auto-fix |
|---|---|
| KB_ROOT directory missing | `mkdir -p` the path |
| `domain_config.yaml` missing | `kb-agent-generate --domain <name> --no-llm --yes` |
| ChromaDB index empty | `kb-agent-generate --domain <name> --no-llm --yes` |
| ChromaDB version mismatch | prompt → `rm -rf .kb_index/chroma/` + full generate |
| Embedding model not cached | `_ensure_embedding_model()` (downloads ~80 MB) |
| Bob skill not installed | `kb-agent-generate --no-llm --yes` |

Non-auto-fixable (printed with manual hint): unset `KB_ROOT` env var, LLM server
unreachable, `kb-agent-serve` not on PATH.

### `cli/status.py`
Read-only status dashboard (`kb-agent-status`). Collects per-domain data from
ChromaDB and the filesystem and renders a Rich table. Zero side effects — safe to run
at any time.

| Column | Source |
|---|---|
| Domain | `kb_root.iterdir()` filtered by `cfg.is_ignored()` |
| Files | `rglob` count of indexable extensions |
| Indexed | `indexed_at_iso` from ChromaDB metadata (falls back to `indexed_at` float for old indexes) |
| Docs | `col.count()` — ChromaDB document count |
| YAML | presence of `domain_config.yaml` |
| Status | fresh / stale (>7 d) / empty index / DB mismatch |

Footer shows: LLM provider, embedding model (cached/not), absolute `kb-agent-serve`
path, Bob skill presence.

Flags:
- `--json` — machine-readable JSON (scriptable)
- `--plain` — no ANSI colours (CI/log capture)
- `--tui` — live-refresh with `rich.live.Live` (Ctrl+C to quit)
- `--interval N` — refresh interval in seconds for `--tui` (default: 5)

---

## Setup pipeline (`kb-agent-setup` / `kb-agent-generate`)

```
kb-agent-setup  (or: python3 scripts/setup.py — shim)
│
├── check_python()              Python ≥ 3.10
├── check_build_tools()         xcode-select / gcc present (soft-block with fix hint)
├── check_venv()                warns if system Python, shows venv commands
├── choose_kb_root()            CWD / existing path / new path
├── choose_llm()                two questions:
│   ├── Q1: Q&A mode            passthrough / Ollama / OpenAI / Anthropic / custom
│   ├── Q2: API key available?  (passthrough path only — for generate + fallback)
│   └── _test_api_key()         live HTTP verification (optional)
├── write_env()                 writes KB_ROOT + LLM vars to .env
├── run_generate()
│   └── kb-agent-generate
│       │
│       ├── _ensure_embedding_model()   downloads all-MiniLM-L6-v2 if not cached
│       ├── _get_client()               probes ChromaDB; offers auto-rebuild on mismatch
│       ├── _discover_folders()         top-level folders under KB_ROOT (ignores built-ins)
│       ├── for each folder:
│       │   ├── build_collection()      upsert changed files into ChromaDB (hash-delta)
│       │   │   └── _upsert_file_sync() snippet() → embed() → col.upsert()
│       │   ├── _generate_yaml_for_folder()   LLM → domain_config.yaml  (or _minimal_yaml())
│       │   ├── _validate_yaml()        required-key check; falls back to minimal on failure
│       │   └── write domain_config.yaml
│       └── _install_bob_skill()        writes ~/.bob/skills/knowledgebase-agent/SKILL.md
└── interactive_keyword_editor()
        offered when domains received minimal YAML (no LLM during generate);
        edits only the `keywords:` section of domain_config.yaml

---

## Query pipeline (`ask()` per MCP call)

```
MCP client → server.ask()
│
├── _check_stale_cached()       mtime scan (TTL-cached); prepends ⚠ banner if stale
│
└── orchestrator.ask()
    │
    ├── _get_agents()                   lazy-load DomainAgent registry (once per process)
    ├── detect_format_intent()          regex → format instruction string
    ├── get_history_sync()              load session turns (cache-first; disk only on cold start)
    ├── _keyword_confidence()           fast pre-filter against domain keywords
    │
    ├── [if not confident] _classify_intent()
    │       └── call_llm() → JSON { domains, needs_clarification }
    │           (passthrough: keyword fallback, no LLM call)
    │
    ├── _adjusted_top_n()               reduce top_n if passthrough context would overflow
    │
    ├── asyncio.gather( DomainAgent.run() × N )
    │   └── DomainAgent.run()
    │       ├── [data question] _pre_rank() → vector_store.search() + apply_pin_rules()
    │       └── base_agent.ask()
    │           │
    │           ├── [README-first]
    │           │   ├── _find_readme()  [_README_CACHE hit → no disk I/O on warm calls]
    │           │   ├── [simple]  _extract_auto_index() → context_budget.build_context()
    │           │   └── [complex] full README → context_budget.trim()
    │           │
    │           ├── [RAG fallback]
    │           │   ├── vector_store.search()
    │           │   └── asyncio.gather( file_parser.extract() × top_n )
    │           │
    │           ├── [LLM mode]        call_llm(system + context + question)
    │           └── [passthrough]     _build_passthrough_block()
    │
    ├── _merge_answers()                combine domain results; unwrap passthrough blocks
    ├── _stale_warnings()               per-domain rglob vs ChromaDB count
    ├── _minimal_keyword_notice()       warn if domain had ≤1 keyword at generate time
    └── add_turn_sync()                 persist question + answer to session file
```

---

## Data Analyst pipeline (`query_data()` per MCP call)

```
MCP client → server.query_data(path, question, session_id?)
│
├── analyst.engine.query_data()
│   │
│   ├── analyst.inspector.inspect_file(path)
│   │     └── [cache hit]  return cached DataCard (mtime + 5-min TTL)
│   │     └── [cache miss] parse file → build DataCard → store in _CARD_CACHE
│   │
│   ├── _needs_clarification(question, card, params)
│   │     checks: metric ambiguity (>1 metric col, none named in question)
│   │             time ambiguity  (time cols present, no period named)
│   │
│   ├── [clarification needed]
│   │     return { status: "clarifying", clarifications: [...] }
│   │     save AnalystSession with pending_clarifications
│   │
│   └── [all params known]
│         ├── _load_rows(path)       xlsx / csv / json → list[dict]
│         ├── _filter_rows(...)      apply time + entity filters
│         └── _build_answer(...)     dispatch by question keywords:
│               "churn/attrition"  → _attrition_pivot()  (entity × time pivot)
│               "total/sum"        → _aggregate(metric, None)
│               "top/biggest"      → _aggregate(metric, entity), _top_n_by()
│               "breakdown/group"  → _aggregate(metric, group_col)
│               "summary/quality"  → DataCard prose summary + warnings
│               fallback           → SUM of first metric column
│
│         return { status: "answered", answer, reasoning, suggested_followups }
│         save AnalystSession (last_answer, turns)

MCP client → server.refine_query(session_id, feedback)
│
└── analyst.engine.refine_query()
      ├── load_session(session_id)
      ├── _apply_clarification_feedback(feedback, sess)
      │     parse: FY2025/Q1/2026 → sess.params["time_range"]
      │            "top 20"       → sess.params["top_n"]
      │            pending clq    → match against choices, store in params
      └── query_data(file_path, original_question, session_id)
            (re-runs full pipeline with updated params)
```

---

## Data storage

```
{KB_ROOT}/
├── <Domain Folder>/
│   ├── domain_config.yaml          agent name, description, keywords, retrieval rules
│   └── <documents>                 PDF, DOCX, XLSX, MD, TXT, …
└── .kb_index/
    ├── chroma/                     ChromaDB persistent store (one collection per domain)
    │   └── <collection>/           embeddings, document text, metadata (hash, indexed_at)
    ├── session_memory/
    │   └── <session_id>.json       { messages: [...], last_active: <unix ts> }
    └── analyst_sessions/
        └── <session_id>.json       { file_path, data_card, params, last_answer, turns, … }
```

---

## LLM provider matrix

| `KB_LLM_PROVIDER` | Q&A calls | Embedding | Notes |
|---|---|---|---|
| `ollama` | `/api/chat` | `/api/embeddings` | Local; falls back to passthrough if unreachable |
| `openai` | `/chat/completions` | `/embeddings` | `KB_API_KEY` required |
| `anthropic` | `/v1/messages` | `/embeddings` (OpenAI-compat) | `KB_API_KEY` required |
| `custom` | `/chat/completions` | `/embeddings` | Any OpenAI-compatible server |
| `passthrough` | None (host AI answers) | `sentence-transformers` | Recommended default |

Embedding fallback: when any provider's embedding endpoint fails and
`KB_PASSTHROUGH_FALLBACK=true`, `sentence-transformers` (`all-MiniLM-L6-v2`)
is used automatically.
