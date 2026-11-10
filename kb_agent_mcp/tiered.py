"""
kb_agent_mcp/tiered.py
──────────────────────
Tiered retrieval from the markdown context store (Phase 4, flag KB_CONTEXT_STORE).

Tiers, cheapest first.  Anything that finds nothing returns None and the caller
falls back to the existing README / Chroma path (tier 5):

  1. MANIFEST.md   routing between domains — done by the orchestrator, not here.
  2. INDEX.md      what the domain holds.  Used as the answer to "what files
                   do you have" questions.
  3. digests       the few digests that best match the question.
  4. analyst       the analyst engine run on the raw file, for exact numbers
                   from a spreadsheet that a digest picked.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from kb_agent_mcp.config import cfg
from kb_agent_mcp.context_store.frontmatter import parse_front_matter
from kb_agent_mcp.context_store.paths import INDEX_NAME, context_dir, domain_slug

logger = logging.getLogger(__name__)

MAX_DIGESTS   = 3        # digests put into one answer
DIGEST_CHARS  = 6000     # cap per digest, after compaction
ANALYST_CHARS = 3000
ANALYST_TIMEOUT = 30.0   # seconds
MIN_SCORE     = 2.0      # best digest must score at least this, else fall back
REL_SCORE     = 0.5      # other digests must reach this share of the best score

_TABULAR = {"xlsx", "xls", "csv", "tsv"}

_OVERVIEW_RE = re.compile(
    r"\b(what|which) (files|documents|docs)\b|\blist (of )?(the |all )?(files|documents|docs)\b",
    re.IGNORECASE,
)
_STOP = frozenset(
    "the and for are was were what which who whom when where why how does did "
    "with from that this these those about there their have has had can could "
    "should would you your our tell show give list all any please into between "
    "than then them they its not but also more most some such only own same "
    "very will just per via say get got".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class TierResult:
    context: str
    sources: list[dict]
    label: str
    tiers: list[str] = field(default_factory=list)
    redacted: list[str] = field(default_factory=list)


@dataclass
class _Doc:
    digest: Path
    source: str          # source path relative to the KB root, e.g. "BizOps/a.xlsx"
    type: str
    text: str
    name_tokens: frozenset
    kw_tokens: frozenset
    body: Counter


# ── Scoring ────────────────────────────────────────────────────────────────────

def _tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN_RE.findall(text.lower()):
        if t in _STOP or not (len(t) >= 3 or any(c.isdigit() for c in t)):
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


_DOC_CACHE: dict[Path, tuple[int, _Doc]] = {}


def _load_doc(path: Path) -> _Doc | None:
    try:
        mtime = path.stat().st_mtime_ns
        cached = _DOC_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm = parse_front_matter(text)
    source = str(fm.get("path") or "")
    if not source:
        return None                                  # hand-written file, not a digest
    kws = fm.get("keywords") or []
    doc = _Doc(
        digest=path,
        source=source,
        type=str(fm.get("type") or "").lower(),
        text=text,
        name_tokens=frozenset(_tokens(Path(source).name)),
        kw_tokens=frozenset(t for k in kws for t in _tokens(str(k))),
        body=Counter(_tokens(text)),
    )
    _DOC_CACHE[path] = (mtime, doc)
    return doc


def _domain_docs(domain_dir: Path) -> list[_Doc]:
    docs = []
    for p in sorted(domain_dir.rglob("*.md")):
        if p.name != INDEX_NAME and (d := _load_doc(p)):
            docs.append(d)
    return docs


def select_digests(domain_dir: Path, question: str) -> list[tuple[float, _Doc]]:
    """Digests of one domain that best match the question, best first."""
    docs = _domain_docs(domain_dir)
    terms = set(_tokens(question))
    if not docs or not terms:
        return []

    def has(d: _Doc, t: str) -> bool:
        return t in d.name_tokens or t in d.kw_tokens or t in d.body

    idf = {}
    for t in terms:
        df = sum(1 for d in docs if has(d, t))
        if df:
            idf[t] = math.log(1 + len(docs) / df)

    scored = []
    for d in docs:
        s = sum(
            w * (3 * (t in d.name_tokens) + 2 * (t in d.kw_tokens) + min(d.body[t], 3))
            for t, w in idf.items()
        )
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < MIN_SCORE:
        return []
    best = scored[0][0]
    return [x for x in scored if x[0] >= REL_SCORE * best][:MAX_DIGESTS]


def domain_scores(question: str, domain_names: list[str], ctx: Path | None = None) -> dict[str, float]:
    """Best-matching digest score per domain (0.0 = nothing relevant). Routing signal."""
    base = ctx or context_dir()
    out = {}
    for name in domain_names:
        ddir = base / domain_slug(name)
        picked = select_digests(ddir, question) if ddir.is_dir() else []
        out[name] = picked[0][0] if picked else 0.0
    return out


# ── Digest → context ───────────────────────────────────────────────────────────

def compact_digest(text: str) -> str:
    """Digest body without front-matter and without the per-sheet Schema blocks."""
    lines = text.split("\n")
    if lines and lines[0] == "---":
        try:
            lines = lines[lines.index("---", 1) + 1:]
        except ValueError:
            pass
    out, skipping = [], False
    for ln in lines:
        if ln.startswith("#"):
            skipping = ln.strip() == "### Schema"
        if not skipping:
            out.append(ln)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return body if len(body) <= DIGEST_CHARS else body[:DIGEST_CHARS].rstrip() + "…"


# ── Entry point ────────────────────────────────────────────────────────────────

async def tiered_context(
    folder_name: str,
    question: str,
    *,
    data_question: bool = False,
    session_id: str = "default",
    ctx: Path | None = None,
    kb_root: Path | None = None,
) -> TierResult | None:
    """Context for `question` from the context store, or None to fall back to Chroma."""
    ddir = (ctx or context_dir()) / domain_slug(folder_name)
    index = ddir / INDEX_NAME
    if not index.is_file():
        return None

    if _OVERVIEW_RE.search(question):
        text = index.read_text(encoding="utf-8")
        return TierResult(
            context=f"--- Domain index: {folder_name} ---\n{text}",
            sources=[{"name": f"{folder_name} index", "path": f"{folder_name}/{INDEX_NAME}",
                      "score": 1.0, "tier": "index"}],
            label=f"Context store index ({folder_name})",
            tiers=["index"],
        )

    picked = await asyncio.to_thread(select_digests, ddir, question)
    if not picked:
        return None

    root = kb_root or cfg.kb_root_path
    gate_ok = True
    if cfg.KB_SECURITY_GATE_ENABLED:
        from kb_agent_mcp.security_gate import is_gate_acknowledged
        gate_ok = is_gate_acknowledged(session_id)

    blocks, sources, redacted = [], [], []
    kept: list[_Doc] = []
    top = picked[0][0]
    for score, d in picked:
        src = root / d.source
        conf = False
        if cfg.KB_SECURITY_GATE_ENABLED and src.exists():
            from kb_agent_mcp.security_gate import classify_confidential
            conf, _ = classify_confidential(src)
        name = Path(d.source).name
        if conf and not gate_ok:
            redacted.append(name)
            continue
        label = f"🔒 {name}" if conf else name
        blocks.append(f"--- Digest: {label} ---\n{compact_digest(d.text)}")
        sources.append({"name": label, "path": d.source, "score": round(score / top, 2),
                        "confidential": conf, "tier": "digest"})
        kept.append(d)

    if not blocks:
        return None                                  # let the old path explain the redaction
    tiers = ["digest"]

    # Tier 4 — exact numbers from the raw spreadsheet the best digest points at.
    if data_question and kept[0].type in _TABULAR:
        answer = await _analyst_answer(kept[0].source, question)
        if answer:
            blocks.append(f"--- Analyst result on {Path(kept[0].source).name} ---\n{answer}")
            tiers.append("analyst")

    if redacted:
        blocks.append(
            "Note: " + ", ".join(f"`{n}`" for n in redacted)
            + " excluded (confidential — call `acknowledge_gate()` to include)."
        )
    return TierResult(
        context="\n\n".join(blocks),
        sources=sources,
        label="Context store: " + ", ".join(s["name"] for s in sources[:3]),
        tiers=tiers,
        redacted=redacted,
    )


async def _analyst_answer(source: str, question: str) -> str | None:
    """Analyst-engine answer, or None when it needs clarification, fails or is empty."""
    try:
        from kb_agent_mcp.analyst.engine import query_data
        res = await asyncio.wait_for(query_data(source, question), ANALYST_TIMEOUT)
    except Exception as exc:
        logger.debug("analyst tier failed for %s: %s", source, exc)
        return None
    if res.get("status") != "answered":
        return None
    answer = str(res.get("answer") or "").strip()
    if not answer:
        return None
    return answer if len(answer) <= ANALYST_CHARS else answer[:ANALYST_CHARS].rstrip() + "…"
