# Architecture: kb-agent-mcp

This document is the authoritative internal reference for the `kb-agent-mcp`
package. It covers every module, the three main pipelines (setup, query, and
data-analyst), the security gate mechanism, the data storage layout, all
environment variables, and the complete inter-module import graph.

Every statement here is grounded in the source code — no speculation.

---

## System overview

[![Architecture Flow Diagram](architecture%20flow%20diagram.png)](architecture%20flow%20diagram.png)

The diagram above shows all three pipelines and every major component.

```
╔══════════════════════════════════════════════════════════════════════════════════════════╗
║  MCP HOST  (Claude Desktop / Bob / Cursor)                                               ║
║  ┌──────────────────────────────────────────────────────────────────────────────────┐    ║
║  │  AI Model  ←── tool responses (markdown / JSON) ── MCP Client SDK               │    ║
║  │                                                         ↑                        │    ║
║  │              tool calls (JSON-RPC over stdio or HTTP) ──┘                        │    ║
║  └──────────────────────────────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════╦═══════════════════════════════════════════════════╝
                                       ║ stdio pipe  OR  HTTP/SSE
╔══════════════════════════════════════╩═══════════════════════════════════════════════════╗
║  kb-agent-serve  (FastMCP server process)                                                ║
║                                                                                          ║
║  ┌─────────────────────────────────  server.py  (14 tools)  ──────────────────────────┐  ║
║  │                                                                                     │  ║
║  │  ╔══ KB tools ════════════════╗  ╔══ Security Gate ══════════╗  ╔══ Analyst ═════╗ │  ║
║  │  ║ ask()                      ║  ║ check_confidential()      ║  ║ analyze_file() ║ │  ║
║  │  ║ list_domains()             ║  ║ acknowledge_gate()        ║  ║ suggest_q()    ║ │  ║
║  │  ║ reindex()                  ║  ╚═══════════════╦══════════╝  ║ query_data()   ║ │  ║
║  │  ║ clear_memory()             ║                  ║             ║ refine_query() ║ │  ║
║  │  ║ show_memory()              ║                  ║             ╚══════╦═════════╝ │  ║
║  │  ║ domain_status()            ║                  ║                    ║            │  ║
║  │  ║ read_audit()               ║                  ║                    ║            │  ║
║  │  ║ resume_session()           ║                  ║                    ║            │  ║
║  │  ║ rate_answer()              ║                  ║                    ║            │  ║
║  │  ║ update_document()          ║                  ║                    ║            │  ║
║  │  ╚══════════╦═════════════════╝                  ║                    ║            │  ║
║  └─────────────╫───────────────────────────────╫────────────────────────╫────────────┘  ║
║                ║                               ║                        ║                ║
║  ┌─────────────╨──────────────────────────┐    ║security_gate.py        ║                ║
║  │  orchestrator.py                       │    ║ classify_confidential  ║                ║
║  │                                        │    ║ scan_all_domains       ║                ║
║  │  1. detect_format_intent()             │    ║ generate_ack_token     ║                ║
║  │  2. _keyword_confidence()  ─────┐      │    ║ validate_ack_token     ║                ║
║  │  3. _classify_intent() (LLM) ◄──┘      │    ║ GateSession → disk     ║                ║
║  │  4. _adjusted_top_n()                  │    ╚════════════════════════╝                ║
║  │  5. asyncio.gather( DomainAgent × N )  │                                              ║
║  │  6. aggregate() OR _merge_answers()    │    ┌────────────────────────────────────┐    ║
║  │     + source citations block           │    │  analyst/                          │    ║
║  │  7. add_turn_sync() → session file     │    │                                    │    ║
║  └────────────┬───────────────────────────┘    │  inspector.py → DataCard           │    ║
║               │                               │  planner.py   → QuestionMenu       │    ║
║       ┌───────┴──────────────────────┐         │  engine.py    → answer+reasoning   │    ║
║       │  DomainAgent × N (per domain)│         │  session.py   → AnalystSession     │    ║
║       │  domain_rules.py (DomainConfig│        └────────────────────┬───────────────┘    ║
║       │  pin_files, boost_keywords)  │                              │                    ║
║       └───────┬──────────────────────┘                              │ raw file reads     ║
║               │                                                     │                    ║
║  ┌────────────╨────────────────────────────────────────────────┐    │                    ║
║  │  base_agent.py                                              │    │                    ║
║  │                                                             │    │                    ║
║  │  is_complex_question() / is_data_question()                 │    │                    ║
║  │                                                             │    │                    ║
║  │  ┌─ README-first path ──────────────────────────────────┐   │    │                    ║
║  │  │  _find_readme() → _README_CACHE (5-min TTL)          │   │    │                    ║
║  │  │  simple  → AUTO-INDEX block + context_budget         │   │    │                    ║
║  │  │  complex → full README (up to KB_BUDGET_FULL_README) │   │    │                    ║
║  │  └──────────────────────────────────────────────────────┘   │    │                    ║
║  │                                                             │    │                    ║
║  │  ┌─ RAG fallback path ──────────────────────────────────┐   │    │                    ║
║  │  │  vector_store.search() → file_parser.extract() × N  │   │    │                    ║
║  │  └──────────────────────────────────────────────────────┘   │    │                    ║
║  │                                                             │    │                    ║
║  │  ┌─ LLM call  OR  passthrough block ───────────────────┐   │    │                    ║
║  │  │  Ollama /api/chat                                    │   │    │                    ║
║  │  │  OpenAI /chat/completions                           │   │    │                    ║
║  │  │  Anthropic /v1/messages                             │   │    │                    ║
║  │  │  passthrough → <<<KB_PASSTHROUGH>>> block           │   │    │                    ║
║  │  └─────────────────────────────────────────────────────┘   │    │                    ║
║  └────────────┬────────────────────────────────────────────────┘    │                    ║
║               │                                                     │                    ║
║  ┌────────────╨──────────────┐  ┌─────────────────────────────────┐ │                    ║
║  │  vector_store.py          │  │  embeddings.py                  │ │                    ║
║  │  ChromaDB PersistentClient│  │  Ollama /api/embeddings         │ │                    ║
║  │  one collection per domain│  │  OpenAI /embeddings             │ │                    ║
║  │  MD5 hash change detection│  │  sentence-transformers fallback │ │                    ║
║  │  128-entry embed LRU cache│  │  _embed_sync() ← vector_store  │ │                    ║
║  └───────────────────────────┘  └─────────────────────────────────┘ │                    ║
╚═══════════════════════════════════════════════════════════╦══════════╧══════════════════╝
                                                            ║
╔═══════════════════════════════════════════════════════════╩════════════════════════════╗
║  FILESYSTEM  (KB_ROOT)                                                                 ║
║                                                                                        ║
║  ┌─────────────────────────────────────────────────────────────────────────────────┐  ║
║  │  <Domain A>/        PDF  DOCX  XLSX  MD  TXT  CSV  …      domain_config.yaml   │  ║
║  │  <Domain B>/        …                                      domain_config.yaml   │  ║
║  │  <Domain N>/        …                                      domain_config.yaml   │  ║
║  │                                                                                 │  ║
║  │  .kb_index/                                                                     │  ║
║  │    chroma/                  ChromaDB collections — embeddings + metadata         │  ║
║  │      <domain_a>/            {id, embedding, {path, hash, summary, …}}           │  ║
║  │      <domain_b>/            …                                                   │  ║
║  │    session_memory/          <session_id>.json  {messages, last_active}          │  ║
║  │    analyst_sessions/        <session_id>.json  {file_path, params, answer, …}   │  ║
║  │    gate_sessions.json       {session_id: GateSession, …}                        │  ║
║  │    audit.jsonl              append-only Q&A audit log (auto-rotates at 50 MB)   │  ║
║  │    feedback.jsonl           per-answer 1–5 star ratings + comments              │  ║
║  └─────────────────────────────────────────────────────────────────────────────────┘  ║
╚════════════════════════════════════════════════════════════════════════════════════════╝
```

