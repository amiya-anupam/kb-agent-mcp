"""
kb_agent_mcp/cli/setup.py — Interactive setup wizard
-----------------------------------------------------
Guides a new user through:
  1. Python version check
  2. Build-tools pre-flight (Risk 1 — detect missing gcc/xcode, soft block)
  3. Virtual-environment guidance (Risk 5 — detect non-venv, recommend venv)
  4. KB_ROOT folder selection
  5. LLM / passthrough configuration (Risk 4 — split Q&A mode from key availability)
  6. .env creation
  7. Running kb-agent-generate to build indexes
  8. Interactive keyword editor for domains that got minimal YAML (Risk 4)
  9. Completion output showing absolute kb-agent-serve path (Risk 3)

Usage:
  kb-agent-setup            # interactive (recommended)
  kb-agent-setup --yes      # non-interactive (passthrough defaults)
  kb-agent-setup --kb-root /path/to/docs
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


logger = logging.getLogger(__name__)


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


def _confirm(prompt: str, default: bool = False) -> bool:
    """Yes/No prompt. Returns bool. Handles non-interactive stdin gracefully."""
    hint = "[Y/n]" if default else "[y/N]"
    try:
        val = input(f"  {prompt} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not val:
        return default
    return val in ("y", "yes")


# ── Step 1: Python check ───────────────────────────────────────────────────────

def check_python() -> None:
    hdr("① Checking Python version")
    v = sys.version_info
    if v < (3, 10):
        err(f"Python 3.10+ required — you have {v.major}.{v.minor}")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


# ── Step 1b: Build-tools pre-flight (Risk 1) ──────────────────────────────────

def _build_tools_present() -> bool:
    """Return True when the C++ build toolchain is available on this platform."""
    if sys.platform == "win32":
        return True  # Windows: no C++ compilation needed for chromadb wheels
    if sys.platform == "darwin":
        # xcode-select -p exits 0 when tools are installed, 2 when missing
        result = subprocess.run(
            ["xcode-select", "-p"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    # Linux: check for gcc
    return shutil.which("gcc") is not None


def _build_tools_fix_hint() -> str:
    if sys.platform == "darwin":
        return "xcode-select --install"
    if sys.platform.startswith("linux"):
        return "sudo apt install build-essential python3-dev"
    return ""


def check_build_tools(yes: bool) -> None:
    """Risk 1 — detect missing build tools, soft-block with fix hint."""
    if sys.platform == "win32":
        return  # not needed on Windows

    if _build_tools_present():
        return  # tools present — say nothing (no warning fatigue)

    hint = _build_tools_fix_hint()
    hdr("① Build tools check")
    warn("chromadb requires C++ build tools that are NOT installed on this machine.")
    warn(f"  Install them first:  {hint}")
    print()
    if yes:
        warn("--yes mode: continuing without build tools (pip install may fail).")
        return
    if not _confirm("Continue anyway? (pip install may fail)", default=False):
        print()
        info(f"Run this first:  {hint}")
        info("Then re-run kb-agent-setup.")
        sys.exit(0)


# ── Step 1c: Virtual-environment guidance (Risk 5) ────────────────────────────

def _in_venv() -> bool:
    """Return True when running inside a virtual environment."""
    return sys.prefix != sys.base_prefix


def check_venv(yes: bool) -> None:
    """Risk 5 — detect non-venv state, recommend venv, show commands."""
    if _in_venv():
        return  # already in a venv — say nothing

    hdr("① Virtual environment check")
    warn("You are installing into the system Python (no virtual environment detected).")
    print()
    print("  Recommended: install into a venv so CLI commands stay isolated")
    print("  and kb-agent-serve is always findable by your MCP host.")
    print()
    print("  To set one up:")
    print("    python3 -m venv .venv")
    print("    source .venv/bin/activate          # macOS / Linux")
    print("    .venv\\Scripts\\activate             # Windows")
    print("    pip install kb-agent-mcp")
    print("    kb-agent-setup")
    print()
    if yes:
        warn("--yes mode: continuing with system Python.")
        return
    if not _confirm("Continue with system Python?", default=False):
        print()
        info("Re-run kb-agent-setup after activating your venv.")
        sys.exit(0)


# ── API-key preflight test ─────────────────────────────────────────────────────

def _test_api_key(provider: str, base_url: str, api_key: str, model: str) -> bool:
    """Make a lightweight authenticated request to verify the key.

    Returns True on success, False on auth failure.
    Prints a warning on failure and a notice when network is unreachable.
    Does NOT hard-exit — caller decides whether to soft-block.
    """
    import urllib.request
    import urllib.error
    from kb_agent_mcp.config import ANTHROPIC_API_VERSION

    provider = provider.lower()
    try:
        if provider == "anthropic":
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": ANTHROPIC_API_VERSION,
                },
            )
        else:
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status < 300:
                ok("API key verified ✓")
                return True
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            warn(f"API key test failed (HTTP {exc.code}). Double-check the key.")
            return False
        else:
            warn(f"API key test returned HTTP {exc.code} — proceeding anyway.")
    except Exception as exc:
        logger.warning("API key test failed (%s); treating as passing (network may be down)", exc)
        warn("API key test skipped (network unreachable or timeout) — proceeding.")
    return True  # non-auth failures are treated as passing (network may be down)


# ── Step 2: KB_ROOT folder ─────────────────────────────────────────────────────

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


# ── Step 3: LLM — redesigned (Risk 4) ────────────────────────────────────────
#
# Two independent decisions:
#   Question 1: How should the agent ANSWER questions?  (runtime behaviour)
#   Question 2: Do you have a cloud API key available?  (generate + fallback)
#
# This separates "I want passthrough for Q&A" from "I have no LLM at all".
# The key is stored as KB_API_KEY and used for:
#   • kb-agent-generate (one-time config generation → rich domain YAML)
#   • Q&A fallback when Ollama is unreachable (existing KB_PASSTHROUGH_FALLBACK chain)

def _collect_api_key(provider_name: str, base_url: str, default_model: str) -> dict[str, str]:
    """Prompt for API key + model, validate, return env-var dict."""
    key   = _prompt(f"{provider_name} API key")
    if not key:
        warn("No key entered — skipping API key setup.")
        return {}
    model = _prompt(f"{provider_name} model", default_model)
    valid = _test_api_key(provider_name.lower(), base_url, key, model)
    if not valid:
        if not _confirm("Key appears invalid. Use it anyway?", default=False):
            warn("API key not saved.")
            return {}
    return {
        "KB_API_KEY":     key,
        "KB_MODEL":       model,
    }


def choose_llm(yes: bool) -> dict[str, str]:
    """Risk 4 — redesigned LLM setup: split Q&A mode from key availability."""
    if yes:
        info("LLM: passthrough mode (recommended — no local LLM required)")
        return {"KB_LLM_PROVIDER": "passthrough"}

    # ── Question 1: How should the agent answer questions? ────────────────────
    hdr("③ How should the agent answer questions?")
    print()
    print("  1) Passthrough  (recommended — your AI tool (Bob, Claude, Cursor)")
    print("                   reads retrieved context and answers for you.")
    print("                   No local software needed.")
    print()
    print("  2) Ollama        (free, fully local — install from https://ollama.com)")
    print("  3) OpenAI        (cloud API key required)")
    print("  4) Anthropic     (cloud API key required)")
    print("  5) Custom        (any OpenAI-compatible local server)")
    print()
    choice = _prompt("Choice", "1")

    # ── Non-passthrough paths: key is already collected for Q&A ──────────────

    if choice == "2":
        model = _prompt("Ollama model", "qwen3:14b")
        info("Make sure Ollama is running: `ollama serve`")
        info(f"Pull the model first: `ollama pull {model}`")
        return {
            "KB_LLM_PROVIDER": "ollama",
            "KB_MODEL":        model,
            "KB_EMBED_MODEL":  "nomic-embed-text",
        }

    if choice == "3":
        key_cfg = _collect_api_key("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini")
        base = {
            "KB_LLM_PROVIDER": "openai",
            "KB_LLM_BASE_URL": "https://api.openai.com/v1",
            "KB_EMBED_MODEL":  "text-embedding-3-small",
        }
        return {**base, **key_cfg}

    if choice == "4":
        key_cfg = _collect_api_key("Anthropic", "https://api.anthropic.com", "claude-3-5-haiku-20241022")
        base = {
            "KB_LLM_PROVIDER": "anthropic",
            "KB_LLM_BASE_URL": "https://api.anthropic.com",
        }
        return {**base, **key_cfg}

    if choice == "5":
        url   = _prompt("Base URL", "http://localhost:1234/v1")
        model = _prompt("Model name")
        return {"KB_LLM_PROVIDER": "custom", "KB_LLM_BASE_URL": url, "KB_MODEL": model}

    # ── Passthrough path ──────────────────────────────────────────────────────
    info("Passthrough selected — your AI tool answers using retrieved context.")

    # ── Question 2: Do you have a cloud API key? (Risk 4, Sub-problem B) ─────
    # The key is optional but improves generate quality and acts as Q&A fallback.
    print()
    print("  ③b Do you have an OpenAI or Anthropic API key available?")
    print("     It will be used for:")
    print("       • Generating richer domain config during this setup (one-time)")
    print("       • Answering questions if Ollama becomes unavailable (fallback)")
    print("     You can add this later by editing .env")
    print()

    has_key = _confirm("Enter an API key now?", default=False)

    if not has_key:
        warn(
            "No API key. Domain config will use minimal keyword defaults.\n"
            "  You'll get a chance to add keywords interactively after indexing."
        )
        return {"KB_LLM_PROVIDER": "passthrough"}

    # Collect the key for generate + fallback
    print()
    print("  Provider:")
    print("  1) OpenAI")
    print("  2) Anthropic")
    print()
    prov = _prompt("Provider", "1")

    if prov == "2":
        key_cfg = _collect_api_key("Anthropic", "https://api.anthropic.com", "claude-3-5-haiku-20241022")
        provider_extra = {
            "KB_LLM_PROVIDER":          "passthrough",
            "KB_LLM_PROVIDER_GENERATE": "anthropic",
            "KB_LLM_BASE_URL":          "https://api.anthropic.com",
        }
    else:
        key_cfg = _collect_api_key("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini")
        provider_extra = {
            "KB_LLM_PROVIDER":          "passthrough",
            "KB_LLM_PROVIDER_GENERATE": "openai",
            "KB_LLM_BASE_URL":          "https://api.openai.com/v1",
            "KB_EMBED_MODEL":           "text-embedding-3-small",
        }

    if key_cfg:
        info(
            "Key stored as KB_API_KEY.\n"
            "  Used for: domain config generation + Q&A fallback when Ollama "
            "is unreachable."
        )

    return {**provider_extra, **key_cfg}


# ── Step 4: write .env ────────────────────────────────────────────────────────

def _read_env_key(env_path: Path, key: str) -> str | None:
    """Return the current value of `key` from an existing .env file, or None."""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1:].strip()
    return None


def write_env(kb_root: Path, llm: dict[str, str], cwd: Path) -> None:
    hdr("④ Writing .env")
    env_path     = kb_root / ".env"
    example_path = cwd / ".env.example"

    if env_path.exists():
        ok(".env already exists — keeping existing values")
        _patch_env_key(env_path, "KB_ROOT", str(kb_root))
        new_provider = llm.get("KB_LLM_PROVIDER", "")
        old_provider = _read_env_key(env_path, "KB_LLM_PROVIDER") or ""
        if new_provider and old_provider and new_provider != old_provider:
            try:
                ans = input(
                    f"\n  Your .env has KB_LLM_PROVIDER={old_provider}.\n"
                    f"  Update it to {new_provider}? [y/N]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
                print()
            if ans == "y":
                for k, v in llm.items():
                    _patch_env_key(env_path, k, v)
                ok(f"LLM settings updated to provider={new_provider}")
            else:
                info(f"Keeping existing provider={old_provider}")
        return

    if example_path.exists():
        content = example_path.read_text(encoding="utf-8")
        content = content.replace("# KB_ROOT=/path/to/your/KnowledgeBase", f"KB_ROOT={kb_root}")
    else:
        content = f"KB_ROOT={kb_root}\n"

    env_path.write_text(content, encoding="utf-8")
    for k, v in llm.items():
        _patch_env_key(env_path, k, v)
    ok(f".env written  (KB_ROOT={kb_root}, provider={llm.get('KB_LLM_PROVIDER', '?')})")
    ok(f".env location: {env_path}")


def _patch_env_key(env_path: Path, key: str, value: str) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="

    # Prefer an uncommented live line; fall back to the first commented form.
    live_idx     = next((i for i, ln in enumerate(lines) if ln.startswith(prefix)), None)
    comment_idx  = next(
        (i for i, ln in enumerate(lines) if ln.lstrip("# ").startswith(prefix)), None
    )
    replace_idx  = live_idx if live_idx is not None else comment_idx

    if replace_idx is not None:
        new_lines = [
            (f"{prefix}{value}" if i == replace_idx else ln)
            for i, ln in enumerate(lines)
        ]
        # Drop all OTHER occurrences of the same key (commented or not)
        new_lines = [
            ln for i, ln in enumerate(new_lines)
            if i == replace_idx
            or not (ln.startswith(prefix) or ln.lstrip("# ").startswith(prefix))
        ]
    else:
        new_lines = lines + [f"{prefix}{value}"]

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── Clipboard helper ──────────────────────────────────────────────────────────

def _copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard.

    Tries pbcopy (macOS) → xclip → xsel → clip.exe (Windows) in order.
    Returns True on success, False when no clipboard command is available.
    Silent on failure — clipboard is a convenience, not a hard requirement.
    """
    import subprocess as _sp
    candidates = [
        ["pbcopy"],                       # macOS
        ["xclip", "-selection", "clipboard"],  # Linux (X11)
        ["xsel", "--clipboard", "--input"],    # Linux (X11 alt)
        ["clip"],                         # Windows
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            _sp.run(cmd, input=text.encode(), check=True,
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            return True
        except Exception as exc:
            logger.debug("Editor candidate failed (%s); trying next", exc)
            continue
    return False


# ── Step 5: run kb-agent-generate ─────────────────────────────────────────────

def _serve_path() -> str:
    """Return the absolute path to kb-agent-serve (Risk 3 — venv-aware)."""
    found = shutil.which("kb-agent-serve")
    if found:
        return found
    candidate = Path(sys.prefix) / "bin" / "kb-agent-serve"
    if candidate.exists():
        return str(candidate)
    return "kb-agent-serve"


def run_generate(yes: bool) -> list[str]:
    """Run kb-agent-generate. Returns list of domain names that got minimal YAML.

    Risk 4 — the list is passed to the interactive keyword editor so users
    without an LLM can still enrich their domain configs interactively.
    """
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

    # Detect domains that ended up with minimal YAML (Risk 4 — keyword editor)
    minimal_domains: list[str] = []
    if yes:
        # --no-llm mode always produces minimal YAML for all domains
        try:
            from kb_agent_mcp.config import cfg
            for entry in sorted(cfg.kb_root_path.iterdir()):
                if entry.is_dir() and not cfg.is_ignored(entry.name):
                    yaml_path = entry / "domain_config.yaml"
                    if yaml_path.exists():
                        content = yaml_path.read_text(encoding="utf-8")
                        # Minimal YAML has only 1 keyword (the folder name lowercased)
                        import yaml as _yaml
                        data = _yaml.safe_load(content) or {}
                        kws = data.get("keywords", [])
                        if len(kws) <= 1:
                            minimal_domains.append(entry.name)
        except Exception as exc:
            logger.warning("Failed to scan domains for minimal YAML detection (%s); skipping keyword editor pre-check", exc)
    return minimal_domains


# ── Step 6: Interactive keyword editor (Risk 4) ────────────────────────────────

def _kw_editor_prompt(domain_name: str, current: list[str]) -> list[str] | None:
    """Rich-based keyword prompt for one domain.

    Displays a formatted header with the current keyword list.
    Returns a new keyword list, or None if the user skipped.

    Uses Rich if available (it is a hard dependency), falls back to plain
    input() when stdout is not a tty (CI / --yes mode is already gated upstream).
    """
    _DIVIDER = "─" * 54

    # ── Rich path (interactive tty) ──────────────────────────────────────────
    try:
        from rich.console import Console as _Console
        from rich.panel  import Panel   as _Panel
        from rich.text   import Text    as _Text
        from rich.prompt import Prompt  as _Prompt

        console = _Console(highlight=False)
        console.print()
        console.print(_DIVIDER)

        # Build a styled header: folder name + current keywords as a tag list
        header = _Text()
        header.append(f"  📁 {domain_name}/", style="bold cyan")
        if current:
            header.append("  current keywords: ", style="dim")
            for i, kw in enumerate(current):
                header.append(kw, style="yellow")
                if i < len(current) - 1:
                    header.append(", ", style="dim")
        else:
            header.append("  no keywords yet", style="dim")
        console.print(header)
        console.print()
        console.print(
            "  [dim]Enter comma-separated keywords, or press Enter to skip.[/dim]"
        )
        console.print(
            "  [dim]Example: revenue, quota, deals, pipeline, forecast[/dim]"
        )
        console.print()

        try:
            raw = _Prompt.ask("  Keywords", default="", console=console)
        except (EOFError, KeyboardInterrupt):
            console.print()
            return None

        if not raw.strip():
            return None
        return [k.strip() for k in raw.split(",") if k.strip()]

    except Exception as exc:
        logger.debug("Rich keyword editor failed (%s); falling back to plain input", exc)
        # Plain fallback (Rich unavailable or tty issue)
        print(f"\n{_DIVIDER}")
        print(f"  📁 {domain_name}/  (current: {', '.join(current) or '(none)'})")
        print()
        try:
            raw = input("  Keywords (comma-separated, Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not raw:
            return None
        return [k.strip() for k in raw.split(",") if k.strip()]


def interactive_keyword_editor(minimal_domains: list[str], kb_root: Path, yes: bool) -> None:
    """For domains with minimal YAML, offer to add keywords interactively.

    Only edits the `keywords:` section — leaves all other YAML fields intact.
    Keywords-only scope is intentional: minimal surface area, can't break
    system_prompt or retrieval_rules.
    """
    if not minimal_domains or yes:
        if minimal_domains and yes:
            warn(
                "Domain config used minimal keyword defaults for: "
                + ", ".join(minimal_domains)
                + "\n  Edit keywords manually: <domain>/domain_config.yaml → keywords: section"
                + "\n  Then run: kb-agent-generate --force"
            )
        return

    hdr("⑥ Domain keyword editor")
    print()
    print("  The following domains used minimal keyword defaults")
    print("  (no LLM was available during generate):")
    for d in minimal_domains:
        print(f"    • {d}/")
    print()
    print("  Good keywords help the agent route questions to the right domain.")
    print()

    if not _confirm("Edit keywords now?", default=True):
        warn(
            "Skipped. Edit keywords manually at:\n"
            "  <KB_ROOT>/<domain>/domain_config.yaml  (keywords: section)\n"
            "  Then run: kb-agent-generate --force"
        )
        return

    import yaml as _yaml

    for domain_name in minimal_domains:
        yaml_path = kb_root / domain_name / "domain_config.yaml"
        if not yaml_path.exists():
            warn(f"domain_config.yaml not found for {domain_name} — skipping")
            continue

        try:
            content = yaml_path.read_text(encoding="utf-8")
            data    = _yaml.safe_load(content) or {}
            current = data.get("keywords", [])
        except Exception as exc:
            warn(f"Could not read {yaml_path}: {exc} — skipping")
            continue

        new_kws = _kw_editor_prompt(domain_name, current)

        if new_kws is None:
            info(f"Skipped {domain_name} — no changes made")
            continue

        # Patch only the keywords field — preserve all other YAML fields
        try:
            data["keywords"] = new_kws
            updated = _yaml.dump(data, default_flow_style=False, allow_unicode=True)
            yaml_path.write_text(updated, encoding="utf-8")
            ok(f"{domain_name}: {len(new_kws)} keyword(s) saved  "
               f"({', '.join(new_kws[:5])}"
               + (" …" if len(new_kws) > 5 else "") + ")")
        except Exception as exc:
            warn(f"Could not write {yaml_path}: {exc}")

    print(f"\n{'─' * 54}")
    ok("domain_config.yaml files updated.")
    info("Run kb-agent-generate --force later to regenerate with an LLM if needed.")


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
    check_build_tools(args.yes)   # Risk 1 — detect + soft-block missing build tools
    check_venv(args.yes)          # Risk 5 — detect non-venv, recommend venv

    kb_root  = choose_kb_root(cli_root, args.yes)
    llm_cfg  = choose_llm(args.yes)
    write_env(kb_root, llm_cfg, cwd)

    minimal_domains = run_generate(args.yes)
    interactive_keyword_editor(minimal_domains, kb_root, args.yes)  # Risk 4

    # Risk 3 / Risk 5 — absolute path to kb-agent-serve is the FIRST thing
    # shown in the completion block, not buried at the bottom.
    serve_cmd = _serve_path()

    hdr("✅  Setup complete!")
    print()

    mcp_config_block = (
        '"kb-agent-mcp": {\n'
        f'  "command": "{serve_cmd}",\n'
        f'  "env": {{ "KB_ROOT": "{kb_root}" }}\n'
        '}'
    )

    print(_c("1", "  MCP host config — paste this exactly:"))
    print(_c("36", "  " + "─" * 52))
    for line in mcp_config_block.splitlines():
        print(f"  {line}")
    print(_c("36", "  " + "─" * 52))
    print()

    if not args.yes and sys.stdout.isatty():
        try:
            ans = input("  Copy config to clipboard? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
            print()
        if ans in ("", "y", "yes"):
            if _copy_to_clipboard(mcp_config_block):
                ok("Copied to clipboard.")
            else:
                warn("Clipboard not available — copy the block above manually.")

    print()
    if not _in_venv():
        warn(
            "Not in a venv — if the above command path doesn't work,\n"
            "  run `which kb-agent-serve` in your terminal for the correct path."
        )
    print()
    print("  Start the MCP server:")
    print(f"    {serve_cmd}                    # stdio (for Claude Desktop / Bob)")
    print(f"    {serve_cmd} --transport http   # HTTP/SSE")
    print()
    print(f"  .env location:  {kb_root / '.env'}")
    print()
    print("  Re-index after adding documents:")
    print("    kb-agent-generate")
    print()
    print("  Watch for file changes automatically:")
    print("    kb-agent-watch")
    print()
    print("  Run a health check:")
    print("    kb-agent-doctor")
    print()


if __name__ == "__main__":
    main()
