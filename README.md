# KnowledgeBase Agent

A fully dynamic, multi-domain knowledge base agent system built for [Bob AI](https://github.com/ibm/bob).  
Add a folder of documents -> run `generate.py` -> ask questions in natural language via Bob or the CLI.

---

## Architecture

### Component map

```
+-------------------------------------------------------+
|  CLOUD  [internet required]                           |
|                                                       |
|  Bob's Claude                                         |
|    - detects skill trigger from your question         |
|    - runs the local agent as a subprocess             |
|    - relays the answer back to you                    |
|    - passthrough mode: answers using retrieved context|
|    NOTE: never sees your raw document files           |
+-------------------------------------------------------+
         |  subprocess                   ^  stdout
         v                               |
+-------------------------------------------------------+
|  YOUR MAC  [fully offline once set up]                |
|                                                       |
|  watch_kb.py  (launchd daemon, always running)        |
|    watches KB_ROOT for file/folder changes            |
|    keeps *_index.json + README AUTO-INDEX current     |
|                                                       |
|  agent_knowledgebase.py  (orchestrator)               |
|    |                                                  |
|    +-- keyword_route()    fast match, no LLM          |
|    |                                                  |
|    +-- classify_intent() --> Ollama qwen3:14b         |
|           (only when keyword route is ambiguous)      |
|    |                                                  |
|    +-- dispatches to domain agents (parallel):        |
|           agent_ace_docs.py                           |
|           agent_bizops.py                             |
|           agent_cp4i_docs.py                          |
|           agent_<any-folder>.py                       |
|    |                                                  |
|    v                                                  |
|  agent_base.py  (shared RAG logic)                    |
|    |                                                  |
|    +-- Strategy 1: README-first  (primary)            |
|    |     reads <Folder>/README.md AUTO-INDEX block    |
|    |     normal question  -> index block + intro      |
|    |     complex question -> full README (40k chars)  |
|    |                                                  |
|    +-- Strategy 2: vector search  (fallback)          |
|    |     cosine similarity over *_index.json          |
|    |                                                  |
|    +-- calls Ollama qwen3:14b -> answer text          |
|                                                       |
|  agents/vector_store/                                 |
|    *_index.json         embeddings cache per domain   |
|    domain_meta.json     descriptions + keywords       |
|    file_summaries.json  LLM summary per file          |
|    session_memory.json  conversation history          |
|                                                       |
|  <Folder>/README.md     primary retrieval context     |
|    <!-- KB:AUTO-INDEX:START --> ... <!-- END -->       |
+-------------------------------------------------------+
```

### Setup flow — run once

```
Your document folders           generate.py
  ACE Docs/          -------->    |
  BizOps/                         | 1. discover folders with indexable files
  CP4I Docs/                      | 2. build *_index.json  (embed every file)
  <any folder>/                   | 3. call Ollama -> description + keywords
                                  | 4. write domain_meta.json
                                  | 5. generate agent_<folder>.py per domain
                                  | 6. write agents/SKILL.md
                                  v
                            agents/
                              agent_base.py          core RAG
                              embeddings.py          vector index
                              memory.py              session memory
                              agent_knowledgebase.py orchestrator
                              agent_<folder>.py      one per domain
                              SKILL.md               Bob skill definition
                              vector_store/
                                <folder>_index.json
                                domain_meta.json
                                file_summaries.json
                                session_memory.json
                                  |
                                  v
                     ~/.bob/skills/knowledgebase-agent/SKILL.md
                     (auto-copied so Bob knows the CLI command to run)

watch_kb.py then generates the AUTO-INDEX block in each folder README
(one-sentence LLM summary per file -- this is the primary retrieval context)
```

### Query flow — every question

```
You  [ask a question in Bob chat]
 |
 v
Bob's Claude  [cloud]
 |  reads SKILL.md, detects intent
 |  runs: python3 agents/agent_knowledgebase.py "<question>"
 v
agent_knowledgebase.py  [local]
 |
 +---> keyword_route()
 |       scan question against domain keywords in domain_meta.json
 |       fast O(1) match, no LLM involved
 |
 +---> classify_intent()  [only if keyword route is ambiguous]
 |       calls Ollama qwen3:14b  [local]
 |       returns: which domain(s) to route to
 |
 +---> dispatch to domain agent(s)
         |
         |  single domain   ->  agent_<domain>.py
         |  multi-domain    ->  all agents run in parallel (ThreadPoolExecutor)
         |
         v
       agent_base.ask()  [local]
         |
         +-- README-first strategy  (primary)
         |     find <Folder>/README.md
         |     normal question   -> AUTO-INDEX block + brief intro
         |     complex question  -> full README up to 40,000 chars
         |
         +-- vector search fallback  (if README is absent or too thin)
               query *_index.json by cosine similarity
               extract full text from top-N matched files
         |
         v
       Ollama qwen3:14b  [local]
         system_prompt + context + question -> answer text
         |
         v
       merge_answers()
         combine results from all domain agents
         |
         v  stdout
Bob's Claude reads output  [cloud]
 |  formats and delivers answer to you
 v
Answer
```

### Passthrough mode — when Ollama is not running

```
agent_base.py detects Ollama unreachable (timeout on localhost:11434)
 |
 |  uses sentence-transformers for embeddings  [offline, ~80 MB]
 |  retrieves context from README or vector index  [fully local]
 |
 v
emit_passthrough()
 |
 |  prints to stdout:
 |
 |    <<<KB_PASSTHROUGH>>>
 |    AGENT: <domain agent name>
 |    QUESTION: <your question>
 |    SYSTEM_PROMPT:
 |    <domain-specific system prompt>
 |    ---CONTEXT---
 |    <retrieved text excerpt from README or files>
 |    <<<KB_PASSTHROUGH_END>>>
 |
 v
Bob's Claude reads the block  [cloud]
 |  answers the question using the provided context excerpt
 v
Answer

NOTE: raw document files never leave your machine.
      Only the retrieved text excerpt is seen by Claude.
      When Ollama is running, nothing goes to Claude at all.
```


### Token consumption — online vs. offline

Every query goes through two layers. The numbers below are for a **simple question** (README index mode, 4-turn history, average 25-word question).

#### Per-query token budget breakdown

| Component | Online (passthrough) | Offline (local LLM) |
|---|---|---|
| `classify_intent()` LLM call | — skipped (keyword route used) | ~120 tok |
| System prompt | ~48 tok | ~48 tok |
| Conversation history (4 turns) | 0 tok (not sent in passthrough) | ~200 tok |
| Retrieved context (README index) | domain-specific (see below) | domain-specific (see below) |
| User question | ~25 tok | ~25 tok |

#### Domain token breakdown (README index mode vs. RAG fallback)

| Domain | Online + README | Offline + README | Online + RAG | Offline + RAG | README saves (offline) |
|---|---|---|---|---|---|
| ACE Docs | **1,410 tok** | **1,675 tok** | 4,103 tok | 4,368 tok | −2,693 tok (62%) |
| BizOps | **2,023 tok** | **2,288 tok** | 4,103 tok | 4,368 tok | −2,080 tok (48%) |
| CP4I Docs | **754 tok** | **1,019 tok** | 4,104 tok | 4,369 tok | −3,349 tok (77%) |

**Key observations:**
- **Online vs. offline delta is only +265 tok per query** — the extra cost is the single `classify_intent()` routing call and conversation history passed to the local LLM.
- **README index mode saves 48–77%** vs. raw-file RAG fallback — the compacted index block is the biggest win.
- **CP4I Docs is smallest context** (754 tok online) because its README has only 11 files; its 100 KB narrative is capped by `KB_BUDGET_PRE_INDEX` (500 tok).
- **BizOps is largest context** (2,023 tok online) because it has the most files (76) — but EPM2-004 and screenshot collapsing keeps it under the 2,000-token index budget.
- RAG fallback is always ~4,100 tok regardless of domain — it's bounded by `top_n=4` files × `KB_BUDGET_RAG_FILE` (1,000 tok each).

#### What drives the online→offline +265 tok delta

```
Online (passthrough) mode:
  1. keyword_route()    — O(1) keyword scan, zero tokens
  2. emit_passthrough() — context + system_prompt sent to Bob's Claude
     Bob's Claude pays the token cost from its own context window

Offline (local LLM) mode:
  1. classify_intent()  — 1 LLM call: ~120 tok (routing prompt + question)
  2. agent_base.ask()   — system_prompt + history + context + question
     Ollama pays the token cost locally
```


### What needs internet vs. what is offline

| Operation | Runs on | Network |
|---|---|---|
| Skill trigger detection | Bob's Claude | Internet |
| Answer relay to you | Bob's Claude | Internet |
| Passthrough Q&A | Bob's Claude | Internet |
| Intent classification | Ollama (qwen3:14b) | Local only |
| Q&A answering | Ollama (qwen3:14b) | Local only |
| Text embedding | Ollama (nomic-embed-text) | Local only |
| File summary generation | Ollama (qwen3:14b) | Local only |
| Vector index search | numpy / scikit-learn | Local only |
| File watching | macOS FSEvents | Local only |
| Document reading | pypdf / pptx / openpyxl | Local only |

---

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url>
cd knowledgebase-agent

# 2. Add your knowledge folders (any top-level folder with documents)
mkdir "My Domain"
cp /path/to/your/docs/*.pdf "My Domain/"

# 3. Run the one-command installer
python3 setup.py
```

`setup.py` handles everything automatically:
- installs Python dependencies
- creates `.env` with `KB_ROOT` pre-filled to the repo location
- prompts for your LLM choice (Ollama / OpenAI / Anthropic / passthrough)
- runs `generate.py` — builds vector indexes, installs the Bob skill

After setup, the Bob skill is live at `~/.bob/skills/knowledgebase-agent/SKILL.md`.
Ask questions directly in Bob: `"What does my KnowledgeBase say about X?"`
or via CLI: `python3 agents/agent_knowledgebase.py "your question here"`

**No local LLM required** — passthrough mode lets Bob's Claude answer using retrieved context.

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|---|---|---|
| `KB_ROOT` | _(repo root)_ | Absolute path to your knowledge base directory |
| `KB_LLM_PROVIDER` | `ollama` | LLM provider: `ollama` \| `openai` \| `anthropic` \| `custom` |
| `KB_LLM_BASE_URL` | `http://localhost:11434` | Base URL for the LLM API |
| `KB_MODEL` | `qwen3:14b` | Model name for Q&A and routing |
| `KB_API_KEY` | _(empty)_ | API key for OpenAI / Anthropic / custom providers |
| `KB_EMBED_MODEL` | `nomic-embed-text` | Embedding model (leave blank for offline fallback) |
| `KB_IGNORE_FOLDERS` | _(empty)_ | Comma-separated extra folders to exclude from discovery |

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

## `agents/context_budget.py` — Token Compaction Engine

`context_budget.py` is the **single source of truth** for all token-affecting decisions in the pipeline. Both `watch_kb.py` (index-time) and `agent_base.py` (query-time) import from it.

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

The **recommended way** (no code change, not shared with cloners) — add to your `.env`:

```bash
# Single rule
KB_COLLAPSE_PATTERNS=Weekly_Report|weekly reports|Weekly status reports ({n} files)

# Multiple rules separated by ;;
KB_COLLAPSE_PATTERNS=EPM2-004|EPM snapshots|Weekly files for {quarters} ({n} files);;^Screenshot|screenshots|Snapshot images ({n} files)
```

Format per rule: `regex_pattern|label|description_template`
- `{n}` — number of matched files
- `{quarters}` — quarter codes extracted from filenames (e.g. `Q126, Q226`)

This covers both index-time (watcher rewrites the README when the watcher next runs) and query-time (agent compacts on the fly) automatically.

**Alternative** — if you want a rule to apply for everyone who clones the repo, add it to `_BUILTIN_COLLAPSE_RULES` in `agents/context_budget.py`. Only put genuinely universal patterns there (e.g. OS junk files).

---

## Adding a New Knowledge Domain

1. Create a top-level folder in the repo root (e.g. `mkdir "Sales Reports"`)
2. Copy your documents into it (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`, `.csv`, `.boxnote`)
3. Run `python3 generate.py`

The generator will automatically:
- Discover the new folder
- Build a vector index for it
- Generate a description + keywords using the LLM
- Create `agents/agent_sales_reports.py`
- Update `agents/SKILL.md` and auto-copy it to `~/.bob/skills/`

---

## Supported File Types

`.pdf` `.docx` `.pptx` `.xlsx` `.md` `.txt` `.csv` `.boxnote` `.ppt` `.doc`

---

## LLM Providers

| Provider | `KB_LLM_PROVIDER` | Notes |
|---|---|---|
| Ollama (local) | `ollama` | Default. Run `ollama serve` first. |
| OpenAI | `openai` | Set `KB_API_KEY` |
| Anthropic | `anthropic` | Set `KB_API_KEY` |
| LM Studio / Jan | `custom` | Set `KB_LLM_BASE_URL` to your local server URL |

**No LLM?** No problem. Embeddings fall back to `sentence-transformers` (offline, ~80MB download on first use).
Answers fall back to Bob's Claude via the passthrough mechanism.  
Run `generate.py --no-llm` to skip description/keyword generation.

---

## Passthrough Mode (no local LLM required)

When Ollama is not running and no `KB_API_KEY` is set, the agent automatically switches to passthrough mode:

1. Documents are retrieved locally using offline embeddings (`sentence-transformers`)
2. Retrieved context is emitted as a `<<<KB_PASSTHROUGH>>>` block to stdout
3. Bob's Claude reads the block and answers using that context

No document content ever touches the internet unless you explicitly configure an OpenAI/Anthropic key.

Force passthrough: `KB_LLM_PROVIDER=passthrough`  
Disable auto-detection: `KB_PASSTHROUGH_FALLBACK=false`

---

## Watcher (auto-update on file changes)

```bash
python3 watch_kb.py
```

Watches `KB_ROOT` for filesystem events and keeps everything in sync -- no manual
`generate.py` runs needed for day-to-day file changes.

### Watcher event handling

| Event | Debounced? | What happens |
|---|---|---|
| File added inside existing folder | 5 s | Re-embeds file, updates `*_index.json`, regenerates file summary, rewrites README AUTO-INDEX block |
| File modified | 5 s | Same as above |
| File deleted | 5 s | Removes entry from `*_index.json`, removes summary cache entry, rewrites README AUTO-INDEX block |
| File renamed/moved | 5 s | Deindexes old path, indexes new path, updates README |
| **New top-level folder created** | 5 s | Triggers `generate.py` -- only event that needs it |
| Folder deleted | **Immediate** | Deletes `agent_<safe>.py` + `<safe>_index.json` + domain meta entry |
| Folder renamed | **Immediate** | Renames agent .py + index .json, re-keys domain meta + summary cache |

### README AUTO-INDEX block

Each folder's README contains a maintained 2-column table kept current by the watcher:

```markdown
<!-- KB:AUTO-INDEX:START -->
| File | Summary |
|---|---|
| `doc.pdf` | One-sentence LLM summary (≤100 chars)... |
| `report.xlsx` | Quarterly pipeline analysis for CP4I and ACE |
| _EPM2-004 weekly snapshots_ | Weekly pipeline detail files for Q126, Q226 (19 files) — query by quarter/week |
<!-- KB:AUTO-INDEX:END -->
```

The watcher generates this block. `context_budget.py` compacts it at both write-time (watcher) and query-time (agent):

- **2 columns only** — File + Summary (Type/Size/Last Modified stripped)
- **Summary ≤ 100 chars** — `KB_BUDGET_SUMMARY` caps each row
- **Repeated-version groups collapsed** — e.g. 19 EPM2-004 files become 1 summary row
- **Heading boilerplate stripped** — `## 📁 Folder Index`, count lines removed

This block is the **primary retrieval context** — agents read it first before
falling back to raw vector search.

> **Note:** The watcher runs as a `launchd` daemon on macOS (service `com.knowledgebase.watcher`).
> Restart it via `launchctl stop/start com.knowledgebase.watcher`, not by killing the process.

---

## Bob AI Assistant Integration

If you use [Bob](https://github.com/ibm/bob), run `python3 generate.py` once -- the skill is
auto-installed to `~/.bob/skills/knowledgebase-agent/SKILL.md`. Bob will then trigger the
agent automatically when you ask questions about your documents.

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

---

## How `generate.py` is triggered

| Trigger | When |
|---|---|
| `python3 generate.py` | Manually -- run after first clone, or to force rebuild |
| `python3 generate.py --force` | Force regenerate everything from scratch |
| `python3 generate.py --no-llm` | Skip LLM steps (index + file gen only) |
| `watch_kb.py` (automatic) | Only when a **new top-level folder** is created |

---

## Known Issues & Fixes

### `is_readme` NameError in `watch_kb.py` _(fixed in commit `cf1ef9e`)_

**Affected versions:** all commits before `cf1ef9e`

**Symptom:** After starting `watch_kb.py`, adding, modifying, or deleting any file inside
an existing knowledge folder would silently crash the watchdog observer thread with:

```
NameError: name 'is_readme' is not defined. Did you mean: 'find_readme'?
  File "watch_kb.py", line 734, in on_created
```

The watcher process remained alive but stopped responding to all file system events --
no auto-indexing, no README updates would fire until the watcher was restarted.

**Root cause:** `is_readme()` was called in `on_created()`, `on_deleted()`, and `on_moved()`
event handlers but was never defined as a function.

**Fix:** Added the missing `is_readme(path)` helper alongside `should_skip()`:

```python
def is_readme(path: pathlib.Path) -> bool:
    """Return True if this path is a README file (should not be indexed as a doc)."""
    return "readme" in path.name.lower() or path.name.lower() == path.parent.name.lower() + ".md"
```

**If you cloned before this fix:** `git pull` to get the latest `watch_kb.py`, then restart the watcher.
