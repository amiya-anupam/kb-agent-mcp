---
name: knowledgebase-agent
description: >
  Multi-domain KnowledgeBase agent. Routes questions to the correct
  specialist sub-agent automatically based on your knowledge folders.
  Use when asking about any content in your KnowledgeBase.
  Works without a local LLM: when no Ollama/API is configured the script
  emits a <<<KB_PASSTHROUGH>>> block and Bob answers using the retrieved
  context directly. After running the script, if the output contains
  <<<KB_PASSTHROUGH>>> blocks, read the AGENT, QUESTION, SYSTEM_PROMPT
  and CONTEXT fields from each block and answer the QUESTION using that
  CONTEXT, following the SYSTEM_PROMPT instructions. Do not show the raw
  block to the user — just answer naturally.

  Trigger phrases: ask the agent, KnowledgeBase Agent, query knowledge base,
  what does my KnowledgeBase say, /kb, /agent

  NOTE: Run `python3 generate.py` after cloning to discover your folders
  and regenerate this skill with your own domains and paths.

execute: |
  python3 ${KB_ROOT}/agents/agent_knowledgebase.py "${QUESTION}"
---

# KnowledgeBase Agent Skill

> **Note:** This is the template version of the skill. Run `python3 generate.py`
> after cloning to generate a personalised version with your own domain names,
> keywords, and the correct absolute path to your KB root.

## How Bob uses this skill

When you ask Bob a question that triggers this skill, Bob runs:
```
python3 /path/to/your/KnowledgeBase/agents/agent_knowledgebase.py "<your question>"
```

**With a local LLM (Ollama) or API key:**
Bob's Claude triggers the skill. The Python script handles routing, retrieval, and answering
using your local LLM. Document content stays local — it is never sent to Claude.

**Without a local LLM — Passthrough mode (auto-detected):**
The script retrieves the relevant document context locally (offline embeddings), then emits a
`<<<KB_PASSTHROUGH>>>` block to stdout. Bob's Claude reads that block and answers the question
directly. In this mode, the retrieved document content is passed to Claude to generate the answer.

## Setup

1. Clone the repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy and configure your environment:
   ```bash
   cp .env.example .env
   # Set KB_ROOT (absolute path to this repo), KB_MODEL, KB_LLM_PROVIDER, etc.
   ```
3. Add your documents into top-level folders, then run the generator:
   ```bash
   python3 generate.py
   ```
   This discovers your folders, builds vector indexes, and regenerates this skill
   with your domain names, keywords, and the correct `execute:` path.

## Usage

Just ask naturally — Bob detects the intent and runs the agent:
- "What does my KnowledgeBase say about X?"
- "Ask the KnowledgeBase agent about Y"

## Commands
- `/kb <question>` — query the knowledge base
- `/agent <question>` — same as /kb
- `/kb --clear` — clear conversation memory
- `/kb --memory` — show conversation history summary

## How the pipeline works

**With a local LLM (Ollama) or API key:**
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

**Without a local LLM — Passthrough mode (auto-detected):**
```
You → Bob (Claude) → detects skill trigger
                   → runs: python3 agent_knowledgebase.py "<question>"
                             ↓
                        keyword_route() / classify_intent() ← routing only
                             ↓
                        search() ← embeddings (sentence-transformers, offline)
                             ↓
                        emit <<<KB_PASSTHROUGH>>> block to stdout
                             ↓
                   → Bob (Claude) reads the context block
                             ↓
                   → Bob answers the question directly
```

Passthrough mode activates automatically when Ollama is not running and no
`KB_API_KEY` is set. Force it explicitly with `KB_LLM_PROVIDER=passthrough`.
Disable auto-detection with `KB_PASSTHROUGH_FALLBACK=false`.

## Technical Details
- Embedding: configurable via `KB_EMBED_MODEL` (Ollama / OpenAI / offline fallback)
- LLM: configurable via `KB_MODEL` and `KB_LLM_PROVIDER` (`passthrough` = Bob answers)
- Passthrough fallback: auto-enabled when no LLM reachable; disable with `KB_PASSTHROUGH_FALLBACK=false`
- Conversation memory: persists across sessions (auto-resets after 2h inactivity)
- Invocation: `python3 /path/to/KnowledgeBase/agents/agent_knowledgebase.py "<question>"`
