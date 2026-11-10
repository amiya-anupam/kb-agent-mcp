"""Markdown context store: per-file digests readable with read_file / grep."""
from __future__ import annotations

from pathlib import Path

TABLE_EXTS = frozenset({".xlsx", ".xls", ".csv", ".tsv"})


def digestable(path: str | Path) -> bool:
    """True if a digest can be built for this file type."""
    from kb_agent_mcp.context_store.doc_digest import DOC_EXTS
    return Path(path).suffix.lower() in TABLE_EXTS | DOC_EXTS


def build_digest_for(path: str | Path, root: str | Path | None = None) -> str:
    """Route a file to the table or document digest builder by extension."""
    ext = Path(path).suffix.lower()
    if ext in TABLE_EXTS:
        from kb_agent_mcp.context_store.digest import build_digest
        return build_digest(path, root)
    from kb_agent_mcp.context_store.doc_digest import build_doc_digest
    return build_doc_digest(path, root)
