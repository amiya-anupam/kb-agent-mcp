# KnowledgeBase Agent

A fully dynamic, multi-domain knowledge base agent system.  
Add a folder of documents → run `generate.py` → ask questions in natural language.

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url>
cd KnowledgeBase

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your environment (copy and edit)
cp .env.example .env
# Edit .env — set KB_ROOT, KB_MODEL, KB_LLM_PROVIDER etc.

# 4. Add your knowledge folders (any top-level folder with documents)
#    e.g. mkdir "My Project" && cp *.pdf "My Project/"

# 5. Run the generator (discovers folders, builds indexes, generates agents)
python3 generate.py

# 6. Ask a question
python3 agents/agent_knowledgebase.py "your question here"
```

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

## Current Domains

| `ACE Docs` | Folder containing App Connect ACE documentation, presentations, guides, and migration resources. |
| `BizOps` | Folder containing IBM App Connect Enterprise (ACE) purchasing options, renewal materials, and customer tracking documents. |
| `CP4I Docs` | Folder containing Cloud Pak for Integration documentation, presentations, and sales materials. |
| `Test Domain` | A folder containing files related to Test Domain, including FAQs and integration testing content. |

## Adding a New Knowledge Domain

1. Create a folder in `/Users/amiyaanupam/Desktop/KnowledgeBase` (e.g. `mkdir "Sales Reports"`)
2. Copy your documents into it
3. Run `python3 generate.py`

That's it. The generator will:
- Auto-discover the new folder
- Build a vector index for it
- Generate a description + keywords using the LLM
- Create `agents/agent_sales_reports.py`
- Update the orchestrator and skill

## Architecture

```
generate.py                    ← run once to set everything up
├── agents/
│   ├── agent_base.py          ← shared RAG logic (extract, embed, ask)
│   ├── embeddings.py          ← dynamic vector index (Ollama/OpenAI/offline)
│   ├── memory.py              ← conversation memory (persists across sessions)
│   ├── agent_knowledgebase.py ← orchestrator (auto-generated)
│   ├── agent_<folder>.py      ← one per domain (auto-generated)
│   ├── SKILL.md               ← Bob skill definition (auto-generated)
│   └── vector_store/
│       ├── <folder>_index.json   ← embeddings cache per domain
│       └── domain_meta.json      ← descriptions + keywords per domain
└── <YourFolder>/              ← your knowledge documents
```

## Supported File Types

`.pdf` `.docx` `.pptx` `.xlsx` `.md` `.txt` `.csv` `.boxnote` `.ppt` `.doc`

## LLM Providers

| Provider | `KB_LLM_PROVIDER` | Notes |
|---|---|---|
| Ollama (local) | `ollama` | Default. Run `ollama serve` first. |
| OpenAI | `openai` | Set `KB_API_KEY` |
| Anthropic | `anthropic` | Set `KB_API_KEY` |
| LM Studio / Jan | `custom` | Set `KB_LLM_BASE_URL` to local server URL |

**No LLM?** Embeddings fall back to `sentence-transformers` (offline, ~80MB).  
Run `generate.py --no-llm` to skip description/keyword generation.

## Watcher (auto-update on file changes)

```bash
python3 watch_kb.py
```

Watches for new top-level folders and file changes, then auto-triggers `generate.py`.

## Bob AI Assistant Integration

If you use [Bob](https://github.com/ibm/bob), the skill is auto-installed to  
`~/.bob/skills/knowledgebase-agent/SKILL.md` when you run `generate.py`.
