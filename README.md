# KnowledgeBase Agent

A fully dynamic, multi-domain knowledge base agent. Point it at a folder of documents,
run one command, and ask questions in natural language — via any AI tool or the CLI.

---

## 🤔 What is `kb-agent-mcp`?

It's all three — depending on which layer you're looking at.

### 🏗️ A Package / Product
A Python package published to PyPI (`pip install kb-agent-mcp`). It has versioning, a build system, entry-point CLI scripts, optional extras, and a full release lifecycle. From a distribution standpoint, **it is a product**.

### 🤖 An Agent
The core runtime is a **multi-domain RAG agent**. It routes user queries across knowledge domains, synthesises context from indexed documents, and uses an LLM (local or passthrough) to generate answers. The `agents/` directory and the `kb-agent` CLI are the agent layer — internally, **it is an agent**.

### 🛠️ An MCP Server / Skill
From the perspective of Bob, Claude, Cursor, or any MCP-capable host, `kb-agent-mcp` surfaces as a **pluggable MCP server** — a tool an AI assistant calls at runtime. The Bob skill (`.bob/skills/knowledgebase-agent/`) is the routing layer that tells the host AI when and how to invoke it. To a host AI, **it is a skill**.

> **One-line definition:** *"A multi-domain knowledge agent packaged as an MCP server."*

---

## 🚀 Quickest way to get started — pip install

If you just want to use the MCP server (recommended for most users):

```bash
pip install kb-agent-mcp
cd /path/to/your/documents
kb-agent-setup        # interactive wizard — configures LLM, builds indexes
kb-agent-serve        # starts the MCP server
```

See **[README-MCP.md](README-MCP.md)** for the full pip install guide, including how to connect to Claude Desktop, Bob, and Cursor.

---

## 🛠️ Developer / legacy CLI setup (cloning this repo)

If you want to contribute, run the legacy CLI, or build from source — follow the steps below.

---

## ⚡ AI Agent Installation Guide

> **For AI tools:** If a user shares this repo URL and asks you to set it up,
> follow the numbered steps below exactly. Every step is a concrete terminal command
> or file operation — no interpretation required.

### Prerequisites (check before starting)

| Requirement | How to check | Fix if missing |
|---|---|---|
| Python 3.10+ | `python3 --version` | Download from https://python.org/downloads |
| git | `git --version` | Download from https://git-scm.com |
| ~500 MB free disk space | — | Free up space or choose a smaller install location |
| Build tools (macOS) | `xcode-select -p` | Run `xcode-select --install` if not found |
| Build tools (Linux) | `gcc --version` | Run `sudo apt install build-essential python3-dev` |

> **LLM is optional.** The agent works in passthrough mode with no local model installed.
> Bob's Claude (or whatever AI tool is driving this) answers questions using retrieved context.
> You can add Ollama, OpenAI, or Anthropic later.

---

### Step 1 — Clone the repository

```bash
git clone https://github.com/amiya-anupam/kb-agent-mcp.git ~/KnowledgeBase
cd ~/KnowledgeBase
```

Replace `~/KnowledgeBase` with a different path if preferred.

---

### Step 2 — Add knowledge documents

Create one or more folders inside the repo and copy documents into them.
Any folder name works — the agent discovers all top-level folders automatically.

```bash
# Example: create a folder and add PDFs to it
mkdir "My Project"
cp /path/to/your/docs/*.pdf "My Project/"
```

**Supported file types:**

| Category | Extensions |
|---|---|
| Documents | `.pdf` `.docx` `.pptx` `.xlsx` `.xls` `.md` `.txt` `.csv` |
| Web & structured data | `.html` `.htm` `.rtf` `.json` `.yaml` `.yml` `.xml` `.epub` `.eml` |
| Box Notes | `.boxnote` |
| Images | `.png` `.jpg` `.jpeg` `.gif` `.webp` (visual analysis via AI vision) |

> Skip this step now if the user wants to add documents later. The agent will work with
> zero folders — just run `python3 scripts/generate.py` again after adding documents.

---