**Legend:**
- `╔══╗` / `╚══╝` — major system boundaries (MCP host, server process, filesystem)
- `┌──┐` / `└──┘` — internal modules / sub-systems
- `║` / `│` — data-flow connections
- Analyst tools (right column) bypass the vector index entirely — they read raw files directly from `KB_ROOT`
- Security gate sits between `server.ask()` and `orchestrator.ask()` — unanswered sessions are blocked before any retrieval occurs

There are three independent processing pipelines:

| Pipeline | Entry point | Purpose |
|---|---|---|
| **Setup** | `kb-agent-setup` / `kb-agent-generate` | Index knowledge folders into ChromaDB; generate `domain_config.yaml`; install Bob skill |
| **Query** | MCP `ask()` | Route question → retrieve context → call LLM (or passthrough) → return answer |
| **Data Analyst** | MCP `query_data()` | Profile file → clarify params → load rows → compute → return answer + reasoning |

---

## Package layout

```
kb_agent_mcp/
├── __init__.py          Package metadata (__version__ from importlib.metadata)
├── server.py            FastMCP server — 14 MCP tools; startup validation; stale-index TTL cache
├── orchestrator.py      Query pipeline: format detection → keyword route → LLM classify → dispatch → aggregate → merge
├── domain_agent.py      DomainAgent wrapper — per-domain config, pre-rank, stale_file_count
├── base_agent.py        README-first RAG pipeline + all LLM call implementations + question classifiers
├── vector_store.py      ChromaDB client — upsert, search, collection metadata, 128-entry embed LRU cache
├── embeddings.py        2-tier embedding backend with sentence-transformers fallback
├── file_parser.py       Multi-format text extractor — sync + async; image OCR; .noindex sentinel enforcement
├── domain_rules.py      domain_config.yaml loader + DomainConfig dataclass + pin/boost rules
├── memory.py            Per-session conversation memory — disk-persisted JSON, 5-min in-process cache
├── context_budget.py    Character budget registry + compaction engine (trim, compact, build_context)
├── config.py            Frozen Config dataclass — reads all env vars + .env; module-level cfg singleton
├── security_gate.py     Anti-trick confidentiality gate — classify, scan, token, GateSession persistence
├── aggregator.py        Cross-domain answer synthesis — merges multi-agent results into a single coherent answer
├── audit.py             Append-only JSONL audit log — log_turn(), read_log(); size-capped rotation
├── feedback.py          Per-answer 1–5 star ratings — record(), read_feedback(); persisted to feedback.jsonl
├── writeback.py         Safe document write-back — write_document(rel_path, content, mode) → WriteResult
├── analyst/
│   ├── __init__.py      Re-exports: inspect_file, DataCard, suggest_questions, query_data, refine_query
│   ├── inspector.py     Schema profiler → DataCard (columns, types, grain, themes); (path, mtime) cache
│   ├── planner.py       DataCard → QuestionMenu (themed analytical questions); pure logic, no I/O
│   ├── engine.py        Query engine: clarify → load rows → compute → answer + reasoning; refine_query
│   └── session.py       AnalystSession dataclass — disk-persisted, 5-min in-process cache
└── cli/
    ├── main.py          Unified `kb-agent` root command (in-process dispatch, no subprocess fork)
    ├── setup.py         Interactive setup wizard (kb-agent-setup / kb-agent setup)
    ├── generate.py      Index builder + domain YAML generator (kb-agent-generate / kb-agent generate)
    ├── watch.py         Filesystem watcher with debounce (kb-agent-watch / kb-agent watch)
    ├── doctor.py        9-check health checklist with auto-fix (kb-agent-doctor / kb-agent doctor)
    └── status.py        Read-only per-domain status table with Rich (kb-agent-status / kb-agent status)

scripts/
└── setup.py             12-line shim → delegates to kb_agent_mcp.cli.setup (backward compat)
```

---

## Module responsibilities

### `config.py`
A **frozen dataclass** (`Config`) that reads every tunable value from environment
variables (or a `.env` file auto-discovered in order: CWD → `$HOME` → `KB_ROOT`
→ package root). Values already in `os.environ` are never overwritten.

Key derived properties:

| Property | Value |
|---|---|
| `kb_root_path` | `Path(KB_ROOT).expanduser().resolve()` |
| `kb_index_path` | `kb_root_path / ".kb_index"` |
| `kb_root_is_explicit` | `True` only when `KB_ROOT` is in the environment (not the CWD fallback) |

`validate()` checks `KB_ROOT` exists, `KB_LLM_PROVIDER` is valid, and `KB_API_KEY`
is set when required. Called at server startup (exits on failure) and by the CLI.

`is_ignored(folder_name)` returns `True` for: dotfolders, `BUILTIN_IGNORE` names
(`.kb_index`, `.git`, `__pycache__`, `agents`, `scripts`, `tests`, `kb_agent_mcp`,
etc.), `.egg-info` / `.dist-info` suffixes, and any name in `KB_IGNORE_FOLDERS`.

A module-level singleton `cfg = Config()` is imported by every other module.

---

### `server.py`
The FastMCP application. Registers **fourteen MCP tools** in four groups:

**Knowledge Base tools:**

| Tool | Signature | What it does |
|---|---|---|
| `ask` | `ask(question, format?, session_id?)` | Gate check → stale check → `orchestrator.ask()` → optional ⚠ banner |
| `list_domains` | `list_domains()` | `orchestrator.list_domains()` → names + descriptions |
| `reindex` | `reindex()` | Rebuilds ChromaDB; clears stale cache, passthrough cache, gate sessions |
| `clear_memory` | `clear_memory(session_id?)` | `memory.clear(session_id)` |
| `show_memory` | `show_memory(session_id?)` | Session summary + last N turns (200-char truncated) |

**Security Gate tools:**

