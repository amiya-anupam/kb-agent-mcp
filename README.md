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
python3 scripts/setup.py
```

`scripts/setup.py` handles everything in order:

1. Checks Python version (3.10+ required)
2. Runs `pip install -r requirements.txt`
3. Creates `.env` with `KB_ROOT` pre-filled to the current directory
4. Asks which LLM provider to use (Ollama / OpenAI / Anthropic / passthrough)
5. Runs `scripts/generate.py` — discovers folders, builds vector indexes, writes the agent skill

**Non-interactive mode** (no prompts, uses passthrough by default):
```bash
python3 scripts/setup.py --yes
```

**Custom install location:**
```bash
python3 scripts/setup.py --kb-root /absolute/path/to/folder
```

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
| `pip install` fails | Run `python3 -m pip install --upgrade pip` first, then retry |
| Skill file not found at `~/.bob/skills/` | Run `python3 scripts/generate.py` again |
| Agent returns empty answers | Check that your folders contain supported file types |
| `python3` not found (Windows) | Use `python` instead of `python3` throughout |
| Ollama not running | Either start it with `ollama serve` or choose passthrough mode |
| Permission denied on `.env` | Run `chmod 644 .env` |

---

## 🔒 Security & Privacy

### Data residency — what leaves your machine

| Operation | Goes to | Condition |
|---|---|---|
| Ingest script (`ingest.py`) | **Nowhere** — 100% local | Always |
| Q&A via local LLM (Ollama) | **Nowhere** | When Ollama is running |
| Q&A via cloud LLM (passthrough / OpenAI / Anthropic) | Remote cloud API | When `KB_LLM_PROVIDER` ≠ `ollama` or Ollama is unreachable |

> **Rule of thumb:** If `KB_LLM_PROVIDER=ollama` and Ollama is reachable, zero document content leaves your machine. Use `KB_PASSTHROUGH_FALLBACK=false` to prevent silent fallback to passthrough.

### Ingest script hardening

The `ingest.py` extraction script includes the following security controls:

| Control | Detail |
|---|---|
| Path traversal prevention | `sys.argv[1]` validated against an allowlist (`~/Desktop/KnowledgeBase`, `/tmp`) — any path outside exits with code 2 |
| Symlink traversal prevention | All symlinks skipped unconditionally during `rglob` walk |
| XML bomb / XXE prevention | All XML parsing uses `defusedxml` — stdlib `ElementTree` is not used |
| Image memory guard | Images over 50 MB are skipped before loading — only the path is emitted |
| EML recursion bomb prevention | MIME walk depth-limited to 50 parts per email |
| Error message sanitisation | Exception text stripped of absolute paths before entering LLM context |
| Per-file text cap | 50,000 chars per file |
| Total aggregate cap | 10,000,000 chars across all files — hard stop with truncation sentinel |

### Confidentiality classification

Every extracted file is automatically scanned for sensitivity signals. The result is surfaced in the Q&A skill as a consent gate — you choose whether to include flagged files in the session.

| Signal source | What is checked |
|---|---|
| **Text body** | Case-insensitive scan for keywords: `CONFIDENTIAL`, `INTERNAL USE ONLY`, `NOT FOR DISTRIBUTION`, `NOT FOR SHARING`, `DO NOT SHARE`, `DO NOT DISTRIBUTE`, `PROPRIETARY`, `RESTRICTED`, `PRIVILEGED`, `IBM CONFIDENTIAL`, `COMPANY CONFIDENTIAL`, `FOR INTERNAL USE`, `CLASSIFICATION:`, `SENSITIVE`, `TOP SECRET`, `PRIVATE AND CONFIDENTIAL` |
| **Filename / folder path** | Same keyword list applied to the full path string |
| **PDF metadata** | `/Keywords` and `/Subject` fields from the PDF information dictionary |
| **DOCX core properties** | `category` and `keywords` fields from the document's core properties |
| **EML header** | `Sensitivity:` header — matches `confidential`, `company-confidential`, `personal`, `private`, `restricted` |

**How it works in the skill:**
1. Step 2 shows `🔒` next to flagged files in the inventory, with the detection reason
2. Step 2b pauses and asks: include flagged files? (yes / no / pick by number)
3. Excluded files are never loaded into the LLM context — their content is replaced with a placeholder
4. Included flagged files are answered normally, with `🔒` prefix on all citations from them

**`.noindex` sentinel — hard exclusion:**
Place an empty file named `.noindex` inside any subfolder to prevent **all** files in that folder (and nested subfolders) from being extracted at all — they won't even appear in the inventory. Use this for truly off-limits directories:
```
~/Desktop/KnowledgeBase/
  passwords/
    .noindex          ← drop this empty file here
    my-passwords.txt  ← never extracted, never in context
