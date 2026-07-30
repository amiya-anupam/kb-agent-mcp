# kb-agent-mcp

A zero-config pip-installable MCP server that turns **any folder of documents** into a queryable, multi-agent knowledge base.

Connect it to Claude Desktop, Bob, Cursor, or any MCP-compatible AI tool — then ask questions in natural language.

![kb-agent-mcp routing diagram](architecture%20flow%20diagram.png)

---

## Features

- **Zero configuration** — point at a folder, run one command, start asking questions
- **Multi-domain routing** — automatically routes questions to the right knowledge domain
- **README-first RAG** — uses compact AUTO-INDEX blocks for fast answers; falls back to full-document search for complex/data questions
- **Passthrough mode** — works with *no local LLM*; your AI tool answers using retrieved context
- **Supports all major document types** — PDF, DOCX, XLSX (with streaming aggregation for large files), PPTX, MD, TXT, CSV, BoxNote
- **ChromaDB vector search** — persistent, hash-based change detection (only re-indexes changed files)
- **Multi-session memory** — per-session conversation history with configurable timeout
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

Once the server is running, the following **eleven tools** are available in three groups:

### Knowledge Base tools (5)

| Tool | Description |
|---|---|
| `ask(question, format?, session_id?)` | Query all relevant domains and return a markdown answer |
| `list_domains()` | List indexed knowledge domains with descriptions |
| `reindex()` | Re-scan KB_ROOT and rebuild ChromaDB indexes. After reindexing, any new domain folders that are still missing `domain_config.yaml` are surfaced as a warning in the tool response — run `kb-agent-generate` from the CLI to generate them. |
| `clear_memory(session_id?)` | Clear conversation history for a session |
| `show_memory(session_id?)` | Show current session state and recent history |

### Security Gate tools (2)

These tools implement the **anti-trick confidentiality gate**. Call `check_confidential()` before asking sensitive questions when your knowledge base may contain restricted documents.

| Tool | Description |
|---|---|
| `check_confidential(session_id?)` | Scan all domains for confidential-flagged files. If any are found, activates the gate and returns a one-time acknowledgement token that you must supply to `acknowledge_gate()`. Returns "✅ clear" when nothing is flagged. |
| `acknowledge_gate(session_id, token)` | Unlock the gate for a session by supplying the token printed by `check_confidential()`. The token is generated at call time — it cannot be pre-planted in any document, preventing prompt-injection attacks. Once cleared, confidential file citations are prefixed with 🔒. |

> **How the anti-trick mechanism works:** `check_confidential()` calls `secrets.token_hex(4)` at that moment — after all documents were indexed. No document content can contain the correct token because it did not exist when the document was written. Only a live user reading the chat can supply the right value.

> **`.noindex` sentinel:** Place an empty file named `.noindex` in any subfolder to hard-exclude all files in that subtree from both scanning and indexing. Files under `.noindex` ancestors never appear in scan results and are never added to the vector index.

> **Disable the gate:** Set `KB_SECURITY_GATE_ENABLED=false` in your `.env` to bypass the gate entirely (e.g. fully air-gapped installs with only trusted documents).

### Data Analyst tools (4)

These tools run **live computation** over raw files — no vector index required. They answer aggregation, trending, filtering, and comparison questions that semantic search cannot handle.

| Tool | Description |
|---|---|
| `analyze_file(path)` | Profile any file → returns a DataCard (schema, column types, grain, themes, warnings) |
| `suggest_questions(path)` | Returns a menu of analytical questions grouped by theme (revenue, attrition, growth, concentration, anomaly) |
| `query_data(path, question, session_id?)` | Asks clarifying questions if needed, then computes the answer with full reasoning |
| `refine_query(session_id, feedback)` | Re-runs the last query using updated parameters from your feedback |

Supported file formats: `.xlsx` `.xls` `.csv` `.json` `.jsonl` `.pdf` `.docx` `.pptx` `.txt` `.md`

### `ask` examples

```
ask("What is IBM ACE?")
ask("What is our Q3 revenue by product?", format="table")
ask("Explain the architecture of CP4I", format="bullets")
ask("How many deals closed last quarter?", session_id="my-session")
```

### `query_data` examples

