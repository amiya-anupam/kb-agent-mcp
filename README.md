# kb-agent-mcp

A zero-config, pip-installable MCP server that turns **any folder of documents** into a queryable, multi-agent knowledge base.

Connect it to Claude Desktop, Bob, Cursor, or any MCP-compatible AI tool — then ask questions in natural language.

---

## What is `kb-agent-mcp`?

It's all three — depending on which layer you're looking at.

- **A Package / Product** — Published to PyPI (`pip install kb-agent-mcp`). Versioned, with entry-point CLI scripts, optional extras, and a full release lifecycle.
- **An Agent** — A multi-domain RAG agent that routes user queries across knowledge domains, synthesises context from indexed documents, and uses an LLM (local or passthrough) to generate answers.
- **An MCP Server / Skill** — From the perspective of Bob, Claude, or Cursor, it surfaces as a pluggable MCP server. To a host AI, it is a skill.

> **One-line definition:** *"A multi-domain knowledge agent packaged as an MCP server."*

---

## Features

- **Zero configuration** — point at a folder, run one command, start asking questions
- **Multi-domain routing** — automatically routes questions to the right knowledge domain
- **README-first RAG** — uses compact AUTO-INDEX blocks for fast answers; falls back to full-document search for complex/data questions
- **Passthrough mode** — works with *no local LLM*; your AI tool answers using retrieved context
- **Supports all major document types** — PDF, DOCX, XLSX (with streaming aggregation for large files), PPTX, MD, TXT, CSV, BoxNote, and images (PNG, JPG, GIF, WebP via OCR)
- **Source citations** — every answer includes inline `[Source: …]` citations linking back to the source file
- **Cross-domain aggregation** — multi-domain questions produce a single synthesised answer
- **ChromaDB vector search** — persistent, hash-based change detection (only re-indexes changed files)
- **Multi-session memory** — per-session conversation history with configurable timeout
- **Session resume** — resume any prior session without re-querying via `resume_session`
- **Audit log** — every `ask()` call is appended to `.kb_index/audit.jsonl` for traceability
- **Answer ratings** — rate individual answers 1–5 stars via `rate_answer`; persisted to `.kb_index/feedback.jsonl`
- **Document write-back** — update or append to documents in your KB directly from the AI tool via `update_document`
- **Hot-reload** — `kb-agent-watch` keeps indexes in sync as you add/modify files
- **LLM providers** — Ollama (local), OpenAI, Anthropic, any OpenAI-compatible endpoint

---

## Quick Start

```bash
# Install
pip install kb-agent-mcp

# First-time setup (recommended) — runs setup → generate → doctor in one step
cd /path/to/your/documents
kb-agent init

# Or run each step separately
kb-agent-setup      # interactive wizard
kb-agent-generate   # build indexes + domain configs

# Start the MCP server (stdio — for Claude Desktop / Bob)
kb-agent-serve

# Or HTTP/SSE
kb-agent-serve --transport http --port 8765
```

---

## Installation

> **Build tools required on macOS and Linux.**
> `chromadb` compiles native C++ bindings at install time.
> `kb-agent-setup` checks for build tools before running and prints the exact
> fix command if they are missing — but installing them first is faster.
>
> - **macOS:** `xcode-select --install`
> - **Linux (Debian/Ubuntu):** `sudo apt install build-essential python3-dev`
> - **Windows:** No extra steps needed.

```bash
pip install kb-agent-mcp

# With OpenAI embeddings
pip install "kb-agent-mcp[openai]"

# With Anthropic
pip install "kb-agent-mcp[anthropic]"

# For development
pip install "kb-agent-mcp[dev]"
```

Requires Python 3.10+.

---

## MCP Tools

Once the server is running, the following **fourteen tools** are available in four groups:

### Knowledge Base tools (5)

