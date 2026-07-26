# kb-agent-mcp

A zero-config pip-installable MCP server that turns **any folder of documents** into a queryable, multi-agent knowledge base.

Connect it to Claude Desktop, Bob, Cursor, or any MCP-compatible AI tool — then ask questions in natural language.

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

# Run the setup wizard
cd /path/to/your/documents
kb-agent-setup

# Or manually: generate indexes and domain configs
kb-agent-generate

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

Once the server is running, the following tools are available:

| Tool | Description |
|---|---|
| `ask(question, format?, session_id?)` | Query all relevant domains and return a markdown answer |
| `list_domains()` | List indexed knowledge domains with descriptions |
| `reindex()` | Re-scan KB_ROOT and rebuild ChromaDB indexes. After reindexing, any new domain folders that are still missing `domain_config.yaml` are surfaced as a warning in the tool response — run `kb-agent-generate` from the CLI to generate them. |
| `clear_memory(session_id?)` | Clear conversation history for a session |
| `show_memory(session_id?)` | Show current session state and recent history |

### `ask` examples

```
ask("What is IBM ACE?")
ask("What is our Q3 revenue by product?", format="table")
ask("Explain the architecture of CP4I", format="bullets")
ask("How many deals closed last quarter?", session_id="my-session")
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
  .kb_index/         ← ChromaDB + session memory (auto-created)
    chroma/
    session_memory/
```

Files in nested subfolders are indexed into their parent domain.

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

| Command | Description |
|---|---|
| `kb-agent-setup` | Interactive setup wizard |
| `kb-agent-generate` | Build ChromaDB indexes + generate domain_config.yaml |
| `kb-agent-serve` | Start the MCP server |
| `kb-agent-watch` | Watch for file changes and auto-update indexes |
| `kb-agent-doctor` | Run a health checklist to diagnose problems |

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

If something isn't working, run:

```bash
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