```

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

## How `scripts/generate.py` is triggered

| Trigger | When |
|---|---|
| `python3 scripts/generate.py` | Manually — run after first clone, or to force rebuild |
| `python3 scripts/generate.py --force` | Force regenerate everything from scratch |
| `python3 scripts/generate.py --no-llm` | Skip LLM steps (index + skill file only) |
| `scripts/watch_kb.py` (automatic) | Only when a **new top-level folder** is created |

---

## Architecture

> For the complete technical reference — call graphs, security model, every decision tree, all environment variables — see **[ARCHITECTURE.md](ARCHITECTURE.md)** (18 sections, ground-truth from source).

### Component map

```
+---------------------------------------------------------------+
|  CLOUD  [internet required]                                   |
|                                                               |
|  Bob's Claude (or any AI tool)                                |
|    - detects skill trigger from your question                 |
|    - runs agent_knowledgebase.py (subprocess, for agent)      |
|    - relays the answer back to you                            |
|    - passthrough mode: answers using retrieved context        |
+---------------------------------------------------------------+
         |  subprocess / execute_command        ^  stdout
         v                                      |
+---------------------------------------------------------------+
|  YOUR MACHINE  [fully offline once set up]                    |
|                                                               |
|  agent_knowledgebase.py  (orchestrator)                       |
|    reads domain_meta.json to discover all domains             |
|    detect_format_intent() -- --format flag or NL              |
|    keyword_route() + _keyword_confidence()                    |
|      fast match, no LLM; confident if 1 domain >= 2 hits OR  |
|      one domain has >=3x hits of any other (dominant-match)   |
|    classify_intent() -- local LLM only if keyword ambiguous   |
|    call_sub_agent() -- loads agents/agent_<domain>.py via     |
|      importlib; falls back to agent_base.ask() if no file     |
|    run_agents_parallel() -- ThreadPoolExecutor fan-out        |
|                                                               |
|  agent_base.py  (shared RAG logic)                            |
|    _apply_format_instruction() — appends OUTPUT FORMAT        |
|      DIRECTIVE to system_prompt (imported by sub-agents too)  |
|    Data-question bypass: _is_data_question() skips README     |
|      for numeric/revenue/breakdown questions → RAG directly   |
|    Strategy 1: README-first  (primary, non-data questions)    |
|      reads <Folder>/README.md AUTO-INDEX block                |
|      simple question  -> index block + intro (8k chars)       |
|      complex question -> full README (up to 24k chars)        |
|    Strategy 2: vector search  (fallback / data questions)     |
|      cosine similarity over *_index.json                      |
|      XLSX: cache-first (index summary) → streaming aggregation|
|      _pre_ranked_results kwarg: sub-agents can pin files      |
|    confidence footer (High/Medium/Low) appended               |
|    calls Ollama or emits passthrough block                    |
|                                                               |
|  watch_kb.py  (daemon)                                        |
|    watches KB_ROOT for file/folder changes                    |
|    keeps *_index.json + README AUTO-INDEX current             |
|                                                               |
|  scripts/ask.py  (CLI wrapper)                                |
|    runs agent subprocess, intercepts passthrough blocks       |
|    re-sends context + question directly to Ollama             |
|    falls back to raw context if Ollama also unreachable       |
|                                                               |
|  agents/vector_store/                                         |
|    *_index.json         embeddings cache per domain           |
|    domain_meta.json     descriptions + keywords               |
|    session_memory.json  conversation history                  |
|                                                               |
|  <Folder>/README.md     primary retrieval context             |
|    <!-- KB:AUTO-INDEX:START --> ... <!-- END -->               |
|  <Folder>/.noindex      sentinel: skip entire folder          |
+---------------------------------------------------------------+
```

### Setup flow — run once

```
python3 scripts/setup.py
  │
  ├─ 1-6.  check Python, pip install, choose KB_ROOT + LLM, write .env, verify folders
  │
  ├─ 7.  run scripts/generate.py
  │         │
  │         │  Your document folders
  │         │    "My Domain"/       ──►  1. discover folders with indexable files
  │         │    "Other Domain"/         2. build *_index.json  (embed every file)
  │         │    <any folder>/           3. call LLM → description + keywords
  │         │                            4. write domain_meta.json
  │         │                            5. write agents/SKILL.md
  │         │                            v
  │         │                      agents/
  │         │                        agent_base.py          core RAG pipeline
  │         │                        embeddings.py          vector index
  │         │                        memory.py              session memory
  │         │                        agent_knowledgebase.py data-driven orchestrator
  │         │                        context_budget.py      token budget engine
  │         │                        SKILL.md               AI skill definition
  │         │                        vector_store/
  │         │                          <folder>_index.json
  │         │                          domain_meta.json
  │         │                          session_memory.json
  │         │                            │
  │         │                            v
  │         │               ~/.bob/skills/knowledgebase-agent/SKILL.md
  │         │               (auto-copied so Bob knows the CLI command to run)
  │
  └─ 8.  install_install_skill()
            copies skills/knowledgebase-install/ → ~/.bob/

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