| Tool | Description |
|---|---|
| `ask(question, format?, session_id?)` | Query all relevant domains and return a markdown answer |
| `list_domains()` | List indexed knowledge domains with descriptions |
| `reindex()` | Re-scan KB_ROOT and rebuild ChromaDB indexes |
| `clear_memory(session_id?)` | Clear conversation history for a session |
| `show_memory(session_id?)` | Show current session state and recent history |

### Security Gate tools (2)

| Tool | Description |
|---|---|
| `check_confidential(session_id?)` | Scan all domains for confidential-flagged files. Returns a one-time token if any are found. |
| `acknowledge_gate(session_id, token)` | Unlock the gate for a session by supplying the token from `check_confidential()`. |

### Data Analyst tools (4)

| Tool | Description |
|---|---|
| `analyze_file(path)` | Profile any file → returns a DataCard (schema, column types, grain, themes, warnings) |
| `suggest_questions(path)` | Returns a menu of analytical questions grouped by theme |
| `query_data(path, question, session_id?)` | Computes the answer with full reasoning |
| `refine_query(session_id, feedback)` | Re-runs the last query using updated parameters from your feedback |

Supported file formats: `.xlsx` `.xls` `.csv` `.json` `.jsonl` `.pdf` `.docx` `.pptx` `.txt` `.md`

### Session & Feedback tools (5)

| Tool | Description |
|---|---|
| `domain_status()` | Returns per-domain indexing status: file counts, stale counts, and last-indexed timestamps |
| `read_audit(session_id?, limit?)` | Returns recent audit log entries from `.kb_index/audit.jsonl` |
| `resume_session(session_id)` | Returns the last N turns of a prior session |
| `rate_answer(session_id, turn_index, rating, comment?)` | Records a 1–5 star rating for a specific answer turn |
| `update_document(rel_path, content, mode?)` | Writes or appends to a document under `KB_ROOT` |

### `ask` examples

```
ask("What is IBM ACE?")
ask("What is our Q3 revenue by product?", format="table")
ask("Explain the architecture of CP4I", format="bullets")
ask("How many deals closed last quarter?", session_id="my-session")
```

### `query_data` examples

```
query_data("BizOps/Revenue.xlsx", "What are the top 10 customers by revenue in FY2025?")
query_data("BizOps/Revenue.xlsx", "Which customers churned compared to last year?", session_id="analyst-1")
refine_query("analyst-1", "Show only the Americas region")
```

---

## Configuration

All configuration is via environment variables (or a `.env` file):

```env
# Required
KB_ROOT=/path/to/your/KnowledgeBase

# LLM provider (default: ollama)
KB_LLM_PROVIDER=ollama          # ollama | openai | anthropic | custom | passthrough
KB_LLM_BASE_URL=http://localhost:11434
KB_MODEL=qwen3:14b
KB_API_KEY=                     # required for openai/anthropic/custom

# Embeddings
KB_EMBED_MODEL=                 # auto-detected from provider; or set explicitly

# Context budgets (chars, ~4 chars = 1 token)
KB_BUDGET_TOTAL=24000
KB_BUDGET_INDEX=8000
KB_BUDGET_FULL_README=24000
KB_BUDGET_RAG_FILE=4000

# Session memory
KB_SESSION_TIMEOUT_HOURS=2
KB_SESSION_MAX_TURNS=20
KB_SESSION_MAX_ANSWER_CHARS=400

# Security gate (default: enabled)
KB_SECURITY_GATE_ENABLED=true

# Audit log
KB_AUDIT_ENABLED=true
KB_AUDIT_MAX_MB=10

# Stale file detection
KB_STALE_DAYS=90               # days before flagging a file as stale (0 = disabled)

# Passthrough fallback
KB_PASSTHROUGH_FALLBACK=true   # auto-switch to passthrough when Ollama unreachable

# Image OCR (disabled by default — requires tesseract or easyocr)
KB_OCR_ENABLED=false
KB_OCR_ENGINE=tesseract        # tesseract | easyocr

# Ignore these top-level folders
KB_IGNORE_FOLDERS=archive,tmp
```

