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
   6. Embedding model mismatch (index-time model vs current KB_EMBED_MODEL)
   7. sentence-transformers model cached
   8. LLM reachable (or passthrough confirmed)
   9. kb-agent-serve on PATH (absolute path shown)
  10. Bob skill installed

Exit code 0 when all checks pass, 1 when any check fails.

With --fix: attempts to auto-repair fixable failures, then re-runs all checks.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, NamedTuple

from kb_agent_mcp.config import Config  # imported at module level so tests can patch it

logger = logging.getLogger(__name__)

# Stale-index threshold in days — shared with status.py
STALE_DAYS = 7


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

def _fixing(label: str) -> None:
    print(_c("36", f"  → fixing: {label}"))

def _fixed(label: str) -> None:
    print(_c("32", f"  ✓ fixed: {label}"))

def _unfixable(label: str, manual: str = "") -> None:
    suffix = f"\n      {_c('33', '→ Manual: ' + manual)}" if manual else ""
    print(_c("33", f"  ⚠ cannot auto-fix: {label}") + suffix)


# ── Fix result type ────────────────────────────────────────────────────────────

class CheckResult(NamedTuple):
    label:   str
    passed:  bool
    fix_fn:  Callable[[], bool] | None  # None = no auto-fix available


# ── Individual checks ──────────────────────────────────────────────────────────

def _check_python() -> CheckResult:
    v = sys.version_info
    if v >= (3, 10):
        _pass(f"Python {v.major}.{v.minor}.{v.micro}")
        return CheckResult("python", True, None)
    _fail(
        f"Python {v.major}.{v.minor}.{v.micro}",
        "Python 3.10+ required. Download from https://python.org/downloads",
    )
    return CheckResult("python", False, None)


def _check_kb_root(cfg) -> tuple[CheckResult, Path | None]:
    root = cfg.kb_root_path
    if not cfg.kb_root_is_explicit:
        _fail(
            f"KB_ROOT not set (defaulting to {root})",
            'Add KB_ROOT to your MCP host config env block: "env": {"KB_ROOT": "/path/to/KB"}',
        )
        return CheckResult("KB_ROOT", False, None), None

    if not root.exists():
        def _fix_kb_root() -> bool:
            try:
                root.mkdir(parents=True, exist_ok=True)
                _fixed(f"created directory {root}")
                return True
            except Exception as exc:
                print(_c("31", f"  ✗ could not create {root}: {exc}"))
                return False

        _fail(f"KB_ROOT does not exist: {root}", "Create the directory or update KB_ROOT.")
        return CheckResult("KB_ROOT", False, _fix_kb_root), None

    if not root.is_dir():
        _fail(f"KB_ROOT is not a directory: {root}", "KB_ROOT must point to a folder.")
        return CheckResult("KB_ROOT", False, None), None

    _pass(f"KB_ROOT: {root}")
    return CheckResult("KB_ROOT", True, None), root


def _check_domain_folders(root: Path, cfg) -> tuple[CheckResult, list[str]]:
    try:
        entries = [
            e.name for e in sorted(root.iterdir())
            if e.is_dir() and not cfg.is_ignored(e.name)
        ]
    except Exception as exc:
        _fail(f"Cannot list KB_ROOT: {exc}")
        return CheckResult("domain folders", False, None), []

    if not entries:
        _fail(
            "No domain folders found under KB_ROOT",
            "Create at least one subfolder with documents and run kb-agent-generate.",
        )
        return CheckResult("domain folders", False, None), []

    _pass(f"{len(entries)} domain folder(s): {', '.join(entries[:5])}"
          + (" …" if len(entries) > 5 else ""))
    return CheckResult("domain folders", True, None), entries


def _check_domain_configs(root: Path, domains: list[str]) -> list[CheckResult]:
    results = []
    for name in domains:
        yaml_path = root / name / "domain_config.yaml"
        if yaml_path.exists():
            _pass(f"domain_config.yaml: {name}/")
            results.append(CheckResult(f"domain_config:{name}", True, None))
        else:
            def _fix_yaml(n: str = name) -> bool:
                _fixing(f"running kb-agent-generate --domain {n}")
                rc = subprocess.run(
                    [sys.executable, "-m", "kb_agent_mcp.cli.generate",
                     "--domain", n, "--no-llm", "--yes"],
                ).returncode
                if rc == 0:
                    _fixed(f"domain_config.yaml generated for {n}/")
                    return True
                print(_c("31", f"  ✗ kb-agent-generate --domain {n} failed"))
                return False

            _warn(
                f"domain_config.yaml missing: {name}/",
                "Run kb-agent-generate to create it.",
            )
            results.append(CheckResult(f"domain_config:{name}", False, _fix_yaml))
    return results


