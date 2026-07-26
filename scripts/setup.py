#!/usr/bin/env python3
"""
scripts/setup.py — KnowledgeBase Agent: one-command installer
--------------------------------------------------------------
Run this once after cloning (or after adding new knowledge folders).

What it does:
  1. Checks Python version (3.10+)
  2. Installs Python dependencies from requirements.txt
  3. Asks where to store knowledge documents (link existing folder or create new)
  4. Asks whether to use a local LLM or rely on the calling AI tool (passthrough)
  5. Creates .env with KB_ROOT and LLM settings pre-filled
  6. Runs scripts/generate.py to build indexes and install the agent skill

Usage:
  python3 scripts/setup.py                    # interactive
  python3 scripts/setup.py --yes              # non-interactive (accept all defaults)
  python3 scripts/setup.py --kb-root /path    # skip the root folder prompt

After setup the skill is live at:
  ~/.bob/skills/knowledgebase-agent/SKILL.md
"""

import os
import sys
import shutil
import pathlib
import subprocess
import textwrap
import urllib.request
import urllib.error

# scripts/ lives one level below the repo root — resolve upward so all
# relative paths (.env, requirements.txt, agents/, etc.) stay correct.
SCRIPT_DIR = pathlib.Path(__file__).parent.parent.resolve()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _color(code: str, text: str) -> str:
    """ANSI colour if the terminal supports it."""
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

def ok(msg):  print(_color("32", f"  ✓ {msg}"))
def info(msg): print(_color("36", f"  → {msg}"))
def warn(msg): print(_color("33", f"  ⚠ {msg}"))
def err(msg):  print(_color("31", f"  ✗ {msg}"))
def hdr(msg):  print(_color("1",  f"\n{msg}"))


def ask(prompt: str, default: str = "") -> str:
    """Prompt with a default value shown in brackets."""
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val if val else default


def run(cmd: list[str], cwd: pathlib.Path = SCRIPT_DIR) -> int:
    """Run a subprocess, streaming output. Returns exit code."""
    result = subprocess.run(cmd, cwd=str(cwd))
    return result.returncode


# ── Step 1: Python version check ─────────────────────────────────────────────

def check_python():
    hdr("① Checking Python version")
    v = sys.version_info
    if v < (3, 10):
        err(f"Python 3.10+ is required. You have {v.major}.{v.minor}.")
        err("Download from https://python.org/downloads")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


# ── Build-tools pre-flight (for chromadb native bindings) ─────────────────────

def _preflight_build_tools() -> str:
    """Return a platform-specific fix hint for chromadb C++ build failures."""
    if sys.platform == "darwin":
        return "xcode-select --install"
    if sys.platform.startswith("linux"):
        return "sudo apt install build-essential python3-dev"
    return ""


def _print_build_hint(hint: str) -> None:
    if hint:
        warn("If chromadb install fails due to missing build tools, run:")
        warn(f"  {hint}")


# ── API-key preflight test ─────────────────────────────────────────────────────

def _test_api_key(provider: str, base_url: str, api_key: str, model: str) -> None:
    """Make a lightweight authenticated request to verify the key before .env is written.

    Prints "API key verified ✓" on success.
    Prints a warning on auth failure (HTTP 401/403).
    Prints a notice (not a hard failure) when the network is unreachable.
    Does not block setup if the test fails — a timeout is treated as a warning.
    """
    provider = provider.lower()
    try:
        if provider == "anthropic":
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
        else:
            # OpenAI-compatible: list models endpoint
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status < 300:
                ok("API key verified ✓")
                return
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            warn(f"API key test failed (HTTP {exc.code}). Double-check the key and try again.")
        else:
            warn(f"API key test returned HTTP {exc.code} — proceeding anyway.")
    except Exception:
        warn("API key test skipped (network unreachable or timeout) — proceeding.")


# ── Step 2: pip install ───────────────────────────────────────────────────────