### Token budget variables

All token-affecting limits are tunable via env vars — no code changes needed:

| Variable | Default | Tokens (~) | Description |
|---|---|---|---|
| `KB_BUDGET_TOTAL` | `24000` chars | ~6,000 | Hard ceiling — any context sent to any LLM |
| `KB_BUDGET_INDEX` | `8000` chars | ~2,000 | README index block (simple-query context) |
| `KB_BUDGET_FULL_README` | `24000` chars | ~6,000 | Full README (complex-query context) |
| `KB_BUDGET_PRE_INDEX` | `2000` chars | ~500 | Hand-written README intro prepended to index |
| `KB_BUDGET_RAG_FILE` | `4000` chars | ~1,000 | Max chars extracted per file in RAG fallback |
| `KB_BUDGET_SUMMARY` | `100` chars | ~25 | Per-file summary line in the AUTO-INDEX table |
| `KB_BUDGET_HISTORY` | `4` turns | — | Conversation history turns sent with each request |

---

## LLM Providers

| Provider | `KB_LLM_PROVIDER` | Notes |
|---|---|---|
| Ollama (local) | `ollama` | Default. Run `ollama serve` first. |
| OpenAI | `openai` | Set `KB_API_KEY=sk-...` in `.env` |
| Anthropic | `anthropic` | Set `KB_API_KEY=...` in `.env` |
| LM Studio / Jan | `custom` | Set `KB_LLM_BASE_URL` to your local server URL |
| None (passthrough) | `passthrough` | Bob's Claude answers using retrieved context |

**No LLM?** No problem. Set `KB_LLM_PROVIDER=passthrough` or just leave Ollama stopped.
Embeddings fall back to `sentence-transformers` (offline, ~80 MB download on first use).

---

## Passthrough Mode

When `KB_LLM_PROVIDER=passthrough` (or when Ollama is unreachable and `KB_PASSTHROUGH_FALLBACK` is not `false`), the server returns the retrieved document context as clean markdown:

```markdown
> **No local LLM detected.** Retrieved context is provided below —
> use it to answer the question.

### BizOps Agent
*Source: BizOps/Revenue.xlsx*

Q1 revenue: $1.2M
Q2 revenue: $1.5M
```

The calling AI tool receives this from the `ask` tool and answers from the context — no special parsing needed.

To disable the automatic fallback (hard-fail instead):
```env
KB_PASSTHROUGH_FALLBACK=false
```

---

## Folder Structure

Each top-level folder under `KB_ROOT` becomes a **knowledge domain**:

```
~/KnowledgeBase/
  ACE Docs/          ← domain "ACE Docs"
    Installation.pdf
    API Reference.md
    domain_config.yaml   ← generated by kb-agent-generate
  BizOps/            ← domain "BizOps"
    Revenue.xlsx
    Won Deals.xlsx
    domain_config.yaml
  .kb_index/         ← auto-created by kb-agent-generate
    chroma/                  ChromaDB vector index
    session_memory/          per-session conversation history
    analyst_sessions/        per-session analyst state
    audit.jsonl              append-only log of every ask() call
    feedback.jsonl           per-answer ratings from rate_answer()
```

Files in nested subfolders are indexed into their parent domain.

---

## `domain_config.yaml`

Generated by `kb-agent-generate`, one per domain folder. Edit manually to tune the agent:

```yaml
folder_name: BizOps
agent_name: BizOps Agent
description: Business operations — CP4I and ACE revenue, won deals, renewals
keywords:
  - revenue
  - quota
  - attainment
top_n: 5
max_chars: 8000
system_prompt: |
  You are the BizOps Agent, a specialist in IBM APC region business data.
  Be concise, accurate, and cite the source file.
retrieval_rules:
  pin_files:
    - "*Revenue*.xlsx"
  boost_keywords:
    - revenue
  question_classifier:
    data_patterns:
      - "\\brevenue\\b"
    complex_patterns: []
```

