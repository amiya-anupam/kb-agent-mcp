"""
kb_agent_mcp/writeback.py
─────────────────────────
Safe write-back of documents into the knowledge base (Feature 1).

All writes are validated to stay within KB_ROOT to prevent path traversal.
After a successful write the affected file is immediately re-indexed into its
domain's vector store so the knowledge base stays current without a full
reindex.

Public API
----------
write_document(rel_path, content, mode)  → WriteResult
    Write *content* to *rel_path* (relative to KB_ROOT).

    mode values
    -----------
    "overwrite"  — Replace the entire file content (default).
    "append"     — Append *content* to the end of the existing file.
    "prepend"    — Insert *content* at the beginning of the file.

WriteResult
-----------
    {
        "ok":          bool,
        "path":        str,    # absolute path written
        "domain":      str,    # domain folder name (or "" if not in a domain)
        "reindexed":   bool,   # True when vector store was updated
        "message":     str,    # human-readable status / error
    }
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import TypedDict

from kb_agent_mcp.config import cfg
from kb_agent_mcp.file_parser import INCLUDE_EXTS, should_skip

logger = logging.getLogger(__name__)


# ── Result type ────────────────────────────────────────────────────────────────

class WriteResult(TypedDict):
    ok:        bool
    path:      str
    domain:    str
    reindexed: bool
    message:   str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resolve_safe(rel_path: str) -> pathlib.Path | None:
    """
    Resolve *rel_path* against KB_ROOT and confirm the result stays inside it.
    Returns None on path traversal attempt.
    """
    kb_root = cfg.kb_root_path.resolve()
    target  = (kb_root / rel_path).resolve()
    try:
        target.relative_to(kb_root)
        return target
    except ValueError:
        return None  # path escapes KB_ROOT


def _domain_for_path(abs_path: pathlib.Path) -> str:
    """Return the domain folder name for *abs_path*, or '' if not in a domain."""
    kb_root = cfg.kb_root_path.resolve()
    try:
        rel = abs_path.relative_to(kb_root)
    except ValueError:
        return ""
    parts = rel.parts
    return parts[0] if parts else ""


# ── Core write logic (sync, called via asyncio.to_thread) ─────────────────────

def _write_sync(
    abs_path: pathlib.Path,
    content: str,
    mode: str,
) -> tuple[bool, str]:
    """
    Write *content* to *abs_path* according to *mode*.
    Returns (success, message).
    """
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if mode == "append":
            existing = abs_path.read_text(encoding="utf-8") if abs_path.exists() else ""
            abs_path.write_text(existing + content, encoding="utf-8")
        elif mode == "prepend":
            existing = abs_path.read_text(encoding="utf-8") if abs_path.exists() else ""
            abs_path.write_text(content + existing, encoding="utf-8")
        else:  # overwrite (default)
            abs_path.write_text(content, encoding="utf-8")
        return True, f"Written ({mode}): {abs_path}"
    except OSError as exc:
        return False, f"Write failed: {exc}"


# ── Public async API ───────────────────────────────────────────────────────────

async def write_document(
    rel_path: str,
    content: str,
    mode: str = "overwrite",
) -> WriteResult:
    """
    Write *content* to *rel_path* (relative to KB_ROOT) and re-index the file.

    Args:
        rel_path: Path relative to KB_ROOT, e.g. "BizOps/notes.md".
                  Parent directories are created if they do not exist.
                  Path traversal (e.g. "../../etc/passwd") is rejected.
        content:  Text content to write.
        mode:     "overwrite" | "append" | "prepend".  Defaults to "overwrite".

    Returns:
        WriteResult dict.
    """
    # ── Validate mode ─────────────────────────────────────────────────────────
    valid_modes = {"overwrite", "append", "prepend"}
    if mode not in valid_modes:
        return WriteResult(
            ok=False, path="", domain="", reindexed=False,
            message=f"Invalid mode '{mode}'. Must be one of: {', '.join(sorted(valid_modes))}",
        )

    # ── Resolve & validate path ───────────────────────────────────────────────
    abs_path = _resolve_safe(rel_path)
    if abs_path is None:
        return WriteResult(
            ok=False, path=rel_path, domain="", reindexed=False,
            message=(
                f"Path traversal rejected: '{rel_path}' resolves outside KB_ROOT. "
                "Use a path relative to your knowledge base folder."
            ),
        )

    domain = _domain_for_path(abs_path)

    # ── Write the file ────────────────────────────────────────────────────────
    ok, msg = await asyncio.to_thread(_write_sync, abs_path, content, mode)
    if not ok:
        return WriteResult(ok=False, path=str(abs_path), domain=domain,
                           reindexed=False, message=msg)

    # ── Re-index when the file extension is indexable ─────────────────────────
    reindexed = False
    if domain and abs_path.suffix.lower() in INCLUDE_EXTS and not should_skip(abs_path):
        try:
            from kb_agent_mcp.vector_store import upsert_file as _upsert
            await _upsert(domain, abs_path)
            reindexed = True

            # Invalidate the server-level stale-index cache so the next ask()
            # sees a fresh stale check rather than a cached (possibly stale) result.
            try:
                from kb_agent_mcp import server as _srv
                _srv._clear_stale_cache()
            except Exception:
                pass  # server module may not be loaded in test context
        except Exception as exc:
            logger.warning("Re-index after write failed for %s: %s", abs_path, exc)
            msg += f" (re-index skipped: {exc})"

    return WriteResult(
        ok=True,
        path=str(abs_path),
        domain=domain,
        reindexed=reindexed,
        message=msg,
    )
