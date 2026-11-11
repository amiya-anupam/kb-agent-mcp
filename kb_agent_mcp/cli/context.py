"""
kb_agent_mcp/cli/context.py — markdown context store commands
---------------------------------------------------------------
  kb-agent context build [--force] [--domain NAME]   digest every file, write INDEX.md + MANIFEST.md
  kb-agent context refresh [--domain NAME]           re-digest only new/changed files (cheap)

The store lives at <KB_ROOT>/.kb_index/context/ and is plain markdown, so an agent can
read it with read_file / grep and no MCP server.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kb-agent context",
        description="Build or refresh the markdown context store (digests, INDEX.md, MANIFEST.md).",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    b = sub.add_parser("build", help="build the store; --force re-digests every file")
    b.add_argument("--force", action="store_true", help="re-digest even unchanged files")
    b.add_argument("--domain", default=None, help="only this domain folder (exact name)")
    r = sub.add_parser("refresh", help="re-digest only new/changed files and rebuild indexes")
    r.add_argument("--domain", default=None, help="only this domain folder (exact name)")
    args = parser.parse_args()

    from kb_agent_mcp.config import cfg
    from kb_agent_mcp.context_store.paths import context_dir
    from kb_agent_mcp.context_store.sync import sync

    root = cfg.kb_root_path
    if not root.is_dir():
        print(f"KB_ROOT does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    force = getattr(args, "force", False)
    domains = [args.domain] if args.domain else None
    if domains and not (root / args.domain).is_dir():
        print(f"No such domain folder: {args.domain}", file=sys.stderr)
        sys.exit(1)

    res = sync(root, domains=domains, force=force,
               progress=(lambda m: print(f"  {m}", flush=True)) if args.action == "build" else None)
    print(f"Context store: {res.summary()}")
    print(f"  location: {context_dir(root)}")
    for rel, err in sorted(res.failed.items()):
        print(f"  FAILED {rel}: {err}", file=sys.stderr)
    sys.exit(1 if res.failed else 0)


if __name__ == "__main__":
    main()
