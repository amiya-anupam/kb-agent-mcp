"""Generate the INDEX.md files and MANIFEST.md of the context store.

Everything here is derived from the digests already on disk (their front-matter),
so the output is deterministic and needs no LLM, MCP server or source parsing.

    MANIFEST.md             one line per domain: counts, types, freshness, keywords
    <domain>/INDEX.md       the domain's top folder: sub-folders and files
    <domain>/<sub>/INDEX.md the same for each sub-folder

Each INDEX.md stays within about 3 KB: when a folder has too many files the lines
are shortened step by step, and as a last resort the list is cut with a note.
"""
from __future__ import annotations

import datetime as _dt
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from kb_agent_mcp.context_store.frontmatter import parse_front_matter
from kb_agent_mcp.context_store.paths import INDEX_NAME, MANIFEST_NAME

INDEX_BUDGET = 3000        # bytes for one INDEX.md
MANIFEST_BUDGET = 8000     # bytes for MANIFEST.md
_FM_READ_BYTES = 16384
_COUNT_KEYS = ("rows", "slides", "pages", "sections")
_CONVENTION = "A file's digest is `<file name>.md` in the same folder of the context store."


@dataclass
class Entry:
    name: str                 # source file name, e.g. "Q226.xlsx"
    digest: str               # digest file name, e.g. "Q226.xlsx.md"
    fm: dict[str, object]
    mtime: float = 0.0


@dataclass
class Folder:
    parts: tuple[str, ...]                       # path below the domain, () for the top
    files: list[Entry] = field(default_factory=list)
    folders: dict[str, "Folder"] = field(default_factory=dict)

    def all_entries(self):
        yield from self.files
        for f in self.folders.values():
            yield from f.all_entries()


def read_front_matter(path: Path) -> dict[str, object]:
    """Front-matter of a digest, reading only the head of the file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return parse_front_matter(f.read(_FM_READ_BYTES))
    except OSError:
        return {}


def _scan(domain_dir: Path) -> Folder:
    top = Folder(())
    for dirpath, dirnames, filenames in os.walk(domain_dir):
        dirnames.sort()
        rel = Path(dirpath).relative_to(domain_dir).parts
        node = top
        for part in rel:
            node = node.folders.setdefault(part, Folder(node.parts + (part,)))
        for fn in sorted(filenames, key=str.casefold):
            if fn == INDEX_NAME or not fn.endswith(".md"):
                continue
            p = Path(dirpath) / fn
            fm = read_front_matter(p)
            if not fm.get("path"):
                continue                      # not a digest
            node.files.append(Entry(fn[:-3], fn, fm, p.stat().st_mtime))
    _drop_empty(top)
    return top


def _drop_empty(node: Folder) -> bool:
    """Remove sub-folders that hold no digests; True if `node` itself is empty."""
    for name in [n for n, sub in node.folders.items() if _drop_empty(sub)]:
        del node.folders[name]
    return not node.files and not node.folders


# ── formatting ────────────────────────────────────────────────────────────────

def _count_text(fm: dict[str, object]) -> str:
    for key in _COUNT_KEYS:
        v = fm.get(key)
        if isinstance(v, str) and v.isdigit():
            return f"{int(v):,} {key if v != '1' else key.rstrip('s')}"
    return ""


def _descriptor(fm: dict[str, object], keywords: int) -> str:
    bits = [str(fm.get("type", "")), _count_text(fm)]
    period = fm.get("period")
    if isinstance(period, str) and period:
        bits.append(period)
    if fm.get("extraction") == "empty":
        bits.append("no text extracted")
    if fm.get("partial") == "true":
        bits.append("partial")
    text = ", ".join(b for b in bits if b)
    kws = fm.get("keywords")
    if keywords and isinstance(kws, list) and kws:
        text += "; " + ", ".join(str(k) for k in kws[:keywords])
    return text


def _file_line(e: Entry, level: int) -> str:
    if level >= 3:
        return f"- {e.name}"
    if level == 2:
        return f"- {e.name} ({e.fm.get('type', '')})"
    desc = _descriptor(e.fm, 3 if level == 0 else 0)
    return f"- [{e.name}]({quote(e.digest)}) — {desc}"


def _type_counts(entries) -> str:
    c = Counter(str(e.fm.get("type", "?")) for e in entries)
    return ", ".join(f"{n} {t}" for t, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


def _render_folder(domain: str, node: Folder, not_digested: Counter | None, level: int,
                   limit: int | None) -> str:
    title = " / ".join((domain,) + node.parts)
    here = len(node.files)
    below = sum(1 for _ in node.all_entries()) - here
    lines = [
        "---",
        f"domain: {domain}",
        f"folder: {'/'.join(node.parts)}",
        f"files: {here + below}",
        "---",
        "",
        f"# {title}",
        "",
        f"{here + below} digested files ({here} here, {below} in sub-folders). {_CONVENTION}",
        "Open a digest with read_file; open the original file only for exact values.",
        "",
    ]
    if node.folders:
        lines += ["## Folders", ""]
        for name, sub in sorted(node.folders.items(), key=lambda kv: kv[0].casefold()):
            entries = list(sub.all_entries())
            lines.append(f"- [{name}/]({quote(name)}/{INDEX_NAME}) — {len(entries)} files "
                         f"({_type_counts(entries)})")
        lines.append("")
    if node.files:
        lines += ["## Files", ""]
        shown = node.files if limit is None else node.files[:limit]
        lines += [_file_line(e, level) for e in shown]
        if limit is not None and limit < len(node.files):
            lines.append(f"- … and {len(node.files) - limit} more; list the folder to see them")
        lines.append("")
    if not_digested:
        parts = ", ".join(f"{n} {ext}" for ext, n in sorted(not_digested.items()))
        lines += ["## Not digested", "",
                  f"No digest exists for these file types, so read the originals: {parts}.", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_index(domain: str, node: Folder, not_digested: Counter | None = None) -> str:
    """INDEX.md text for one folder, shortened step by step to fit INDEX_BUDGET."""
    for level in (0, 1, 2, 3):
        text = _render_folder(domain, node, not_digested, level, None)
        if len(text.encode("utf-8")) <= INDEX_BUDGET:
            return text
    limit = len(node.files)
    while limit > 0:
        limit = max(0, limit - max(1, limit // 8))
        text = _render_folder(domain, node, not_digested, 3, limit)
        if len(text.encode("utf-8")) <= INDEX_BUDGET:
            break
    return text


# ── writing ───────────────────────────────────────────────────────────────────

def write_if_changed(path: Path, text: str) -> bool:
    """Write text atomically unless the file already has it. Returns True if written."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def _domain_name(node: Folder, fallback: str) -> str:
    for e in node.all_entries():
        first = str(e.fm.get("path", "")).split("/", 1)[0]
        if first:
            return first
    return fallback


