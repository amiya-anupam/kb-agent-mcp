"""
kb_agent_mcp/cli/main.py — kb-agent unified entry point
--------------------------------------------------------
Single command that dispatches to all kb-agent-mcp subcommands.

Usage:
  kb-agent setup      # interactive setup wizard
  kb-agent generate   # build / rebuild vector indexes
  kb-agent serve      # start the MCP server
  kb-agent watch      # watch KB_ROOT for changes
  kb-agent doctor     # health check (--fix to auto-repair)
  kb-agent status     # per-domain status table
  kb-agent init       # first-time setup: setup → generate → doctor in sequence

All flags accepted by each subcommand pass through unchanged:
  kb-agent generate --force --domain BizOps
  kb-agent doctor --fix
  kb-agent status --diff --plain
  kb-agent setup --yes --kb-root /path/to/docs
  kb-agent init --yes --kb-root /path/to/docs
"""

from __future__ import annotations

import argparse
import logging
import sys

logger = logging.getLogger(__name__)

# ── Subcommand registry ────────────────────────────────────────────────────────

_SUBCOMMANDS = {
    "setup":    ("kb_agent_mcp.cli.setup",    "main"),
    "generate": ("kb_agent_mcp.cli.generate", "main"),
    "serve":    ("kb_agent_mcp.server",       "main"),
    "watch":    ("kb_agent_mcp.cli.watch",    "main"),
    "doctor":   ("kb_agent_mcp.cli.doctor",   "main"),
    "status":   ("kb_agent_mcp.cli.status",   "main"),
}

_SUBCOMMAND_HELP = {
    "setup":    "interactive setup wizard (configure LLM, KB_ROOT, write .env)",
    "generate": "build / rebuild ChromaDB vector indexes for all knowledge folders",
    "serve":    "start the MCP server",
    "watch":    "watch KB_ROOT for file changes and keep indexes in sync",
    "doctor":   "run health checks; use --fix to auto-repair failures",
    "status":   "show per-domain health table and system summary",
    "init":     "first-time setup: runs setup → generate → doctor in sequence",
}


def _dispatch(subcommand: str, remaining_args: list[str]) -> None:
    """Import and call a subcommand's main(), injecting remaining_args into sys.argv."""
    module_path, fn_name = _SUBCOMMANDS[subcommand]
    import importlib
    mod = importlib.import_module(module_path)
    fn  = getattr(mod, fn_name)
    # Patch sys.argv so the subcommand's own argparse sees the right program name
    sys.argv = [f"kb-agent {subcommand}"] + remaining_args
    fn()


def _run_init(args: argparse.Namespace, remaining: list[str]) -> None:
    """
    Option 2 — first-time init sequence: setup → generate → doctor.

    Runs each step in the same Python process (no subprocess) so there's no
    PATH dependency on the installed scripts. Each step's main() patches
    sys.argv itself the same way _dispatch() does.

    Flags forwarded:
      --yes / --kb-root   → setup
      --yes               → generate (non-interactive)
      (no flags)          → doctor (just reports)
    """
    _divider = "─" * 52

    def _banner(label: str) -> None:
        print(f"\n\033[1;36m{_divider}\033[0m")
        print(f"\033[1;36m  kb-agent init — {label}\033[0m")
        print(f"\033[1;36m{_divider}\033[0m\n")

    # Build per-step argv lists
    setup_argv: list[str] = []
    if args.yes:
        setup_argv.append("--yes")
    if args.kb_root:
        setup_argv.extend(["--kb-root", args.kb_root])

    generate_argv: list[str] = ["--yes"] if args.yes else []

    steps = [
        ("Step 1 of 3 — Setup",           "kb_agent_mcp.cli.setup",    "main", setup_argv),
        ("Step 2 of 3 — Generate indexes", "kb_agent_mcp.cli.generate", "main", generate_argv),
        ("Step 3 of 3 — Health check",     "kb_agent_mcp.cli.doctor",   "main", []),
    ]

    import importlib
    for label, module_path, fn_name, extra_argv in steps:
        _banner(label)
        mod = importlib.import_module(module_path)
        fn  = getattr(mod, fn_name)
        sys.argv = [f"kb-agent init ({fn_name})"] + extra_argv
        try:
            fn()
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
            if rc != 0:
                print(f"\n\033[31m  ✗ {label} failed (exit {rc}). Fix the issue above and re-run.\033[0m\n")
                sys.exit(rc)

    print("\n\033[1;32m  ✅  kb-agent init complete — your knowledge base is ready.\033[0m\n")
    print("  Start the MCP server:  kb-agent serve")
    print("  Watch for changes:     kb-agent watch\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kb-agent",
        description="KnowledgeBase Agent MCP — unified CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(
            f"  kb-agent {cmd:<12} {desc}"
            for cmd, desc in _SUBCOMMAND_HELP.items()
        ),
    )
    parser.add_argument(
        "subcommand",
        choices=list(_SUBCOMMANDS.keys()) + ["init"],
        help="Subcommand to run",
    )
    # init-specific flags (forwarded to setup/generate)
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Non-interactive mode (forwarded to setup and generate)")
    parser.add_argument("--kb-root", type=str, default=None,
                        help="KB_ROOT path (forwarded to setup)")

    # Parse only the first positional + known flags; pass the rest to the subcommand
    args, remaining = parser.parse_known_args()

    if args.subcommand == "init":
        _run_init(args, remaining)
        return

    _dispatch(args.subcommand, remaining)


if __name__ == "__main__":
    main()