```
query_data("BizOps/Renewal Tracking/Revenue/ACE Revenue.xlsx",
           "What are the top 10 customers by revenue in FY2025?")

query_data("BizOps/Renewal Tracking/Revenue/ACE Revenue.xlsx",
           "Which customers churned compared to last year?",
           session_id="analyst-1")

refine_query("analyst-1", "Show only the Americas region")
```

> **Session isolation:** On **HTTP transport**, omitting `session_id` auto-generates a
> unique UUID per call — the generated ID is returned as `<!-- session_id: <id> -->` in
> the response so you can reuse it across turns. On **stdio transport** (Claude Desktop /
> Bob), a single user per process is assumed so the shared `"default"` session is safe.
> For explicit multi-turn control, always pass a unique `session_id` per conversation thread.

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
# Set to false for fully air-gapped installs with only trusted documents
KB_SECURITY_GATE_ENABLED=true

# Ignore these top-level folders
KB_IGNORE_FOLDERS=archive,tmp
```

### Passthrough mode

When `KB_LLM_PROVIDER=passthrough` (or when Ollama is unreachable and `KB_PASSTHROUGH_FALLBACK` is not `false`), the server automatically detects that no local LLM is available and returns the retrieved document context as clean markdown:

```markdown
> **No local LLM detected.** Retrieved context is provided below —
> use it to answer the question.

### BizOps Agent
*Source: BizOps/Revenue.xlsx*

Q1 revenue: $1.2M
Q2 revenue: $1.5M
```

The calling AI tool (Claude, Bob, Cursor) receives this directly from the `ask` tool and can answer the question from the context — **no special parsing or configuration needed on the client side**.

To disable the automatic fallback (hard-fail instead):
```env
KB_PASSTHROUGH_FALLBACK=false
```

This is the recommended mode for most users — no local model required.

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
    analyst_sessions/        per-session analyst state (params, last answer)
```

Files in nested subfolders are indexed into their parent domain.

> **Analyst tools work on any file under `KB_ROOT`** — pass either an absolute path
> or a path relative to `KB_ROOT` (e.g. `"BizOps/Revenue.xlsx"`).

---

## domain_config.yaml

Generated by `kb-agent-generate`, one per domain folder. Edit manually to tune the agent:

```yaml
folder_name: BizOps
agent_name: BizOps Agent
description: Business operations — CP4I and ACE revenue, won deals, renewals
keywords:
  - revenue
  - quota
  - attainment
  - ACE
  - CP4I
top_n: 5
max_chars: 8000
system_prompt: |
  You are the BizOps Agent, a specialist in IBM APC region business data.
  CRITICAL: For revenue questions use only Revenue Report files (Rev Act @ PC column).
  Be concise, accurate, and cite the source file.
retrieval_rules:
  pin_files:
    - "*Revenue*.xlsx"      # always included for data questions
  boost_keywords:
    - revenue               # ranked to top of results
  question_classifier:
    data_patterns:
      - "\\brevenue\\b"     # regex → bypass README-first, use raw file content
    complex_patterns: []
```

---

## CLI Commands

### Unified entry point

| Command | Description |
|---|---|
| `kb-agent init` | First-time setup: runs setup → generate → doctor in sequence |
| `kb-agent setup` | Interactive setup wizard |
| `kb-agent generate` | Build ChromaDB indexes + generate domain_config.yaml |
| `kb-agent serve` | Start the MCP server |
| `kb-agent watch` | Watch for file changes and auto-update indexes |
| `kb-agent doctor` | Run a health checklist to diagnose problems |
| `kb-agent status` | Show a live system-health dashboard (indexes, LLM, memory) |

### Legacy standalone commands (still available)

| Command | Description |
|---|---|
| `kb-agent-setup` | Interactive setup wizard |
| `kb-agent-generate` | Build ChromaDB indexes + generate domain_config.yaml |
| `kb-agent-serve` | Start the MCP server |
| `kb-agent-watch` | Watch for file changes and auto-update indexes |
| `kb-agent-doctor` | Run a health checklist to diagnose problems |
| `kb-agent-status` | Show a live system-health dashboard (indexes, LLM, memory) |

### kb-agent-generate flags

```bash
kb-agent-generate               # incremental — skip unchanged
kb-agent-generate --force       # regenerate all domain_config.yaml files
kb-agent-generate --no-llm      # index only, use minimal YAML defaults
kb-agent-generate --domain Foo  # only process the "Foo" folder
```

### kb-agent-serve flags