def _write_folder_indexes(out_dir: Path, domain: str, node: Folder,
                          not_digested: Counter | None, written: list[Path]) -> set[Path]:
    """Write INDEX.md for node and every sub-folder; return the INDEX paths that should exist."""
    target = out_dir / INDEX_NAME
    wanted = {target}
    if write_if_changed(target, render_index(domain, node, not_digested)):
        written.append(target)
    for name, sub in node.folders.items():
        wanted |= _write_folder_indexes(out_dir / name, domain, sub, None, written)
    return wanted


@dataclass
class DomainStats:
    slug: str
    name: str
    files: int
    types: str
    partial: int
    empty: int
    not_digested: int
    newest: float
    keywords: list[str]


def _stats(slug: str, name: str, top: Folder, nd: Counter | None) -> DomainStats:
    entries = list(top.all_entries())
    kw = Counter(k for e in entries for k in (e.fm.get("keywords") or []) if isinstance(k, str))
    ranked = [k for k, _ in sorted(kw.items(), key=lambda kv: (-kv[1], kv[0].casefold()))]
    return DomainStats(
        slug=slug, name=name, files=len(entries), types=_type_counts(entries),
        partial=sum(1 for e in entries if e.fm.get("partial") == "true"),
        empty=sum(1 for e in entries if e.fm.get("extraction") == "empty"),
        not_digested=sum(nd.values()) if nd else 0,
        newest=max((e.mtime for e in entries), default=0.0), keywords=ranked,
    )


def _manifest_line(s: DomainStats, keywords: int) -> str:
    bits = [f"{s.files} digests ({s.types})"]
    if s.partial:
        bits.append(f"{s.partial} partial")
    if s.empty:
        bits.append(f"{s.empty} unreadable")
    if s.not_digested:
        bits.append(f"{s.not_digested} not digested")
    day = _dt.datetime.fromtimestamp(s.newest, _dt.timezone.utc).strftime("%Y-%m-%d")
    bits.append(f"updated {day}")
    line = f"- **{s.name}** — [{s.slug}/{INDEX_NAME}]({quote(s.slug)}/{INDEX_NAME}) · " + " · ".join(bits)
    if keywords and s.keywords:
        line += " · " + ", ".join(s.keywords[:keywords])
    return line


def render_manifest(stats: list[DomainStats]) -> str:
    for kw in (8, 4, 0):
        lines = [
            "# Knowledge base manifest",
            "",
            f"{len(stats)} domains. Read a domain's INDEX.md to see its files, then a digest "
            "for what a file contains. Digests are summaries built by code; they point to the "
            "original file for exact values.",
            "",
        ] + [_manifest_line(s, kw) for s in stats]
        text = "\n".join(lines) + "\n"
        if len(text.encode("utf-8")) <= MANIFEST_BUDGET:
            break
    return text


def build_indexes(ctx: Path, not_digested: dict[str, Counter] | None = None) -> list[Path]:
    """Rewrite every INDEX.md and MANIFEST.md from the digests in `ctx`.

    not_digested maps a domain slug to counts of source files with no digest, by
    extension. Stale INDEX.md files (folders that no longer hold digests) are
    removed. Returns the files that changed.
    """
    written: list[Path] = []
    stats: list[DomainStats] = []
    if not ctx.is_dir():
        return written
    for d in sorted((p for p in ctx.iterdir() if p.is_dir()), key=lambda p: p.name):
        top = _scan(d)
        if not any(True for _ in top.all_entries()):
            for stale in d.rglob(INDEX_NAME):
                stale.unlink()
            continue
        nd = (not_digested or {}).get(d.name)
        wanted = _write_folder_indexes(d, _domain_name(top, d.name), top, nd, written)
        for p in d.rglob(INDEX_NAME):
            if p not in wanted:
                p.unlink()
        stats.append(_stats(d.name, _domain_name(top, d.name), top, nd))
    if write_if_changed(ctx / MANIFEST_NAME, render_manifest(stats)):
        written.append(ctx / MANIFEST_NAME)
    return written