---

## CLI Commands

### Unified entry point

| Command | Description |
|---|---|
| `kb-agent init` | First-time setup: runs setup → generate → doctor in sequence |
| `kb-agent setup` | Interactive setup wizard |
| `kb-agent generate` | Build ChromaDB indexes + generate `domain_config.yaml` |
| `kb-agent serve` | Start the MCP server |
| `kb-agent watch` | Watch for file changes and auto-update indexes |
| `kb-agent doctor` | Run a health checklist to diagnose problems |
| `kb-agent status` | Show a live system-health dashboard (indexes, LLM, memory) |

### Legacy standalone commands (still available)

| Command | Description |
|---|---|
| `kb-agent-setup` | Interactive setup wizard |
| `kb-agent-generate` | Build ChromaDB indexes + generate `domain_config.yaml` |
| `kb-agent-serve` | Start the MCP server |
| `kb-agent-watch` | Watch for file changes and auto-update indexes |
| `kb-agent-doctor` | Run a health checklist to diagnose problems |
| `kb-agent-status` | Show a live system-health dashboard |

### Flags

```bash
# generate
kb-agent-generate               # incremental — skip unchanged
kb-agent-generate --force       # regenerate all domain_config.yaml files
kb-agent-generate --no-llm      # index only, use minimal YAML defaults
kb-agent-generate --domain Foo  # only process the "Foo" folder

# serve
kb-agent-serve                           # stdio (Claude Desktop / Bob)
kb-agent-serve --transport http          # HTTP/SSE on port 8765
kb-agent-serve --transport http --port 9000
kb-agent-serve --version

# setup
kb-agent-setup --yes                     # non-interactive, passthrough by default
kb-agent-setup --kb-root /absolute/path
```

### When `kb-agent-generate` is triggered

| Trigger | When |
|---|---|
| `kb-agent-generate` | Manually — run after first setup or to pick up new documents |
| `kb-agent-watch` (automatic) | Triggers incrementally on every file change |
| `python3 scripts/generate.py` | Legacy alias — delegates to `kb-agent-generate` |

---

## Connecting to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "kb-agent-serve",
      "env": {
        "KB_ROOT": "/path/to/your/KnowledgeBase"
      }
    }
  }
}
```

> `kb-agent-setup` prints a ready-to-paste config block — copy it directly from the wizard output.

---

## Connecting to Bob

After running `kb-agent-generate`, a SKILL.md is auto-installed at:

```
~/.bob/skills/knowledgebase-agent/SKILL.md
```

Bob will automatically load it. Configure the server in your Bob MCP settings with:

```json
{
  "command": "/absolute/path/to/kb-agent-serve",
  "env": { "KB_ROOT": "/path/to/your/KnowledgeBase" }
}
```

> Use the **absolute path** for `"command"` — run `which kb-agent-serve` if needed.

---

## Watcher (auto-update on file changes)

```bash
kb-agent-watch
# or legacy:
python3 scripts/watch_kb.py
```

Watches `KB_ROOT` for filesystem events and keeps everything in sync.

| Event | What happens |
|---|---|
| File added / modified / deleted | Re-embeds, updates index, rewrites README AUTO-INDEX block |
| New top-level folder created | Triggers `kb-agent-generate` automatically |
| Folder deleted | Removes index and domain metadata |
| Folder renamed | Renames index, re-keys domain metadata |

Stale file alerts print a warning for each file over the `KB_STALE_DAYS` threshold (default 90 days).

> **macOS note:** The watcher runs as a `launchd` daemon (`com.knowledgebase.watcher`).
> Restart with `launchctl stop/start com.knowledgebase.watcher`.

---

## CLI Usage (legacy agents layer)

```bash
# Single question
python3 agents/agent_knowledgebase.py "your question"