def install_deps():
    hdr("② Installing Python dependencies")
    req = SCRIPT_DIR / "requirements.txt"
    if not req.exists():
        warn("requirements.txt not found — skipping pip install")
        return
    hint = _preflight_build_tools()
    _print_build_hint(hint)
    rc = run([sys.executable, "-m", "pip", "install", "-r", str(req), "-q"])
    if rc != 0:
        err("pip install failed. Check the output above.")
        if hint:
            err(f"If the error mentions missing build tools, run:  {hint}")
        sys.exit(1)
    ok("Dependencies installed")


# ── Step 3: choose KB root folder ────────────────────────────────────────────

def choose_kb_root(cli_kb_root: pathlib.Path | None, yes: bool) -> pathlib.Path:
    """Ask the user where their knowledge documents live (or should live).

    Three outcomes:
      a) --kb-root flag was passed  → use it directly, no prompt
      b) --yes flag                 → default to repo directory, no prompt
      c) interactive                → ask: link existing folder OR create new one
    """
    if cli_kb_root is not None:
        ok(f"KB root: {cli_kb_root}")
        return cli_kb_root

    if yes:
        ok(f"KB root: {SCRIPT_DIR}  (default)")
        return SCRIPT_DIR

    hdr("③ Knowledge documents folder")
    print()
    print("  Where are (or will be) your knowledge documents stored?")
    print()
    print("  1) Use this repo folder  (create subfolders here for each domain)")
    print(f"       {SCRIPT_DIR}/")
    print("  2) Link an existing folder on my machine")
    print("       (e.g. ~/Documents/MyProject — its subfolders become domains)")
    print("  3) Create a new folder somewhere")
    print()

    choice = ask("Choice", "1")

    if choice == "2":
        while True:
            raw = ask("Full path to your existing folder")
            path = pathlib.Path(raw).expanduser().resolve()
            if path.is_dir():
                ok(f"KB root set to: {path}")
                return path
            err(f"'{path}' does not exist or is not a directory. Try again.")

    elif choice == "3":
        raw = ask("Full path for the new folder", str(pathlib.Path.home() / "KnowledgeBase"))
        path = pathlib.Path(raw).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            err(f"Permission denied: cannot create '{path}'")
            err(f"Choose a path inside your home directory, e.g. ~/KnowledgeBase")
            sys.exit(1)
        except OSError as e:
            err(f"Could not create folder '{path}': {e}")
            sys.exit(1)
        ok(f"Created and set KB root to: {path}")
        return path

    else:
        ok(f"KB root: {SCRIPT_DIR}")
        return SCRIPT_DIR


# ── Step 4: choose LLM ────────────────────────────────────────────────────────