| Tool | Signature | What it does |
|---|---|---|
| `check_confidential` | `check_confidential(session_id?)` | `scan_all_domains()` → `generate_ack_token()` → save `GateSession(blocked)` |
| `acknowledge_gate` | `acknowledge_gate(session_id, token)` | `validate_ack_token()` → save `GateSession(acknowledged)` |

**Data Analyst tools:**

| Tool | Signature | What it does |
|---|---|---|
| `analyze_file` | `analyze_file(path)` | `inspector.inspect_file()` → DataCard JSON |
| `suggest_questions` | `suggest_questions(path)` | `planner.suggest_questions(card)` → QuestionMenu JSON |
| `query_data` | `query_data(path, question, session_id?)` | `engine.query_data()` → answer or clarifications |
| `refine_query` | `refine_query(session_id, feedback)` | `engine.refine_query()` → updated answer |

**Session & Feedback tools:**

| Tool | Signature | What it does |
|---|---|---|
| `domain_status` | `domain_status()` | Returns per-domain indexing status: file counts, stale counts, last-indexed timestamps |
| `read_audit` | `read_audit(session_id?, limit?)` | Returns recent audit log entries from `audit.jsonl` (filtered by session when provided) |
| `resume_session` | `resume_session(session_id)` | Returns the last N turns of a prior session so the AI can continue without re-querying |
| `rate_answer` | `rate_answer(session_id, turn_index, rating, comment?)` | Records a 1–5 star rating for a specific turn; persists to `feedback.jsonl` |
| `update_document` | `update_document(rel_path, content, mode?)` | Writes (overwrite) or appends to a document under `KB_ROOT` via `writeback.write_document()` |

**Module-level state:**
- `_stale_cache: dict` — `{stale, details, checked_at}`; TTL-guarded mtime scan
- `_transport_mode: str` — `"stdio"` (default) or `"http"` (set by `main()`)

---

### `orchestrator.py`
Coordinates the full query pipeline for every `ask()` call:

1. **Format intent detection** — `detect_format_intent()` scans for regex phrases
   (`"as a table"`, `"in bullet points"`, etc.) and explicit `format=` flag.
   Returns an instruction string injected into every domain agent's system prompt.
2. **Keyword pre-filter** — `_keyword_confidence()` scores each domain's keyword list
   against the question. Confident (≥2 hits in one domain, or 3× lead over others)
   → skip LLM routing entirely.
3. **LLM intent classifier** — `_classify_intent()` calls the LLM when keyword routing
   is ambiguous. Returns `{ domains, needs_clarification, clarification_question }`.
   Falls back to keyword routing in passthrough mode (no LLM call made).
4. **Passthrough budget check** — `_adjusted_top_n()` estimates
   `n_domains × top_n × max_chars` vs `KB_BUDGET_PASSTHROUGH_THRESHOLD × KB_BUDGET_TOTAL`.
   Reduces `top_n` if overflow; emits a warning.
5. **Parallel dispatch** — `asyncio.gather(DomainAgent.run() × N)` across selected domains.
6. **Answer merge / aggregation** — single domain → answer returned directly.
   Multiple domains → `aggregator.aggregate(results, question)` is called first; if the
   aggregator produces a coherent synthesis it is returned as-is, otherwise answers are
   joined with `---` separators. Each cited source is tagged with a `[Source: …]`
   inline citation. Passthrough blocks are unwrapped into clean markdown.
7. **Memory persistence** — `add_turn_sync(session_id, question, answer)` appends
   to the session file (sync disk write at the end of the pipeline).
8. **Audit logging** — `audit.log_turn(session_id, question, answer)` appends one
   JSONL record to `.kb_index/audit.jsonl` after every successful `ask()`.

`_agents` is a module-level dict loaded lazily on first `ask()` call (double-checked
locking via `asyncio.Lock`). `refresh_agents()` rebuilds it after `reindex()`.

---

### `domain_agent.py`
`DomainAgent` wraps one knowledge folder. On each `run()` call:

- Resolves `effective_top_n` — uses `top_n_override` from orchestrator (budget
  reduction) when set, otherwise `self.config.top_n`.
- Checks `_global_data_q(question)` (global data regex) OR
  `self.config.is_data_question(question)` (domain data patterns). When true:
  calls `_pre_rank()` (vector search + `apply_pin_rules()`) and passes
  pre-ranked results directly to `base_agent.ask()`.
- When not a data question: calls `base_agent.ask()` with no pre-ranked results
  (README-first path).
- `session_id` is threaded from orchestrator → `run()` → `base_agent.ask()` for
  per-file confidential redaction in the security gate.
- `stale_file_count()` returns `(files_on_disk, files_indexed)` using `rglob` +
  `col.count()`. Returns `(0, 0)` on any error.

`build_all_domain_agents()` (called by `refresh_agents()`) walks `KB_ROOT`,
calls `load_domain_config(folder_name)` for each non-ignored directory, and
instantiates one `DomainAgent` per discovered domain.

---

### `base_agent.py`
The README-first RAG pipeline. Also owns all LLM call implementations and
question classifiers.

**Question classifiers** (module-level compiled regexes):

| Function | Regex | Effect |
|---|---|---|
| `is_complex_question()` | `_COMPLEX_QUESTION_RE` — compare, contrast, step-by-step, architecture, pros/cons, trade-off, etc. | Forces full README mode |
| `is_data_question()` | `_DATA_QUESTION_RE` — revenue, total, how many, breakdown, by quarter/region, FY20XX, YTD, etc. | Forces raw-file RAG |

**README discovery priority cascade** (`_find_readme()`):
1. Any `.md` whose name contains `readme`
2. `<FolderName>.md`
3. First `.md` with a Markdown heading in its first 500 chars
4. First `.md` found in the folder

README is cached per `folder_name` in `_README_CACHE` (dict of `(path, text, loaded_at)`).
TTL = 300 s. Only disk I/O on cold start or after TTL expiry.

**README context selection:**
- Data question → skip README, go straight to RAG
- README body < `KB_MIN_README_CHARS` (200) → treat as absent, go to RAG
- Simple question → `_extract_auto_index()` (between `<!-- KB:AUTO-INDEX:START/END -->`)
  + `context_budget.build_context()`
- Complex question → full README text, trimmed to `KB_BUDGET_FULL_README`

**RAG fallback** (when README absent/thin or data question):
- `vector_store.search(domain, query, top_n)` → ranked `SearchResult` list
- `asyncio.gather(file_parser.extract(f) for f in results)` — concurrent extraction
- Context assembled as labelled blocks with source path and similarity score

**Passthrough path** (`is_passthrough()` → `True`):
- Returns `<<<KB_PASSTHROUGH>>>…<<<KB_PASSTHROUGH_END>>>` block with the retrieved
  context. Orchestrator unwraps to clean markdown for the host AI.
- `_passthrough_cache: bool | None` — checked once per process; reset by `reindex()`.

**LLM call dispatch** (all in `base_agent.py`, called by `base_agent.ask()`):
- Ollama: `POST /api/chat` with `{"model", "messages", "stream": false, "options": {"num_ctx"}}`
- OpenAI / custom: `POST /chat/completions` with `{"model", "messages"}`
- Anthropic: `POST /v1/messages` with `{"model", "messages", "max_tokens"}` + `x-api-key` header

