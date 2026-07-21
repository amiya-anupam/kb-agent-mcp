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
git clone https://github.ibm.com/Amiya-Anupam1/knowledgebase-agent.git
cd knowledgebase-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your environment
cp .env.example .env
# Edit .env -- set KB_ROOT to the absolute path of this repo, and configure your LLM

# 4. Add your knowledge folders (any top-level folder with documents)
mkdir "My Domain"
cp /path/to/your/docs/*.pdf "My Domain/"

# 5. Run the generator -- discovers folders, builds indexes, generates agents + Bob skill
python3 generate.py

# 6. Ask a question via CLI
python3 agents/agent_knowledgebase.py "your question here"
```

After `generate.py` runs, the Bob skill is auto-installed to `~/.bob/skills/knowledgebase-agent/SKILL.md`
and you can ask questions directly in Bob.

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

Each folder's README contains a maintained table kept current by the watcher:

```markdown
<!-- KB:AUTO-INDEX:START -->
## Folder Index

| File | Type | Size | Last Modified | Summary |
|---|---|---|---|---|
| `doc.pdf` | PDF | 1.2 MB | 2024-11-01 | One-sentence LLM summary... |
<!-- KB:AUTO-INDEX:END -->
```

This block is the **primary retrieval context** -- agents read it first before
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
