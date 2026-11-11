"""Build and refresh the context store for a knowledge base.

`sync(kb_root)` walks every domain folder and brings `<kb_root>/.kb_index/context/`
in line with it:

  * a digest is rebuilt only when its source file changed (size, then sha256,
    compared with the digest's front-matter);
  * digests whose source file is gone are deleted;
  * INDEX.md and MANIFEST.md are rewritten if anything changed.

Digest building is deterministic and needs no LLM, MCP server or Ollama.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from kb_agent_mcp.context_store import build_digest_for, digestable
from kb_agent_mcp.context_store.digest import sha256_of
from kb_agent_mcp.context_store.index import build_indexes, read_front_matter, write_if_changed
from kb_agent_mcp.context_store.paths import (
    INDEX_NAME, MANIFEST_NAME, context_dir, digest_path, domain_slug,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    built: list[str] = field(default_factory=list)       # source paths, relative to kb_root
    unchanged: int = 0
    removed: list[str] = field(default_factory=list)     # digest paths, relative to the context dir
    failed: dict[str, str] = field(default_factory=dict)  # source path -> error
    indexes_changed: int = 0
    seconds: float = 0.0

    @property
    def changed(self) -> bool:
        return bool(self.built or self.removed or self.indexes_changed)

    def summary(self) -> str:
        return (f"{len(self.built)} built, {self.unchanged} unchanged, {len(self.removed)} removed, "
                f"{len(self.failed)} failed in {self.seconds:.1f}s")


def _domain_folders(kb_root: Path, only: Iterable[str] | None) -> list[Path]:
    from kb_agent_mcp.config import cfg
    wanted = set(only) if only is not None else None
    out = []
    for p in sorted(kb_root.iterdir(), key=lambda q: q.name):
        if not p.is_dir() or cfg.is_ignored(p.name):
            continue
        if wanted is None or p.name in wanted:
            out.append(p)
    return out


def _source_files(folder: Path) -> list[Path]:
    from kb_agent_mcp.file_parser import INCLUDE_EXTS, should_skip
    return sorted(
        (f for f in folder.rglob("*")
         if f.is_file() and f.suffix.lower() in INCLUDE_EXTS and not should_skip(f)),
        key=lambda f: str(f).casefold(),
    )


def is_current(source: Path, digest: Path) -> bool:
    """True if `digest` exists and was built from the current content of `source`.

    Same size and a digest newer than the source is accepted without hashing, so a
    resync of an unchanged multi-hundred-MB workbook costs two stat() calls. Otherwise
    the sha256 decides (a touched-but-identical file is still current).
    """
    if not digest.is_file():
        return False
    fm = read_front_matter(digest)
    st = source.stat()
    if fm.get("size_bytes") != str(st.st_size):
        return False
    if digest.stat().st_mtime >= st.st_mtime:
        return True
    return fm.get("sha256") == sha256_of(source)


def sync(kb_root: str | Path | None = None, domains: Iterable[str] | None = None,
         force: bool = False, ctx: Path | None = None,
         progress: Callable[[str], None] | None = None) -> SyncResult:
    """Bring the context store up to date. `domains` limits the work to those folder names."""
    if kb_root is None:
        from kb_agent_mcp.config import cfg
        root = cfg.kb_root_path
    else:
        root = Path(kb_root).expanduser().resolve()
    ctx = ctx or context_dir(root)
    started = time.monotonic()
    res = SyncResult()
    say = progress or (lambda _m: None)

    for folder in _domain_folders(root, domains):
        slug = domain_slug(folder.name)
        expected: set[Path] = set()
        for src in _source_files(folder):
            if not digestable(src):
                continue
            dp = digest_path(ctx, root, src)
            expected.add(dp)
            rel = str(src.relative_to(root))
            try:
                if not force and is_current(src, dp):
                    res.unchanged += 1
                    continue
                say(f"digest {rel}")
                text = build_digest_for(src, root)
                dp.parent.mkdir(parents=True, exist_ok=True)
                write_if_changed(dp, text)
                res.built.append(rel)
            except Exception as exc:                 # one bad file must not stop the run
                logger.warning("digest failed for %s: %s", rel, exc)
                res.failed[rel] = f"{type(exc).__name__}: {exc}"
        _remove_orphans(ctx / slug, expected, ctx, res)

    # A domain folder deleted from the knowledge base: drop its digests too.
    if domains is None:
        live = {domain_slug(p.name) for p in _domain_folders(root, None)}
        if ctx.is_dir():
            for d in sorted(p for p in ctx.iterdir() if p.is_dir() and p.name not in live):
                _remove_orphans(d, set(), ctx, res)

    nd = _not_digested(root)
    res.indexes_changed = len(build_indexes(ctx, nd))
    _remove_empty_dirs(ctx)
    res.seconds = time.monotonic() - started
    return res


def safe_sync(kb_root: str | Path | None = None, domains: Iterable[str] | None = None,
              force: bool = False, log: Callable[[str], None] | None = None) -> SyncResult | None:
    """`sync()` for background hooks: never raises, so indexing and the watcher are never broken by it."""
    say = log or (lambda _m: None)
    try:
        res = sync(kb_root, domains=domains, force=force)
    except Exception as exc:
        logger.warning("context store sync failed: %s", exc)
        say(f"context store sync failed: {type(exc).__name__}: {exc}")
        return None
    if res.changed:
        say(f"context store: {res.summary()}")
    return res


def digest_text_for(source: str | Path, kb_root: str | Path | None = None) -> str | None:
    """Text of the current digest of `source`, building (and storing) it if missing or stale.

    Returns None when the file is not digestable, lies outside a domain folder, or the
    digest cannot be built; never raises, so vector indexing can fall back to raw text.
    """
    try:
        if kb_root is None:
            from kb_agent_mcp.config import cfg
            root = cfg.kb_root_path
        else:
            root = Path(kb_root).expanduser().resolve()
        src = Path(source)
        if not digestable(src):
            return None
        dp = digest_path(context_dir(root), root, src)
        if not is_current(src, dp):
            dp.parent.mkdir(parents=True, exist_ok=True)
            write_if_changed(dp, build_digest_for(src, root))
        return dp.read_text(encoding="utf-8")
    except Exception as exc:
        logger.debug("no digest text for %s: %s", source, exc)
        return None


def _remove_orphans(domain_dir: Path, expected: set[Path], ctx: Path, res: SyncResult) -> None:
    if not domain_dir.is_dir():
        return
    for p in sorted(domain_dir.rglob("*.md")):
        if p.name == INDEX_NAME or p in expected:
            continue
        if not read_front_matter(p).get("path"):     # hand-written file: never delete
            continue
        p.unlink()
        res.removed.append(str(p.relative_to(ctx)))


def _remove_empty_dirs(ctx: Path) -> None:
    if not ctx.is_dir():
        return
    for d in sorted((q for q in ctx.rglob("*") if q.is_dir()), reverse=True):
        try:
            d.rmdir()                                # only succeeds when empty
        except OSError:
            pass


def _not_digested(root: Path) -> dict[str, Counter]:
    """Counts of indexable files that have no digest (images etc.), by domain slug."""
    out: dict[str, Counter] = {}
    for folder in _domain_folders(root, None):
        c = Counter(f.suffix.lower() for f in _source_files(folder) if not digestable(f))
        if c:
            out[domain_slug(folder.name)] = c
    return out


def read_context(kind: str, ctx: Path | None = None, domain: str = "", path: str = "") -> str:
    """Return MANIFEST.md, a domain/folder INDEX.md, or one file's digest as text.

    kind: "manifest" | "index" | "digest". For "index", `domain` is a domain name
    and `path` an optional sub-folder. For "digest", `path` is the source file path
    relative to the knowledge base root (e.g. "BizOps/Revenue/a.xlsx").
    """
    ctx = ctx or context_dir()
    if kind == "manifest":
        target = ctx / MANIFEST_NAME
    elif kind == "index":
        if not domain:
            raise ValueError("domain is required for kind='index'")
        target = ctx / domain_slug(domain) / path.strip("/") / INDEX_NAME
    elif kind == "digest":
        parts = Path(path).parts
        if len(parts) < 2:
            raise ValueError("path must be '<domain>/<file path>' for kind='digest'")
        target = ctx / domain_slug(parts[0]) / Path(*parts[1:]).parent / (parts[-1] + ".md")
    else:
        raise ValueError("kind must be 'manifest', 'index' or 'digest'")
    resolved = target.resolve()
    if ctx.resolve() not in resolved.parents:
        raise ValueError("path escapes the context store")
    if not resolved.is_file():
        raise FileNotFoundError(f"no {kind} found; run `kb context build` first")
    return resolved.read_text(encoding="utf-8")
