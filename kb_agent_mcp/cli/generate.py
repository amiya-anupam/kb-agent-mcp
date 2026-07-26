"""
kb_agent_mcp/cli/generate.py — Index builder + domain_config.yaml generator
-----------------------------------------------------------------------------
Run this after adding new knowledge folders, or to rebuild indexes from scratch.

What it does:
  1. Discovers top-level knowledge folders under KB_ROOT
  2. Builds (or updates) ChromaDB vector indexes for each folder
  3. For folders without domain_config.yaml: generates one via LLM (Accept/Skip)
  4. Writes domain_config.yaml into the accepted folder
  5. Copies knowledgebase-agent SKILL.md to ~/.bob/skills/ (if Bob is installed)

Usage:
  kb-agent-generate                # incremental (skip unchanged)
  kb-agent-generate --force        # rebuild everything
  kb-agent-generate --no-llm       # index only (skip YAML generation)
  kb-agent-generate --domain Foo   # only process folder named Foo
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx

# ── Config is loaded lazily inside each function so KB_ROOT from .env is used ──

INCLUDE_EXTS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt",
    ".csv", ".boxnote", ".ppt", ".doc",
}
SKIP_PATTERNS = {"readme", ".ds_store", "__pycache__", "domain_config"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

def ok(msg: str):   print(_c("32", f"  ✓ {msg}"))
def info(msg: str): print(_c("36", f"  → {msg}"))
def warn(msg: str): print(_c("33", f"  ⚠ {msg}"))
def err(msg: str):  print(_c("31", f"  ✗ {msg}"))
def hdr(msg: str):  print(_c("1",  f"\n{msg}"))


def _should_skip(path: Path) -> bool:
    return any(p in path.name.lower() for p in SKIP_PATTERNS)


def _discover_folders(kb_root: Path) -> list[str]:
    from kb_agent_mcp.config import cfg
    found = []
    for entry in sorted(kb_root.iterdir()):
        if not entry.is_dir() or cfg.is_ignored(entry.name):
            continue
        has_files = any(
            f.suffix.lower() in INCLUDE_EXTS
            for f in entry.rglob("*")
            if f.is_file() and not _should_skip(f)
        )
        if has_files:
            found.append(entry.name)
    return found


def _count_files(folder: Path) -> int:
    return sum(
        1 for f in folder.rglob("*")
        if f.is_file() and f.suffix.lower() in INCLUDE_EXTS and not _should_skip(f)
    )


# ── Folder manifest builder (for LLM YAML generation) ─────────────────────────

def _build_folder_manifest(folder: Path, max_snippet: int = 500) -> str:
    """
    Build a structured text description of a knowledge folder for the LLM.
    Includes: tree (truncated), file counts per subfolder, and text snippets
    from the 5 largest files.
    """
    from kb_agent_mcp.file_parser import snippet as _snippet

    lines = [f"Folder: {folder.name}"]

    # Tree
    all_files = sorted(
        (f for f in folder.rglob("*") if f.is_file() and not _should_skip(f)),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    lines.append(f"Total files: {len(all_files)}")
    lines.append("File list (largest first, max 30):")
    for f in all_files[:30]:
        rel = f.relative_to(folder)
        sz  = f.stat().st_size
        lines.append(f"  {rel}  ({sz // 1024} KB)")

    # Text snippets from top 5 largest files
    lines.append("\nContent samples (first 500 chars of 5 largest files):")
    for f in all_files[:5]:
        lines.append(f"\n--- {f.relative_to(folder)} ---")
        try:
            text = _snippet(f, max_chars=max_snippet)
            lines.append(text[:max_snippet])
        except Exception as e:
            lines.append(f"[snippet error: {e}]")

    return "\n".join(lines)


# ── LLM YAML generation ────────────────────────────────────────────────────────

def _llm_available() -> bool:
    from kb_agent_mcp.config import cfg
    try:
        if cfg.KB_LLM_PROVIDER == "ollama":
            r = httpx.get(f"{cfg.KB_LLM_BASE_URL}/api/tags", timeout=5.0)
        else:
            r = httpx.get(cfg.KB_LLM_BASE_URL.rstrip("/"), timeout=5.0)
        return r.status_code < 500
    except Exception:
        return False


def _call_llm_sync(prompt: str) -> str:
    from kb_agent_mcp.config import cfg
    messages = [{"role": "user", "content": prompt}]

    provider = cfg.KB_LLM_PROVIDER.lower()

    if provider == "anthropic":
        r = httpx.post(
            f"{cfg.KB_LLM_BASE_URL}/v1/messages",
            headers={"x-api-key": cfg.KB_API_KEY, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": cfg.KB_MODEL, "max_tokens": 1024, "temperature": 0.1,
                  "messages": messages},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()

    if provider in ("openai", "custom"):
        base = cfg.KB_LLM_BASE_URL.rstrip("/")
        if "11434" in base and not base.endswith("/v1"):
            base += "/v1"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.KB_API_KEY:
            headers["Authorization"] = f"Bearer {cfg.KB_API_KEY}"
        r = httpx.post(
            f"{base}/chat/completions",
            headers=headers,
            json={"model": cfg.KB_MODEL, "messages": messages, "temperature": 0.1},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    # Ollama
    r = httpx.post(
        f"{cfg.KB_LLM_BASE_URL}/api/chat",
        json={"model": cfg.KB_MODEL, "messages": messages, "stream": False,
              "options": {"temperature": 0.1, "num_ctx": 8192}, "think": False},
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


_YAML_PROMPT_TEMPLATE = """
You are generating a domain_config.yaml for a knowledge base folder.