All three use `_get_http_client()` — a `httpx.Client` singleton with connection
pooling (`max_keepalive=5`, `max_connections=10`). Saves 100–500 ms per call vs
a per-request client.

**Security gate integration** (`session_id` param):
- `is_gate_acknowledged(session_id)` is checked before returning context.
- Unacknowledged confidential files: their extracted text is replaced with a
  placeholder (redacted); acknowledged ones are included with a `🔒` citation prefix.

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
Embedding backend with a two-tier fallback chain:

1. **Configured provider** — used based on `KB_LLM_PROVIDER`:
   - `ollama`: `POST {KB_LLM_BASE_URL}/api/embeddings` with `{"model", "prompt"}`
   - `openai` / `anthropic` / `custom`: `POST {KB_LLM_BASE_URL}/embeddings` with `{"model", "input"}`
   - `passthrough`: goes directly to tier 2 (no LLM endpoint called)
2. **sentence-transformers** (`all-MiniLM-L6-v2`, ~80 MB, 384-dim) — used
   when `KB_LLM_PROVIDER=passthrough`, or as an auto-fallback when the primary
   provider fails and `KB_PASSTHROUGH_FALLBACK=true`.

Public API: `await embed(text) → list[float]`, `_embed_sync(text) → list[float]`
(sync wrapper used by `vector_store`), `embedding_dim() → int`, `backend_name() → str`.

`_st_model_is_cached()` checks `~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2`
and the legacy torch path before attempting a download. `_ensure_embedding_model()`
is called at generate-time to front-load the download with a progress message.

When `TRANSFORMERS_OFFLINE=1` is set and the model is not cached, a `RuntimeError`
is raised with pre-cache instructions rather than silently hanging.

---

### `file_parser.py`
Multi-format text extractor. All extractors are synchronous and are called via
`asyncio.to_thread()` from the async pipeline.

**`INCLUDE_EXTS`** (the set of indexed extensions):
`.pdf`, `.docx`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.md`, `.txt`, `.csv`, `.boxnote`, `.doc`,
`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`

| Format | Extractor |
|---|---|
| `.txt` `.md` `.csv` | UTF-8 read with `errors="ignore"` |
| `.docx` `.doc` | XML extraction from zip (`word/document.xml`) |
| `.pdf` | `pypdf` page iteration |
| `.pptx` `.ppt` | `python-pptx` shape text + table cells + speaker notes + slide labels |
| `.xlsx` `.xls` < 50 MB | `openpyxl` with smart aggregation for sheets > 200 rows |
| `.xlsx` `.xls` ≥ 50 MB | Streaming XML `iterparse` — never loads full workbook |
| `.boxnote` | Recursive JSON tree walk |
| `.png` `.jpg` `.jpeg` `.gif` `.webp` | Image OCR via configured engine (`KB_OCR_ENGINE`); returns extracted text or filename fallback when OCR is disabled |
| other extensions | Filename returned as fallback text |

**Large XLSX streaming strategy:** the sheet is walked once with `iterparse`,
numeric columns are summed by detected group-by dimensions (`_AGG_KEYWORDS` dict:
product, geography, quarter, year, division, etc.), and a compact markdown summary
is returned instead of raw rows. Threshold = 50 MB (`_LARGE_XLSX_BYTES`).

**`.noindex` sentinel** (`_has_noindex_ancestor(path)`): walks up the path from
the file to `KB_ROOT` looking for a `.noindex` file. Returns `True` if found.
`should_skip(path)` calls this (plus checks `_SKIP_PATTERNS` and non-`INCLUDE_EXTS`).

Public API: `await extract(file_path, max_chars?) → str`, `snippet(file_path, max_chars=2000) → str` (sync, used by indexing).

---

### `domain_rules.py`
Loads and validates `domain_config.yaml` for each knowledge folder.

`DomainConfig` dataclass fields:
`folder_name`, `agent_name`, `description`, `keywords` (list), `top_n` (int, default 5),
`max_chars` (int), `system_prompt` (str), `pin_files` (list of glob patterns),
`boost_keywords` (list), `data_patterns` (list of regex strings), `complex_patterns` (list).

`load_domain_config(folder_name)` reads `domain_config.yaml` from the domain folder
(via PyYAML when available, else falls back to a minimal config). Compiled
`re.Pattern` objects for `data_patterns` / `complex_patterns` are materialised lazily
on first `is_data_question()` / `is_complex_question()` call.

`apply_pin_rules(results, config)` applies two retrieval adjustments to the
`SearchResult` list returned by `vector_store.search()`:
- **pin_files** — any result whose path matches a glob is prepended regardless of score
- **boost_keywords** — results whose filename contains a boost keyword are sorted to top

---

### `memory.py`
Per-session conversation memory with disk persistence and an in-process cache.

**Storage:** one JSON file per session at `{KB_ROOT}/.kb_index/session_memory/<session_id>.json`.

Session schema:
```json
{ "messages": [{"role": "user"|"assistant", "content": "…"}, …], "last_active": <unix float> }
```

`_SESSION_CACHE: dict[str, tuple[dict, float]]` — in-process cache keyed by
`session_id`, value is `(data, loaded_at)`. TTL = 300 s. Warm reads return from
cache without disk I/O. `_save_sync()` writes to both cache and disk.

Session lifecycle:
- Expires after `KB_SESSION_TIMEOUT_HOURS` of inactivity (reset to empty on access)
- Last `KB_SESSION_MAX_TURNS` turns retained (`messages[:KB_SESSION_MAX_TURNS*2]`)
- Assistant answers truncated to `KB_SESSION_MAX_ANSWER_CHARS` before storage

Session filename is sanitised: `_SAFE_SESSION_RE = re.compile(r"[^a-zA-Z0-9_\-]")`.

### `analyst/` — Data Analyst capability add-on

A self-contained sub-package for **live file computation**. Does not use the
vector index. Invoked when the question requires aggregation, trending,
filtering, or comparison rather than semantic retrieval.

Re-exports from `analyst/__init__.py`: `inspect_file`, `DataCard`,
`suggest_questions`, `query_data`, `refine_query`.

**`analyst/inspector.py`** — Schema profiler

Reads any supported file and returns a `DataCard` dataclass:
- `columns`: list of `ColumnInfo(name, kind, sample_values, …)`
- Column kinds: `metric`, `id`, `entity`, `time`, `categorical`, `text`, `unknown`
  (classified by `_METRIC_HINTS` / `_ID_HINTS` / `_TIME_HINTS` name dictionaries
  + value statistics: numeric ratio, cardinality)
- `grain`: what one row represents (detected by entity+time duplicity rate)
- `themes`, `quality_warnings`, `row_count`, `col_count`

Tabular formats: `.xlsx`, `.xls`, `.csv`, `.tsv`, `.json` (list-of-dicts), `.jsonl`.
Document formats: `.pdf`, `.docx`, `.pptx`, `.txt`, `.md`, `.boxnote`, `.rtf`.
Mixed: PDFs with ≥1 table of ≥3 columns and ≥5 rows are profiled as tabular.
Large XLSX (> 50 MB) uses a sparse-row cell-reference XML parser.

DataCards are cached in `_CARD_CACHE` per `(path_str, mtime)` with a 5-min TTL.

**`analyst/planner.py`** — Question planner (pure logic, no I/O)

`suggest_questions(card: DataCard) → QuestionMenu` returns a dict keyed by theme:
`revenue`, `attrition`, `growth`, `concentration`, `anomaly`, `summary`, `document`.
Each `Question` dict carries: `question`, `theme`, `requires` (column kinds needed),
`clarifications` (list of clarifying-question dicts the engine will ask before running).
Intentionally over-inclusive — suggests everything the data *could* answer.

**`analyst/engine.py`** — Query engine

`query_data(path, question, session_id?)`:
1. `inspect_file(path)` → `DataCard` (cache hit or compute)
2. `_needs_clarification(question, card, params)` — checks: metric ambiguity
   (>1 metric col, none named in question); time ambiguity (time cols present,
   no period named). Returns `{status: "clarifying", clarifications: […]}` if needed.
3. `_load_rows(path)` → `list[dict]` (xlsx / csv / json / jsonl; handles sparse xlsx)
4. `_filter_rows(rows, params)` — time and entity filters
5. `_build_answer(rows, question, card, params)` — dispatches by keywords:
   - `"churn"` / `"attrition"` → `_attrition_pivot()` (entity × time pivot table)
   - `"total"` / `"sum"` → `_aggregate(metric, None)`
   - `"top"` / `"biggest"` → `_aggregate(metric, entity)` + `_top_n_by()`
   - `"breakdown"` / `"group"` → `_aggregate(metric, group_col)`
   - `"summary"` / `"quality"` → DataCard prose summary + warnings
   - fallback → SUM of first metric column
6. Returns `{status: "answered", answer, reasoning, suggested_followups, session_id}`

`refine_query(session_id, feedback)` parses free-text feedback into param updates:
- `FY2025` / `Q1` / `2026` → `sess.params["time_range"]`
- `"top 20"` → `sess.params["top_n"]`
- pending clarification answer → matched against choices, stored in params
Then re-runs `query_data(file_path, original_question, session_id)`.

**`analyst/session.py`** — Analyst session state (separate from `memory.py`)

`AnalystSession` dataclass: `session_id`, `file_path`, `data_card`, `original_question`,
`params`, `pending_clarifications`, `last_answer`, `last_reasoning`, `turns` (20-turn window).

Storage: `{KB_ROOT}/.kb_index/analyst_sessions/<session_id>.json`.
Same 5-min in-process TTL cache pattern as `memory.py`.
Expiry: `KB_SESSION_TIMEOUT_HOURS` (shared env var).

---

### `context_budget.py`
Central registry of all character budgets (read from `cfg` at module load).

Budget keys and values:

| Key | Default (chars) | Description |
|---|---|---|
| `total` | 24 000 | Hard ceiling — any context sent to any LLM |
| `index` | 8 000 | README AUTO-INDEX block (simple questions) |
| `full_readme` | 24 000 | Full README (complex questions) |
| `pre_index` | 2 000 | Hand-written README intro |
| `rag_file` | 4 000 | Max chars per file in RAG fallback + gate scan |
| `history` | 4 | Conversation turns (not chars) included in each LLM call |
| `summary` | 500 | Per-file summary line in AUTO-INDEX table |
| `embed_chars` | 3 500 | Max chars of text sent to embedding endpoint |
| `min_readme` | 200 | README below this is treated as absent |
| `num_ctx` | 32 768 | Ollama `num_ctx` option |

Public API:
- `get(key) → int` — return budget value; raises `KeyError` if unknown
- `tokens(key) → int` — `get(key) // 4` (rough token estimate)
- `trim(text, budget_key) → str` — hard-trim at newline boundary
- `trim_summary(summary, filename) → str` — inline trim for index table rows
- `compact_index_block(block) → str` — strips headings, normalises tables to
  `File | Summary`, collapses repeated-version groups, truncates per-row summaries
