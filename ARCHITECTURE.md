# Architecture: kb-agent-mcp

This document describes the internal structure of the `kb-agent-mcp` package.
It covers every module, the two main pipelines (setup and query), and the data flows between them.

---

## Package layout

```
kb_agent_mcp/
├── server.py            MCP server — exposes 5 tools via FastMCP
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
└── cli/
    ├── setup.py         Interactive setup wizard (kb-agent-setup)
    ├── generate.py      Index builder + domain YAML generator (kb-agent-generate)
    ├── watch.py         Filesystem watcher (kb-agent-watch)
    └── doctor.py        Health checklist (kb-agent-doctor)
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
The FastMCP application. Registers five MCP tools:

| Tool | What it does |
|---|---|
| `ask` | Full query pipeline via `orchestrator.ask()` |
| `list_domains` | Returns indexed domain names and descriptions |
| `reindex` | Rebuilds ChromaDB collections for all domains |
| `clear_memory` | Deletes a session's conversation history |
| `show_memory` | Returns a session's turn history |

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

### `vector_store.py`
ChromaDB persistence layer. One collection per domain, stored under
`{KB_ROOT}/.kb_index/chroma/`. Each file is stored with its MD5 hash;
`_upsert_file_sync()` skips files whose hash hasn't changed (incremental
indexing). Embeddings are computed via `embeddings._embed_sync()`.

Search uses sklearn `cosine_similarity` over all stored embeddings (not
ChromaDB's built-in ANN) for consistent results across mixed embedding
dimensions. Falls back to keyword matching if embeddings are missing.

`set_domain_metadata()` / `get_domain_metadata()` store domain config and the
`indexed_at` timestamp as ChromaDB collection metadata (flat key-value, JSON-
serialised for lists/dicts). The server's stale-index TTL cache compares file
`mtime` values against this timestamp.

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
Disk-persisted session memory. Each session is a JSON file at
`{KB_ROOT}/.kb_index/session_memory/<session_id>.json` containing a message
list and a `last_active` timestamp. Sessions expire automatically after
`KB_SESSION_TIMEOUT_HOURS` hours of inactivity. Only the last
`KB_SESSION_MAX_TURNS` turns are retained; assistant answers are truncated to
`KB_SESSION_MAX_ANSWER_CHARS` before storage (the full answer was already
returned to the caller).

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

## Setup pipeline (`kb-agent-setup` / `kb-agent-generate`)

```
kb-agent-setup
│
├── check_python()              Python ≥ 3.10
├── check_build_tools()         xcode-select / gcc present
├── check_venv()                warns if system Python
├── choose_kb_root()            CWD / existing path / new path
├── choose_llm()                passthrough / Ollama / OpenAI / Anthropic / custom
│   └── _test_api_key()         live HTTP verification (optional)
├── write_env()                 writes KB_ROOT + LLM vars to .env
└── run_generate()
    └── kb-agent-generate
        │
        ├── _ensure_embedding_model()   downloads all-MiniLM-L6-v2 if not cached
        ├── _get_client()               probes ChromaDB; offers auto-rebuild on mismatch
        ├── _discover_folders()         top-level folders under KB_ROOT (ignores built-ins)
        ├── for each folder:
        │   ├── build_collection()      upsert changed files into ChromaDB (hash-delta)
        │   │   └── _upsert_file_sync() snippet() → embed() → col.upsert()
        │   ├── _generate_yaml_for_folder()   LLM → domain_config.yaml  (or _minimal_yaml())
        │   ├── _validate_yaml()        required-key check; falls back to minimal on failure
        │   └── write domain_config.yaml
        └── _install_bob_skill()        writes ~/.bob/skills/knowledgebase-agent/SKILL.md
```

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
    ├── get_history_sync()              load session turns from disk
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
    │           │   ├── _find_readme()
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

## Data storage

```
{KB_ROOT}/
├── <Domain Folder>/
│   ├── domain_config.yaml          agent name, description, keywords, retrieval rules
│   └── <documents>                 PDF, DOCX, XLSX, MD, TXT, …
└── .kb_index/
    ├── chroma/                     ChromaDB persistent store (one collection per domain)
    │   └── <collection>/           embeddings, document text, metadata (hash, indexed_at)
    └── session_memory/
        └── <session_id>.json       { messages: [...], last_active: <unix ts> }
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