All notable changes to this project are listed here, newest first.

<!-- CHANGELOG_START -->
---

### _(latest)_ — chore: repo cleanup + agent improvements

**Routing & dispatch**
- `agent_knowledgebase.py`: `_keyword_confidence()` now uses a dominant-match rule — one domain with ≥3× the keyword hits of any other is treated as confident, routing queries like "ACE and CP4I revenue" to BizOps without calling the LLM
- `call_sub_agent()`: checks for `agents/agent_<safe>.py` first; if present, loads it via `importlib` and calls `module.domain_ask()` — enables domain-specific retrieval logic without modifying shared code

**`agent_base.py`**
- `_apply_format_instruction()` moved here from `agent_knowledgebase.py` so per-domain sub-agent files can import it without circular dependency
- `ask()` accepts `_pre_ranked_results` kwarg — sub-agents can pass pre-ordered file results (used by BizOps to pin Revenue files)

**`agents/agent_bizops.py`** _(generated)_
- Revenue-file pinning in `domain_ask()` — `*Revenue*.xlsx` files are always included first in search results for data questions

**`scripts/generate.py`**
- `generate_sub_agent()` restored — writes `agents/agent_<safe>.py` per domain after index build

**Repo hygiene**
- Removed: `kb-arch-online-offline.html`, `knowledgebase-agent-architecture.html` (one-off HTML artifacts)
- Removed: `agents/vector_store/requirements_txt_index.json` (orphaned index)
- Removed: `__pycache__/` at repo root (stale pyc from old script paths)
- Added `.bob/` and `*.html` to `.gitignore`

---

### — feat: data-question bypass + cache-first XLSX aggregation + KB_GENERATE_TIMEOUT

**`agents/agent_base.py`**
- Added `_DATA_QUESTION_PATTERNS` regex and `_is_data_question()` — numeric/revenue/breakdown questions bypass README-first entirely and go straight to raw-file RAG
- Added `VECTOR_STORE` path constant and `folder_to_safe_name()` helper
- `_get_readme_context()` returns `(None, "")` immediately when `_is_data_question()` is True
- `extract_full_text()` for `.xlsx/.xls`: checks vector index cache first (if cached summary >200 chars, returns it instantly); falls back to single-pass streaming aggregation detecting revenue + group-by columns

**`agents/embeddings.py`**
- `extract_text_snippet()` for `.xlsx/.xls`: replaced 30-row dump with single-pass streaming aggregation; for large sheets stores pre-aggregated totals (up to 8000 chars) as the index `summary` field — eliminating the ~52 s file-open cost at query time

**`scripts/watch_kb.py`**
- Added `KB_GENERATE_TIMEOUT` env var (default `900` s); `run_generate()` uses it and prints it; timeout error message includes a hint to increase the var

---

### — chore: remove knowledge-qa skill — replaced by knowledgebase-agent

**`scripts/setup.py`**
- Removed `install_knowledge_qa_skill()` and `prewarm_uv_cache()` steps — no longer needed
- Setup flow reduced from 10 steps to 8

**`agents/SKILL.md`** + **`~/.bob/skills/knowledgebase-agent/SKILL.md`**
- Expanded trigger phrases and domain descriptions so Bob routes all document questions directly to the knowledgebase-agent skill
- Removed `knowledge-qa` fallback reference

**Deleted files:** `skills/knowledge-qa/`, `scripts/sync_skill.sh`

---

### `96c0a61` — feat: add scripts/ask.py — offline-capable CLI wrapper

**`scripts/ask.py`** _(new file)_
- Wraps `agent_knowledgebase.py` as a subprocess, capturing stdout
- Detects `<<<KB_PASSTHROUGH>>>` blocks in output — when present, extracts question + context and re-sends directly to Ollama `localhost:11434/api/chat`
- Falls back to printing raw retrieved context if Ollama is also unreachable, so the user always gets document excerpts even with zero network
- `KB_MODEL` and `KB_LLM_BASE_URL` respected from `.env`