- `compact_pre_index(text) → str` — trims intro section to `pre_index` budget
- `build_context(pre_index, index_block) → str` — assembles compacted README context
- `COLLAPSE_RULES` — extensible via `KB_COLLAPSE_PATTERNS` env var (comma-separated)

---

## Module responsibilities (CLI)

### `cli/main.py`
Unified entry point (`kb-agent`). Reads `sys.argv[1]` as the subcommand,
patches `sys.argv`, and imports + calls the subcommand's `main()` in-process
(no subprocess fork). Registered subcommands:

| Subcommand | Module | Description |
|---|---|---|
| `setup` | `cli.setup` | Interactive setup wizard |
| `generate` | `cli.generate` | Build/rebuild ChromaDB indexes |
| `serve` | `server` | Start MCP server |
| `watch` | `cli.watch` | Filesystem watcher |
| `doctor` | `cli.doctor` | Health checks with auto-fix |
| `status` | `cli.status` | Per-domain status table |
| `init` | _(inline)_ | `setup` → `generate` → `doctor` in sequence |

`kb-agent init` is the recommended first-time path — runs all three steps in one command.

---

### `cli/setup.py`
The canonical interactive setup wizard (`kb-agent-setup`). Setup steps:

```
Python ≥ 3.10 check
Build tools pre-flight (xcode-select / gcc)
venv recommendation (warns if system Python)
KB_ROOT selection (CWD / existing path / new path)
LLM configuration
  Q1: Q&A mode  → passthrough / ollama / openai / anthropic / custom
  Q2: API key available? (passthrough path only — for generate + fallback)
  _test_api_key() — live HTTP verification (optional)
write_env() → writes KB_ROOT + LLM vars to .env
run_generate() → kb-agent-generate (discovers, indexes, writes skill)
interactive_keyword_editor() (offered when domains got minimal YAML)
```

Flags: `--yes` (non-interactive, passthrough default), `--kb-root <path>`.

`scripts/setup.py` is a 12-line shim → `kb_agent_mcp.cli.setup`. Exists for
backward compatibility with cloned-repo users and the `knowledgebase-install` skill.

---

### `cli/generate.py`
Index builder and domain YAML generator (`kb-agent-generate`).

```
_ensure_embedding_model()        download all-MiniLM-L6-v2 if not cached
_get_client()                    probe ChromaDB; offer auto-rebuild on schema mismatch
_discover_folders()              top-level non-ignored folders under KB_ROOT
for each folder:
  build_collection(domain, folder_path)
    for each file (hash-delta — skips unchanged):
      snippet(file_path) → _embed_sync() → col.upsert(id, embedding, metadata)
    set_domain_metadata(domain, {indexed_at, indexed_at_iso, …})
  _generate_yaml_for_folder()    LLM → domain_config.yaml  (or _minimal_yaml() if no LLM)
  _validate_yaml()               required-key check; falls back to minimal on failure
  write domain_config.yaml
_install_bob_skill()             writes ~/.bob/skills/knowledgebase-agent/SKILL.md
```

