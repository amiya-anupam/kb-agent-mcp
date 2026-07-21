# KnowledgeBase Agent

A fully dynamic, multi-domain knowledge base agent system built for [Bob AI](https://github.com/ibm/bob).  
Add a folder of documents → run `generate.py` → ask questions in natural language via Bob or the CLI.

---

## Architecture

### Setup — run once

```
Your document folders  →  generate.py  →  (LLM: descriptions + keywords)
   ACE Docs/                  │
   BizOps/                    ▼
   CP4I Docs/         ┌───────────────────────────────────────┐
   <any folder>/      │  agents/                               │
                      │  ├── agent_base.py       core RAG      │
                      │  ├── embeddings.py       vector index  │
                      │  ├── memory.py           session mem   │
                      │  ├── agent_knowledgebase.py  router    │
                      │  ├── agent_<folder>.py   one per domain│
                      │  ├── SKILL.md            Bob skill     │
                      │  └── vector_store/                     │
                      │      ├── <folder>_index.json           │
                      │      └── domain_meta.json              │
                      └───────────────────────────────────────┘
```

### Query flow — every question

```
You ──► Bob (Claude) ──► agent_knowledgebase.py (subprocess)
                                    │
                         ┌──────────▼──────────┐
                         │  keyword_route()     │  fast, no LLM
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │  classify_intent()   │──► Local LLM
                         └──────────┬──────────┘     (routing)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             agent_A.py       agent_B.py      agent_C.py
                    │               │               │
                    └───────────────┴───────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │   agent_base.py      │
                         │  README-first RAG    │──► Local LLM (Q&A)
                         │  or vector search    │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │   merge_answers()    │
                         └──────────┬──────────┘
                                    │
                         Answer returned to you
```

### Passthrough mode (no local LLM)

```
sub-agent retrieves context  →  emit_passthrough()  →  Bob (Claude) answers
(offline embeddings)             <<<KB_PASSTHROUGH>>>   using retrieved context
```

> **Privacy:** your documents never leave your machine. Only retrieved text snippets
> are sent to Claude in passthrough mode. When a local LLM is running, nothing goes to Claude.

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
# Edit .env — set KB_ROOT to the absolute path of this repo, and configure your LLM

# 4. Add your knowledge folders (any top-level folder with documents)
mkdir "My Domain"
cp /path/to/your/docs/*.pdf "My Domain/"

# 5. Run the generator — discovers folders, builds indexes, generates agents + Bob skill
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

Watches for new top-level folders and file changes, then auto-triggers `generate.py`.

### What the watcher handles without running `generate.py`

| Event | Action |
|---|---|
| File added inside existing folder | Embeds + adds to vector index immediately |
| File modified | Re-embeds and updates index |
| File deleted | Removes from index |
| Folder renamed | Renames agent file, index, and meta entry |
| Folder deleted | Purges agent file, index, and meta entry |
| **New top-level folder created** | Runs `generate.py` (only case that needs it) |

> **Note:** The watcher is designed to run as a persistent background process.
> If you use `launchd` (macOS) or `systemd` (Linux) to manage it, restart via those
> services rather than killing the process directly.

---

## Bob AI Assistant Integration

If you use [Bob](https://github.com/ibm/bob), run `python3 generate.py` once — the skill is
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
| `python3 generate.py` | Manually — run after first clone, or to force rebuild |
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

The watcher process remained alive but stopped responding to all file system events —
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
