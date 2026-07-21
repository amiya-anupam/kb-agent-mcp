#!/usr/bin/env python3
"""
generate.py — KnowledgeBase Agent Generator
--------------------------------------------
Run this script once after cloning, or whenever you add/remove knowledge folders.

What it does (in order):
  1.  Loads env vars (.env or system environment)
  2.  Discovers top-level knowledge folders under KB_ROOT
  3.  Cleans up stale vector index files for removed folders
  4.  Builds / updates vector indexes for each folder
  5.  Generates (or updates) domain descriptions + keywords via LLM
      (soft-skipped if LLM is unreachable — uses folder name as placeholder)
  6.  Writes agents/vector_store/domain_meta.json
      (orchestrator reads this at runtime — no per-domain .py files needed)
  7.  Writes requirements.txt
  8.  Writes README.md
  9.  Writes agents/SKILL.md and auto-copies to ~/.bob/skills/ if Bob is installed

Usage:
  python3 generate.py            # incremental (skip unchanged folders)
  python3 generate.py --force    # regenerate everything from scratch
  python3 generate.py --no-llm   # skip LLM steps (index + file gen only)
"""

import os
import re
import sys
import json
import shutil
import pathlib
import textwrap
import argparse

# ── Environment loader ────────────────────────────────────────────────────────

def load_env(root: pathlib.Path):
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

# ── Config resolution ─────────────────────────────────────────────────────────

SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()

def resolve_kb_root() -> pathlib.Path:
    raw = os.environ.get("KB_ROOT", "")
    return pathlib.Path(raw).resolve() if raw else SCRIPT_DIR

_DEFAULT_BLOCKLIST = {
    "agents", ".git", "__pycache__", ".ds_store", "node_modules",
    ".venv", "venv", "env", ".bob", ".idea", ".vscode", "dist", "build",
}

def get_blocklist() -> set[str]:
    extra = os.environ.get("KB_IGNORE_FOLDERS", "")
    user  = {f.strip().lower() for f in extra.split(",") if f.strip()}
    return _DEFAULT_BLOCKLIST | user

INCLUDE_EXTS  = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt",
                 ".csv", ".boxnote", ".ppt", ".doc"}