### Step 3 — Run the installer

```bash
kb-agent-setup
```

`kb-agent-setup` (the canonical entry point after `pip install kb-agent-mcp`) handles everything in order:

1. Checks Python version (3.10+ required)
2. Checks for native build tools (prints the exact fix command if missing)
3. Creates `.env` with `KB_ROOT` pre-filled to the current directory
4. Asks which LLM provider to use (Ollama / OpenAI / Anthropic / passthrough)
5. Runs `kb-agent-generate` — discovers folders, builds ChromaDB indexes, writes the agent skill

**Non-interactive mode** (no prompts, uses passthrough by default):
```bash
kb-agent-setup --yes
```

**Custom install location:**
```bash
kb-agent-setup --kb-root /absolute/path/to/folder
```

> **Legacy path (repo clone, no pip install):** `python3 scripts/setup.py` is a thin shim that delegates to `kb-agent-setup`. Both accept the same flags.

---

### Step 4 — Verify the installation

After `scripts/setup.py` completes, the skill file exists at:

```
~/.bob/skills/knowledgebase-agent/SKILL.md
```

To confirm everything works, run a test question:

```bash
python3 agents/agent_knowledgebase.py "what documents do you know about?"
```

You should get a response listing the indexed folders and files.

---

### Step 5 — Use it

**If using Bob AI:**
Ask any question in the chat window. Bob detects the skill automatically.
```
"What does my KnowledgeBase say about X?"
"/kb how does Y work?"
```

**If using any other AI tool:**
Share the output of the test question above with the AI. Then ask:
```
"Based on that context, answer: <your question>"
```

Or run the agent directly and pipe the output:
```bash
python3 agents/agent_knowledgebase.py "your question here"
```

---

### Step 6 — Adding more documents later

Drop files into any top-level folder, then:

```bash
python3 scripts/generate.py
```

To add a completely new domain:
```bash
mkdir "New Domain"
cp /path/to/new/docs/* "New Domain/"
python3 scripts/generate.py
```

---

### Troubleshooting