def choose_llm(yes: bool) -> dict:
    """Ask whether the user wants a local LLM or passthrough mode.

    Returns a dict of env-var key→value pairs to write into .env.
    """
    if yes:
        info("LLM: passthrough mode (AI tool answers using retrieved context)")
        return {"KB_LLM_PROVIDER": "passthrough"}

    hdr("④ LLM (language model) setup")
    print()
    print("  The agent needs a language model to answer questions.")
    print("  You have two options:")
    print()
    print("  1) Use your AI tool directly  (passthrough — recommended to start)")
    print("       No extra software needed. The agent retrieves relevant context")
    print("       from your documents locally, then your AI tool (Bob, Claude,")
    print("       ChatGPT, etc.) reads that context and answers the question.")
    print("       Your raw documents never leave your machine.")
    print()
    print("  2) Install a local LLM  (fully offline, no AI tool involved)")
    print("       The agent answers entirely on your machine.")
    print("       Options: Ollama (free, local), OpenAI API key, Anthropic API key.")
    print()

    top = ask("Choice", "1")

    if top == "1":
        info("Passthrough mode selected.")
        return {"KB_LLM_PROVIDER": "passthrough"}

    # Local LLM sub-menu
    print()
    print("  Which local LLM provider?")
    print("  a) Ollama  (free, runs on your machine — install from https://ollama.com)")
    print("  b) OpenAI  (cloud API key required)")
    print("  c) Anthropic  (cloud API key required)")
    print("  d) Custom / LM Studio / Jan  (any OpenAI-compatible local server)")
    print()

    sub = ask("Provider", "a").lower()

    if sub == "b":
        key   = ask("OpenAI API key (sk-...)")
        model = ask("OpenAI model", "gpt-4o-mini")
        _test_api_key("openai", "https://api.openai.com/v1", key, model)
        return {
            "KB_LLM_PROVIDER":  "openai",
            "KB_LLM_BASE_URL":  "https://api.openai.com/v1",
            "KB_MODEL":         model,
            "KB_API_KEY":       key,
            "KB_EMBED_MODEL":   "text-embedding-3-small",
        }
    elif sub == "c":
        key   = ask("Anthropic API key")
        model = ask("Anthropic model", "claude-3-5-haiku-20241022")
        _test_api_key("anthropic", "https://api.anthropic.com", key, model)
        return {
            "KB_LLM_PROVIDER":  "anthropic",
            "KB_LLM_BASE_URL":  "https://api.anthropic.com",
            "KB_MODEL":         model,
            "KB_API_KEY":       key,
        }
    elif sub == "d":
        url   = ask("Base URL of your local server", "http://localhost:1234/v1")
        model = ask("Model name")
        return {
            "KB_LLM_PROVIDER":  "custom",
            "KB_LLM_BASE_URL":  url,
            "KB_MODEL":         model,
        }
    else:
        # Ollama (default)
        model = ask("Ollama model", "qwen3:14b")
        print()
        info("Make sure Ollama is running before asking questions: `ollama serve`")
        info("Pull the model if you haven't already: `ollama pull " + model + "`")
        return {
            "KB_LLM_PROVIDER":  "ollama",
            "KB_MODEL":         model,
            "KB_EMBED_MODEL":   "nomic-embed-text",
        }


# ── Step 5: write .env ────────────────────────────────────────────────────────

def _read_env_key(env_path: pathlib.Path, key: str) -> str | None:
    """Return the current value of `key` from an existing .env file, or None."""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1:].strip()
    return None