---

**`requirements.txt`**
- Added: `python-docx`, `beautifulsoup4`, `striprtf`, `pyyaml`, `ebooklib`, `defusedxml`

**`README.md`**
- Supported file types table expanded with all new formats
- New Security & Privacy section with data residency table and ingest hardening table
- "What needs internet" table updated: added `uv` PyPI install row, network audit probe row, updated document reading row

---

### `bcab415` — docs: update README and .env.example for all recent features

README.md: - CLI Usage: new Structured Answer Format section with --format flag,   inline mode, NL
phrase examples, and format table - Watcher: new Stale File Alerts subsection with startup/hourly
cadence,   example output, and KB_STALE_DAYS reference - Environment Variables: added KB_STALE_DAYS
and KB_PASSTHROUGH_FALLBACK rows - Architecture component map: added detect_format_intent(), format
directive   injection, and confidence footer to agent_base.py description - Query flow diagram:
added detect_format_intent step, format directive   injection, and confidence footer step to the
flow - Changelog section (bottom): full entry for every commit since cf1ef9e —   f6acfdf (format
flag), a50127c (stale watcher), f7d29b1 (confidence score),   202811e (auto-summarise), 045d9de
(token efficiency), cfa5787 (error   handling), cf1ef9e (is_readme fix)

.env.example: - KB_LLM_PROVIDER: added passthrough to supported values list -
KB_PASSTHROUGH_FALLBACK: new variable with full inline documentation - KB_STALE_DAYS: updated
comment to mention startup + hourly cadence - KB_FORMAT_DEFAULT: new variable documenting the
structured format flag   with all supported values and aliases

---

### `f6acfdf` — feat: structured answer format flag

Add --format CLI flag and natural-language intent detection that injects a format directive into the
system prompt before every LLM call.

Supported formats (canonical names + aliases):   table     — Markdown table with headers   bullets
— Markdown bullet list  (aliases: bullet, list)   oneline   — single sentence       (aliases: 1line,
one-line, one-liner)   paragraph — prose paragraphs      (aliases: prose, paragraphs)   numbered  —
numbered Markdown list (aliases: num, numbered-list)   json      — raw JSON output

Natural-language phrase detection (no flag required):   'give me a table', 'as bullet points', 'in
one sentence',   'as a numbered list', 'return as json', 'as paragraphs', etc.

Changes:   agents/agent_knowledgebase.py   - _FORMAT_INSTRUCTIONS dict: canonical format → system
prompt instruction   - _FORMAT_PHRASE_MAP list: compiled regex patterns → format key   -
_FORMAT_ALIASES dict: shorthands normalised to canonical names   - detect_format_intent(question,
explicit_flag): returns (question, instruction)   - _apply_format_instruction(system_prompt,
instruction): appends directive   - call_sub_agent: accepts format_instruction kwarg, applies before
ask()   - run_agents_parallel: forwards format_instruction to all sub-agents   - ask_knowledgebase:
accepts format_flag kwarg, calls detect_format_intent   - run_interactive: parses inline '--format
X' from typed questions   - __main__: parses --format / --format=value from CLI argv

Passthrough path unaffected: format directive is appended to system_prompt before emit_passthrough
is called, so the SYSTEM_PROMPT block in the passthrough output already carries the format
instruction for Bob's Claude.

---

### `a50127c` — feat: stale file watcher alert

Add KB_STALE_DAYS env var (default: 90 days) and check_stale_files() to watch_kb.py. Emits warnings
for any indexed file whose mtime exceeds the configured threshold, e.g.:

  ⚠ BizOps: Q3_Renewal_Tracker.xlsx was last updated 112 days ago.

Changes: - STALE_DAYS config: reads KB_STALE_DAYS, defaults to 90, ValueError-   safe for bad input;
set to 0 to disable entirely - _STALE_CHECK_INTERVAL = 3600 (hourly re-scan cadence) -
check_stale_files(folders): iterates gather_files() per domain,   reads st_mtime, compares against
timedelta(days=STALE_DAYS), returns   list of warning strings; OSError on stat() silently skipped -
main(): runs stale check at startup, prints warnings or clean-bill   message, shows configured
threshold - KBHandler.__init__: adds _next_stale_check timestamp - dispatch_pending() step 6: hourly
re-scan via _next_stale_check - .env.example: documents KB_STALE_DAYS with example output and
disable instruction

No agent files modified. Feature is entirely self-contained in watch_kb.py.

<!-- CHANGELOG_END -->