Flags: `--force` (regenerate all YAML), `--no-llm` (index only), `--domain <name>`, `--yes`.

---

### `cli/watch.py`
Filesystem watcher (`kb-agent-watch`). Backed by `watchdog`, debounced at 5 s.

| Event | Action |
|---|---|
| File added / modified | `upsert_file(domain, path)` → re-embed into ChromaDB |
| File deleted | `delete_file(domain, path)` → remove from ChromaDB |
| File renamed | remove old path + upsert new path |
| New top-level folder | prompt Accept/Skip → if accepted, run generate flow |
| Top-level folder deleted | `delete_collection(domain)` — purge ChromaDB collection |

Flags: `--no-prompt` — auto-accepts new folders (CI/headless).

---

### `cli/doctor.py`
Health checklist (`kb-agent-doctor`). Runs 9 checks and prints `✓`/`✗`/`⚠`.
Exit code 0 = all pass, 1 = any failure.

The ChromaDB check also detects a schema/version mismatch as a branch within check ⑤ and offers an auto-fix; it is not a separate numbered check.

| # | Check | Auto-fixable? | Fix |
|---|---|---|---|
| ① | Python ≥ 3.10 | ✗ | — |
| ② | `KB_ROOT` set + exists | ✗ | Hint: set env var |
| ③ | At least one domain folder | ✗ | Hint: create a folder |
| ④ | `domain_config.yaml` present per domain | ✓ | `kb-agent-generate --domain <name> --no-llm --yes` |
| ⑤ | ChromaDB collection non-empty per domain (+ version mismatch branch) | ✓ | `kb-agent-generate --domain <name> --no-llm --yes` / delete index |
| ⑥ | Embedding model cached | ✓ | `_ensure_embedding_model()` (~80 MB download) |
| ⑦ | LLM reachable (or passthrough) | ✗ | Hint: start Ollama or set provider |
| ⑧ | `kb-agent-serve` on PATH | ✗ | Hint: check pip install / PATH |
| ⑨ | Bob skill installed | ✓ | `kb-agent-generate --no-llm --yes` |

`--fix` calls `fix_fn()` for each fixable failure, then re-runs all checks.
`stale_file_count()` uses `STALE_DAYS = 7` constant shared with `status.py`.

---

### `cli/status.py`
Read-only status dashboard (`kb-agent-status`). Renders a Rich table — zero side effects.

Rich table columns:

| Column | Source |
|---|---|
| Domain | `kb_root.iterdir()` filtered by `cfg.is_ignored()` |
| Files | `rglob` count of indexable extensions (via `file_parser.INCLUDE_EXTS`) |
| Indexed | `indexed_at_iso` from ChromaDB metadata (falls back to `indexed_at` float) |
| Age | days since `indexed_at` |
| Docs | `col.count()` — ChromaDB document count |
| YAML | ✓ / ✗ — presence of `domain_config.yaml` |
| Status | `fresh` / `stale (>7 d)` / `empty index` / `DB mismatch` |

Footer shows: LLM provider, embedding model (cached/not), absolute `kb-agent-serve` path,
Bob skill presence.

Flags:
- `--diff` — show stale / missing files per domain (per-file breakdown)
- `--json` — machine-readable JSON output (scriptable)
- `--plain` — no ANSI colours (CI / log capture)
- `--tui` — live-refresh table with `rich.live.Live` (Ctrl+C to quit)
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

---

## Security gate

### Overview

`kb_agent_mcp/security_gate.py` implements a **patentable anti-trick gate** that
prevents a malicious document from self-authorising access to confidential content.

The key mechanism: the acknowledgement token is generated **at call time** — it
cannot exist inside any document that was indexed before `check_confidential()` was
called. A prompt-injection attack (a document that says "token is ABCD1234") cannot
succeed because the correct token only materialises in the live terminal/chat after
the scan, never inside indexed text.

### Classification pipeline

Five signal sources are checked in priority order; the first match wins.

| Priority | Source | Mechanism |
|---|---|---|
| 1 | EML `Sensitivity:` header | `email.message_from_bytes()` → header value in `_EML_SENSITIVE_VALUES` |
| 2 | PDF `/Keywords` + `/Subject` | `pypdf.PdfReader.metadata` → `_CONFIDENTIAL_RE` keyword scan |
| 3 | DOCX core properties | `docProps/core.xml` inside zip → `_CONFIDENTIAL_RE` scan |
| 4 | File path / filename | Full path string, `_` and `-` normalised to spaces → `_CONFIDENTIAL_RE` |
| 5 | Text body | First `KB_BUDGET_RAG_FILE` chars of extracted text → `_CONFIDENTIAL_RE` |

`_CONFIDENTIAL_RE` matches (case-insensitive, word-bounded) 16 keywords:
`confidential`, `internal use only`, `not for distribution`, `not for sharing`,
`do not share`, `do not distribute`, `proprietary`, `restricted`, `privileged`,
`ibm confidential`, `company confidential`, `for internal use`, `classification:`,
`sensitive`, `top secret`, `private and confidential`.

The path classifier normalises `_` and `-` to spaces before scanning so that
filenames like `ibm_confidential_doc.pdf` are detected correctly despite `\b`
word boundaries not firing around underscore characters.

### `.noindex` sentinel — hard exclusion

A file named `.noindex` placed in any subfolder hard-excludes **all files** in that
folder and every nested subfolder. This is enforced in two independent places:

- **`security_gate.scan_domain()`** — `.noindex`-covered files are skipped before
  `classify_confidential()` is called; they never appear in scan results.
- **`file_parser.should_skip()`** — `_has_noindex_ancestor()` returns `True` for
  any file under a `.noindex` ancestor; the file is never extracted during indexing.

Because both enforcement points are independent, even if the scan were bypassed the
file would still be absent from the vector index.

### Acknowledgement flow (per-session)

```
User (or AI tool)
│
├── check_confidential(session_id)
│     ├── scan_all_domains()
│     │   └── for each domain:
│     │       └── scan_domain(name)
│     │             ├── skip .noindex files
│     │             └── classify_confidential(file) → (True, reason) or (False, "")
│     │
│     ├── [no confidential files found]
│     │     save GateSession(status="clear")
│     │     return "✅ Security gate: clear."
│     │
│     └── [confidential files found]
│           token = generate_ack_token()   ← secrets.token_hex(4).upper()
│           save GateSession(status="blocked", ack_token=token, files=[…])
│           return "⛔ Gate activated.  Token: <TOKEN>"
│                  ↑ user reads this in the chat — no document can forge it
│
├── acknowledge_gate(session_id, token)
│     ├── load_gate_session(session_id)
│     ├── validate_ack_token(stored, provided)
│     │     └── hmac.compare_digest(stored.upper(), provided.upper())
│     │                             (constant-time — no timing oracle)
│     ├── [token wrong]  return "❌ Wrong token."
│     └── [token correct]
│           save GateSession(status="acknowledged", acknowledged_at=now)
│           return "✅ Gate cleared."
│
└── ask(question, session_id)   ← all subsequent calls
      ├── is_gate_acknowledged(session_id)
      │     └── [not acknowledged AND status==blocked]
      │           return "⛔ Security gate is active…"  (refuses to answer)
      └── [clear or acknowledged]
            → normal orchestrator dispatch
```

