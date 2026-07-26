"""
kb_agent_mcp/cli/setup.py — Interactive setup wizard
-----------------------------------------------------
Guides a new user through:
  1. Python version check
  2. KB_ROOT folder selection
  3. LLM / passthrough configuration
  4. .env creation
  5. Running kb-agent-generate to build indexes

Usage:
  kb-agent-setup            # interactive (recommended)
  kb-agent-setup --yes      # non-interactive (passthrough defaults)
  kb-agent-setup --kb-root /path/to/docs
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path


# ── ANSI colour helpers ────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

def ok(msg: str):   print(_c("32", f"  ✓ {msg}"))
def info(msg: str): print(_c("36", f"  → {msg}"))
def warn(msg: str): print(_c("33", f"  ⚠ {msg}"))
def err(msg: str):  print(_c("31", f"  ✗ {msg}"))
def hdr(msg: str):  print(_c("1",  f"\n{msg}"))


def _prompt(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val if val else default


# ── Step 1: Python check ───────────────────────────────────────────────────────

def check_python() -> None:
    hdr("① Checking Python version")
    v = sys.version_info
    if v < (3, 10):
        err(f"Python 3.10+ required — you have {v.major}.{v.minor}")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


# ── Step 2: KB_ROOT folder ────────────────────────────────────────────────────

def choose_kb_root(cli_path: Path | None, yes: bool) -> Path:
    if cli_path is not None:
        ok(f"KB_ROOT: {cli_path}")
        return cli_path

    if yes:
        root = Path.cwd()
        ok(f"KB_ROOT: {root}  (current directory — default)")
        return root

    hdr("② Knowledge documents folder")
    print()
    print("  Where are (or will be) your knowledge documents stored?")
    print()
    print(f"  1) Use the current directory  ({Path.cwd()})")
    print("  2) Link an existing folder on this machine")
    print("  3) Create a new folder somewhere")
    print()
    choice = _prompt("Choice", "1")

    if choice == "2":
        while True:
            raw  = _prompt("Full path to your existing folder")
            path = Path(raw).expanduser().resolve()
            if path.is_dir():
                ok(f"KB_ROOT: {path}")
                return path
            err(f"'{path}' does not exist or is not a directory.")

    if choice == "3":
        raw  = _prompt("Full path for the new folder", str(Path.home() / "KnowledgeBase"))
        path = Path(raw).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as exc:
            err(f"Could not create '{path}': {exc}")
            sys.exit(1)
        ok(f"Created and set KB_ROOT: {path}")
        return path

    root = Path.cwd()
    ok(f"KB_ROOT: {root}")
    return root


# ── Step 3: LLM ───────────────────────────────────────────────────────────────

def choose_llm(yes: bool) -> dict[str, str]:
    if yes:
        info("LLM: passthrough mode (recommended — no local LLM required)")
        return {"KB_LLM_PROVIDER": "passthrough"}

    hdr("③ LLM (language model) setup")
    print()
    print("  1) Passthrough  (recommended — your AI tool answers using retrieved context)")
    print("  2) Ollama        (free, local — install from https://ollama.com)")
    print("  3) OpenAI        (API key required)")
    print("  4) Anthropic     (API key required)")
    print("  5) Custom / LM Studio / Jan  (any OpenAI-compatible server)")
    print()
    choice = _prompt("Choice", "1")

    if choice == "2":
        model = _prompt("Ollama model", "qwen3:14b")
        info(f"Make sure Ollama is running: `ollama serve`")
        info(f"Pull the model first: `ollama pull {model}`")
        return {"KB_LLM_PROVIDER": "ollama", "KB_MODEL": model, "KB_EMBED_MODEL": "nomic-embed-text"}

    if choice == "3":
        key   = _prompt("OpenAI API key (sk-…)")
        model = _prompt("OpenAI model", "gpt-4o-mini")
        return {
            "KB_LLM_PROVIDER": "openai",
            "KB_LLM_BASE_URL": "https://api.openai.com/v1",
            "KB_MODEL": model,
            "KB_API_KEY": key,
            "KB_EMBED_MODEL": "text-embedding-3-small",
        }

    if choice == "4":
        key   = _prompt("Anthropic API key")
        model = _prompt("Anthropic model", "claude-3-5-haiku-20241022")
        return {
            "KB_LLM_PROVIDER": "anthropic",
            "KB_LLM_BASE_URL": "https://api.anthropic.com",
            "KB_MODEL": model,
            "KB_API_KEY": key,
        }

    if choice == "5":
        url   = _prompt("Base URL", "http://localhost:1234/v1")
        model = _prompt("Model name")
        return {"KB_LLM_PROVIDER": "custom", "KB_LLM_BASE_URL": url, "KB_MODEL": model}

    # Default: passthrough
    info("Passthrough mode selected.")
    return {"KB_LLM_PROVIDER": "passthrough"}


# ── Step 4: write .env ────────────────────────────────────────────────────────

def write_env(kb_root: Path, llm: dict[str, str], cwd: Path) -> None:
    hdr("④ Writing .env")
    env_path     = cwd / ".env"
    example_path = cwd / ".env.example"

    if env_path.exists():
        ok(".env already exists — keeping it (update manually if needed)")
        _patch_env_key(env_path, "KB_ROOT", str(kb_root))
        return

    # Build from example if present, otherwise minimal
    if example_path.exists():
        content = example_path.read_text(encoding="utf-8")
        content = content.replace("# KB_ROOT=/path/to/your/KnowledgeBase", f"KB_ROOT={kb_root}")
    else:
        content = f"KB_ROOT={kb_root}\n"

    env_path.write_text(content, encoding="utf-8")
    # Patch in LLM settings
    for k, v in llm.items():
        _patch_env_key(env_path, k, v)
    ok(f".env written  (KB_ROOT={kb_root}, provider={llm.get('KB_LLM_PROVIDER', '?')})")


def _patch_env_key(env_path: Path, key: str, value: str) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines = []
    for ln in lines:
        stripped = ln.lstrip("# ")
        if stripped.startswith(f"{key}=") or ln.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(ln)
    if not found:
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── Step 5: run kb-agent-generate ────────────────────────────────────────────

def run_generate(yes: bool) -> None:
    hdr("⑤ Running kb-agent-generate  (builds indexes)")
    flags = ["--no-llm"] if yes else []
    result = subprocess.run(
        [sys.executable, "-m", "kb_agent_mcp.cli.generate"] + flags,
    )
    if result.returncode != 0:
        err("kb-agent-generate failed — check the output above.")
        err("Re-run manually to see the full error:  kb-agent-generate")
        sys.exit(1)
    ok("kb-agent-generate completed")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kb-agent-setup",
        description="KnowledgeBase Agent MCP — one-command installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              kb-agent-setup                   # interactive
              kb-agent-setup --yes             # non-interactive (all defaults)
              kb-agent-setup --kb-root /data   # skip the folder prompt
        """),
    )
    parser.add_argument("--yes", action="store_true",
                        help="Non-interactive: accept all defaults (passthrough mode)")
    parser.add_argument("--kb-root", type=str, default=None,
                        help="Absolute path to use as KB_ROOT")
    args = parser.parse_args()

    cli_root = Path(args.kb_root).resolve() if args.kb_root else None
    cwd      = Path.cwd()

    print(_c("1;36", "\n╔══════════════════════════════════════════════╗"))
    print(_c("1;36",   "║   kb-agent-mcp — Setup                       ║"))
    print(_c("1;36",   "╚══════════════════════════════════════════════╝"))

    check_python()
    kb_root = choose_kb_root(cli_root, args.yes)
    llm_cfg = choose_llm(args.yes)
    write_env(kb_root, llm_cfg, cwd)
    run_generate(args.yes)

    hdr("✅  Setup complete!")
    print()
    print("  Start the MCP server:")
    print("    kb-agent-serve                    # stdio (for Claude Desktop / Bob)")
    print("    kb-agent-serve --transport http   # HTTP/SSE")
    print()
    print("  Re-index after adding documents:")
    print("    kb-agent-generate")
    print()
    print("  Watch for file changes automatically:")
    print("    kb-agent-watch")
    print()


if __name__ == "__main__":
    main()