# Interactive chat
python3 agents/agent_knowledgebase.py

# Clear conversation memory
python3 agents/agent_knowledgebase.py --clear

# Show memory summary
python3 agents/agent_knowledgebase.py --memory

# Control answer format
python3 agents/agent_knowledgebase.py "What does CP4I include?" --format table
python3 agents/agent_knowledgebase.py "List ACE deployment steps" --format bullets
python3 agents/agent_knowledgebase.py "What is the ACE toolkit?"  --format oneline
python3 agents/agent_knowledgebase.py "Show renewal data"         --format json
```

| Format | Aliases | Output style |
|---|---|---|
| `table` | — | Markdown table with headers |
| `bullets` | `bullet`, `list` | Markdown bullet list |
| `oneline` | `1line`, `one-liner` | Exactly one sentence |
| `paragraph` | `prose`, `paragraphs` | Prose paragraphs (default) |
| `numbered` | `num`, `numbered-list` | Numbered Markdown list |
| `json` | — | Raw JSON, no fences |

---

## 🔒 Security & Privacy

### Data residency — what leaves your machine

| Operation | Goes to | Condition |
|---|---|---|
| Indexing (`kb-agent-generate`) | **Nowhere** — 100% local | Always |
| Q&A via local LLM (Ollama) | **Nowhere** | When Ollama is running |
| Q&A via cloud LLM (passthrough / OpenAI / Anthropic) | Remote cloud API | When `KB_LLM_PROVIDER` ≠ `ollama` or Ollama is unreachable |

> Use `KB_PASSTHROUGH_FALLBACK=false` to prevent silent fallback to passthrough.

### MCP security gate

The server implements an **anti-trick confidentiality gate** (`kb_agent_mcp/security_gate.py`). The token is generated **at call time** — no document can contain the correct value, preventing prompt-injection attacks.

**Workflow:**
1. Call `check_confidential(session_id)` — if flagged files are found, a one-time 8-character hex token is printed in the chat.
2. Call `acknowledge_gate(session_id, token)` — type the token shown in step 1. Subsequent `ask()` calls include confidential content with a `🔒` prefix on citations from flagged files.
3. If no confidential files exist, `check_confidential` returns "✅ clear".

**`.noindex` sentinel — hard exclusion:**

Place an empty file named `.noindex` inside any subfolder to hard-exclude all files in that folder and every nested subfolder from indexing and scanning.

```
~/KnowledgeBase/
  secrets/
    .noindex             ← drop this empty file here
    my-passwords.txt     ← never indexed, never scanned, never in context
```

**Disable the gate:**
```env
KB_SECURITY_GATE_ENABLED=false
```

---

## Architecture

> For the complete technical reference — module descriptions, call graphs, data-flow diagrams — see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

### System overview

```
AI tool (Claude, Bob, Cursor, …)
        │   MCP protocol
        ▼
┌───────────────────────────────────────────────────────────────┐
│  server.py  (FastMCP — 14 tools)                              │
├──────────────────────────┬────────────────────────────────────┤
│  Knowledge Base (5)      │  Data Analyst (4)                  │
│  ask()                   │  analyze_file()                    │
│  list_domains()          │  suggest_questions()               │
│  reindex()               │  query_data()                      │
│  clear_memory()          │  refine_query()                    │
│  show_memory()           │                                    │
└──────────┬───────────────┴──────────────┬─────────────────────┘
           │                              │
           ▼                              ▼
  ┌─────────────────┐          ┌──────────────────────┐
  │ orchestrator.py │          │ analyst/             │
  │ route→dispatch  │          │   inspector.py       │
  └────────┬────────┘          │   planner.py         │
           │                   │   engine.py          │
           ▼                   │   session.py         │
  ┌─────────────────┐          └──────────────────────┘
  │ domain_agent.py │
  │ base_agent.py   │
  │ vector_store.py │
  │ ChromaDB index  │
  └─────────────────┘
