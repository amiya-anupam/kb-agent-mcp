"""Where digests live and how a source file maps to its digest.

Layout, under `<KB_ROOT>/.kb_index/context/`:

    MANIFEST.md                         one line per domain
    <domain-slug>/INDEX.md              folders and files of the domain
    <domain-slug>/<sub>/INDEX.md        one INDEX.md per folder
    <domain-slug>/<sub>/<file>.<ext>.md the digest of `<domain>/<sub>/<file>.<ext>`

The digest name keeps the source extension, so `a.xlsx` and `a.csv` never collide.
"""
from __future__ import annotations

import re
from pathlib import Path

INDEX_NAME = "INDEX.md"
MANIFEST_NAME = "MANIFEST.md"


def context_dir(kb_root: str | Path | None = None) -> Path:
    """The context store directory for a knowledge base (default: the configured one)."""
    if kb_root is None:
        from kb_agent_mcp.config import cfg
        return cfg.kb_index_path / "context"
    return Path(kb_root).expanduser().resolve() / ".kb_index" / "context"


def domain_slug(domain: str) -> str:
    """Folder name of a domain inside the context store ("ACE Docs" -> "ace_docs")."""
    slug = re.sub(r"[^a-z0-9_-]", "_", domain.lower()).strip("_-")
    return slug or "domain"


def digest_path(ctx: Path, kb_root: Path, source: Path) -> Path:
    """Digest location for `source`, which must be inside a domain folder of `kb_root`."""
    rel = source.resolve().relative_to(kb_root.resolve())
    if len(rel.parts) < 2:
        raise ValueError(f"not inside a domain folder: {source}")
    sub = Path(*rel.parts[1:])
    return ctx / domain_slug(rel.parts[0]) / sub.parent / (sub.name + ".md")
