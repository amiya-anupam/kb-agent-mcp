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

  Current domains (4):
  - **ACE Docs**: Folder containing App Connect ACE documentation, presentations, guides, and migration resources.
  - **BizOps**: Folder containing IBM App Connect Enterprise (ACE) purchasing options, renewal materials, and customer tracking documents.
  - **CP4I Docs**: Folder containing Cloud Pak for Integration documentation, presentations, and sales materials.
  - **Test Domain**: A folder containing files related to Test Domain, including FAQs and integration testing content.

  Trigger phrases: ask the agent, KnowledgeBase Agent, query knowledge base,
  App Connect, ACE, migration, ACE, purchasing options, renewal, CP4I, Cloud Pak for Integration, presentation, Test Domain, faq.txt, getting_started.md, what does my KnowledgeBase say, /kb, /agent

execute: |
  python3 /Users/amiyaanupam/Desktop/KnowledgeBase/agents/agent_knowledgebase.py "${QUESTION}"
---

# KnowledgeBase Agent Skill

## How Bob uses this skill

When you ask Bob a question that triggers this skill, Bob runs:
```
python3 /Users/amiyaanupam/Desktop/KnowledgeBase/agents/agent_knowledgebase.py "<your question>"
```

**With a local LLM (Ollama) or API key:**
Bob's Claude triggers the skill. The Python script handles routing, retrieval, and answering
using your local LLM. Document content stays local — it is never sent to Claude.

**Without a local LLM — Passthrough mode (auto-detected):**
The script retrieves the relevant document context locally (offline embeddings), then emits a
`<<<KB_PASSTHROUGH>>>` block to stdout. Bob's Claude reads that block and answers the question
directly. In this mode, the retrieved document content is passed to Claude to generate the answer.

## Current Domains
- **ACE Docs**: Folder containing App Connect ACE documentation, presentations, guides, and migration resources.
- **BizOps**: Folder containing IBM App Connect Enterprise (ACE) purchasing options, renewal materials, and customer tracking documents.
- **CP4I Docs**: Folder containing Cloud Pak for Integration documentation, presentations, and sales materials.
- **Test Domain**: A folder containing files related to Test Domain, including FAQs and integration testing content.

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

## Setup
Knowledge base root: `/Users/amiyaanupam/Desktop/KnowledgeBase`
Domains discovered: ACE Docs, BizOps, CP4I Docs, Test Domain

To add a new domain: add a folder with documents to `/Users/amiyaanupam/Desktop/KnowledgeBase`, then run:
```
python3 /Users/amiyaanupam/Desktop/KnowledgeBase/generate.py
```

## Technical Details
- Embedding: configurable via `KB_EMBED_MODEL` (Ollama / OpenAI / offline fallback)
- LLM: configurable via `KB_MODEL` and `KB_LLM_PROVIDER` (`passthrough` = Bob answers)
- Passthrough fallback: auto-enabled when no LLM reachable; disable with `KB_PASSTHROUGH_FALLBACK=false`
- Conversation memory: persists across sessions (auto-resets after 2h inactivity)
- Invocation: `python3 /Users/amiyaanupam/Desktop/KnowledgeBase/agents/agent_knowledgebase.py "<question>"`