Here is a structured manifest of the folder contents:
{manifest}

Generate a complete domain_config.yaml for this folder.
The folder is named: {folder_name}

Required format (YAML, no extra text before or after):

folder_name: {folder_name}
agent_name: {folder_name} Agent
description: <one sentence describing what this knowledge domain contains>
keywords:
  - <keyword1>
  - <keyword2>
  - <keyword3>
  - <up to 12 relevant keywords users would type to search this domain>
top_n: 5
max_chars: 8000
system_prompt: |
  You are the {folder_name} Agent, a specialist in this knowledge domain.
  <2-3 sentences describing the domain and any critical answering rules>
  You answer questions strictly based on the provided document context.
  Be concise, accurate, and cite which document your answer came from.
  If the answer is not in the provided context, say so clearly.
  Format your answer in clean markdown.
retrieval_rules:
  pin_files:
    - <glob pattern for authoritative files, e.g. "*Revenue*.xlsx", or omit if none>
  boost_keywords:
    - <filename keyword to boost to top of results, or omit if none>
  question_classifier:
    data_patterns:
      - <regex for data/numeric questions that need raw file content, e.g. "\\\\brevenue\\\\b">
    complex_patterns: []

Return ONLY the YAML. No explanation, no markdown fences.
""".strip()


def _generate_yaml_for_folder(folder: Path) -> str | None:
    """Generate domain_config.yaml content via LLM. Returns YAML string or None."""
    manifest = _build_folder_manifest(folder)
    prompt   = _YAML_PROMPT_TEMPLATE.format(
        manifest=manifest,
        folder_name=folder.name,
    )
    try:
        return _call_llm_sync(prompt)
    except Exception as e:
        warn(f"LLM call failed for {folder.name}: {e}")
        return None


def _minimal_yaml(folder_name: str) -> str:
    """Generate a minimal domain_config.yaml without LLM."""
    return textwrap.dedent(f"""\
        folder_name: {folder_name}
        agent_name: {folder_name} Agent
        description: Knowledge domain: {folder_name}
        keywords:
          - {folder_name.lower()}
        top_n: 4
        max_chars: 8000
        system_prompt: |
          You are the {folder_name} Agent, a specialist in the {folder_name} knowledge domain.
          You answer questions strictly based on the provided document context.
          Be concise, accurate, and cite which document your answer came from.
          If the answer is not in the provided context, say so clearly.
          Format your answer in clean markdown.
        retrieval_rules:
          pin_files: []
          boost_keywords: []
          question_classifier:
            data_patterns: []
            complex_patterns: []
    """)


# ── Rich / plain YAML preview ──────────────────────────────────────────────────

def _print_yaml_preview(folder_name: str, yaml_text: str) -> None:
    try:
        from rich.syntax import Syntax
        from rich.console import Console
        console = Console()
        console.print(f"\n[bold cyan]domain_config.yaml for [bold white]{folder_name}:[/bold white][/bold cyan]")
        console.print(Syntax(yaml_text, "yaml", theme="monokai", line_numbers=False))
    except ImportError:
        print(f"\n--- domain_config.yaml for {folder_name} ---")
        print(yaml_text)
        print("---")


def _prompt_accept(folder_name: str) -> bool:
    """Prompt Accept or Skip. Returns True for Accept."""
    while True:
        try:
            answer = input(f"\n  [A]ccept / [S]kip for '{folder_name}': ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if answer in ("A", "ACCEPT", ""):
            return True
        if answer in ("S", "SKIP"):
            return False
        print("  Please type A or S.")


# ── Bob SKILL.md installer ─────────────────────────────────────────────────────

_SKILL_TEMPLATE = """\
---
name: knowledgebase-agent
description: >
  Multi-domain KnowledgeBase agent (MCP). Routes questions to the correct
  specialist sub-agent automatically based on your knowledge folders.
  Use when asking about any content in your KnowledgeBase.
  Current domains ({domain_count}): {domain_list}
  Trigger phrases: ask the agent, KnowledgeBase Agent, query knowledge base,
  {trigger_keywords}
