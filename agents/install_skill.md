---
name: knowledgebase-install
description: >
  Install the KnowledgeBase Agent skill from a git repo URL. Handles the
  complete end-to-end setup: clone, pip install, .env creation, and
  running generate.py to build indexes and install the Bob skill.

  Use this skill when a user says any of:
  - "install the KnowledgeBase skill"
  - "set up the KB agent"
  - "here's the repo link, install the skill"
  - "clone and set up [repo URL]"
  - "help me install the knowledgebase agent"
  - "/kb-install"

  IMPORTANT: This skill uses the execute block ONLY for the final automated
  run (kb-agent-setup --yes). All earlier steps — cloning the repo,
  choosing where to put it — are done interactively by Bob asking the user.

instructions: |
  Follow these steps exactly. Do not skip any step. Ask the user before
  proceeding at each decision point marked [ASK].

  STEP 1 — Get the repo URL
    If the user already provided a URL in their message, use it.
    Otherwise [ASK]: "What is the git repo URL?"

  STEP 2 — Choose install location
    [ASK]: "Where would you like to clone the repo?
    Press Enter to use your home directory (~), or type a full path."
    Default: ~/KnowledgeBase
    Store this as INSTALL_DIR.

  STEP 3 — Clone the repo
    Tell the user to run:
      git clone <REPO_URL> <INSTALL_DIR>
    Then ask them to confirm it completed successfully before continuing.

  STEP 4 — Run the automated setup
    Once cloning is confirmed, install the package and run setup:
      pip install -e <INSTALL_DIR>
      kb-agent-setup
    Or without pip install (works from the cloned directory):
      python3 <INSTALL_DIR>/scripts/setup.py
    This single command handles everything:
      • checks Python version and build tools
      • creates and configures .env (KB_ROOT is auto-set)
      • prompts for LLM provider (Ollama / OpenAI / Anthropic / passthrough)
      • runs kb-agent-generate to build vector indexes
      • installs the Bob skill to ~/.bob/skills/knowledgebase-agent/

  STEP 5 — Add knowledge documents
    After setup.py completes, ask:
    "Do you have documents you'd like to add to the knowledge base?
    If yes, copy them into folders inside <INSTALL_DIR> and I'll re-run
    the generator for you."
    If they say yes, ask for the folder name, then tell them to run:
      kb-agent-generate
    (or `python3 <INSTALL_DIR>/scripts/generate.py` if not pip-installed)

  STEP 6 — Verify and finish
    Ask the user to type: /kb hello
    If it responds, setup is complete. Confirm the skill is working.
    If it doesn't trigger, the Bob skill may not have been picked up yet —
    tell the user to restart Bob or open a new chat window.

  NOTES:
  - If the user is on Windows, replace `python3` with `python` in all commands.
  - If git is not installed, tell the user to download it from https://git-scm.com
  - If pip fails, suggest: python3 -m pip install --upgrade pip first.
  - The setup works WITHOUT a local LLM — passthrough mode auto-detects and
    uses Bob's Claude to answer questions using retrieved context.
---

# KnowledgeBase Agent — Installation Skill

This skill guides you through complete end-to-end setup of the KnowledgeBase Agent.

## What it does

Takes you from zero to a working KB agent in one conversation:

```
You: "Here's the repo link, install the skill"
Bob: asks where to clone → tells you to run scripts/setup.py → done
```

## What kb-agent-setup does automatically

When you run `kb-agent-setup` (or `python3 scripts/setup.py`), it:

1. Checks Python version (3.10+ required) and build tools
2. Recommends a virtual environment if not already in one
3. Creates `.env` with `KB_ROOT` pre-filled to your install location
4. Prompts for your LLM choice (Ollama / OpenAI / Anthropic / passthrough)
5. Runs `kb-agent-generate` — discovers folders, builds vector indexes, installs Bob skill
6. Offers an interactive keyword editor for domains without an LLM

After that, the skill is live at `~/.bob/skills/knowledgebase-agent/SKILL.md`.

## Non-interactive mode (for automation)

```bash
kb-agent-setup --yes
# or without pip install:
python3 scripts/setup.py --yes
```

Skips all prompts, uses safe defaults (passthrough mode), and completes silently.
Useful if you want Bob to drive the entire setup without any human input.

## Adding documents later

Drop files into any top-level folder, then:

```bash
kb-agent-generate
```

or just ask Bob: *"Re-run the KnowledgeBase generator"*