```

### Token consumption — online vs. offline

| Component | Passthrough | Local LLM (Ollama) |
|---|---|---|
| `classify_intent()` | — skipped | ~120 tok |
| System prompt | ~48 tok | ~48 tok |
| Conversation history (4 turns) | 0 tok | ~200 tok |
| Retrieved context | domain-specific | domain-specific |
| User question | ~25 tok | ~25 tok |

**README index mode saves 48–77% tokens** vs. raw-file RAG fallback.

---

## `context_budget.py` — Token Compaction Engine

`context_budget.py` is the single source of truth for all token-affecting decisions.

### Adding a new collapse group

Add to your `.env` (no code changes needed):

```bash
# Single rule
KB_COLLAPSE_PATTERNS=Weekly_Report|weekly reports|Weekly status reports ({n} files)

# Multiple rules separated by ;;
KB_COLLAPSE_PATTERNS=EPM2-004|EPM snapshots|Weekly files for {quarters} ({n} files);;^Screenshot|screenshots|Snapshot images ({n} files)
```

Format: `regex_pattern|label|description_template`
- `{n}` — number of matched files
- `{quarters}` — quarter codes extracted from filenames (e.g. `Q126, Q226`)

---

## Development

```bash
git clone https://github.com/amiya-anupam/kb-agent-mcp.git ~/KnowledgeBase
cd ~/KnowledgeBase
pip install -e ".[dev]"
pytest tests/ -q
```

---

## Releasing

Merging to `main` triggers the CI/CD pipeline, which automatically:

1. Bumps the **patch** version in `pyproject.toml` (e.g. `0.1.0` → `0.1.1`)
2. Commits the bump back to `main` with `[skip ci]` to prevent re-triggering
3. Builds the wheel + source distribution
4. Publishes to PyPI as `kb-agent-mcp`

For a **minor** or **major** version bump, manually edit `version` in `pyproject.toml` in your PR before merging.

---

## Troubleshooting

`kb-agent-setup` (and `kb-agent init`) automatically runs `kb-agent-doctor` at the end of setup. Re-run it at any time:

```bash
kb-agent doctor
```

Pass `--fix` to automatically apply safe repairs:

```bash
kb-agent-doctor --fix
```

### Common issues

| Problem | Solution |
|---|---|
| `pip install` fails (macOS/Linux) | Build tools missing — run `xcode-select --install` (macOS) or `sudo apt install build-essential python3-dev` (Linux), then retry |
| `KB_ROOT` not set | Copy the config block that `kb-agent-setup` printed and paste it into your MCP host config |
| `kb-agent-serve` not found | Run `which kb-agent-serve` to get the absolute path |
| Skill file not found at `~/.bob/skills/` | Run `kb-agent-generate` again |
| Empty answers / no domains | Re-run `kb-agent-generate` after adding documents |
| Stale index warning | Run `kb-agent-generate` or call `reindex()` from within the AI chat |
| Ollama not running | Either start it with `ollama serve` or use passthrough mode |
| ChromaDB error after upgrading | Run `kb-agent-generate` — it detects incompatibilities and offers to rebuild. Or manually: `rm -rf .kb_index && kb-agent-generate` |
| Embedding model download blocked (proxy/air-gap) | Set `TRANSFORMERS_OFFLINE=1`. To use a mirror: `HF_ENDPOINT=https://hf-mirror.com` |

---

## Known Issues & Fixes

### `is_readme` NameError in `watch_kb.py` _(fixed in commit `cf1ef9e`)_

The watcher stayed alive but stopped responding to all filesystem events after this error. **Fix:** Added the missing `is_readme(path)` helper. If you cloned before commit `cf1ef9e`, run `git pull` and restart the watcher.

---

## Changelog

See `git log` for full history.

---

## License

MIT