| Problem | Solution |
|---|---|
| `pip install` fails (macOS/Linux) | Build tools missing — run `xcode-select --install` (macOS) or `sudo apt install build-essential python3-dev` (Linux), then retry. `scripts/setup.py` checks for this and prints the fix if detected. |
| Skill file not found at `~/.bob/skills/` | Run `python3 scripts/generate.py` again |
| Agent returns empty answers | Check that your folders contain supported file types; also confirm `KB_ROOT` in `.env` points to the right directory |
| `python3` not found (Windows) | Use `python` instead of `python3` throughout |
| Ollama not running | Either start it with `ollama serve` or choose passthrough mode |
| Permission denied on `.env` | Run `chmod 644 .env` |
| ChromaDB error after upgrading | Index format may be incompatible. Run `kb-agent-generate` — it detects this automatically and offers to rebuild. Or manually: `rm -rf .kb_index && kb-agent-generate` |
| Embedding model download fails (proxy/air-gap) | Set `TRANSFORMERS_OFFLINE=1` and pre-cache the model. See [README-MCP.md Troubleshooting](README-MCP.md#troubleshooting) |

---

## 🔒 Security & Privacy

### Data residency — what leaves your machine

| Operation | Goes to | Condition |
|---|---|---|
| Indexing (`kb-agent-generate`) | **Nowhere** — 100% local | Always |
| Q&A via local LLM (Ollama) | **Nowhere** | When Ollama is running |
| Q&A via cloud LLM (passthrough / OpenAI / Anthropic) | Remote cloud API | When `KB_LLM_PROVIDER` ≠ `ollama` or Ollama is unreachable |

> **Rule of thumb:** If `KB_LLM_PROVIDER=ollama` and Ollama is reachable, zero document content leaves your machine. Use `KB_PASSTHROUGH_FALLBACK=false` to prevent silent fallback to passthrough.

### MCP security gate

The `kb-agent-mcp` server implements an **anti-trick confidentiality gate**
(`kb_agent_mcp/security_gate.py`). The gate prevents prompt-injection attacks where
a malicious document pre-plants an acknowledgement token — the token is generated
**at call time** (after indexing) so no document can contain the correct value.

**Workflow:**

1. Call `check_confidential(session_id)` — scans all domains for sensitivity signals.
   If flagged files are found, a one-time 8-character hex token is printed in the chat.
2. Call `acknowledge_gate(session_id, token)` — type the token shown in step 1.
   The gate is cleared; subsequent `ask()` calls include confidential content with
   `🔒` prefix on all citations from flagged files.
3. If no confidential files exist, `check_confidential` returns "✅ clear" and
   `ask()` proceeds without any gate check.

**Confidentiality classification signals (priority order):**

| Signal source | What is checked |
|---|---|
| **EML header** | `Sensitivity:` header — matches `confidential`, `company-confidential`, `personal`, `private`, `restricted` |
| **PDF metadata** | `/Keywords` and `/Subject` fields from the PDF information dictionary |
| **DOCX core properties** | `category` and `keywords` fields from the document's core properties (`docProps/core.xml`) |
| **Filename / folder path** | Full path string (with `_` and `-` normalised to spaces) scanned for 16 keywords |
| **Text body** | First 4,000 characters of extracted text scanned for keywords: `CONFIDENTIAL`, `INTERNAL USE ONLY`, `NOT FOR DISTRIBUTION`, `NOT FOR SHARING`, `DO NOT SHARE`, `DO NOT DISTRIBUTE`, `PROPRIETARY`, `RESTRICTED`, `PRIVILEGED`, `IBM CONFIDENTIAL`, `COMPANY CONFIDENTIAL`, `FOR INTERNAL USE`, `CLASSIFICATION:`, `SENSITIVE`, `TOP SECRET`, `PRIVATE AND CONFIDENTIAL` |

**`.noindex` sentinel — hard exclusion:**
Place an empty file named `.noindex` inside any subfolder to hard-exclude **all**
files in that folder and every nested subfolder. Files under a `.noindex` ancestor
are excluded at both scan time (never appear in `check_confidential` results) and
at index time (never added to the vector database):
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
Use this for fully air-gapped installs where all documents are already trusted.

---

## Environment Variables

After running `scripts/setup.py`, your `.env` file is created automatically. Edit it to change settings:

| Variable | Default | Description |
|---|---|---|
| `KB_ROOT` | _(repo root)_ | Absolute path to your knowledge base directory |
| `KB_LLM_PROVIDER` | `ollama` | LLM provider: `ollama` \| `openai` \| `anthropic` \| `custom` \| `passthrough` |
| `KB_LLM_BASE_URL` | `http://localhost:11434` | Base URL for the LLM API |
| `KB_MODEL` | `qwen3:14b` | Model name for Q&A and routing |
| `KB_API_KEY` | _(empty)_ | API key for OpenAI / Anthropic / custom providers |
| `KB_EMBED_MODEL` | `nomic-embed-text` | Embedding model (leave blank for offline fallback) |
| `KB_IGNORE_FOLDERS` | _(empty)_ | Comma-separated extra folders to exclude from discovery |
| `KB_STALE_DAYS` | `90` | Days before a file is flagged as stale by `watch_kb.py` (0 = disabled) |
| `KB_GENERATE_TIMEOUT` | `900` | Timeout in seconds for the `generate.py` subprocess in `watch_kb.py` (increase for large folders) |
| `KB_PASSTHROUGH_FALLBACK` | `true` | Auto-switch to passthrough when Ollama unreachable (`false` = disable) |

### Token budget variables (`agents/context_budget.py`)

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
Run `scripts/generate.py --no-llm` to skip description/keyword generation entirely.

---

## Passthrough Mode (no local LLM required)

When Ollama is not running and no `KB_API_KEY` is set, the agent automatically switches to passthrough mode:

1. Documents are retrieved locally using offline embeddings (`sentence-transformers`)
2. Retrieved context is emitted as a `<<<KB_PASSTHROUGH>>>` block to stdout
3. The calling AI tool reads the block and answers using that context

No document content ever touches the internet unless you explicitly configure an OpenAI/Anthropic key.

Force passthrough: `KB_LLM_PROVIDER=passthrough`  
Disable auto-detection: `KB_PASSTHROUGH_FALLBACK=false`

---

## CLI Usage

```bash
# Single question
python3 agents/agent_knowledgebase.py "your question"

# Interactive chat
python3 agents/agent_knowledgebase.py

# Clear conversation memory
python3 agents/agent_knowledgebase.py --clear

# Show memory summary
python3 agents/agent_knowledgebase.py --memory
```

### Structured Answer Format

Control how the LLM formats its answer with a `--format` flag or natural-language phrases.

**Explicit flag (CLI):**
```bash
python3 agents/agent_knowledgebase.py "What does CP4I include?" --format table
python3 agents/agent_knowledgebase.py "List ACE deployment steps"  --format bullets
python3 agents/agent_knowledgebase.py "What is the ACE toolkit?"   --format oneline
python3 agents/agent_knowledgebase.py "Explain MQ integration"     --format paragraph
python3 agents/agent_knowledgebase.py "List supported file types"  --format numbered
python3 agents/agent_knowledgebase.py "Show renewal data"          --format json
```

**Inline flag (interactive mode):**
```
You: What does CP4I include? --format table
You: List ACE deployment steps --format bullets
```

**Natural-language phrases (no flag needed):**
```
"Compare ACE and CP4I as a table"
"Give me bullet points on the toolkit"
"In one sentence, what is ACE?"
"Return the renewal figures as json"
"As a numbered list, what are the deployment steps?"
```

| Format | Aliases | Output style |
|---|---|---|
| `table` | — | Markdown table with headers |
| `bullets` | `bullet`, `list` | Markdown bullet list |
| `oneline` | `1line`, `one-line`, `one-liner` | Exactly one sentence |
| `paragraph` | `prose`, `paragraphs` | Prose paragraphs (default) |
| `numbered` | `num`, `numbered-list` | Numbered Markdown list |
| `json` | — | Raw JSON, no fences |

> The format directive is injected as a highest-priority instruction in the system prompt
> before the LLM call. It works in both online (Ollama / OpenAI / Anthropic) and offline
> (passthrough) modes — the directive is embedded in the `SYSTEM_PROMPT` block of the
> passthrough output so the calling AI tool also honours it.

---

## Watcher (auto-update on file changes)

```bash
python3 scripts/watch_kb.py
```

Watches `KB_ROOT` for filesystem events and keeps everything in sync — no manual
`scripts/generate.py` runs needed for day-to-day file changes.

| Event | What happens |
|---|---|
| File added / modified / deleted inside existing folder | Re-embeds, updates index, rewrites README AUTO-INDEX block |
| New top-level folder created | Triggers `scripts/generate.py` automatically |
| Folder deleted | Removes index and domain metadata |
| Folder renamed | Renames index, re-keys domain metadata |

### Stale file alerts

The watcher automatically checks all indexed files against a configurable age threshold:

- **Startup:** checks all files when `scripts/watch_kb.py` launches
- **Hourly:** re-checks every 60 minutes while the watcher is running
- **Output:** prints a warning for each file over the threshold, e.g.:
  ```
  ⚠ BizOps: Q3_Renewal_Tracker.xlsx was last updated 112 days ago.
  ```
- **Disable:** set `KB_STALE_DAYS=0` in `.env`
- **Threshold:** default 90 days, configurable via `KB_STALE_DAYS`

> **macOS note:** The watcher runs as a `launchd` daemon (`com.knowledgebase.watcher`).
> Restart with `launchctl stop/start com.knowledgebase.watcher`.

---

## How `kb-agent-generate` is triggered

| Trigger | When |
|---|---|
| `kb-agent-generate` | Manually — run after first setup, or to pick up new documents |
| `kb-agent-generate --force` | Force regenerate all `domain_config.yaml` files from scratch |
| `kb-agent-generate --no-llm` | Skip LLM steps (index only, use minimal YAML defaults) |
| `kb-agent-generate --domain Foo` | Only process the "Foo" folder |
| `kb-agent-watch` (automatic) | Triggers incrementally on every file change |
| `python3 scripts/generate.py` | Legacy alias — delegates to `kb-agent-generate` |

---

## Architecture

> For the complete technical reference — module descriptions, call graphs, data-flow diagrams, and all environment variables — see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

### System overview

The `kb-agent-mcp` package exposes **two independent pipelines** through a single MCP server:

```
AI tool (Claude, Bob, Cursor, …)
        │   MCP protocol
        ▼
┌───────────────────────────────────────────────────────────────┐
│  server.py  (FastMCP — 9 tools)                               │
├──────────────────────────┬────────────────────────────────────┤
│  Knowledge Base (5)      │  Data Analyst (4) — NEW            │
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
  │ keyword+LLM     │          │   planner.py         │
  └────────┬────────┘          │   engine.py          │
           │                   │   session.py         │
           ▼                   └──────────┬───────────┘
  ┌─────────────────┐                     │
  │ domain_agent.py │          loads file data live
  │ base_agent.py   │          (no ChromaDB needed)
  │ vector_store.py │
  │ ChromaDB index  │
  └─────────────────┘
```

**RAG pipeline** (left) — uses the vector index. Best for semantic questions:
_"What is IBM ACE?" · "Explain the CP4I architecture" · "What are the migration steps?"_

**Data Analyst pipeline** (right) — loads raw files and computes. Best for data questions:
_"Top 10 customers by revenue in FY2025" · "Which accounts churned?" · "Revenue breakdown by region"_

### Component map (pip-installed MCP server)

```
+---------------------------------------------------------------+
|  CLOUD  [internet required]                                   |
|                                                               |
|  Any AI tool (Claude, Bob, Cursor, …)                         |
|    - calls MCP tools via the protocol                         |
|    - passthrough mode: answers using retrieved context        |
+---------------------------------------------------------------+
         |  MCP protocol (stdio or HTTP/SSE)    ^  tool response
         v                                      |
+---------------------------------------------------------------+
|  YOUR MACHINE  [fully offline once set up]                    |
|                                                               |
|  kb-agent-serve  (server.py / FastMCP)                        |
|    9 registered tools — 5 KB core + 4 Data Analyst            |
|                                                               |
|  ── KB tools route through ──────────────────────────────     |
|  orchestrator.py                                              |
|    keyword_confidence() + classify_intent()                   |
|    asyncio.gather(DomainAgent.run() × N)                      |
|  base_agent.py                                                |
|    Strategy 1: README-first (AUTO-INDEX block)                |
|    Strategy 2: vector search (ChromaDB → file_parser)         |
|    Ollama · OpenAI · Anthropic · passthrough                  |
|                                                               |
|  ── Analyst tools route through ────────────────────────────  |
|  analyst/inspector.py  — DataCard: schema, types, grain       |
|  analyst/planner.py    — QuestionMenu by theme                |
|  analyst/engine.py     — clarify → load → compute → answer   |
|  analyst/session.py    — per-session state (params, answer)   |
|                                                               |
|  kb-agent-watch  (daemon)                                     |
|    watches KB_ROOT → auto-reindex on change                   |
|                                                               |
|  .kb_index/                                                   |
|    chroma/              ChromaDB vector index                 |
|    session_memory/      KB conversation history               |
|    analyst_sessions/    Analyst session state                 |
+---------------------------------------------------------------+
```

### Setup flow — run once

```
kb-agent-setup   (or: python3 scripts/setup.py  ← shim, same flags)
  │
  ├─ 1.  check Python version (3.10+)
  ├─ 2.  check native build tools; print fix command if missing
  ├─ 3.  create/update .env  (KB_ROOT + LLM provider)
  ├─ 4.  ask LLM provider  (Ollama / OpenAI / Anthropic / passthrough)
  │        └─ for Ollama: also ask which model to pull
  │
  ├─ 5.  run kb-agent-generate
  │         │
  │         │  Your document folders
  │         │    "My Domain"/       ──►  1. discover folders with indexable files
  │         │    "Other Domain"/         2. build ChromaDB collection (embed every file)
  │         │    <any folder>/           3. call LLM → description + keywords
  │         │                               interactive_keyword_editor() — review + edit
  │         │                            4. write domain_config.yaml  (per domain)
  │         │                            5. write ~/.bob/skills/knowledgebase-agent/SKILL.md
  │         │                            v
  │         │                      kb_agent_mcp/
  │         │                        server.py              MCP server
  │         │                        retrieval.py           RAG pipeline
  │         │                        embeddings.py          ChromaDB wrapper
  │         │                        memory.py              session memory
  │         │                        cli/
  │         │                          setup.py             wizard
  │         │                          generate.py          index builder
  │         │                          watch.py             file watcher
  │         │                          doctor.py            health checker (--fix)
  │         │                          status.py            live dashboard
  │         │                        .kb_index/
  │         │                          chroma/              ChromaDB collections
  │         │                          session_memory/
  │         │                            │
  │         │                            v
  │         │               ~/.bob/skills/knowledgebase-agent/SKILL.md
  │         │               (auto-installed so Bob loads the skill on next start)
  │
  └─ 6.  install_skill()
            copies skills/knowledgebase-install/ → ~/.bob/

kb-agent-watch then keeps ChromaDB + domain_config.yaml current as files change
```

### Query flow — every question

```
You  [ask a question]
 |
 v
AI tool / Bob's Claude  [cloud]
 |  reads SKILL.md, detects intent
 |  runs: python3 agents/agent_knowledgebase.py "<question>"
 v
agent_knowledgebase.py  [local]
 |
 +---> detect_format_intent()
 |       --format flag (explicit) or NL phrase scan
 |       returns format_instruction string (empty = no preference)
 |
 +---> keyword_route()
 |       scan question against domain keywords in domain_meta.json
 |       fast O(1) match, no LLM involved
 |
 +---> classify_intent()  [only if keyword route is ambiguous]
 |       calls local LLM (uses file_summaries for richer routing)
 |       returns: which domain(s) to route to
 |
 +---> dispatch to domain agent(s) via call_sub_agent()
         |
         +-- checks for agents/agent_<domain>.py first
         |     present  -> module.domain_ask() (domain-specific logic)
         |     absent   -> agent_base.ask() directly
         |
         +-- format_instruction injected into system_prompt
         |     _apply_format_instruction() appends OUTPUT FORMAT DIRECTIVE
         |
         +-- README-first strategy  (primary)
         |     find <Folder>/README.md
         |     simple question   -> AUTO-INDEX block + intro
         |     complex question  -> full README up to 24,000 chars
         |
         +-- vector search fallback  (if README absent or too thin)
         |     query *_index.json by cosine similarity
         |     extract full text from top-N matched files
         |
         +-- confidence footer appended to answer
               High (≥0.80) / Medium (≥0.60) / Low (<0.60)
               README-first: source-only footer (no label)
         |
         v
       Local LLM (Ollama) OR passthrough block -> calling AI tool
         |
         v
 Answer delivered
```

### Passthrough mode — when no local LLM is running

```
agent_base.py detects Ollama unreachable
 |
 |  uses sentence-transformers for embeddings  [offline, ~80 MB]
 |  retrieves context from README or vector index  [fully local]
 |
 v
emit_passthrough()
 |  prints to stdout:
 |
 |    <<<KB_PASSTHROUGH>>>
 |    AGENT: <domain name>
 |    QUESTION: <your question>
 |    SYSTEM_PROMPT: <domain-specific prompt>
 |    ---CONTEXT---
 |    <retrieved text excerpt from README or files>
 |    <<<KB_PASSTHROUGH_END>>>
 |
 v
Calling AI tool reads the block and answers using the provided context

NOTE: raw document files never leave your machine.
      Only the retrieved text excerpt is seen by the AI tool.
      When Ollama is running, nothing goes to the cloud at all.
```

### Token consumption — online vs. offline

Every query goes through two layers. Numbers are for a **simple question** (README index mode, 4-turn history, ~25-word question).

#### Per-query token budget breakdown

| Component | Passthrough (no local LLM) | Local LLM (Ollama) |
|---|---|---|
| `classify_intent()` call | — skipped (keyword route used) | ~120 tok |
| System prompt | ~48 tok | ~48 tok |
| Conversation history (4 turns) | 0 tok (not sent in passthrough) | ~200 tok |
| Retrieved context (README index) | domain-specific (see below) | domain-specific (see below) |
| User question | ~25 tok | ~25 tok |

#### Domain token breakdown

| Domain | Passthrough + README | Local LLM + README | Passthrough + RAG | Local LLM + RAG |
|---|---|---|---|---|
| 3-domain example (small) | ~754 tok | ~1,019 tok | ~4,104 tok | ~4,369 tok |
| 3-domain example (medium) | ~1,410 tok | ~1,675 tok | ~4,103 tok | ~4,368 tok |
| 3-domain example (large) | ~2,023 tok | ~2,288 tok | ~4,103 tok | ~4,368 tok |

**README index mode saves 48–77% tokens** vs. raw-file RAG fallback.
RAG fallback is always ~4,100 tok regardless of domain — bounded by `top_n=4 × KB_BUDGET_RAG_FILE`.

### What needs internet vs. what is offline

| Operation | Runs on | Network | Notes |
|---|---|---|---|
| Skill trigger detection | AI tool / Bob's Claude | **Internet** | Cloud LLM only |
| Answer relay to you | AI tool / Bob's Claude | **Internet** | Cloud LLM only |
| Passthrough Q&A | AI tool / Bob's Claude | **Internet** | Cloud LLM only |
| `uv` package install | PyPI | **Internet** (first run) | Use `--offline` after first run |
| Intent classification | Ollama (local) | Local only | — |
| Q&A answering | Ollama (local) | Local only | — |
| Text embedding | Ollama / sentence-transformers | Local only | — |
| File summary generation | Ollama (local) | Local only | — |
| Vector index search | numpy / scikit-learn | Local only | — |
| File watching | OS filesystem events | Local only | — |
| Document reading | pypdf / docx / openpyxl / bs4 / defusedxml | Local only | All extraction is offline |
| Network audit probe | TCP to 8.8.8.8:53 | **Internet** (check only) | No data sent; connectivity detection only |

---

## `agents/context_budget.py` — Token Compaction Engine

`context_budget.py` is the **single source of truth** for all token-affecting decisions. Both `watch_kb.py` (index-time) and `agent_base.py` (query-time) import from it.

### Public API

| Function | Used by | What it does |
|---|---|---|
| `trim(text, key)` | `agent_base.py` | Hard-trim text to a named budget |
| `trim_summary(summary, filename)` | `watch_kb.py` | Trim file summary; replace useless fallbacks with filename |
| `compact_index_block(block)` | both | Strip boilerplate, normalise columns, collapse repeated-version groups |
| `compact_pre_index(text)` | `agent_base.py` | Trim the hand-written README intro |
| `build_context(pre, index)` | `agent_base.py` | Assemble final context within `KB_BUDGET_INDEX` |
| `get(key)` | both | Return the character budget for a named key |
| `COLLAPSE_RULES` | both | Importable list of `(pattern, label, template)` tuples |

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

## Known Issues & Fixes

### `is_readme` NameError in `watch_kb.py` _(fixed in commit `cf1ef9e`)_

**Symptom:** After starting `watch_kb.py`, adding/modifying/deleting any file inside
an existing folder silently crashed the observer thread:

```
NameError: name 'is_readme' is not defined. Did you mean: 'find_readme'?
  File "watch_kb.py", line 734, in on_created
```

The watcher stayed alive but stopped responding to all filesystem events.

**Fix:** Added the missing `is_readme(path)` helper. **If you cloned before commit `cf1ef9e`:** run `git pull` and restart the watcher.

---

## Changelog

See `git log` for full history.