def setup_env(kb_root: pathlib.Path, llm_settings: dict):
    hdr("⑤ Configuring environment (.env)")
    env_path     = SCRIPT_DIR / ".env"
    example_path = SCRIPT_DIR / ".env.example"

    if env_path.exists():
        ok(".env already exists — keeping existing values")
        # Always patch KB_ROOT in case the repo was moved
        _patch_kb_root(env_path, kb_root)
        # 2.5 — Check if the user chose a different LLM provider than what's in .env
        new_provider = llm_settings.get("KB_LLM_PROVIDER", "")
        old_provider = _read_env_key(env_path, "KB_LLM_PROVIDER") or ""
        if new_provider and old_provider and new_provider != old_provider:
            try:
                ans = ask(
                    f"Your .env has KB_LLM_PROVIDER={old_provider}. "
                    f"Update it to {new_provider}? [y/N]", "N"
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
                print()
            if ans == "y":
                lines = env_path.read_text(encoding="utf-8").splitlines()

                def _set(k: str, v: str):
                    new_lines, found = [], False
                    for ln in lines:
                        stripped = ln.lstrip("# ")
                        if stripped.startswith(f"{k}=") or ln.startswith(f"{k}="):
                            new_lines.append(f"{k}={v}")
                            found = True
                        else:
                            new_lines.append(ln)
                    if not found:
                        new_lines.append(f"{k}={v}")
                    lines[:] = new_lines

                for k, v in llm_settings.items():
                    _set(k, v)
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                ok(f"LLM settings updated to provider={new_provider}")
            else:
                info(f"Keeping existing provider={old_provider}")
        return

    if not example_path.exists():
        warn(".env.example not found — creating a minimal .env")
        lines = [f"KB_ROOT={kb_root}"]
        for k, v in llm_settings.items():
            lines.append(f"{k}={v}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok(f".env created")
        return

    # Start from the example, patch KB_ROOT, then apply all LLM settings
    content = example_path.read_text(encoding="utf-8")
    content = content.replace("# KB_ROOT=/path/to/your/KnowledgeBase",
                               f"KB_ROOT={kb_root}")
    env_path.write_text(content, encoding="utf-8")

    lines = env_path.read_text(encoding="utf-8").splitlines()

    def _set(key: str, value: str):
        new_lines, found = [], False
        for ln in lines:
            stripped = ln.lstrip("# ")
            if stripped.startswith(f"{key}=") or ln.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(ln)
        if not found:
            new_lines.append(f"{key}={value}")
        lines[:] = new_lines

    for k, v in llm_settings.items():
        _set(k, v)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok(f".env configured  (KB_ROOT={kb_root}, provider={llm_settings.get('KB_LLM_PROVIDER', '?')})")


def _patch_kb_root(env_path: pathlib.Path, kb_root: pathlib.Path):
    """Ensure KB_ROOT in an existing .env points to the current location."""
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    patched = False
    for ln in lines:
        if ln.startswith("KB_ROOT=") and ln.strip() != f"KB_ROOT={kb_root}":
            new_lines.append(f"KB_ROOT={kb_root}")
            patched = True
        else:
            new_lines.append(ln)
    if not patched:
        # KB_ROOT not set yet — append it
        if not any(ln.startswith("KB_ROOT=") for ln in lines):
            new_lines.append(f"KB_ROOT={kb_root}")
            patched = True
    if patched:
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        ok(f"KB_ROOT updated to {kb_root}")


# ── Step 6: knowledge folder check ───────────────────────────────────────────

BLOCKLIST = {
    "agents", ".git", "__pycache__", ".ds_store", "node_modules",
    ".venv", "venv", "env", ".bob", ".idea", ".vscode", "dist", "build",
}
INCLUDE_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt",
                ".csv", ".boxnote", ".ppt", ".doc"}

def check_knowledge_folders(kb_root: pathlib.Path, yes: bool):
    hdr("⑥ Checking knowledge folders")
    folders = [
        p for p in sorted(kb_root.iterdir())
        if p.is_dir()
        and p.name.lower() not in BLOCKLIST
        and any(f.suffix.lower() in INCLUDE_EXTS for f in p.rglob("*") if f.is_file())
    ]
    if folders:
        ok(f"Found {len(folders)} knowledge folder(s):")
        for f in folders:
            count = sum(1 for x in f.rglob("*")
                        if x.is_file() and x.suffix.lower() in INCLUDE_EXTS)
            print(f"     • {f.name}/  ({count} files)")
        return

    warn("No knowledge folders found.")
    if yes:
        info("Skipping folder creation — add folders manually and re-run setup.py")
        return

    print()
    print("  Add a folder of documents now?")
    print("  Example: mkdir 'My Project' && cp ~/Documents/*.pdf 'My Project/'")
    name = ask("Folder name (or Enter to skip)", "")
    if name:
        folder = kb_root / name
        folder.mkdir(exist_ok=True)
        ok(f"Created {folder}/")
        info(f"Copy your documents into '{name}/' then re-run setup.py, or run `python3 generate.py`")
    else:
        info("Skipping — you can add folders and run `python3 generate.py` later")


# ── Step 7: run generate.py ───────────────────────────────────────────────────

def run_generate(yes: bool):
    hdr("⑦ Running generate.py  (builds indexes + installs agent skill)")
    gen = SCRIPT_DIR / "scripts" / "generate.py"
    if not gen.exists():
        err("scripts/generate.py not found — cannot continue")
        sys.exit(1)
    flags = ["--no-llm"] if yes else []
    # In non-interactive mode skip LLM description generation to keep it fast;
    # user can run `python3 scripts/generate.py` separately to enrich descriptions.
    rc = run([sys.executable, str(gen)] + flags)
    if rc != 0:
        err("generate.py exited with an error (see output above).")
        err("Common causes:")
        err("  • KB_ROOT in .env points to a folder that doesn't exist")
        err("  • No knowledge subfolders with documents were found")
        err("  • A required Python package is missing (re-run: pip install -r requirements.txt)")
        err("Re-run manually to see the full error:  python3 scripts/generate.py")
        sys.exit(1)
    ok("generate.py completed")


# ── Step 6: install the knowledgebase-install skill ──────────────────────────

def install_install_skill():
    """Copy agents/install_skill.md → ~/.bob/skills/knowledgebase-install/SKILL.md
    so that any user who cloned this repo can also guide others through setup."""
    src = SCRIPT_DIR / "agents" / "install_skill.md"
    if not src.exists():
        return  # not fatal — skill body lives in the repo, just not copied yet
    dest_dir = pathlib.Path.home() / ".bob" / "skills" / "knowledgebase-install"
    dest = dest_dir / "SKILL.md"
    if dest.exists():
        ok("knowledgebase-install skill already present")
        return
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        ok(f"knowledgebase-install skill installed: {dest}")
    except Exception as e:
        warn(f"Could not install knowledgebase-install skill: {e}")


# ── Done ──────────────────────────────────────────────────────────────────────

def print_done(kb_root: pathlib.Path):
    skill         = pathlib.Path.home() / ".bob" / "skills" / "knowledgebase-agent" / "SKILL.md"
    install_skill = pathlib.Path.home() / ".bob" / "skills" / "knowledgebase-install" / "SKILL.md"
    # 2.4 — Resolve absolute path to kb-agent-serve (venv-aware)
    serve_cmd = shutil.which("kb-agent-serve") or str(
        pathlib.Path(sys.prefix) / "bin" / "kb-agent-serve"
    )
    hdr("✅  Setup complete!")
    print()
    if skill.exists():
        print(_color("32", "  Bob skill installed:") + f" {skill}")
        if install_skill.exists():
            print(_color("32", "  Install skill installed:") + f" {install_skill}")
        print()
        print("  Ask Bob a question to get started:")
        print("    \"What does my KnowledgeBase say about X?\"")
        print("    \"/kb how does Y work?\"")
        print()
        print("  Share this repo with anyone — they just need to say:")
        print("    \"Here's the repo link, install the skill\"")
        print("    and any AI tool will guide them through setup.")
    else:
        print("  Bob not detected. You can still use the CLI:")
        print(f"    python3 agents/agent_knowledgebase.py \"your question\"")
    print()
    print("  MCP host config (ready to paste):")
    print("    Claude Desktop → claude_desktop_config.json:")
    print('      "kb-agent-mcp": {')
    print(f'        "command": "{serve_cmd}",')
    print(f'        "env": {{ "KB_ROOT": "{kb_root}" }}')
    print('      }')
    print()
    print("  To add more documents:")
    print(f"    1. Drop files into a folder inside {kb_root}/")
    print(f"    2. Run:  python3 scripts/generate.py")
    print()
    print("  To keep indexes auto-updated as files change:")
    print(f"    python3 scripts/watch_kb.py")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="KnowledgeBase Agent — one-command installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python3 scripts/setup.py                    # interactive (recommended)
              python3 scripts/setup.py --yes              # non-interactive (all defaults)
              python3 scripts/setup.py --kb-root /data/kb # skip the root folder prompt
        """),
    )
    parser.add_argument("--yes",     action="store_true",
                        help="Non-interactive: accept all defaults (passthrough mode)")
    parser.add_argument("--kb-root", type=str, default=None,
                        help="Absolute path to use as KB_ROOT (skips the folder prompt)")
    args = parser.parse_args()

    cli_kb_root = pathlib.Path(args.kb_root).resolve() if args.kb_root else None

    print(_color("1;36", "\n╔══════════════════════════════════════════╗"))
    print(_color("1;36",   "║   KnowledgeBase Agent — Setup            ║"))
    print(_color("1;36",   "╚══════════════════════════════════════════╝"))

    check_python()
    install_deps()
    kb_root     = choose_kb_root(cli_kb_root, args.yes)
    llm_config  = choose_llm(args.yes)
    setup_env(kb_root, llm_config)
    check_knowledge_folders(kb_root, args.yes)
    run_generate(args.yes)
    install_install_skill()
    print_done(kb_root)


if __name__ == "__main__":
    main()