---

# KnowledgeBase Agent (MCP)

This skill connects to the `kb-agent-mcp` MCP server.

## Usage

Use the `ask` MCP tool:
  - `ask(question)` — query all relevant domains
  - `ask(question, format="table")` — request a specific output format
  - `ask(question, session_id="my-session")` — multi-turn conversation

Use `list_domains()` to see available knowledge domains.
Use `reindex()` to rebuild indexes after adding new documents.
Use `clear_memory(session_id)` / `show_memory(session_id)` for session control.
"""


def _install_bob_skill(kb_root: Path, domain_names: list[str]) -> None:
    skill_dir = Path.home() / ".bob" / "skills" / "knowledgebase-agent"
    if not skill_dir.parent.parent.exists():
        return  # Bob not installed

    domain_list    = ", ".join(f"**{n}**" for n in domain_names[:6])
    trigger_kws    = ", ".join(
        kw for name in domain_names[:4] for kw in name.lower().split()
    )
    skill_content = _SKILL_TEMPLATE.format(
        domain_count=len(domain_names),
        domain_list=domain_list or "(none yet)",
        trigger_keywords=trigger_kws or "knowledge base",
    )
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")
    ok(f"Bob skill installed: {skill_dir / 'SKILL.md'}")


# ── Main generate logic ────────────────────────────────────────────────────────

async def _run_generate(
    force: bool = False,
    no_llm: bool = False,
    domain_filter: str | None = None,
) -> int:
    from kb_agent_mcp.config import cfg
    from kb_agent_mcp.vector_store import build_collection as _build

    kb_root = cfg.kb_root_path
    errors  = cfg.validate()
    if errors:
        for e in errors:
            err(e)
        return 1

    hdr(f"kb-agent-generate — KB_ROOT: {kb_root}")

    folders = _discover_folders(kb_root)
    if not folders:
        warn("No knowledge folders found. Add document subfolders and re-run.")
        return 0

    if domain_filter:
        folders = [f for f in folders if f.lower() == domain_filter.lower()]
        if not folders:
            err(f"Domain '{domain_filter}' not found under {kb_root}")
            return 1

    llm_ok  = not no_llm and _llm_available()
    if not no_llm and not llm_ok:
        warn("LLM not reachable — domain_config.yaml will use minimal defaults.")

    accepted_domains: list[str] = []

    for folder_name in folders:
        folder     = kb_root / folder_name
        yaml_path  = folder / "domain_config.yaml"
        file_count = _count_files(folder)

        print(f"\n{'─'*60}")
        print(f"  📁  {folder_name}/  ({file_count} files)")

        # ── 1. Build/update ChromaDB vector index ─────────────────────────────
        try:
            count = await _build(folder_name)
            ok(f"ChromaDB index: {count} files embedded")
        except Exception as e:
            err(f"Index build failed for {folder_name}: {e}")
            continue

        # ── 2. Generate domain_config.yaml (if missing or --force) ────────────
        if yaml_path.exists() and not force:
            ok(f"domain_config.yaml already exists — skipping (use --force to regenerate)")
            accepted_domains.append(folder_name)
            continue

        if llm_ok:
            info("Generating domain_config.yaml via LLM…")
            yaml_text = _generate_yaml_for_folder(folder)
            if not yaml_text:
                yaml_text = _minimal_yaml(folder_name)
        else:
            yaml_text = _minimal_yaml(folder_name)

        _print_yaml_preview(folder_name, yaml_text)

        if _prompt_accept(folder_name):
            yaml_path.write_text(yaml_text, encoding="utf-8")
            ok(f"domain_config.yaml written")
            accepted_domains.append(folder_name)
        else:
            info("Skipped — edit domain_config.yaml manually to add this domain")

    # ── Install Bob skill ─────────────────────────────────────────────────────
    if accepted_domains:
        _install_bob_skill(kb_root, accepted_domains)

    hdr("✅ Done")
    print(f"  Domains indexed: {', '.join(accepted_domains) or '(none)'}")
    print()
    print("  Start the MCP server:  kb-agent-serve")
    print("  Watch for changes:     kb-agent-watch")
    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kb-agent-generate",
        description="Build ChromaDB indexes and generate domain_config.yaml for each knowledge folder.",
    )
    parser.add_argument("--force",  action="store_true",
                        help="Regenerate everything, even if domain_config.yaml already exists")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM-based YAML generation (index only)")
    parser.add_argument("--domain", type=str, default=None,
                        help="Only process one domain folder (exact name)")
    args = parser.parse_args()

    rc = asyncio.run(_run_generate(
        force=args.force,
        no_llm=args.no_llm,
        domain_filter=args.domain,
    ))
    sys.exit(rc)


if __name__ == "__main__":
    main()