### Per-file enforcement in `base_agent.ask()`

When the gate has been acknowledged, `base_agent.ask()` still applies per-file
access control to every retrieved chunk:

| Gate state | File classified confidential | Behaviour |
|---|---|---|
| disabled | — | File content included, no decoration |
| `blocked` | yes | Answer refused entirely at `server.ask()` |
| `acknowledged` | yes | Content included; citation prefixed with `🔒` |
| `clear` | no confidential files exist | Normal answer, no prefix |

### Gate session persistence

Sessions are stored in `{KB_ROOT}/.kb_index/gate_sessions.json` as a flat JSON
dict keyed by `session_id`. Each entry is a serialised `GateSession` dataclass:

```json
{
  "my-session": {
    "session_id": "my-session",
    "status": "acknowledged",
    "ack_token": "B7E2A3F1",
    "confidential_files": [
      { "domain": "BizOps", "relative_path": "BizOps/internal_revenue.xlsx",
        "filename": "internal_revenue.xlsx", "reason": "filename / folder path" }
    ],
    "created_at": 1720000000.0,
    "acknowledged_at": 1720000042.0
  }
}
```

`reindex()` calls `clear_all_gate_sessions()` — every session must re-acknowledge
against the refreshed file inventory after a full rebuild.

### Key design invariants

1. **Token cannot be pre-planted** — generated after indexing, never stored in a
   document, surfaces only in the live chat response.
2. **Constant-time comparison** — `hmac.compare_digest` prevents timing oracle.
3. **Dual-enforcement** — `.noindex` exclusion at both scan time and index time.
4. **Reindex invalidation** — gate sessions are wiped on every full reindex.
5. **Gate bypass when disabled** — `KB_SECURITY_GATE_ENABLED=false` makes
   `is_gate_acknowledged()` always return `True`; no disk I/O on the hot path.

---

## System boundary map

```
┌─────────────────────────────────────────────────────────────────────────┐
│  MCP HOST PROCESS  (Claude Desktop / Bob / Cursor / custom client)      │
│                                                                         │
│   [AI Model]  ←──── tool responses ────  [MCP Client SDK]              │
│       │                                           ↑                    │
│       └──────── tool calls (JSON) ────────────────┘                    │
└──────────────────────────────────┬────────────────────────────────────-┘
                                   │  stdio (pipe) or HTTP/SSE
┌──────────────────────────────────▼──────────────────────────────────────┐
│  kb-agent-serve  (FastMCP server process)                               │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  server.py  (14 MCP tools)                                      │   │
│  │  ┌──────────┐ ┌─────────────┐ ┌────────────────┐ ┌──────────┐  │   │
│  │  │  ask()   │ │list_domains │ │   reindex()    │ │ memory   │  │   │
│  │  └─────┬────┘ └──────┬──────┘ └───────┬────────┘ └──────────┘  │   │
│  │        │             │                │                          │   │
│  │  ┌─────▼─────────────▼────────────────▼──────────────────────┐  │   │
│  │  │  check_confidential()    acknowledge_gate()                │  │   │
│  │  │  (Security Gate tools)                                     │  │   │
│  │  └─────────────────────────────────────────────────────────-─┘  │   │
│  │                                                                  │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  Data Analyst tools                                        │  │   │
│  │  │  analyze_file  suggest_questions  query_data  refine_query │  │   │
│  │  └───────────────────────┬────────────────────────────────────┘  │   │
│  │                                                                  │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  Session & Feedback tools                                  │  │   │
│  │  │  domain_status  read_audit  resume_session                 │  │   │
│  │  │  rate_answer    update_document                            │  │   │
│  │  └───────────────────────┬────────────────────────────────────┘  │   │
│  └──────────────────────────┼────────────────────────────────────-──┘   │
│                             │                                            │
│  ┌──────────────────────────▼──────────────────────────────────────┐   │
│  │  orchestrator.py                                                │   │
│  │  keyword_confidence → LLM classify → asyncio.gather(agents)     │   │
│  └────────────┬──────────────────────────────┬─────────────────────┘   │
│               │                              │                          │
│  ┌────────────▼──────────┐      ┌────────────▼──────────┐             │
│  │  domain_agent.py (×N) │ ···  │  domain_agent.py (×N) │             │
│  │  DomainAgent.run()    │      │  DomainAgent.run()    │             │
│  └────────────┬──────────┘      └────────────┬──────────┘             │
│               │                              │                          │
│  ┌────────────▼──────────────────────────────▼─────────────────────┐   │
│  │  base_agent.py                                                   │   │
│  │  README-first → RAG fallback → LLM call / passthrough block     │   │
│  └────────┬───────────────────────────────────────┬────────────────┘   │
│           │                                       │                     │
│  ┌────────▼──────────┐              ┌─────────────▼─────────────────┐  │
│  │  vector_store.py  │              │  file_parser.py               │  │
│  │  ChromaDB client  │              │  multi-format text extractor  │  │
│  └────────┬──────────┘              └───────────────────────────────┘  │
│           │                                                              │
│  ┌────────▼──────────┐   ┌────────────────┐   ┌──────────────────────┐ │
│  │  embeddings.py    │   │   memory.py    │   │  security_gate.py    │ │
│  │  2-tier fallback  │   │  session JSON  │   │  classify / gate     │ │
│  └────────┬──────────┘   └───────────────-┘   └──────────────────────┘ │
└───────────┼─────────────────────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────────────────────────────────────────┐
│  FILESYSTEM  (KB_ROOT)                                                 │
│                                                                        │
│  {KB_ROOT}/                                                            │
│    <Domain A>/   PDF DOCX XLSX MD …   domain_config.yaml              │
│    <Domain B>/   …                    domain_config.yaml              │
│    .kb_index/                                                          │
│      chroma/            ChromaDB collections (embeddings + metadata)  │
│      session_memory/    <session_id>.json                             │
│      analyst_sessions/  <session_id>.json                             │
│      gate_sessions.json gate state per session                        │
└────────────────────────────────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────────────────────────────────────────┐
│  EXTERNAL SERVICES  (optional — zero calls in passthrough/Ollama mode) │
│                                                                        │
│  Ollama API   http://localhost:11434   /api/chat  /api/embeddings      │
│  OpenAI API   https://api.openai.com   /chat/completions  /embeddings  │
│  Anthropic    https://api.anthropic.com  /v1/messages                 │
│  Custom       any OpenAI-compatible URL                                │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Inter-module import graph

```
server.py
├── config.py  (cfg singleton)
├── orchestrator.py
│   ├── config.py
│   ├── domain_agent.py
│   │   ├── config.py
│   │   ├── base_agent.py
│   │   │   ├── config.py
│   │   │   ├── vector_store.py  ──→  embeddings.py ──→  config.py
│   │   │   ├── file_parser.py   ──→  config.py
│   │   │   ├── memory.py        ──→  config.py
│   │   │   └── context_budget.py ──→ config.py
│   │   └── domain_rules.py  ──→  config.py
│   ├── aggregator.py  ──→  config.py
│   └── context_budget.py
├── security_gate.py
│   ├── config.py
│   └── file_parser.py  (for _has_noindex_ancestor, _extract_sync)
├── audit.py     ──→  config.py
├── feedback.py  ──→  config.py
├── writeback.py ──→  config.py
└── analyst/
    ├── inspector.py  ──→  file_parser.py
    ├── planner.py    (pure logic, no imports except dataclasses)
    ├── engine.py     ──→  inspector.py, session.py, config.py
    └── session.py    ──→  config.py

