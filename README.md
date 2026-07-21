# KnowledgeBase Agent

A fully dynamic, multi-domain knowledge base agent. Point it at a folder of documents,
run one command, and ask questions in natural language — via any AI tool or the CLI.

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

> **LLM is optional.** The agent works in passthrough mode with no local model installed.
> Bob's Claude (or whatever AI tool is driving this) answers questions using retrieved context.
> You can add Ollama, OpenAI, or Anthropic later.

---

### Step 1 — Clone the repository

```bash
git clone <REPO_URL> ~/KnowledgeBase
cd ~/KnowledgeBase
```

Replace `<REPO_URL>` with the URL the user provided.
Replace `~/KnowledgeBase` with a different path if the user requested one.

---

### Step 2 — Add knowledge documents

Create one or more folders inside the repo and copy documents into them.
Any folder name works — the agent discovers all top-level folders automatically.

```bash
# Example: create a folder and add PDFs to it
mkdir "My Project"
cp /path/to/your/docs/*.pdf "My Project/"
```

**Supported file types:** `.pdf` `.docx` `.pptx` `.xlsx` `.md` `.txt` `.csv` `.boxnote` `.ppt` `.doc`

> Skip this step now if the user wants to add documents later. The agent will work with
> zero folders — just run `python3 generate.py` again after adding documents.

---

### Step 3 — Run the installer

```bash
python3 setup.py
```

`setup.py` handles everything in order:

1. Checks Python version (3.10+ required)
2. Runs `pip install -r requirements.txt`
3. Creates `.env` with `KB_ROOT` pre-filled to the current directory
4. Asks which LLM provider to use (Ollama / OpenAI / Anthropic / passthrough)
5. Runs `generate.py` — discovers folders, builds vector indexes, writes the agent skill

**Non-interactive mode** (no prompts, uses passthrough by default):
```bash
python3 setup.py --yes
```

**Custom install location:**
```bash
python3 setup.py --kb-root /absolute/path/to/folder
```

---

### Step 4 — Verify the installation

After `setup.py` completes, the skill file exists at:

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
python3 generate.py
```

To add a completely new domain:
```bash
mkdir "New Domain"
cp /path/to/new/docs/* "New Domain/"
python3 generate.py
```

---

### Troubleshooting

| Problem | Solution |
|---|---|
| `pip install` fails | Run `python3 -m pip install --upgrade pip` first, then retry |
| Skill file not found at `~/.bob/skills/` | Run `python3 generate.py` again |
| Agent returns empty answers | Check that your folders contain supported file types |
| `python3` not found (Windows) | Use `python` instead of `python3` throughout |
| Ollama not running | Either start it with `ollama serve` or choose passthrough mode |
| Permission denied on `.env` | Run `chmod 644 .env` |

---

## Environment Variables

After running `setup.py`, your `.env` file is created automatically. Edit it to change settings:

| Variable | Default | Description |
|---|---|---|
| `KB_ROOT` | _(repo root)_ | Absolute path to your knowledge base directory |
| `KB_LLM_PROVIDER` | `ollama` | LLM provider: `ollama` \| `openai` \| `anthropic` \| `custom` \| `passthrough` |
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
Run `generate.py --no-llm` to skip description/keyword generation entirely.

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

---

## Watcher (auto-update on file changes)

```bash
python3 watch_kb.py
```

Watches `KB_ROOT` for filesystem events and keeps everything in sync — no manual
`generate.py` runs needed for day-to-day file changes.

| Event | What happens |
|---|---|
| File added / modified / deleted inside existing folder | Re-embeds, updates index, rewrites README AUTO-INDEX block |
| New top-level folder created | Triggers `generate.py` automatically |
| Folder deleted | Removes index and domain metadata |
| Folder renamed | Renames index, re-keys domain metadata |

> **macOS note:** The watcher runs as a `launchd` daemon (`com.knowledgebase.watcher`).
> Restart with `launchctl stop/start com.knowledgebase.watcher`.

---

## How `generate.py` is triggered

| Trigger | When |
|---|---|
| `python3 generate.py` | Manually — run after first clone, or to force rebuild |
| `python3 generate.py --force` | Force regenerate everything from scratch |
| `python3 generate.py --no-llm` | Skip LLM steps (index + skill file only) |
| `watch_kb.py` (automatic) | Only when a **new top-level folder** is created |

---

## Architecture

### Component map

```
+-------------------------------------------------------+
|  CLOUD  [internet required]                           |
|                                                       |
|  Bob's Claude (or any AI tool)                        |
|    - detects skill trigger from your question         |
|    - runs the local agent as a subprocess             |
|    - relays the answer back to you                    |
|    - passthrough mode: answers using retrieved context|
|    NOTE: never sees your raw document files           |
+-------------------------------------------------------+
         |  subprocess                   ^  stdout
         v                               |
+-------------------------------------------------------+
|  YOUR MACHINE  [fully offline once set up]            |
|                                                       |
|  watch_kb.py  (daemon, always running)                |
|    watches KB_ROOT for file/folder changes            |
|    keeps *_index.json + README AUTO-INDEX current     |
|                                                       |
|  agent_knowledgebase.py  (orchestrator)               |
|    reads domain_meta.json to discover all domains     |
|    keyword_route()   -- fast match, no LLM            |
|    classify_intent() -- Ollama call only if ambiguous |
|    dispatches to agent_base.ask() per domain          |
|    (parallel ThreadPoolExecutor for multi-domain)     |
|                                                       |
|  agent_base.py  (shared RAG logic)                    |
|    Strategy 1: README-first  (primary)                |
|      reads <Folder>/README.md AUTO-INDEX block        |
|      simple question  -> index block + intro          |
|      complex question -> full README (up to 24k chars)|
|    Strategy 2: vector search  (fallback)              |
|      cosine similarity over *_index.json              |
|    calls Ollama or emits passthrough block            |
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
  "My Domain"/       -------->    |
  "Other Domain"/                 | 1. discover folders with indexable files
  <any folder>/                   | 2. build *_index.json  (embed every file)
                                  | 3. call LLM -> description + keywords
                                  | 4. write domain_meta.json
                                  | 5. write agents/SKILL.md
                                  v
                            agents/
                              agent_base.py          core RAG pipeline
                              embeddings.py          vector index
                              memory.py              session memory
                              agent_knowledgebase.py data-driven orchestrator
                              context_budget.py      token budget engine
                              SKILL.md               AI skill definition
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
You  [ask a question]
 |
 v
AI tool / Bob's Claude  [cloud]
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
 |       calls local LLM
 |       returns: which domain(s) to route to
 |
 +---> dispatch to domain agent(s) via agent_base.ask()
         |
         +-- README-first strategy  (primary)
         |     find <Folder>/README.md
         |     simple question   -> AUTO-INDEX block + intro
         |     complex question  -> full README up to 24,000 chars
         |
         +-- vector search fallback  (if README absent or too thin)
               query *_index.json by cosine similarity
               extract full text from top-N matched files
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

| Operation | Runs on | Network |
|---|---|---|
| Skill trigger detection | AI tool / Bob's Claude | Internet |
| Answer relay to you | AI tool / Bob's Claude | Internet |
| Passthrough Q&A | AI tool / Bob's Claude | Internet |
| Intent classification | Ollama (local) | Local only |
| Q&A answering | Ollama (local) | Local only |
| Text embedding | Ollama / sentence-transformers | Local only |
| File summary generation | Ollama (local) | Local only |
| Vector index search | numpy / scikit-learn | Local only |
| File watching | OS filesystem events | Local only |
| Document reading | pypdf / pptx / openpyxl | Local only |

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
