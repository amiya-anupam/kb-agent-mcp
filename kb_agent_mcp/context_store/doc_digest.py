"""
Digest builder for document files (pptx, docx, pdf, boxnote, md).

Same idea as the tabular digest: a small markdown file with front-matter, built
by code from the file itself, so it is deterministic and needs no LLM, MCP
server or Ollama. The content is extractive: headings give the outline and the
keywords, and the first sentence under each heading gives the key points.

Every extractor yields the same simple events, ("heading" | "para", text, level,
loc), so the digest layout is shared. When nothing can be extracted (scanned PDF,
empty or corrupt file) the digest records why instead of repeating the filename.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from kb_agent_mcp.context_store.digest import sha256_of

DOC_EXTS = frozenset({".pptx", ".docx", ".pdf", ".boxnote", ".md"})

_MAX_BYTES = 6000              # hard cap on one document digest
_MAX_FILE_BYTES = 200 * 1024 * 1024
_TIME_BUDGET_S = 30.0
_MAX_UNITS_SCANNED = 300       # slides / pdf pages / outline entries read per file
_MAX_KEYWORDS = 15
_TITLE_CHARS = 90
_POINT_CHARS = 160
_FALLBACK_PARAS = 8

_TYPE_LABEL = {
    "pptx": ("PowerPoint deck", "slides"),
    "docx": ("Word document", "sections"),
    "pdf": ("PDF document", "pages"),
    "boxnote": ("Box Note", "sections"),
    "md": ("Markdown file", "sections"),
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+&'-]{2,}")
_STOP = frozenset("""
the and for with from that this these those into onto over under about your our their
are was were been being has have had not but all any can will would should could may
per via vs etc new one two slide page agenda overview summary notes note contents table
""".split())
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# Page furniture: "Slide 3", "Page 2 of 9", bare page numbers.
_FURNITURE_RE = re.compile(r"^(?:slide|page)\s*\d+(?:\s*(?:of|/)\s*\d+)?$|^\d{1,3}$", re.I)
_MIN_LEAD_WORDS = 4


# ── small text helpers ────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return " ".join(_CTRL_RE.sub(" ", s).split())


def _trim(s: str, n: int) -> str:
    s = _clean(s)
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(",;:-. ") + "…"


def _first_sentence(s: str, n: int) -> str:
    s = _clean(s)
    m = re.match(r"(.+?[.!?])(?:\s|$)", s)
    if m and len(m.group(1)) <= n:
        return m.group(1)
    return _trim(s, n)


# ── extraction ────────────────────────────────────────────────────────────────

@dataclass
class _Extracted:
    units: int = 0                                   # slides / pages / headings
    events: list[tuple[str, str, int, str]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    partial: bool = False
    reason: str = ""                                 # why nothing was extracted


@dataclass
class _Section:
    title: str
    level: int
    loc: str
    lead: str = ""


def _deadline(budget: float) -> float:
    return time.monotonic() + budget


def _pptx_events(path: Path, ex: _Extracted, deadline: float) -> None:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(path))
    slides = list(prs.slides)
    ex.units = len(slides)
    visuals = tables = 0
    for idx, slide in enumerate(slides, 1):
        if idx > _MAX_UNITS_SCANNED or time.monotonic() > deadline:
            ex.partial = True
            break
        title_shape = slide.shapes.title
        title_id = title_shape.shape_id if title_shape is not None else None
        title = ""
        lines: list[str] = []
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or getattr(shape, "has_chart", False):
                visuals += 1
            if shape.has_text_frame:
                text = [_clean(t) for t in shape.text_frame.text.split("\n")]
                text = [t for t in text if t]
                if shape.shape_id == title_id:
                    title = " ".join(text)
                else:
                    lines += text
            if getattr(shape, "has_table", False) and shape.has_table:
                tables += 1
                for row in shape.table.rows:
                    cells = [_clean(c.text) for c in row.cells]
                    row_text = " | ".join(c for c in cells if c)
                    if row_text:
                        lines.append(row_text)
        if not title and lines:
            title = lines.pop(0)
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = _clean(slide.notes_slide.notes_text_frame.text)
        if not title and not lines and not notes:
            continue
        loc = f"Slide {idx}"
        ex.events.append(("heading", title or loc, 1, loc))
        for line in lines:
            ex.events.append(("para", line, 0, loc))
        if notes:
            ex.events.append(("para", notes, 0, loc))
    ex.stats = {"visuals": visuals, "tables": tables}
    if not ex.events:
        ex.reason = "the slides contain no text (images only)"


def _docx_events(path: Path, ex: _Extracted, deadline: float) -> None:
    from docx import Document

    doc = Document(str(path))
    ex.stats = {"tables": len(doc.tables)}
    headings = 0
    for p in doc.paragraphs:
        text = _clean(p.text)
        if not text:
            continue
        style = (p.style.name if p.style is not None and p.style.name else "")
        m = re.match(r"Heading (\d)", style)
        if m or style == "Title":
            headings += 1
            ex.events.append(("heading", text, int(m.group(1)) if m else 1, ""))
        else:
            ex.events.append(("para", text, 0, ""))
    ex.units = headings
    if not ex.events:
        ex.reason = "the document has no body text"


def _pdf_outline(reader, deadline: float) -> list[tuple[str, int, int]]:
    """Flatten the PDF outline to (title, level, page number) tuples."""
    out: list[tuple[str, int, int]] = []

    def walk(items, level: int) -> None:
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
                continue
            if len(out) >= _MAX_UNITS_SCANNED or time.monotonic() > deadline:
                return
            title = _clean(str(getattr(it, "title", "") or ""))
            if not title or _FURNITURE_RE.match(title):
                continue
            try:
                page = reader.get_destination_page_number(it) + 1
            except Exception:
                page = 0
            out.append((title, level, page))

    try:
        walk(reader.outline, 1)
    except Exception:
        pass
    return out


def _pdf_lines(reader, i: int) -> list[str]:
    try:
        text = reader.pages[i].extract_text() or ""
    except Exception:
        return []
    return [l for l in (_clean(x) for x in text.split("\n")) if l and not _FURNITURE_RE.match(l)]


def _pdf_events(path: Path, ex: _Extracted, deadline: float) -> None:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
        if reader.is_encrypted:
            ex.reason = "the PDF is encrypted"
            return
    total = len(reader.pages)
    ex.units = total

    outline = _pdf_outline(reader, deadline)
    if outline:
        for title, level, page in outline:
            loc = f"Page {page}" if page else ""
            ex.events.append(("heading", title, level, loc))
            if page and time.monotonic() <= deadline:
                lines = _pdf_lines(reader, page - 1)
                tl = title.casefold()
                at = next((k for k, l in enumerate(lines) if l.casefold().startswith(tl[:40])), -1)
                body = lines[at + 1:at + 4] if at >= 0 else lines[:3]
                if body:
                    ex.events.append(("para", " ".join(body), 0, loc))
        return

    # No outline: first line of each page is its title, unless it repeats on most
    # pages (running header), in which case the next line is used.
    scan = min(total, _MAX_UNITS_SCANNED)
    pages: list[list[str]] = []
    for i in range(scan):
        if time.monotonic() > deadline:
            break
        pages.append(_pdf_lines(reader, i))
    ex.partial = len(pages) < total
    firsts = [p[0] for p in pages if p]
    repeated = {l for l in set(firsts) if len(pages) >= 4 and firsts.count(l) * 2 > len(pages)}
    for i, lines in enumerate(pages, 1):
        lines = [l for l in lines if l not in repeated]
        if not lines:
            continue
        loc = f"Page {i}"
        ex.events.append(("heading", lines[0], 1, loc))
        if len(lines) > 1:
            ex.events.append(("para", " ".join(lines[1:4]), 0, loc))
    if not ex.events:
        ex.reason = "the PDF has no extractable text (likely scanned images)"


def _boxnote_text(node) -> str:
    parts: list[str] = []

    def walk(n) -> None:
        if isinstance(n, dict):
            if isinstance(n.get("text"), str):
                parts.append(n["text"])
            for c in n.get("content") or []:
                walk(c)
        elif isinstance(n, list):
            for c in n:
                walk(c)

    walk(node)
    return _clean(" ".join(parts))


def _boxnote_events(path: Path, ex: _Extracted, deadline: float) -> None:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if not raw.strip():
        ex.reason = "the Box Note is empty"
        return
    try:
        data = json.loads(raw)
    except ValueError:
        ex.reason = "the Box Note is not valid JSON"
        return
    tables = headings = 0

    def walk(node) -> None:
        nonlocal tables, headings
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        if kind == "heading":
            text = _boxnote_text(node)
            if text:
                headings += 1
                level = (node.get("attrs") or {}).get("level")
                ex.events.append(("heading", text, level if isinstance(level, int) else 1, ""))
        elif kind == "table":
            tables += 1
            for row in node.get("content") or []:
                text = _boxnote_text(row)
                if text:
                    ex.events.append(("para", text, 0, ""))
        elif kind in ("paragraph", "list_item", "check_list_item"):
            text = _boxnote_text(node)
            if text:
                ex.events.append(("para", text, 0, ""))
        else:
            for c in node.get("content") or []:
                walk(c)

    walk(data.get("doc") if isinstance(data, dict) else None)
    ex.units = headings
    ex.stats = {"tables": tables}
    if not ex.events:
        ex.reason = "the Box Note has no text"


def _md_events(path: Path, ex: _Extracted, deadline: float) -> None:
    in_code = False
    block: list[str] = []
    headings = 0

    def flush() -> None:
        if block:
            ex.events.append(("para", _clean(" ".join(block)), 0, ""))
            block.clear()

    for line in path.read_text(encoding="utf-8", errors="ignore").split("\n"):
        if line.lstrip().startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"(#{1,6})\s+(.*\S)", line)
        if m:
            flush()
            headings += 1
            ex.events.append(("heading", _clean(m.group(2)), len(m.group(1)), ""))
        elif line.strip():
            block.append(line.strip())
        else:
            flush()
    flush()
    ex.units = headings
    if not ex.events:
        ex.reason = "the file has no text"


_EXTRACTORS = {
    ".pptx": _pptx_events,
    ".docx": _docx_events,
    ".pdf": _pdf_events,
    ".boxnote": _boxnote_events,
    ".md": _md_events,
}


# ── assembly ──────────────────────────────────────────────────────────────────

def _assemble(events) -> tuple[list[_Section], list[str]]:
    """Group events into sections plus the first plain paragraphs of the file."""
    sections: list[_Section] = []
    paras: list[str] = []
    for kind, text, level, loc in events:
        if kind == "heading":
            sections.append(_Section(text, max(level, 1), loc))
        else:
            if len(paras) < _FALLBACK_PARAS:
                paras.append(text)
            if sections:
                cur = sections[-1]
                # Prefer the first real sentence over a stray number or label.
                if not cur.lead or (len(cur.lead.split()) < _MIN_LEAD_WORDS
                                    and len(text.split()) >= _MIN_LEAD_WORDS):
                    cur.lead = text
    return sections, paras


def _keywords(sections: list[_Section], paras: list[str], folder_words: list[str]) -> list[str]:
    source = [s.title for s in sections] or paras or folder_words
    seen: dict[str, list] = {}
    for n, text in enumerate(source):
        for w in _WORD_RE.findall(text):
            key = w.lower()
            if key in _STOP:
                continue
            if key not in seen:
                seen[key] = [0, n, w]
            seen[key][0] += 1
    ranked = sorted(seen.values(), key=lambda v: (-v[0], v[1], v[2].lower()))
    return [v[2] for v in ranked[:_MAX_KEYWORDS]]


def _outline_line(s: _Section) -> str:
    indent = "  " * min(s.level - 1, 3)
    prefix = f"{s.loc}: " if s.loc else ""
    return f"{indent}- {prefix}{_trim(s.title, _TITLE_CHARS)}"


def _render(rel: str, p: Path, sha: str, ext: str, ex: _Extracted, sections: list[_Section],
            paras: list[str], keywords: list[str], max_outline: int, max_points: int) -> str:
    label, unit = _TYPE_LABEL[ext]
    folder = str(Path(rel).parent)
    empty = bool(ex.reason)

    fm = [
        "---",
        f"path: {rel}",
        f"sha256: {sha}",
        f"type: {ext}",
        f"size_bytes: {p.stat().st_size}",
        f"{unit}: {ex.units}",
        f"extraction: {'empty' if empty else 'ok'}",
        f"partial: {'true' if ex.partial else 'false'}",
        "keywords: " + json.dumps(keywords, ensure_ascii=False),
        "---",
    ]
    body: list[str] = [f"# {p.name}", "", "## What it is", ""]

    where = f" in `{folder}`" if folder != "." else ""
    if ex.units:
        intro = f"{label} with {ex.units} {unit}{where}."
    else:
        intro = f"{label} without headings{where}."
    if empty:
        body += [
            intro,
            "",
            f"No text could be extracted: {ex.reason}. Open the original file to read it.",
            "",
        ]
    else:
        opening = paras[0] if paras else (sections[0].title if sections else "")
        body += [intro, "", f"Opens with: {_trim(opening, 200)}", ""]
        if ex.partial:
            body += ["Only part of the file was read (size or time limit reached).", ""]

        if sections:
            body += ["## Outline", ""]
            body += [_outline_line(s) for s in sections[:max_outline]]
            if len(sections) > max_outline:
                body.append(f"- … and {len(sections) - max_outline} more")
            body.append("")

        points = [(s, s.lead) for s in sections if s.lead][:max_points] if sections else \
                 [(None, t) for t in paras[:max_points]]
        if points and max_points:
            body += ["## Key points", ""]
            for s, text in points:
                head = f"{_trim(s.title, 60).rstrip(':')}: " if s else ""
                body.append(f"- {head}{_first_sentence(text, _POINT_CHARS)}")
            body.append("")

        body += ["## Answers these questions", ""]
        topics = [s.title for s in sections if s.level == min(x.level for x in sections)][:4] if sections else []
        if topics:
            body += [f"- What does this say about {_trim(t, 60)}?" for t in topics]
        else:
            body.append("- What are the main points it states?")
        body.append("")

    body += ["## Does not answer", ""]
    notes = []
    if ex.stats.get("visuals"):
        notes.append(f"Text inside {ex.stats['visuals']} pictures or charts is not extracted.")
    if ex.stats.get("tables"):
        n = ex.stats["tables"]
        notes.append(f"{n} {'table is' if n == 1 else 'tables are'} present; "
                     "cell values are only partly summarised.")
    notes.append("Exact figures and wording: open the original file.")
    body += [f"- {n}" for n in notes]

    return "\n".join(fm + [""] + body).rstrip("\n") + "\n"


def build_doc_digest(path: str | Path, root: str | Path | None = None,
                     time_budget: float = _TIME_BUDGET_S) -> str:
    """Return the markdown digest for one document file."""
    p = Path(path).resolve()
    ext = p.suffix.lower()
    if ext not in _EXTRACTORS:
        raise ValueError(f"not a supported document type: {p.name}")
    rel = str(p.relative_to(Path(root).resolve())) if root else p.name
    ext_key = ext.lstrip(".")

    ex = _Extracted()
    size = p.stat().st_size
    if size > _MAX_FILE_BYTES:
        ex.reason = f"the file is too large to digest ({size // (1024 * 1024)} MB)"
    else:
        try:
            _EXTRACTORS[ext](p, ex, _deadline(time_budget))
        except Exception as exc:  # corrupt or unsupported file: record, do not crash
            ex.events.clear()
            ex.reason = f"the file could not be read ({type(exc).__name__})"

    sections, paras = _assemble(ex.events)
    folder_words = [w for part in Path(rel).parent.parts for w in [part]] if ex.reason else []
    keywords = [] if ex.reason and not folder_words else _keywords(sections, paras, folder_words)
    sha = sha256_of(p)

    for max_outline, max_points in ((40, 12), (30, 8), (20, 5), (12, 3), (8, 0)):
        text = _render(rel, p, sha, ext_key, ex, sections, paras, keywords, max_outline, max_points)
        if len(text.encode("utf-8")) <= _MAX_BYTES:
            return text
    return text