```bash
kb-agent-serve                           # stdio (Claude Desktop / Bob)
kb-agent-serve --transport http          # HTTP/SSE on port 8765
kb-agent-serve --transport http --port 9000
kb-agent-serve --version
```

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

> **Tips:**
> - `kb-agent-setup` prints a ready-to-paste config block with the **absolute path** to
>   `kb-agent-serve` and the correct `KB_ROOT` value — copy it directly from the wizard output.
> - If `KB_ROOT` is omitted, the server prints a clear error on startup and exits — it will
>   not silently index the wrong directory.

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

> **Tips:**
> - Use the **absolute path** for `"command"` — `kb-agent-setup` prints it at the end
>   of setup. If you need it again, run `which kb-agent-serve` in your terminal.
> - If `KB_ROOT` is omitted or wrong, the server prints a clear error on startup and exits.

---

## Backward Compatibility

This package (`kb-agent-mcp`) is built **alongside** the original `agents/` and `scripts/` system. Nothing in the existing codebase is modified. Both systems can run independently from the same `KB_ROOT`.

---

## Development

```bash
git clone <this-repo>
cd KnowledgeBase
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

For a **minor** or **major** version bump (e.g. `0.2.0` or `1.0.0`), manually edit `version` in `pyproject.toml` in your PR before merging — CI will auto-bump the patch on top of it.

---

## Troubleshooting

`kb-agent-setup` (and `kb-agent init`) automatically runs `kb-agent-doctor` at the end of setup and prints a full health report. If you need to re-run it later:

```bash
kb-agent doctor
# or
kb-agent-doctor
```

This command checks everything and prints a `✓` / `✗` report:

| Check | What it verifies |
|---|---|
| Python version | 3.10 or later |
| `KB_ROOT` set | env var present, explicit, and directory exists |
| Domain folders | at least one non-ignored subfolder under `KB_ROOT` |
| `domain_config.yaml` | present per domain |
| ChromaDB index | non-empty collection per domain; warns if index is older than 7 days |
| Embedding model | `all-MiniLM-L6-v2` cached on disk |
| LLM reachable | Ollama/OpenAI/Anthropic endpoint responds |
| `kb-agent-serve` on PATH | absolute path shown |
| Bob skill installed | `~/.bob/skills/knowledgebase-agent/SKILL.md` |

Each failing item shows a one-line fix hint. Exit code 0 = healthy, 1 = fix needed.

Pass `--fix` to automatically apply safe repairs (creates missing `domain_config.yaml` files, regenerates the Bob skill, re-downloads the embedding model if absent):

```bash
kb-agent-doctor --fix
```

### Common issues

**`KB_ROOT` not set or missing from host config** — The server now prints a clear
error on startup and exits rather than silently using the wrong directory. Copy the
config block that `kb-agent-setup` printed and paste it into your MCP host config:
```json
"env": { "KB_ROOT": "/absolute/path/to/your/KnowledgeBase" }
```

**`kb-agent-serve` not found in MCP host config** — `kb-agent-setup` prints the
absolute path at the end of setup. You can also retrieve it at any time:
```bash
which kb-agent-serve
```

**Empty answers / no domains** — Re-run `kb-agent-generate` after adding documents.

**Stale index warning in answers** — The server automatically detects new files and
prepends a `⚠ Index may be stale` banner to answers. Run `kb-agent-generate` (or call
`reindex()` from within the AI chat) to clear it.

**After upgrading (`pip install -U kb-agent-mcp`)** — If the index format is
incompatible with the new version, `kb-agent-serve` and `kb-agent-generate` both
detect this automatically and print a clear error with the exact fix. When prompted
interactively, `kb-agent-generate` offers to wipe and rebuild the index for you:
```bash
kb-agent-generate   # detects incompatibility, offers auto-rebuild
# or manually:
rm -rf /path/to/your/KnowledgeBase/.kb_index && kb-agent-generate
```

**Embedding model download blocked (corporate proxy / air-gapped machine)** — Set
`TRANSFORMERS_OFFLINE=1` in your environment to prevent download attempts (raises a
clear error if the model is not already cached). To use a Hugging Face mirror:
```env
HF_ENDPOINT=https://hf-mirror.com
```
Pre-download on a networked machine, then copy `~/.cache/huggingface/hub/` here.

---

## License

MIT
