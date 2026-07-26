"""
kb_agent_mcp/cli/doctor.py — kb-agent-doctor diagnostic command
----------------------------------------------------------------
Runs a self-contained health checklist and prints a pass/fail report.

Checks:
  1. Python version (≥ 3.10)
  2. KB_ROOT set and directory exists
  3. At least one domain folder found under KB_ROOT
  4. domain_config.yaml present per domain
  5. ChromaDB collection non-empty per domain
  6. sentence-transformers model cached
  7. LLM reachable (or passthrough confirmed)
  8. kb-agent-serve on PATH (absolute path shown)
  9. Bob skill installed

Exit code 0 when all checks pass, 1 when any check fails.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from kb_agent_mcp.config import Config  # imported at module level so tests can patch it


# ── ANSI colour helpers ────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

def _pass(label: str, detail: str = "") -> None:
    suffix = f"  {_c('90', detail)}" if detail else ""
    print(_c("32", f"  ✓ {label}") + suffix)

def _fail(label: str, hint: str = "") -> None:
    suffix = f"\n      {_c('33', '→ ' + hint)}" if hint else ""
    print(_c("31", f"  ✗ {label}") + suffix)

def _warn(label: str, hint: str = "") -> None:
    suffix = f"\n      {_c('33', '→ ' + hint)}" if hint else ""
    print(_c("33", f"  ⚠ {label}") + suffix)

def _hdr(label: str) -> None:
    print(_c("1", f"\n{label}"))


# ── Individual checks ──────────────────────────────────────────────────────────

def _check_python() -> bool:
    v = sys.version_info
    if v >= (3, 10):
        _pass(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    _fail(
        f"Python {v.major}.{v.minor}.{v.micro}",
        "Python 3.10+ required. Download from https://python.org/downloads",
    )
    return False


def _check_kb_root(cfg) -> tuple[bool, Path | None]:
    root = cfg.kb_root_path
    if not cfg.kb_root_is_explicit:
        _fail(
            f"KB_ROOT not set (defaulting to {root})",
            'Add KB_ROOT to your MCP host config env block: "env": {"KB_ROOT": "/path/to/KB"}',
        )
        return False, None
    if not root.exists():
        _fail(f"KB_ROOT does not exist: {root}", "Create the directory or update KB_ROOT.")
        return False, None
    if not root.is_dir():
        _fail(f"KB_ROOT is not a directory: {root}", "KB_ROOT must point to a folder.")
        return False, None
    _pass(f"KB_ROOT: {root}")
    return True, root


def _check_domain_folders(root: Path, cfg) -> list[str]:
    try:
        entries = [
            e.name for e in sorted(root.iterdir())
            if e.is_dir() and not cfg.is_ignored(e.name)
        ]
    except Exception as exc:
        _fail(f"Cannot list KB_ROOT: {exc}")
        return []

    if not entries:
        _fail(
            "No domain folders found under KB_ROOT",
            "Create at least one subfolder with documents and run kb-agent-generate.",
        )
        return []

    _pass(f"{len(entries)} domain folder(s): {', '.join(entries[:5])}"
          + (" …" if len(entries) > 5 else ""))
    return entries


def _check_domain_configs(root: Path, domains: list[str]) -> None:
    for name in domains:
        yaml_path = root / name / "domain_config.yaml"
        if yaml_path.exists():
            _pass(f"domain_config.yaml: {name}/")
        else:
            _warn(
                f"domain_config.yaml missing: {name}/",
                "Run kb-agent-generate to create it.",
            )


def _check_chroma_collections(domains: list[str]) -> None:
    """Check ChromaDB collection health for each domain.

    Also detects potential version-mismatch errors (Risk 12): if ChromaDB
    raises a RuntimeError while opening the client, it likely means the DB
    was created by an older version and needs to be rebuilt.
    """
    try:
        from kb_agent_mcp.vector_store import get_or_create_collection, _get_client
    except ImportError:
        _warn("ChromaDB not importable", "pip install kb-agent-mcp")
        return

    # Risk 12 — probe the client first; a RuntimeError almost always means
    # version mismatch (e.g. chromadb upgraded while index was built on older).
    try:
        _get_client()
    except RuntimeError as exc:
        _fail(
            f"ChromaDB client error: {exc}",
            "Version mismatch detected. Delete the .kb_index/ folder and run "
            "kb-agent-generate to rebuild the index from scratch.",
        )
        return
    except Exception:
        pass  # non-RuntimeError errors handled per-collection below

    for name in domains:
        try:
            col = get_or_create_collection(name)
            count = col.count()

            # Risk 11 — stale-index check: read indexed_at metadata if stored
            try:
                meta = col.get(limit=1, include=["metadatas"])
                metas = meta.get("metadatas") or []
                indexed_at_str = None
                for m in metas:
                    if m and "indexed_at" in m:
                        indexed_at_str = m["indexed_at"]
                        break
                if indexed_at_str:
                    import datetime
                    indexed_dt = datetime.datetime.fromisoformat(indexed_at_str)
                    age_days = (datetime.datetime.now(datetime.timezone.utc) - indexed_dt).days
                    if age_days > 7:
                        _warn(
                            f"ChromaDB index: {name}/  ({count} docs, indexed {age_days}d ago)",
                            "Index is older than 7 days. Run kb-agent-generate to refresh.",
                        )
                    else:
                        _pass(f"ChromaDB index: {name}/  ({count} documents, indexed {age_days}d ago)")
                elif count > 0:
                    _pass(f"ChromaDB index: {name}/  ({count} documents)")
                else:
                    _warn(
                        f"ChromaDB index empty: {name}/",
                        "Run kb-agent-generate to build the index.",
                    )
            except Exception:
                # Metadata not available — fall back to count check
                if count > 0:
                    _pass(f"ChromaDB index: {name}/  ({count} documents)")
                else:
                    _warn(
                        f"ChromaDB index empty: {name}/",
                        "Run kb-agent-generate to build the index.",
                    )
        except Exception as exc:
            _fail(f"ChromaDB error for {name}/: {exc}")


def _check_embedding_model() -> bool:
    try:
        from kb_agent_mcp.embeddings import _st_model_is_cached, _ST_MODEL_NAME
        if _st_model_is_cached():
            _pass(f"Embedding model cached: {_ST_MODEL_NAME}")
            return True
        _warn(
            f"Embedding model not cached: {_ST_MODEL_NAME}",
            "Run kb-agent-generate to download it (~80 MB, one-time).",
        )
        return True  # not a hard failure — will auto-download on first use
    except Exception as exc:
        _warn(f"Embedding model check failed: {exc}")
        return True


def _check_llm(cfg) -> bool:
    provider = cfg.KB_LLM_PROVIDER.lower()
    if provider == "passthrough":
        _pass("LLM: passthrough mode (no local LLM required)")
        return True

    try:
        import httpx
        if provider == "ollama":
            r = httpx.get(f"{cfg.KB_LLM_BASE_URL}/api/tags", timeout=5.0)
        else:
            r = httpx.get(cfg.KB_LLM_BASE_URL.rstrip("/"), timeout=5.0)
        if r.status_code < 500:
            _pass(f"LLM reachable: {provider} ({cfg.KB_LLM_BASE_URL})")
            return True
        _fail(
            f"LLM returned HTTP {r.status_code}: {cfg.KB_LLM_BASE_URL}",
            "Check that your LLM server is running.",
        )
        return False
    except Exception as exc:
        _fail(
            f"LLM unreachable ({provider}): {exc}",
            "Start Ollama with `ollama serve` or check your API key / base URL.",
        )
        return False


def _in_venv() -> bool:
    """Return True when running inside a virtual environment."""
    return sys.prefix != sys.base_prefix


def _serve_absolute_path() -> str | None:
    """Return the absolute path to kb-agent-serve, preferring the active venv."""
    # Check active venv bin first (most reliable)
    venv_bin = Path(sys.prefix) / "bin" / "kb-agent-serve"
    if venv_bin.exists():
        return str(venv_bin)
    # Fall back to PATH lookup
    found = shutil.which("kb-agent-serve")
    return found


def _check_serve_path() -> bool:
    in_venv  = _in_venv()
    abs_path = _serve_absolute_path()

    if abs_path:
        _pass(f"kb-agent-serve: {abs_path}")
        if not in_venv:
            _warn(
                "Not running in a virtual environment",
                "Using a venv avoids dependency conflicts.  "
                "Create one: python3 -m venv .venv && source .venv/bin/activate && pip install kb-agent-mcp",
            )
        return True

    _fail(
        "kb-agent-serve not found",
        "Install with: pip install kb-agent-mcp  (preferably inside a venv)",
    )
    return False


def _check_bob_skill() -> bool:
    skill = Path.home() / ".bob" / "skills" / "knowledgebase-agent" / "SKILL.md"
    if skill.exists():
        _pass(f"Bob skill installed: {skill}")
        return True
    _warn(
        "Bob skill not installed",
        "Run kb-agent-generate to install it, or copy agents/SKILL.md manually.",
    )
    return True  # Bob is optional — not a hard failure


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    _hdr("kb-agent-doctor — environment health check")

    cfg = Config()

    failures: list[str] = []

    def _run(label: str, fn) -> None:
        result = fn()
        if result is False:
            failures.append(label)

    _hdr("① Python")
    _run("python", _check_python)

    _hdr("② KB_ROOT")
    ok, root = _check_kb_root(cfg)
    if not ok:
        failures.append("KB_ROOT")
        root = None

    domains: list[str] = []
    if root is not None:
        _hdr("③ Domain folders")
        domains = _check_domain_folders(root, cfg)
        if not domains:
            failures.append("domain folders")

        _hdr("④ domain_config.yaml")
        _check_domain_configs(root, domains)

        _hdr("⑤ ChromaDB indexes")
        _check_chroma_collections(domains)

    _hdr("⑥ Embedding model")
    _run("embedding model", _check_embedding_model)

    _hdr("⑦ LLM")
    _run("llm", lambda: _check_llm(cfg))

    _hdr("⑧ kb-agent-serve")
    _run("serve path", _check_serve_path)

    _hdr("⑨ Bob skill")
    _run("bob skill", _check_bob_skill)

    print()
    if failures:
        print(_c("31;1", f"✗ {len(failures)} check(s) failed: {', '.join(failures)}"))
        print(_c("33", "  Fix the items marked ✗ above, then re-run kb-agent-doctor."))
        sys.exit(1)
    else:
        print(_c("32;1", "✓ All checks passed — kb-agent-mcp is healthy."))
        sys.exit(0)


if __name__ == "__main__":
    main()
