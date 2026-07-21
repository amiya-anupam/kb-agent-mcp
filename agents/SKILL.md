---
name: knowledgebase-agent
description: >
  Multi-domain KnowledgeBase agent. Routes questions to the correct
  specialist sub-agent automatically based on your knowledge folders.
  Use when asking about any content in your KnowledgeBase.

  Current domains (3):
  - **ACE Docs**: Knowledge domain: ACE Docs
  - **BizOps**: Knowledge domain: BizOps
  - **CP4I Docs**: Knowledge domain: CP4I Docs

  Trigger phrases: ask the agent, KnowledgeBase Agent, query knowledge base,
  ace docs, ace docs, bizops, bizops, cp4i docs, cp4i docs, what does my KnowledgeBase say, /kb, /agent

execute: |
  python3 /Users/amiyaanupam/Desktop/KnowledgeBase/agents/agent_knowledgebase.py "${QUESTION}"
---

# KnowledgeBase Agent Skill

## How Bob uses this skill

When you ask Bob a question that triggers this skill, Bob runs:
```
python3 /Users/amiyaanupam/Desktop/KnowledgeBase/agents/agent_knowledgebase.py "<your question>"
```
The Python script handles **all the AI work locally** (routing, retrieval, answering)
using your local LLM (Ollama / OpenAI / etc.). Bob reads the output and relays it back.

**Bob's Claude is used for:** understanding your request and deciding to invoke this skill.
**Your local LLM is used for:** intent classification, semantic routing, document Q&A.
**No document content is ever sent to Claude.**

## Current Domains
- **ACE Docs**: Knowledge domain: ACE Docs
- **BizOps**: Knowledge domain: BizOps
- **CP4I Docs**: Knowledge domain: CP4I Docs

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
                   → runs: python3 agent_knowledgebase.py "<question>"
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
Knowledge base root: `/Users/amiyaanupam/Desktop/KnowledgeBase`
Domains discovered: ACE Docs, BizOps, CP4I Docs

To add a new domain: create a folder with documents in `/Users/amiyaanupam/Desktop/KnowledgeBase`, then run:
```
python3 /Users/amiyaanupam/Desktop/KnowledgeBase/generate.py
```

## Technical Details
- Embedding: configurable via `KB_EMBED_MODEL` (Ollama / OpenAI / offline fallback)
- LLM: configurable via `KB_MODEL` and `KB_LLM_PROVIDER`
- Conversation memory: persists across sessions (auto-resets after 2h inactivity)
- Invocation: `python3 /Users/amiyaanupam/Desktop/KnowledgeBase/agents/agent_knowledgebase.py "<question>"`