def _check_chroma_collections(domains: list[str]) -> list[CheckResult]:
    """Check ChromaDB collection health for each domain."""
    try:
        from kb_agent_mcp.vector_store import get_or_create_collection, _get_client
    except ImportError:
        _warn("ChromaDB not importable", "pip install kb-agent-mcp")
        return [CheckResult("chromadb_import", False, None)]

    # Probe client first — RuntimeError means version mismatch
    try:
        _get_client()
    except RuntimeError as exc:
        from kb_agent_mcp.config import cfg as _cfg
        index_path = _cfg.kb_index_path / "chroma"

        def _fix_chroma_mismatch() -> bool:
            _fixing(f"deleting incompatible ChromaDB index at {index_path}")
            try:
                ans = input(
                    f"  About to delete {index_path} — continue? [Y/n]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                ans = "n"
            if ans not in ("", "y", "yes"):
                print(_c("33", "  ⚠ skipped — delete manually and re-run kb-agent-generate"))
                return False
            import shutil as _shutil
            try:
                _shutil.rmtree(str(index_path))
                _fixed("deleted incompatible ChromaDB index")
            except Exception as del_exc:
                print(_c("31", f"  ✗ could not delete {index_path}: {del_exc}"))
                return False
            # Rebuild
            _fixing("running kb-agent-generate to rebuild indexes")
            rc = subprocess.run(
                [sys.executable, "-m", "kb_agent_mcp.cli.generate", "--no-llm", "--yes"],
            ).returncode
            if rc == 0:
                _fixed("indexes rebuilt successfully")
                return True
            print(_c("31", "  ✗ kb-agent-generate failed — run manually to diagnose"))
            return False

        _fail(
            f"ChromaDB client error: {exc}",
            "Version mismatch detected. Use --fix to auto-rebuild, or delete "
            f".kb_index/chroma/ and run kb-agent-generate.",
        )
        return [CheckResult("chromadb_mismatch", False, _fix_chroma_mismatch)]

    except Exception as exc:
        logger.warning("ChromaDB client check raised unexpected error (%s); continuing per-collection", exc)

    results = []
    for name in domains:
        try:
            col = get_or_create_collection(name)
            count = col.count()

            # Stale-index check
            try:
                import datetime
                meta = col.get(limit=1, include=["metadatas"])
                metas = meta.get("metadatas") or []
                indexed_at_str = None
                for m in metas:
                    if m:
                        # prefer indexed_at_iso; fall back to float→ISO for old indexes
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
                    age_days = (datetime.datetime.now(datetime.timezone.utc) - indexed_dt).days
                    if age_days > STALE_DAYS:
                        _warn(
                            f"ChromaDB index: {name}/  ({count} docs, indexed {age_days}d ago)",
                            "Index is older than 7 days. Run kb-agent-generate to refresh.",
                        )
                    else:
                        _pass(f"ChromaDB index: {name}/  ({count} documents, indexed {age_days}d ago)")
                elif count > 0:
                    _pass(f"ChromaDB index: {name}/  ({count} documents)")
                else:
                    def _fix_empty(n: str = name) -> bool:
                        _fixing(f"running kb-agent-generate --domain {n}")
                        rc = subprocess.run(
                            [sys.executable, "-m", "kb_agent_mcp.cli.generate",
                             "--domain", n, "--no-llm", "--yes"],
                        ).returncode
                        if rc == 0:
                            _fixed(f"index built for {n}/")
                            return True
                        print(_c("31", f"  ✗ kb-agent-generate --domain {n} failed"))
                        return False

                    _warn(
                        f"ChromaDB index empty: {name}/",
                        "Run kb-agent-generate to build the index.",
                    )
                    results.append(CheckResult(f"chroma_empty:{name}", False, _fix_empty))
                    continue
            except Exception as exc:
                logger.debug("indexed_at metadata parse failed for collection %r (%s)", name, exc)
                if count > 0:
                    _pass(f"ChromaDB index: {name}/  ({count} documents)")
                else:
                    _warn(f"ChromaDB index empty: {name}/", "Run kb-agent-generate.")
                    results.append(CheckResult(f"chroma_empty:{name}", False, None))
                    continue

            results.append(CheckResult(f"chroma:{name}", True, None))
        except Exception as exc:
            _fail(f"ChromaDB error for {name}/: {exc}")
            results.append(CheckResult(f"chroma:{name}", False, None))

    return results


def _check_embed_model_mismatch(domains: list[str]) -> list[CheckResult]:
    """
    Check ⑥ — verify that each indexed domain was built with the same
    embedding model that is currently configured.

    Strategy:
      • Read the ``embed_model`` key stamped into each ChromaDB collection's
        metadata by build_collection() since this fix was applied.
      • Compare it to embeddings.effective_model_name() (the current config).
      • Warn (not hard-fail) for domains whose stamp is absent — those were
        indexed before this feature was added and simply need a re-index.
      • Hard-fail (not warn) for domains with a *different* stamp — a mismatch
        is an active retrieval quality issue that the user must resolve.

    Auto-fix: runs kb-agent-generate --domain <name> for mismatched domains.
    """
    try:
        from kb_agent_mcp.vector_store import get_domain_metadata
        from kb_agent_mcp.embeddings import effective_model_name
    except ImportError:
        # Already caught by the ChromaDB import check above — skip silently
        return []

    current_model = effective_model_name()
    results: list[CheckResult] = []

    for name in domains:
        meta = get_domain_metadata(name) or {}
        stored = meta.get("embed_model", "")

        if not stored:
            # Domain was indexed before this feature — not a hard failure,
            # but prompt the user to re-index to populate the stamp.
            _warn(
                f"Embed model unknown for {name}/  (indexed before model tracking)",
                "Run kb-agent-generate to re-index and record the model stamp.",
            )
            results.append(CheckResult(f"embed_model_stamp:{name}", True, None))
            continue

        if stored == current_model:
            _pass(f"Embed model match: {name}/  ({stored})")
            results.append(CheckResult(f"embed_model_match:{name}", True, None))
        else:
            def _fix_mismatch(n: str = name) -> bool:
                _fixing(f"re-indexing {n}/ with current model ({current_model})")
                rc = subprocess.run(
                    [sys.executable, "-m", "kb_agent_mcp.cli.generate",
                     "--domain", n, "--no-llm", "--yes"],
                ).returncode
                if rc == 0:
                    _fixed(f"{n}/ re-indexed with {current_model}")
                    return True
                print(_c("31", f"  ✗ kb-agent-generate --domain {n} failed"))
                return False

            _fail(
                f"Embed model mismatch: {name}/",
                f"Indexed with '{stored}' but current model is '{current_model}'. "
                "Retrieval quality is degraded. Run kb-agent-generate --domain "
                f"{name}  (or --fix) to rebuild.",
            )
            results.append(CheckResult(f"embed_model_mismatch:{name}", False, _fix_mismatch))

    return results


def _check_embedding_model() -> CheckResult:
    try:
        from kb_agent_mcp.embeddings import _st_model_is_cached, _ST_MODEL_NAME
        if _st_model_is_cached():
            _pass(f"Embedding model cached: {_ST_MODEL_NAME}")
            return CheckResult("embedding_model", True, None)

        def _fix_embed() -> bool:
            _fixing("downloading embedding model (one-time, ~80 MB)")
            try:
                from kb_agent_mcp.embeddings import _ensure_embedding_model
                _ensure_embedding_model()
                _fixed("embedding model downloaded and cached")
                return True
            except Exception as exc:
                print(_c("31", f"  ✗ download failed: {exc}"))
                return False

        _warn(
            f"Embedding model not cached: {_ST_MODEL_NAME}",
            "Run kb-agent-generate to download it (~80 MB, one-time).",
        )
        return CheckResult("embedding_model", False, _fix_embed)
    except Exception as exc:
        _warn(f"Embedding model check failed: {exc}")
        return CheckResult("embedding_model", True, None)  # not a hard failure


def _check_llm(cfg) -> CheckResult:
    provider = cfg.KB_LLM_PROVIDER.lower()
    if provider == "passthrough":
        _pass("LLM: passthrough mode (no local LLM required)")
        return CheckResult("llm", True, None)

    try:
        import httpx
        if provider == "ollama":
            r = httpx.get(f"{cfg.KB_LLM_BASE_URL}/api/tags", timeout=5.0)
        else:
            r = httpx.get(cfg.KB_LLM_BASE_URL.rstrip("/"), timeout=5.0)
        if r.status_code < 500:
            _pass(f"LLM reachable: {provider} ({cfg.KB_LLM_BASE_URL})")
            return CheckResult("llm", True, None)
        _fail(
            f"LLM returned HTTP {r.status_code}: {cfg.KB_LLM_BASE_URL}",
            "Check that your LLM server is running.",
        )
    except Exception as exc:
        _fail(
            f"LLM unreachable ({provider}): {exc}",
            "Start Ollama with `ollama serve` or check your API key / base URL.",
        )
    return CheckResult("llm", False, None)  # cannot auto-fix a missing server


def _in_venv() -> bool:
    return sys.prefix != sys.base_prefix


def _serve_absolute_path() -> str | None:
    venv_bin = Path(sys.prefix) / "bin" / "kb-agent-serve"
    if venv_bin.exists():
        return str(venv_bin)
    return shutil.which("kb-agent-serve")


def _check_serve_path() -> CheckResult:
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
        return CheckResult("serve_path", True, None)

    _fail(
        "kb-agent-serve not found",
        "Install with: pip install kb-agent-mcp  (preferably inside a venv)",
    )
    return CheckResult("serve_path", False, None)  # cannot auto-fix a missing package


def _check_bob_skill() -> CheckResult:
    skill = Path.home() / ".bob" / "skills" / "knowledgebase-agent" / "SKILL.md"
    if skill.exists():
        _pass(f"Bob skill installed: {skill}")
        return CheckResult("bob_skill", True, None)

    def _fix_bob_skill() -> bool:
        _fixing("running kb-agent-generate to install Bob skill")
        rc = subprocess.run(
            [sys.executable, "-m", "kb_agent_mcp.cli.generate", "--no-llm", "--yes"],
        ).returncode
        if rc == 0:
            _fixed("Bob skill installed")
            return True
        print(_c("31", "  ✗ kb-agent-generate failed"))
        return False

    _warn(
        "Bob skill not installed",
        "Run kb-agent-generate to install it.",
    )
    return CheckResult("bob_skill", False, _fix_bob_skill)


# ── Fix runner ─────────────────────────────────────────────────────────────────

def _run_fixes(failures: list[CheckResult]) -> list[str]:
    """Attempt auto-fixes for all failed checks that have a fix_fn.

    Returns the list of labels that could not be fixed (either no fix_fn or
    the fix_fn returned False).
    """
    unfixed: list[str] = []
    for result in failures:
        if result.fix_fn is None:
            _unfixable(result.label, "see hint above")
            unfixed.append(result.label)
        else:
            ok = result.fix_fn()
            if not ok:
                unfixed.append(result.label)
    return unfixed


# ── Doctor runner ──────────────────────────────────────────────────────────────

def run_doctor(fix: bool = False) -> int:
    """Run all checks. If fix=True, attempt auto-repairs on failures then re-run.

    Returns exit code: 0 = all pass, 1 = failures remain.
    """
    cfg = Config()

    def _collect() -> list[CheckResult]:
        """Run all checks and collect results."""
        results: list[CheckResult] = []

        _hdr("① Python")
        results.append(_check_python())

        _hdr("② KB_ROOT")
        kb_root_result, root = _check_kb_root(cfg)
        results.append(kb_root_result)

        domains: list[str] = []
        if root is not None:
            _hdr("③ Domain folders")
            df_result, domains = _check_domain_folders(root, cfg)
            results.append(df_result)

            if domains:
                _hdr("④ domain_config.yaml")
                results.extend(_check_domain_configs(root, domains))

                _hdr("⑤ ChromaDB indexes")
                results.extend(_check_chroma_collections(domains))

                _hdr("⑥ Embedding model mismatch")
                results.extend(_check_embed_model_mismatch(domains))

        _hdr("⑦ Embedding model")
        results.append(_check_embedding_model())

        _hdr("⑧ LLM")
        results.append(_check_llm(cfg))

        _hdr("⑨ kb-agent-serve")
        results.append(_check_serve_path())

        _hdr("⑩ Bob skill")
        results.append(_check_bob_skill())

        return results

    # ── First pass ────────────────────────────────────────────────────────────
    results = _collect()
    failures = [r for r in results if not r.passed]

    if not failures:
        print()
        print(_c("32;1", "✓ All checks passed — kb-agent-mcp is healthy."))
        return 0

    print()
    print(_c("31;1", f"✗ {len(failures)} check(s) failed: {', '.join(r.label for r in failures)}"))

    if not fix:
        print(_c("33", "  Fix the items marked ✗ above, then re-run kb-agent-doctor."))
        print(_c("33", "  Tip: kb-agent-doctor --fix  attempts automatic repairs."))
        return 1

    # ── Fix pass ──────────────────────────────────────────────────────────────
    print()
    print(_c("1;36", "── Attempting auto-fixes ────────────────────────────────"))
    _run_fixes(failures)

    # ── Re-check ──────────────────────────────────────────────────────────────
    print()
    print(_c("1;36", "── Re-running checks after fixes ────────────────────────"))
    results2  = _collect()
    failures2 = [r for r in results2 if not r.passed]

    print()
    if not failures2:
        print(_c("32;1", "✓ All checks now pass — kb-agent-mcp is healthy."))
        return 0

    print(_c("31;1", f"✗ {len(failures2)} check(s) still failing: "
             f"{', '.join(r.label for r in failures2)}"))
    print(_c("33", "  Manual action required for the remaining items."))
    return 1


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kb-agent-doctor",
        description="Run a health checklist for kb-agent-mcp.",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Attempt to auto-repair fixable failures, then re-run all checks",
    )
    args = parser.parse_args()
    sys.exit(run_doctor(fix=args.fix))


