"""
kb_agent_mcp/cli/status.py — kb-agent-status
─────────────────────────────────────────────
Prints a per-domain health table and system summary. Read-only, no side effects.

Usage:
  kb-agent-status              # coloured Rich table
  kb-agent-status --diff       # show stale/missing files per domain
  kb-agent-status --json       # machine-readable JSON to stdout
  kb-agent-status --plain      # no ANSI (for CI / log capture)
  kb-agent-status --tui        # live-refresh table (Ctrl+C to quit)
  kb-agent-status --tui --interval 10  # refresh every 10 s
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

# rich is a hard dependency (pyproject.toml) — no try/except needed
from rich.console import Console
from rich.table import Table
from rich import box

# ── Stale threshold constant ───────────────────────────────────────────────────
# Doctor uses 7 days; keep them in sync by centralising the constant here and
# importing it from doctor to avoid drift.
STALE_DAYS = 7


# ── Data collection ────────────────────────────────────────────────────────────

def _indexable_files(folder: Path) -> list[Path]:
    """Return all indexable files under a domain folder, sorted by path."""
    from kb_agent_mcp.file_parser import INCLUDE_EXTS, should_skip
    return sorted(
        f for f in folder.rglob("*")
        if f.is_file() and f.suffix.lower() in INCLUDE_EXTS and not should_skip(f)
    )


def _count_files(folder: Path) -> int:
    """Count indexable files under a domain folder."""
    return len(_indexable_files(folder))


def _domain_row(domain_name: str, kb_root: Path) -> dict:
    """
    Collect all status data for one domain.
    Returns a dict with keys: name, files, doc_count, indexed_str, age_days,
    status_icon, status_text, yaml_ok.
    """
    folder = kb_root / domain_name
    files = _count_files(folder)

    # defaults
    doc_count   = None
    indexed_str = "(not indexed)"
    age_days    = None
    status_icon = "⚠"
    status_text = "not indexed"
    yaml_ok     = (folder / "domain_config.yaml").exists()

    try:
        from kb_agent_mcp.vector_store import get_or_create_collection, _get_client
        _get_client()  # raises RuntimeError on schema mismatch
        col = get_or_create_collection(domain_name)
        doc_count = col.count()

        # Read indexed_at from collection metadata
        try:
            result = col.get(limit=1, include=["metadatas"])
            metas = result.get("metadatas") or []
            indexed_at_str = None
            for m in metas:
                if m:
                    # prefer indexed_at_iso (ISO string); fall back to float→ISO
                    if "indexed_at_iso" in m:
                        indexed_at_str = m["indexed_at_iso"]
                        break
                    elif "indexed_at" in m:
                        try:
                            indexed_at_str = datetime.datetime.fromtimestamp(
                                float(m["indexed_at"]), tz=datetime.timezone.utc
                            ).isoformat()
                        except (TypeError, ValueError):
                            indexed_at_str = str(m["indexed_at"])
                        break
            if indexed_at_str:
                indexed_dt = datetime.datetime.fromisoformat(indexed_at_str)
                age_days = (
                    datetime.datetime.now(datetime.timezone.utc) - indexed_dt
                ).days
                if age_days == 0:
                    indexed_str = "today"
                elif age_days == 1:
                    indexed_str = "1d ago"
                else:
                    indexed_str = f"{age_days}d ago"
            elif doc_count > 0:
                indexed_str = "indexed"
        except Exception:
            if doc_count and doc_count > 0:
                indexed_str = "indexed"

        if doc_count == 0:
            status_icon, status_text = "⚠", "empty index"
        elif age_days is not None and age_days > STALE_DAYS:
            status_icon, status_text = "⚠", f"stale (>{STALE_DAYS}d)"
        else:
            status_icon, status_text = "✓", "fresh"

    except RuntimeError:
        status_icon, status_text = "✗", "DB mismatch"
    except Exception:
        pass  # not indexed yet — defaults stand

    return {
        "name":         domain_name,
        "files":        files,
        "doc_count":    doc_count,
        "indexed_str":  indexed_str,
        "age_days":     age_days,
        "status_icon":  status_icon,
        "status_text":  status_text,
        "yaml_ok":      yaml_ok,
    }


def _system_info() -> dict:
    """Collect LLM, embedding, server-path, Bob-skill info."""
    from kb_agent_mcp.config import cfg

    provider = cfg.KB_LLM_PROVIDER

    embed_label = cfg.KB_EMBED_MODEL or "all-MiniLM-L6-v2 (sentence-transformers)"
    try:
        from kb_agent_mcp.embeddings import _ST_MODEL_NAME, _st_model_is_cached
        cached = _st_model_is_cached()
        embed_label = f"{_ST_MODEL_NAME} ({'cached' if cached else 'not cached'})"
        if cfg.KB_EMBED_MODEL:
            embed_label = cfg.KB_EMBED_MODEL
    except Exception:
        pass

    # Reuse doctor's path logic
    serve_path: str | None = None
    venv_bin = Path(sys.prefix) / "bin" / "kb-agent-serve"
    if venv_bin.exists():
        serve_path = str(venv_bin)
    else:
        serve_path = shutil.which("kb-agent-serve")

    bob_skill = (
        Path.home() / ".bob" / "skills" / "knowledgebase-agent" / "SKILL.md"
    ).exists()

    return {
        "provider":   provider,
        "embed":      embed_label,
        "serve_path": serve_path or "(not found)",
        "bob_skill":  bob_skill,
    }


# ── Table builder ──────────────────────────────────────────────────────────────

def build_table(console: Console) -> Table:
    """Build and return the Rich domain-status Table. Also returns system info
    as side effect via the console title — callers can call this repeatedly for
    TUI refresh."""
    from kb_agent_mcp.config import cfg
    from kb_agent_mcp import __version__

    kb_root = cfg.kb_root_path

    # Collect domain rows
    domains: list[dict] = []
    if kb_root.exists():
        for entry in sorted(kb_root.iterdir()):
            if entry.is_dir() and not cfg.is_ignored(entry.name):
                domains.append(_domain_row(entry.name, kb_root))

    table = Table(
        title=f"[bold]kb-agent-mcp[/bold]  v{__version__}    "
              f"KB_ROOT: [cyan]{kb_root}[/cyan]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("Domain",   style="white",   no_wrap=True)
    table.add_column("Files",    justify="right",  style="cyan")
    table.add_column("Indexed",  justify="right",  style="cyan")
    table.add_column("Docs",     justify="right",  style="cyan")
    table.add_column("YAML",     justify="center", style="cyan")
    table.add_column("Status",   no_wrap=True)

    for row in domains:
        status_color = "green" if row["status_icon"] == "✓" else (
            "red" if row["status_icon"] == "✗" else "yellow"
        )
        doc_str = str(row["doc_count"]) if row["doc_count"] is not None else "—"
        yaml_str = "✓" if row["yaml_ok"] else "[yellow]✗[/yellow]"
        table.add_row(
            row["name"],
            str(row["files"]),
            row["indexed_str"],
            doc_str,
            yaml_str,
            f"[{status_color}]{row['status_icon']} {row['status_text']}[/{status_color}]",
        )

    if not domains:
        table.add_row(
            "[dim]No domains found[/dim]", "—", "—", "—", "—",
            "[dim]run kb-agent-generate[/dim]",
        )

    return table


# ── Diff view ──────────────────────────────────────────────────────────────────

def _get_indexed_file_hashes(domain_name: str) -> dict[str, str]:
    """Return {relative_path_str: hash} for every document stored in ChromaDB
    for this domain.  Returns {} when ChromaDB is unreachable."""
    try:
        from kb_agent_mcp.vector_store import get_or_create_collection, _get_client
        _get_client()
        col = get_or_create_collection(domain_name)
        result = col.get(include=["metadatas"])
        hashes: dict[str, str] = {}
        for meta in (result.get("metadatas") or []):
            if meta:
                path_key  = meta.get("source_path") or meta.get("path") or ""
                file_hash = meta.get("hash") or ""
                if path_key:
                    hashes[path_key] = file_hash
        return hashes
    except Exception:
        return {}


def _diff_domain(domain_name: str, kb_root: Path) -> dict:
    """
    Compare on-disk files against the ChromaDB index for one domain.

    Returns:
        {
          "missing":  [Path, ...],   # on disk but not in index
          "stale":    [Path, ...],   # in index, but mtime newer than indexed_at
          "ok":       int,           # count of files present + current
          "no_index": bool,          # True when ChromaDB is unreachable/empty
        }
    """
    import datetime

    folder = kb_root / domain_name
    disk_files = _indexable_files(folder)

    # Try to get indexed file info
    indexed_hashes = _get_indexed_file_hashes(domain_name)
    no_index = not indexed_hashes

    if no_index:
        # No index data: every file counts as missing
        return {"missing": disk_files, "stale": [], "ok": 0, "no_index": True}

    # Build a set of indexed paths for fast lookup
    # ChromaDB stores paths as absolute strings or relative — normalise to absolute
    indexed_abs: dict[str, str] = {}
    for p, h in indexed_hashes.items():
        abs_p = Path(p).expanduser().resolve()
        indexed_abs[str(abs_p)] = h

    # Also try to get indexed_at timestamp for staleness check
    indexed_at_dt: datetime.datetime | None = None
    try:
        from kb_agent_mcp.vector_store import get_or_create_collection
        col = get_or_create_collection(domain_name)
        result = col.get(limit=1, include=["metadatas"])
        for m in (result.get("metadatas") or []):
            if m:
                # prefer indexed_at_iso; fall back to float→ISO for old indexes
                if "indexed_at_iso" in m:
                    indexed_at_dt = datetime.datetime.fromisoformat(m["indexed_at_iso"])
                    break
                elif "indexed_at" in m:
                    try:
                        indexed_at_dt = datetime.datetime.fromtimestamp(
                            float(m["indexed_at"]), tz=datetime.timezone.utc
                        )
                    except (TypeError, ValueError):
                        # value may already be an ISO string (written by older code)
                        try:
                            indexed_at_dt = datetime.datetime.fromisoformat(
                                str(m["indexed_at"])
                            )
                        except ValueError:
                            pass
                    break
    except Exception:
        pass

    missing: list[Path] = []
    stale:   list[Path] = []
    ok_count = 0

    for f in disk_files:
        abs_str = str(f.resolve())
        if abs_str not in indexed_abs:
            missing.append(f)
        elif indexed_at_dt is not None:
            # File is indexed — check if it was modified after indexing
            try:
                mtime = datetime.datetime.fromtimestamp(
                    f.stat().st_mtime, tz=datetime.timezone.utc
                )
                if mtime > indexed_at_dt:
                    stale.append(f)
                else:
                    ok_count += 1
            except OSError:
                ok_count += 1
        else:
            ok_count += 1

    return {"missing": missing, "stale": stale, "ok": ok_count, "no_index": False}


def print_diff(kb_root: Path, console: Console) -> None:
    """Print a per-domain file diff between disk and ChromaDB index."""
    from kb_agent_mcp.config import cfg

    domains = [
        e.name for e in sorted(kb_root.iterdir())
        if e.is_dir() and not cfg.is_ignored(e.name)
    ] if kb_root.exists() else []

    if not domains:
        console.print("[dim]No domains found — run kb-agent-generate[/dim]")
        return

    any_issue = False
    for domain_name in domains:
        diff = _diff_domain(domain_name, kb_root)
        missing = diff["missing"]
        stale   = diff["stale"]
        ok      = diff["ok"]
        no_idx  = diff["no_index"]

        if not missing and not stale:
            icon = "[green]✓[/green]" if not no_idx else "[yellow]⚠[/yellow]"
            msg  = "all files indexed" if not no_idx else "not indexed yet"
            console.print(f"  {icon}  [bold]{domain_name}/[/bold]  [dim]{msg}[/dim]")
            continue

        any_issue = True
        console.print(f"\n  [yellow]⚠[/yellow]  [bold]{domain_name}/[/bold]"
                      f"  [dim]{ok} ok"
                      + (f", {len(missing)} missing" if missing else "")
                      + (f", {len(stale)} modified since last index" if stale else "")
                      + "[/dim]")

        if missing:
            console.print("    [red]not indexed:[/red]")
            for f in missing[:10]:
                console.print(f"      {f.relative_to(kb_root)}")
            if len(missing) > 10:
                console.print(f"      [dim]… and {len(missing) - 10} more[/dim]")

        if stale:
            console.print("    [yellow]modified since last index:[/yellow]")
            for f in stale[:10]:
                console.print(f"      {f.relative_to(kb_root)}")
            if len(stale) > 10:
                console.print(f"      [dim]… and {len(stale) - 10} more[/dim]")

    console.print()
    if any_issue:
        console.print("  [dim]Re-index: kb-agent-generate[/dim]")
    else:
        console.print("  [dim]Index is current.[/dim]")


def _print_footer(console: Console, sysinfo: dict) -> None:
    """Print the system-info footer below the table."""
    bob = "[green]✓ installed[/green]" if sysinfo["bob_skill"] else "[yellow]✗ not installed[/yellow]"
    console.print()
    console.print(f"  LLM:        [cyan]{sysinfo['provider']}[/cyan]")
    console.print(f"  Embedding:  [cyan]{sysinfo['embed']}[/cyan]")
    console.print(f"  Server:     [cyan]{sysinfo['serve_path']}[/cyan]")
    console.print(f"  Bob skill:  {bob}")
    console.print()
    console.print(
        "  [dim]Re-index: kb-agent-generate  "
        "│  Health check: kb-agent-doctor  "
        "│  Watch: kb-agent-watch[/dim]"
    )


# ── JSON output ────────────────────────────────────────────────────────────────

def _build_json(kb_root: Path, domains: list[dict], sysinfo: dict) -> dict:
    return {
        "kb_root": str(kb_root),
        "domains": [
            {
                "name":        row["name"],
                "files":       row["files"],
                "doc_count":   row["doc_count"],
                "indexed":     row["indexed_str"],
                "age_days":    row["age_days"],
                "status":      row["status_text"],
                "yaml_ok":     row["yaml_ok"],
            }
            for row in domains
        ],
        "llm":      sysinfo["provider"],
        "embed":    sysinfo["embed"],
        "server":   sysinfo["serve_path"],
        "bob_skill": sysinfo["bob_skill"],
    }


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kb-agent-status",
        description="Show per-domain health table and system summary. Read-only.",
    )
    parser.add_argument(
        "--diff",   action="store_true",
        help="Show stale/missing files per domain (compares disk vs ChromaDB index)",
    )
    parser.add_argument(
        "--json",   action="store_true",
        help="Output machine-readable JSON instead of a table",
    )
    parser.add_argument(
        "--plain",  action="store_true",
        help="Disable ANSI colours (useful for CI / log capture)",
    )
    parser.add_argument(
        "--tui",    action="store_true",
        help="Live-refresh the table until Ctrl+C",
    )
    parser.add_argument(
        "--interval", type=int, default=5, metavar="SECS",
        help="Refresh interval for --tui mode (default: 5)",
    )
    args = parser.parse_args()

    from kb_agent_mcp.config import cfg

    # ── Diff mode ─────────────────────────────────────────────────────────────
    if args.diff:
        console = Console(no_color=args.plain)
        console.print()
        print_diff(cfg.kb_root_path, console)
        return

    # ── JSON mode ─────────────────────────────────────────────────────────────
    if args.json:
        kb_root = cfg.kb_root_path
        domains = []
        if kb_root.exists():
            for entry in sorted(kb_root.iterdir()):
                if entry.is_dir() and not cfg.is_ignored(entry.name):
                    domains.append(_domain_row(entry.name, kb_root))
        sysinfo = _system_info()
        print(json.dumps(_build_json(kb_root, domains, sysinfo), indent=2))
        return

    console = Console(no_color=args.plain)

    # ── TUI mode ──────────────────────────────────────────────────────────────
    if args.tui:
        import time
        from rich.live import Live

        try:
            with Live(
                build_table(console),
                console=console,
                refresh_per_second=1,
                screen=False,
            ) as live:
                while True:
                    time.sleep(args.interval)
                    live.update(build_table(console))
        except KeyboardInterrupt:
            pass
        # Print footer once after TUI exits
        _print_footer(console, _system_info())
        return

    # ── Normal (one-shot) mode ────────────────────────────────────────────────
    console.print()
    console.print(build_table(console))
    _print_footer(console, _system_info())