cli/
├── main.py      ──→  setup.py, generate.py, server.py, watch.py, doctor.py, status.py
├── setup.py     ──→  generate.py, config.py
├── generate.py  ──→  vector_store.py, embeddings.py, domain_rules.py, config.py
├── watch.py     ──→  vector_store.py, generate.py, config.py
├── doctor.py    ──→  vector_store.py, embeddings.py, config.py
└── status.py    ──→  vector_store.py, config.py
```

All modules import `config.cfg` at module load time (frozen dataclass singleton).
No circular imports — `config.py` has no imports from the package.
`security_gate.py` imports `file_parser._has_noindex_ancestor` and
`file_parser._extract_sync`; `file_parser.py` does not import `security_gate.py`.

---

## Environment variable reference

| Variable | Default | Module | Description |
|---|---|---|---|
| `KB_ROOT` | CWD | `config.py` | Absolute path to the knowledge base root directory |
| `KB_IGNORE_FOLDERS` | _(empty)_ | `config.py` | Comma-separated extra folder names to skip during discovery |
| `KB_LLM_PROVIDER` | `ollama` | `config.py` | LLM provider: `ollama` \| `openai` \| `anthropic` \| `custom` \| `passthrough` |
| `KB_LLM_BASE_URL` | `http://localhost:11434` | `config.py` | Base URL for the LLM API endpoint |
| `KB_MODEL` | `qwen3:14b` | `config.py` | Model name used for Q&A and intent classification |
| `KB_API_KEY` | _(empty)_ | `config.py` | API key for OpenAI / Anthropic / custom providers |
| `KB_PASSTHROUGH_FALLBACK` | `true` | `config.py` | Auto-switch to passthrough when Ollama is unreachable |
| `KB_LLM_PROVIDER_GENERATE` | _(empty)_ | `config.py` | Override provider used by `kb-agent-generate` (written by setup wizard) |
| `KB_EMBED_MODEL` | _(auto)_ | `config.py` | Embedding model; auto-detected from provider if blank |
| `KB_BUDGET_TOTAL` | `24000` | `context_budget.py` | Hard character ceiling for all LLM context |
| `KB_BUDGET_INDEX` | `8000` | `context_budget.py` | README index block budget (simple questions) |
| `KB_BUDGET_FULL_README` | `24000` | `context_budget.py` | Full README budget (complex questions) |
| `KB_BUDGET_PRE_INDEX` | `2000` | `context_budget.py` | Hand-written README intro budget |
| `KB_BUDGET_RAG_FILE` | `4000` | `context_budget.py` | Max chars per file in RAG fallback and gate scan |
| `KB_BUDGET_SUMMARY` | `500` | `context_budget.py` | Per-file summary line budget in AUTO-INDEX table |
| `KB_BUDGET_EMBED_CHARS` | `3500` | `embeddings.py` | Max chars of text sent to embedding endpoint |
| `KB_MIN_README_CHARS` | `200` | `base_agent.py` | README below this length is treated as absent |
| `KB_NUM_CTX` | `32768` | `base_agent.py` | Ollama `num_ctx` parameter |
| `KB_SESSION_TIMEOUT_HOURS` | `2` | `memory.py` | Session auto-expiry in hours |
| `KB_SESSION_MAX_TURNS` | `20` | `memory.py` | Max turns retained per session |
| `KB_SESSION_MAX_ANSWER_CHARS` | `400` | `memory.py` | Answer characters stored in session history |
| `KB_STALE_CHECK_TTL_SECONDS` | `60` | `server.py` | Seconds between mtime scans in `ask()` (0 = disabled) |
| `KB_BUDGET_PASSTHROUGH_THRESHOLD` | `0.8` | `orchestrator.py` | Fraction of `KB_BUDGET_TOTAL` that triggers `top_n` reduction in passthrough mode |
| `KB_FORMAT_DEFAULT` | _(empty)_ | `server.py` | Default output format when none is specified |
| `KB_SECURITY_GATE_ENABLED` | `true` | `security_gate.py` | Set to `false` to disable the confidentiality gate entirely |
| `KB_DEFAULT_SESSION_ID` | `"default"` | `server.py` | Session ID used when no `session_id` is passed in stdio transport mode |
| `KB_AUDIT_ENABLED` | `true` | `audit.py` | Set to `false` to disable audit logging entirely |
| `KB_AUDIT_MAX_MB` | `10` | `audit.py` | Maximum size of `audit.jsonl` in MB before rotation |
| `KB_OCR_ENABLED` | `false` | `file_parser.py` | Set to `true` to enable image text extraction via OCR |
| `KB_OCR_ENGINE` | `"tesseract"` | `file_parser.py` | OCR engine to use: `tesseract` \| `easyocr` |

`.env` search order: CWD → `$HOME` → `KB_ROOT` → package root.
Values already in the environment are never overwritten.

---

## Backward compatibility — `agents/` layer

The original `agents/` directory is retained unchanged alongside `kb_agent_mcp/`.
Both systems can run independently from the same `KB_ROOT`.

| Component | Path | Status |
|---|---|---|
| Legacy CLI | `agents/agent_knowledgebase.py` | Still works; reads same `.kb_index/` |
| Ingest script | `agents/ingest.py` | Still works; writes JSON context files |
| Setup shim | `scripts/setup.py` | Thin shim → `kb_agent_mcp.cli.setup` |
| Bob skill | `agents/SKILL.md` | Active; points at legacy agent |
| MCP server | `kb_agent_mcp/server.py` | New canonical entry point |
| Bob skill (MCP) | `~/.bob/skills/knowledgebase-agent/SKILL.md` | Generated by `kb-agent-generate` |

The security gate (`security_gate.py`) is implemented only in `kb_agent_mcp/`.
Legacy `agents/` queries bypass the gate — this is intentional for backward
compatibility and does not affect MCP-based deployments.