SKIP_PATTERNS = {"readme", ".ds_store", "watch_kb", "__pycache__"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def should_skip(path: pathlib.Path) -> bool:
    return any(p in path.name.lower() for p in SKIP_PATTERNS)


def folder_to_safe_name(name: str) -> str:
    """ACE Docs → ace_docs  |  My Sales & Revenue → my_sales_revenue"""
    n = name.lower()
    n = re.sub(r"[^a-z0-9]+", "_", n)
    n = n.strip("_")
    return n


def agent_filename(folder_name: str) -> str:
    return f"agent_{folder_to_safe_name(folder_name)}.py"


def discover_folders(kb_root: pathlib.Path, blocklist: set[str]) -> list[str]:
    """Return top-level folder names that contain at least one indexable file."""
    folders = []
    for p in sorted(kb_root.iterdir()):
        if not p.is_dir():
            continue
        if p.name.lower() in blocklist:
            continue
        has_files = any(
            f.suffix.lower() in INCLUDE_EXTS
            for f in p.rglob("*")
            if f.is_file() and not should_skip(f)
        )
        if has_files:
            folders.append(p.name)
    return folders


def count_files(folder: pathlib.Path) -> int:
    return sum(
        1 for f in folder.rglob("*")
        if f.is_file()
        and f.suffix.lower() in INCLUDE_EXTS
        and not should_skip(f)
    )


# ── LLM helpers ───────────────────────────────────────────────────────────────

def llm_available() -> bool:
    """Quick check — try to reach the LLM endpoint."""
    try:
        import httpx
        provider    = os.environ.get("KB_LLM_PROVIDER", "ollama").lower()
        base_url    = os.environ.get("KB_LLM_BASE_URL", "http://localhost:11434")
        if provider == "ollama":
            r = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        else:
            # For OpenAI-compat just check the base URL is reachable
            r = httpx.get(base_url.rstrip("/"), timeout=5.0)
        return r.status_code < 500
    except Exception:
        return False


def call_llm_generate(prompt: str) -> str:
    """Call the LLM with a plain prompt and return text."""
    import httpx

    provider  = os.environ.get("KB_LLM_PROVIDER", "ollama").lower()
    base_url  = os.environ.get("KB_LLM_BASE_URL", "http://localhost:11434")
    model     = os.environ.get("KB_MODEL", "qwen3:14b")
    api_key   = os.environ.get("KB_API_KEY", "")
    messages  = [{"role": "user", "content": prompt}]

    if provider == "anthropic":
        headers = {
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type":      "application/json",
        }
        r = httpx.post(
            f"{base_url}/v1/messages",
            headers=headers,
            json={"model": model, "max_tokens": 1024,
                  "temperature": 0.3, "messages": messages},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()

    if provider in ("openai", "custom"):
        b = base_url.rstrip("/")
        if "11434" in b and not b.endswith("/v1"):
            b = f"{b}/v1"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        r = httpx.post(
            f"{b}/chat/completions",
            headers=headers,
            json={"model": model, "messages": messages, "temperature": 0.3},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    # Ollama
    import importlib as _imp
    _agents_dir = pathlib.Path(__file__).parent / "agents"
    if str(_agents_dir) not in sys.path:
        sys.path.insert(0, str(_agents_dir))
    _cb = _imp.import_module("context_budget")
    r = httpx.post(
        f"{base_url}/api/chat",
        json={"model": model, "messages": messages, "stream": False,
              "options": {"temperature": 0.3, "num_ctx": _cb.get("num_ctx")}, "think": False},
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


# ── Domain meta generation ────────────────────────────────────────────────────

def generate_domain_meta(folder_name: str, folder: pathlib.Path) -> dict:
    """
    Ask the LLM to generate a description and keywords for this folder
    by sampling a few filenames + snippets.
    Returns { "description": str, "keywords": [str, ...] }
    """
    # Collect up to 20 file names + first-line snippets
    samples = []
    for f in sorted(folder.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in INCLUDE_EXTS:
            continue
        if should_skip(f):
            continue
        try:
            if f.suffix.lower() in {".txt", ".md", ".csv"}:
                first_line = f.read_text(encoding="utf-8", errors="ignore")[:200]
            else:
                first_line = f"[{f.suffix.upper().lstrip('.')} file]"
            samples.append(f"- {f.name}: {first_line[:100]}")
        except Exception:
            samples.append(f"- {f.name}")
        if len(samples) >= 20:
            break

    samples_text = "\n".join(samples)

    prompt = f"""You are helping configure a knowledge base search system.
I have a folder called "{folder_name}" containing these files:

{samples_text}

Based on these files, respond with ONLY a valid JSON object in this exact format:
{{
  "description": "One sentence describing what this folder contains (max 200 chars)",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6", "keyword7", "keyword8", "keyword9", "keyword10"]
}}

Rules:
- description: plain English, no quotes inside, max 200 characters
- keywords: 10-15 short words or phrases a user might type when asking about this domain
- respond with ONLY the JSON object, no explanation"""

    raw = call_llm_generate(prompt)

    # Extract JSON from response (LLM may wrap it in markdown)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return {
                "description": str(data.get("description", folder_name))[:200],
                "keywords":    [str(k) for k in data.get("keywords", [])[:15]],
            }
        except json.JSONDecodeError:
            pass

    # Fallback
    return {"description": folder_name, "keywords": [folder_name.lower()]}


# ── README finder (shared by stub generator and stale-check) ─────────────────

def _find_readme(folder: pathlib.Path) -> pathlib.Path | None:
    """
    Locate the README for a knowledge folder using a priority cascade:
      1. Any .md whose name contains 'readme' (case-insensitive)
      2. <FolderName>.md  (standard name used by this generator)
      3. Any .md file whose first 500 chars contain a Markdown heading (# …)
      4. The first .md file found (last resort)

    Fully dynamic — works for any user-chosen filename.
    """
    try:
        md_files = [f for f in folder.iterdir()
                    if f.is_file() and f.suffix.lower() == ".md"]
    except Exception:
        return None

    if not md_files:
        return None

    # Priority 1: name contains "readme"
    for f in md_files:
        if "readme" in f.name.lower():
            return f

    # Priority 2: matches the folder name exactly (e.g. "ACE Docs.md")
    folder_name_md = folder.name + ".md"
    for f in md_files:
        if f.name == folder_name_md:
            return f

    # Priority 3: first .md whose content starts with a Markdown heading
    for f in md_files:
        try:
            head = f.read_text(encoding="utf-8", errors="ignore")[:500]
            if re.search(r"^#{1,3}\s+\S", head, re.MULTILINE):
                return f
        except Exception:
            continue

    # Priority 4: first .md file
    return md_files[0]


# ── README stub generator (for new folders with no README) ───────────────────


def generate_readme_stub(folder_name: str, folder: pathlib.Path, description: str) -> pathlib.Path:
    """
    Create a structured README for a new knowledge folder that has none.
    The watcher will append the AUTO-INDEX block later on first run.
    README filename is derived from the folder name — never hardcoded.
    Returns the path to the created README.
    """
    # Collect file names for the stub
    files = [
        f for f in sorted(folder.rglob("*"))
        if f.is_file() and f.suffix.lower() in INCLUDE_EXTS and not should_skip(f)
    ]
    file_list = "\n".join(f"- {f.name}" for f in files[:20])

    # Name README after the folder itself — no fixed suffix
    readme_path = folder / f"{folder_name}.md"
    existing = _find_readme(folder)
    if existing:
        return existing  # don't overwrite existing README

    # Try to generate a richer stub with the LLM
    stub_content = None
    if llm_available():
        prompt = (
            f'I have a knowledge folder called "{folder_name}" with these files:\n\n'
            f"{file_list}\n\n"
            f"Domain description: {description}\n\n"
            f"Write a concise README for this knowledge domain (3-5 paragraphs max). "
            f"Include: what this domain covers, key topics, and how someone would use it. "
            f"Use plain Markdown. No code blocks. No headers beyond # and ##."
        )
        try:
            stub_content = call_llm_generate(prompt)
        except Exception:
            stub_content = None

    if not stub_content:
        stub_content = (
            f"# {folder_name}\n\n"
            f"{description}\n\n"
            f"## Contents\n\n"
            f"{file_list}\n\n"
            f"_Add your own notes about this domain above this line._\n"
        )

    readme_path.write_text(stub_content, encoding="utf-8")
    return readme_path



def generate_orchestrator(domains: list[dict], agents_dir: pathlib.Path):
    """No-op: orchestrator reads domain_meta.json dynamically at runtime."""
    pass


# ── SKILL.md generator ────────────────────────────────────────────────────────

def generate_skill_md(domains: list[dict], agents_dir: pathlib.Path, kb_root: pathlib.Path):
    domain_lines = "\n".join(
        f"- **{d['folder_name']}**: {d['description']}" for d in domains
    )
    folder_names = ", ".join(d["folder_name"] for d in domains)
    trigger_keywords = ", ".join(
        kw for d in domains for kw in d["keywords"][:3]
    )

    content = f"""\
---
name: knowledgebase-agent
description: >
  Multi-domain KnowledgeBase agent. Routes questions to the correct
  specialist sub-agent automatically based on your knowledge folders.
  Use when asking about any content in your KnowledgeBase.

  Current domains ({len(domains)}):
{textwrap.indent(domain_lines, "  ")}

  Trigger phrases: ask the agent, KnowledgeBase Agent, query knowledge base,
  {trigger_keywords}, what does my KnowledgeBase say, /kb, /agent

execute: |
  python3 {kb_root}/agents/agent_knowledgebase.py "${{QUESTION}}"
---

# KnowledgeBase Agent Skill

## How Bob uses this skill

When you ask Bob a question that triggers this skill, Bob runs:
```
python3 {kb_root}/agents/agent_knowledgebase.py "<your question>"
```
The Python script handles **all the AI work locally** (routing, retrieval, answering)
using your local LLM (Ollama / OpenAI / etc.). Bob reads the output and relays it back.

**Bob's Claude is used for:** understanding your request and deciding to invoke this skill.
**Your local LLM is used for:** intent classification, semantic routing, document Q&A.
**No document content is ever sent to Claude.**

## Current Domains
{domain_lines}

## Usage
Just ask naturally — Bob detects the intent and runs the agent:
- "What is the ACE MCP server?"
- "Which customers are at risk of churn?"
- "How does CP4I licensing work?"
- "Ask the KnowledgeBase agent about ACE licensing"

## Commands
- `/kb <question>` — query the knowledge base
- `/agent <question>` — same as /kb
- `/kb --clear` — clear conversation memory
- `/kb --memory` — show conversation history summary

## How the pipeline works
```
You → Bob (Claude) → detects skill trigger
                   → runs: python3 agent_knowledgebase.py "<question>"
                             ↓
                        keyword_route()  ← fast, no LLM
                             ↓ (if ambiguous)
                        classify_intent() ← your local LLM
                             ↓
                        search() ← embeddings (local)
                             ↓
                        call_llm() ← your local LLM answers
                             ↓
                   → Bob reads stdout and returns answer to you
```

## Setup
Knowledge base root: `{kb_root}`
Domains discovered: {folder_names}

To add a new domain: add a folder with documents to `{kb_root}`, then run:
```
python3 {kb_root}/generate.py
```

## Technical Details
- Embedding: configurable via `KB_EMBED_MODEL` (Ollama / OpenAI / offline fallback)
- LLM: configurable via `KB_MODEL` and `KB_LLM_PROVIDER`
- Conversation memory: persists across sessions (auto-resets after 2h inactivity)
- Invocation: `python3 {kb_root}/agents/agent_knowledgebase.py "<question>"`
"""

    # Write to agents/SKILL.md (in-repo copy)
    skill_path = agents_dir / "SKILL.md"
    skill_path.write_text(content, encoding="utf-8")

    # Auto-copy to ~/.bob/skills/knowledgebase-agent/SKILL.md if Bob is installed
    bob_skills_dir = pathlib.Path.home() / ".bob" / "skills" / "knowledgebase-agent"
    if bob_skills_dir.parent.parent.exists():  # ~/.bob exists
        bob_skills_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_path, bob_skills_dir / "SKILL.md")
        print(f"  ✓ Skill copied to {bob_skills_dir / 'SKILL.md'}")
    else:
        print(f"  ℹ Bob not detected. To install the skill manually:")
        print(f"    mkdir -p ~/.bob/skills/knowledgebase-agent")
        print(f"    cp agents/SKILL.md ~/.bob/skills/knowledgebase-agent/SKILL.md")


# ── requirements.txt generator ────────────────────────────────────────────────

def generate_requirements(out_path: pathlib.Path):
    content = """\
# KnowledgeBase Agent — Python dependencies
# Install with: pip install -r requirements.txt

# ── Core (required) ───────────────────────────────────────────
httpx>=0.27.0
numpy>=1.26.0
scikit-learn>=1.4.0
watchdog>=4.0.0

# ── File format support (required for full document coverage) ─
pypdf>=4.0.0          # PDF reading
python-pptx>=1.0.0    # PPTX/PPT reading
openpyxl>=3.1.0       # XLSX/XLS reading

# ── Offline embedding fallback (optional but recommended) ─────
# Install this if you don't have Ollama or an OpenAI API key.
# Downloads ~80MB model on first use (all-MiniLM-L6-v2).
sentence-transformers>=3.0.0

# ── .env file support (optional) ─────────────────────────────
# Already handled natively — no python-dotenv needed.
"""
    out_path.write_text(content, encoding="utf-8")


# ── README.md generator ───────────────────────────────────────────────────────

def generate_readme(domains: list[dict], kb_root: pathlib.Path, out_path: pathlib.Path):
    domain_table_rows = "\n".join(
        f"| `{d['folder_name']}` | {d['description']} |"
        for d in domains
    )
    folder_names = ", ".join(f"`{d['folder_name']}`" for d in domains)

    content = f"""\
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
| `KB_LLM_PROVIDER` | `ollama` | LLM provider: `ollama` \\| `openai` \\| `anthropic` \\| `custom` |
| `KB_LLM_BASE_URL` | `http://localhost:11434` | Base URL for the LLM API |
| `KB_MODEL` | `qwen3:14b` | Model name for Q&A and routing |
| `KB_API_KEY` | _(empty)_ | API key for OpenAI / Anthropic / custom providers |
| `KB_EMBED_MODEL` | `nomic-embed-text` | Embedding model (leave blank for offline fallback) |
| `KB_IGNORE_FOLDERS` | _(empty)_ | Comma-separated extra folders to exclude from discovery |

## Current Domains

{domain_table_rows}

## Adding a New Knowledge Domain

1. Create a folder in `{kb_root}` (e.g. `mkdir "Sales Reports"`)
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
"""
    out_path.write_text(content, encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate KnowledgeBase agents from discovered folders."
    )
    parser.add_argument("--force",  action="store_true",
                        help="Regenerate everything, ignoring cache")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM steps (index + file gen only, placeholder descriptions)")
    args = parser.parse_args()

    # ── Step 0: load env ──────────────────────────────────────────────────────
    load_env(SCRIPT_DIR)
    kb_root    = resolve_kb_root()
    blocklist  = get_blocklist()
    agents_dir = SCRIPT_DIR / "agents"
    agents_dir.mkdir(exist_ok=True)
    (agents_dir / "vector_store").mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  KnowledgeBase Agent Generator")
    print(f"  KB_ROOT: {kb_root}")
    print(f"{'='*60}\n")

    # ── Step 1: discover folders ──────────────────────────────────────────────
    folders = discover_folders(kb_root, blocklist)
    if not folders:
        print(f"✗ No knowledge folders found under {kb_root}")
        print(f"  Create a folder with documents and re-run generate.py")
        sys.exit(1)
    print(f"Discovered {len(folders)} folder(s): {', '.join(folders)}\n")

    # ── Step 2: clean up stale _index.json files ──────────────────────────────
    # No per-domain .py files are generated; the orchestrator reads domain_meta.json.
    # Delete stale vector index files
    vector_store = agents_dir / "vector_store"
    expected_index_files = {
        f"{folder_to_safe_name(f)}_index.json" for f in folders
    } | {"domain_meta.json", "session_memory.json", "file_summaries.json"}
    for idx_file in vector_store.glob("*_index.json"):
        if idx_file.name not in expected_index_files:
            idx_file.unlink()
            print(f"  🗑  Deleted orphaned index: {idx_file.name}")

    # Clean stale entries from file_summaries.json cache.
    # Keys are stored as POSIX-style paths ("FolderName/file.ext") regardless
    # of OS.  Split on the first "/" to extract the folder name, then check
    # whether that folder is still in our discovered set.
    summaries_path = vector_store / "file_summaries.json"
    if summaries_path.exists():
        try:
            summaries = json.loads(summaries_path.read_text(encoding="utf-8"))
            folder_set = set(folders)
            stale_keys = [
                k for k in summaries
                if k.replace("\\", "/").split("/")[0] not in folder_set
            ]
            if stale_keys:
                for k in stale_keys:
                    del summaries[k]
                summaries_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
                print(f"  🗑  Removed {len(stale_keys)} stale summary cache entries")
        except Exception:
            pass

    # ── Step 3: load existing domain_meta ─────────────────────────────────────
    meta_path    = agents_dir / "vector_store" / "domain_meta.json"
    domain_meta: dict[str, dict] = {}
    if meta_path.exists():
        try:
            domain_meta = json.loads(meta_path.read_text())
        except Exception:
            domain_meta = {}

    # ── Step 4 + 5: build indexes + generate meta ─────────────────────────────
    # Import here so env vars are already set
    sys.path.insert(0, str(agents_dir))
    from embeddings import build_index

    use_llm = not args.no_llm
    if use_llm:
        print("Checking LLM availability...", end=" ", flush=True)
        use_llm = llm_available()
        print("✓ available" if use_llm else "✗ not reachable (will use placeholder descriptions)")
        print()

    domains_list = []

    for folder_name in folders:
        folder = kb_root / folder_name
        safe   = folder_to_safe_name(folder_name)
        n_files = count_files(folder)

        print(f"[{folder_name}]")

        # Build / update vector index
        print(f"  Building index...")
        build_index(folder_name, force=args.force)

        # Check if we can skip meta generation
        existing = domain_meta.get(folder_name, {})
        cached_count = existing.get("file_count", -1)
        has_meta = bool(existing.get("description") and existing.get("keywords"))

        if has_meta and cached_count == n_files and not args.force:
            print(f"  ✓ Meta cached ({n_files} files, unchanged)")
            entry = existing
        elif use_llm:
            print(f"  Generating description + keywords via LLM...")
            try:
                meta = generate_domain_meta(folder_name, folder)
                description = meta["description"]
                keywords    = meta["keywords"]
                print(f"  ✓ Description: {description[:80]}...")
            except Exception as e:
                print(f"  ⚠ LLM meta failed ({e}) — using placeholder")
                description = f"Knowledge domain: {folder_name}"
                keywords    = [folder_name.lower(), safe.replace("_", " ")]
            agent_name    = f"{folder_name} Agent"
            system_prompt = (
                f"You are the {agent_name}, a specialist in the {folder_name} knowledge domain.\n"
                f"Domain description: {description}\n"
                f"You answer questions strictly based on the provided document context.\n"
                f"Be concise, accurate, and cite which document your answer came from.\n"
                f"If the answer is not in the provided context, say so clearly — do not guess.\n"
                f"Format your answer in clean markdown."
            )
            entry = {
                "folder_name":  folder_name,
                "safe_name":    safe,
                "agent_name":   agent_name,
                "description":  description,
                "keywords":     keywords,
                "file_count":   n_files,
                "top_n":        existing.get("top_n", 4),
                "max_chars":    existing.get("max_chars", 6000),
                "system_prompt": system_prompt,
            }
        else:
            print(f"  ℹ Using placeholder description (re-run without --no-llm to generate)")
            agent_name    = f"{folder_name} Agent"
            description   = existing.get("description") or f"Knowledge domain: {folder_name}"
            keywords      = existing.get("keywords") or [folder_name.lower(), safe.replace("_", " ")]
            system_prompt = existing.get("system_prompt") or (
                f"You are the {agent_name}, a specialist in the {folder_name} knowledge domain.\n"
                f"Domain description: {description}\n"
                f"You answer questions strictly based on the provided document context.\n"
                f"Be concise, accurate, and cite which document your answer came from.\n"
                f"If the answer is not in the provided context, say so clearly — do not guess.\n"
                f"Format your answer in clean markdown."
            )
            entry = {
                "folder_name":  folder_name,
                "safe_name":    safe,
                "agent_name":   agent_name,
                "description":  description,
                "keywords":     keywords,
                "file_count":   n_files,
                "top_n":        existing.get("top_n", 4),
                "max_chars":    existing.get("max_chars", 6000),
                "system_prompt": system_prompt,
            }

        domain_meta[folder_name] = entry
        domains_list.append(entry)

        # Create README stub for folders that don't have one yet
        folder_path = kb_root / folder_name
        if not _find_readme(folder_path):
            stub = generate_readme_stub(folder_name, folder_path, entry["description"])
            print(f"  ✓ README stub created: {stub.name}")

        print()

    # Remove stale entries from domain_meta (deleted folders)
    for key in list(domain_meta.keys()):
        if key not in folders:
            del domain_meta[key]
            print(f"  🗑  Removed stale meta: {key}")

    # ── Step 6: write domain_meta.json ────────────────────────────────────────
    meta_path.write_text(json.dumps(domain_meta, indent=2), encoding="utf-8")
    print(f"✓ domain_meta.json written ({len(domain_meta)} domains)\n")

    # ── Step 7: orchestrator reads domain_meta.json — nothing more to generate ─
    print("  ✓ Orchestrator ready (data-driven from domain_meta.json)\n")

    # ── Step 8: generate requirements.txt ────────────────────────────────────
    req_path = SCRIPT_DIR / "requirements.txt"
    generate_requirements(req_path)
    print(f"✓ requirements.txt written\n")

    # ── Step 10: generate README.md ───────────────────────────────────────────
    readme_path = SCRIPT_DIR / "README.md"
    generate_readme(domains_list, kb_root, readme_path)
    print(f"✓ README.md written\n")

    # ── Step 11: generate SKILL.md ────────────────────────────────────────────
    print("Generating SKILL.md...")
    generate_skill_md(domains_list, agents_dir, kb_root)
    print()

    # ── Done ──────────────────────────────────────────────────────────────────
    print(f"{'='*60}")
    print(f"  Generation complete!")
    print(f"  {len(domains_list)} domain(s): {', '.join(d['folder_name'] for d in domains_list)}")
    print(f"\n  Test it:")
    print(f'    python3 agents/agent_knowledgebase.py "your question"')
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
