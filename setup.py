#!/usr/bin/env python3
"""
setup.py — KnowledgeBase Agent: one-command installer
------------------------------------------------------
Run this once after cloning (or after adding new knowledge folders).

What it does:
  1. Checks Python version (3.10+)
  2. Installs Python dependencies from requirements.txt
  3. Creates .env from .env.example if .env does not exist yet
     — auto-fills KB_ROOT to the directory where this script lives
     — prompts for LLM provider/key only if not already set
  4. Prompts the user to add knowledge folders (or accepts --kb-root)
  5. Runs python3 generate.py to build indexes and install the Bob skill

Usage:
  python3 setup.py                    # interactive
  python3 setup.py --yes              # non-interactive (accept all defaults)
  python3 setup.py --kb-root /path    # use an existing folder as KB root

After setup the Bob skill is live at:
  ~/.bob/skills/knowledgebase-agent/SKILL.md
"""

import os
import sys
import shutil
import pathlib
import subprocess
import textwrap

SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()


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


# ── Step 2: pip install ───────────────────────────────────────────────────────

def install_deps():
    hdr("② Installing Python dependencies")
    req = SCRIPT_DIR / "requirements.txt"
    if not req.exists():
        warn("requirements.txt not found — skipping pip install")
        return
    rc = run([sys.executable, "-m", "pip", "install", "-r", str(req), "-q"])
    if rc != 0:
        err("pip install failed. Check the output above.")
        sys.exit(1)
    ok("Dependencies installed")


# ── Step 3: .env setup ────────────────────────────────────────────────────────

def setup_env(kb_root: pathlib.Path, yes: bool):
    hdr("③ Configuring environment (.env)")
    env_path     = SCRIPT_DIR / ".env"
    example_path = SCRIPT_DIR / ".env.example"

    if env_path.exists():
        ok(".env already exists — keeping it")
        # Always patch KB_ROOT to current location in case the repo was moved
        _patch_kb_root(env_path, kb_root)
        return

    if not example_path.exists():
        warn(".env.example not found — creating a minimal .env")
        env_path.write_text(
            f"KB_ROOT={kb_root}\nKB_LLM_PROVIDER=ollama\nKB_MODEL=qwen3:14b\n"
            f"KB_EMBED_MODEL=nomic-embed-text\n",
            encoding="utf-8",
        )
        ok(f".env created with KB_ROOT={kb_root}")
        return

    # Copy example and fill in KB_ROOT automatically
    content = example_path.read_text(encoding="utf-8")
    content = content.replace("# KB_ROOT=/path/to/your/KnowledgeBase",
                               f"KB_ROOT={kb_root}")
    env_path.write_text(content, encoding="utf-8")
    ok(f".env created  (KB_ROOT={kb_root})")

    # Optionally prompt for LLM config
    if yes:
        info("Using default LLM config (Ollama / passthrough). Edit .env to change.")
        return

    print()
    print("  Choose your LLM provider (or press Enter to use passthrough mode):")
    print("  1) Ollama  (local, default — run `ollama serve` first)")
    print("  2) OpenAI  (needs KB_API_KEY)")
    print("  3) Anthropic  (needs KB_API_KEY)")
    print("  4) Skip  (passthrough mode — Bob's Claude answers using retrieved context)")

    choice = ask("Choice", "4")

    lines = env_path.read_text(encoding="utf-8").splitlines()

    def _set(key: str, value: str):
        new_lines = []
        found = False
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

    if choice == "1":
        model = ask("Ollama model", "qwen3:14b")
        _set("KB_LLM_PROVIDER", "ollama")
        _set("KB_MODEL", model)
        _set("KB_EMBED_MODEL", "nomic-embed-text")
    elif choice == "2":
        key   = ask("OpenAI API key (sk-...)")
        model = ask("OpenAI model", "gpt-4o-mini")
        _set("KB_LLM_PROVIDER", "openai")
        _set("KB_LLM_BASE_URL", "https://api.openai.com/v1")
        _set("KB_MODEL", model)
        _set("KB_API_KEY", key)
        _set("KB_EMBED_MODEL", "text-embedding-3-small")
    elif choice == "3":
        key   = ask("Anthropic API key")
        model = ask("Anthropic model", "claude-3-5-haiku-20241022")
        _set("KB_LLM_PROVIDER", "anthropic")
        _set("KB_LLM_BASE_URL", "https://api.anthropic.com")
        _set("KB_MODEL", model)
        _set("KB_API_KEY", key)
    else:
        info("Passthrough mode selected. Bob's Claude will answer using retrieved context.")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok(".env configured")


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


# ── Step 4: knowledge folder check ───────────────────────────────────────────

BLOCKLIST = {
    "agents", ".git", "__pycache__", ".ds_store", "node_modules",
    ".venv", "venv", "env", ".bob", ".idea", ".vscode", "dist", "build",
}
INCLUDE_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt",
                ".csv", ".boxnote", ".ppt", ".doc"}

def check_knowledge_folders(kb_root: pathlib.Path, yes: bool):
    hdr("④ Checking knowledge folders")
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


# ── Step 5: run generate.py ───────────────────────────────────────────────────

def run_generate(yes: bool):
    hdr("⑤ Running generate.py  (builds indexes + installs Bob skill)")
    gen = SCRIPT_DIR / "generate.py"
    if not gen.exists():
        err("generate.py not found — cannot continue")
        sys.exit(1)
    flags = ["--no-llm"] if yes else []
    # In non-interactive mode skip LLM description generation to keep it fast;
    # user can run `python3 generate.py` separately to enrich descriptions.
    rc = run([sys.executable, str(gen)] + flags)
    if rc != 0:
        err("generate.py exited with errors. See output above.")
        sys.exit(1)
    ok("generate.py completed")


# ── Step 6: install the knowledgebase-install skill ───────────────────────────

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
    skill = pathlib.Path.home() / ".bob" / "skills" / "knowledgebase-agent" / "SKILL.md"
    install_skill = pathlib.Path.home() / ".bob" / "skills" / "knowledgebase-install" / "SKILL.md"
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
    print("  To add more documents:")
    print(f"    1. Drop files into a folder inside {kb_root}/")
    print(f"    2. Run:  python3 generate.py")
    print()
    print("  To keep indexes auto-updated as files change:")
    print(f"    python3 watch_kb.py")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="KnowledgeBase Agent — one-command installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python3 setup.py                    # interactive
              python3 setup.py --yes              # non-interactive (all defaults)
              python3 setup.py --kb-root /data/kb # use an existing folder as root
        """),
    )
    parser.add_argument("--yes",     action="store_true",
                        help="Non-interactive: accept all defaults")
    parser.add_argument("--kb-root", type=str, default=None,
                        help="Absolute path to use as KB_ROOT (defaults to repo dir)")
    args = parser.parse_args()

    kb_root = pathlib.Path(args.kb_root).resolve() if args.kb_root else SCRIPT_DIR

    print(_color("1;36", "\n╔══════════════════════════════════════════╗"))
    print(_color("1;36",   "║   KnowledgeBase Agent — Setup            ║"))
    print(_color("1;36",   "╚══════════════════════════════════════════╝"))

    check_python()
    install_deps()
    setup_env(kb_root, args.yes)
    check_knowledge_folders(kb_root, args.yes)
    run_generate(args.yes)
    install_install_skill()
    print_done(kb_root)


if __name__ == "__main__":
    main()
