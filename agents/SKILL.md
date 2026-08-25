---
name: knowledgebase-agent
description: >
  Multi-domain KnowledgeBase agent. Routes questions to the correct
  specialist sub-agent automatically based on your knowledge folders.
  Use when asking about any content in your KnowledgeBase.

  Current domains (4):
  - **ACE Docs**: Folder containing App Connect ACE documentation, presentations, guides, and migration resources.
  - **BizOps**: Folder containing IBM App Connect Enterprise (ACE) purchasing options, renewal materials, and related tracking documents.
  - **CP4I Docs**: Folder containing Cloud Pak for Integration documentation, presentations, and sales materials.
  - **skills**: This folder contains information related to skills, including knowledge domain notes and additional content.

  Trigger phrases: ask the agent, KnowledgeBase Agent, query knowledge base,
  App Connect, ACE, migration, ACE, purchasing options, renewal, Cloud Pak for Integration, CP4I, presentation, skills, knowledge domain, notes, what does my KnowledgeBase say, /kb, /agent

execute: |
  python3 "${SKILL_DIR}/../agent_knowledgebase.py" "${QUESTION}"
---

# KnowledgeBase Agent Skill

## How Bob uses this skill

When you ask Bob a question that triggers this skill, Bob runs:
```
python3 <install-dir>/agents/agent_knowledgebase.py "<your question>"
```
The Python script handles **all the AI work locally** (routing, retrieval, answering)
using your local LLM (Ollama / OpenAI / etc.). Bob reads the output and relays it back.

**Bob's Claude is used for:** understanding your request and deciding to invoke this skill.
**Your local LLM is used for:** intent classification, semantic routing, document Q&A.
**No document content is ever sent to Claude.**

## Current Domains
- **ACE Docs**: Folder containing App Connect ACE documentation, presentations, guides, and migration resources.
- **BizOps**: Folder containing IBM App Connect Enterprise (ACE) purchasing options, renewal materials, and related tracking documents.
- **CP4I Docs**: Folder containing Cloud Pak for Integration documentation, presentations, and sales materials.
- **skills**: This folder contains information related to skills, including knowledge domain notes and additional content.

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
```
You → Bob (Claude) → detects skill trigger
                   → runs: python3 agents/agent_knowledgebase.py "<question>"
                             ↓
                        keyword_route()  ← fast, no LLM
                             ↓ (if ambiguous)
                        classify_intent() ← your local LLM
                             ↓
                        agent_base.ask() ← README-first RAG pipeline
                             ↓
                        call_llm() or passthrough block
                             ↓
                   → Bob reads stdout and returns answer to you
```

## Setup
To add a new domain: create a folder with documents in your KB root, then run:
```
python3 generate.py
```

## Technical Details
- Embedding: configurable via `KB_EMBED_MODEL` (Ollama / OpenAI / offline fallback)
- LLM: configurable via `KB_MODEL` and `KB_LLM_PROVIDER`
- Conversation memory: persists across sessions (auto-resets after 2h inactivity)
- Invocation: `python3 agents/agent_knowledgebase.py "<question>"`
