"""
Prototype digest builder for tabular files (xlsx / csv).

A digest is a small markdown file with YAML front-matter. Everything in it is
computed by code from the file itself (DataCard + simple aggregates), so the
output is deterministic and needs no LLM, MCP server or Ollama.

Units: values are reported exactly as stored; nothing is converted. Headers can
lie, though: a "($M)" column whose per-row values are in the millions actually
holds whole dollars. The digest says so and adds a readable gloss ("= $102.2M")
next to totals, while the stored figure stays untouched.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from kb_agent_mcp.analyst.engine import _to_float
from kb_agent_mcp.analyst.inspector import ColumnProfile, DataCard
from kb_agent_mcp.context_store.table_scan import Plan, SheetScan, scan_sheet
from kb_agent_mcp.context_store.table_stream import open_table

# Columns holding personal data: never listed with values or aggregated.
_PII_RE = re.compile(r"e-?mail|employee|phone|contact|\bowner(ship)?\b", re.I)

# A column keeps the "time" kind only if its name is date-like. The analyst
# inspector also tags names such as "2025 Product Leadership" as time.
_TIME_NAME_RE = re.compile(r"date|month|quarter|period|week|\byear\b|\bfy\b|\bqtr\b|\bkey\b|time|day", re.I)

# A "($M)" header whose per-row values reach this size cannot be in millions.
_UNIT_M_RE = re.compile(r"\(\s*\$\s*m\s*\)", re.I)
_UNIT_M_IMPLAUSIBLE = 100_000

# Breakdown dimensions, in the order they are shown. The first eligible column
# whose name contains one of the hints wins; columns that split the rows the
# same way as an earlier breakdown (code/name pairs) are skipped.
_BREAKDOWN_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("product", ("ut 30 name", "product family", "product name", "product", "brand")),
    ("region", ("iot/gmu", "geography", "region", "imt/gmt", "geo")),
    ("segment", ("client segment type description", "segment")),
    ("ELA", ("ela/non-ela", "ela")),
    ("channel", ("channel type", "channel")),
    ("period", ("fiscal quarter", "fiscal month", "quarter", "month", "year", "period")),
]
_CUSTOMER_HINTS = ("customer name", "client name", "account name", "customer")

# Ratio columns cannot be summed; they are named but not totalled.
_RATIO_RE = re.compile(r"\brrr\b|rate|ratio|percent|%|\bpct\b|margin", re.I)

_MIN_BREAKDOWN_CARD = 2
_MAX_BREAKDOWN_CARD = 40
_BREAKDOWN_ROWS = 8
_TOP_CUSTOMERS = 5
_MAX_LISTED_VALUES = 8        # list values of low-cardinality columns up to this many
_MAX_KEYWORDS = 25
_NULL_NOTE_THRESHOLD = 0.20   # annotate columns with at least this null rate
_TIME_BUDGET_S = 60.0         # wall-clock limit for reading one file
_MAX_BYTES = 10_000           # size budget for a one-sheet digest
_MAX_BYTES_MULTI = 16_000     # size budget for a workbook with several sheets


# ── helpers ───────────────────────────────────────────────────────────────────

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _num(n: float) -> str:
    """Plain number with thousands separators. No K/M/B suffix."""
    if abs(n) >= 1000:
        return f"{n:,.0f}"
    return f"{n:,.2f}".rstrip("0").rstrip(".")


def _kind(c: ColumnProfile) -> str:
    if c.kind == "time" and not _TIME_NAME_RE.search(c.name):
        return "categorical"
    return c.kind


def _gloss(n: float) -> str:
    """Readable form of a whole-dollar amount, shown beside the stored value."""
    a = abs(n)
    sign = "-" if n < 0 else ""
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.1f}K"
    return f"{sign}${a:,.0f}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _is_pii(name: str) -> bool:
    return bool(_PII_RE.search(name))


def _profile(card: DataCard, name: str) -> ColumnProfile:
    return next(c for c in card.columns if c.name == name)


def _column_values(rows: list[dict], col: str) -> list[str]:
    return sorted({str(r.get(col)).strip() for r in rows if r.get(col) not in (None, "")})


def _signature(rows: list[dict], col: str) -> tuple:
    """How a column partitions the rows (value names are ignored)."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        groups[str(r.get(col)).strip()].append(i)
    return tuple(sorted(tuple(ix) for ix in groups.values()))


# ── metric selection ──────────────────────────────────────────────────────────

def _dedupe_metrics(rows: list[dict], metrics: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Drop metric columns whose values are identical to an earlier one."""
    kept: list[str] = []
    twins: dict[str, list[str]] = {}
    seen: dict[tuple, str] = {}
    for m in metrics:
        sig = tuple(_to_float(r.get(m)) for r in rows)
        if sig in seen:
            twins.setdefault(seen[sig], []).append(m)
        else:
            seen[sig] = m
            kept.append(m)
    return kept, twins


def _pick_pair(metrics: list[str]) -> tuple[str | None, str | None]:
    """Find an (expired, renewed) metric pair for a renewal rate."""
    exp = [m for m in metrics if re.search(r"expired", m, re.I) and not re.search(r"quantity|qty", m, re.I)]
    ren = [m for m in metrics if re.search(r"renewed", m, re.I) and not re.search(r"quantity|qty", m, re.I)]
    return (exp[0] if exp else None, ren[0] if ren else None)


# ── breakdown selection ───────────────────────────────────────────────────────

def _pick_breakdowns(card: DataCard, rows: list[dict]) -> list[tuple[str, str]]:
    """Return [(label, column)] chosen by the hint list."""
    chosen: list[tuple[str, str]] = []
    sigs: set[tuple] = set()
    for label, hints in _BREAKDOWN_HINTS:
        found = None
        for hint in hints:
            for c in card.columns:
                if _kind(c) in ("id", "metric", "text", "unknown") or _is_pii(c.name):
                    continue
                if hint not in c.name.lower():
                    continue
                if not (_MIN_BREAKDOWN_CARD <= c.cardinality <= _MAX_BREAKDOWN_CARD):
                    continue
                if label == "period" and "key" in c.name.lower():
                    continue
                sig = _signature(rows, c.name)
                if sig in sigs:
                    continue
                found = (c.name, sig)
                break
            if found:
                break
        if found:
            sigs.add(found[1])
            chosen.append((label, found[0]))
    return chosen


def _pick_customer(card: DataCard) -> str | None:
    for hint in _CUSTOMER_HINTS:
        for c in card.columns:
            if c.kind == "entity" and hint in c.name.lower() and not _is_pii(c.name) \
                    and c.cardinality > _MAX_BREAKDOWN_CARD:
                return c.name
    return None


# ── schema rendering ──────────────────────────────────────────────────────────

_KIND_ORDER = ["time", "entity", "categorical", "id", "metric", "text", "unknown"]


def _schema_lines(card: DataCard, rows: list[dict], inline: dict[str, list[str]]) -> list[str]:
    """Compact schema that still names every column.

    Small columns list their values inline (`name [3: a, b, c]`), so the schema
    answers "what can I filter on" without a separate section.
    """
    constant: list[str] = []
    empty: list[str] = []
    by_kind: dict[str, list[str]] = defaultdict(list)
    for c in card.columns:
        if c.cardinality == 0 or c.null_rate >= 0.99:
            empty.append(c.name)
            continue
        if c.cardinality == 1:
            constant.append(f"{c.name} = {str(c.sample_values[0]).strip()}" if c.sample_values else c.name)
            continue
        note = f"{c.cardinality}"
        if c.name in inline:
            note += ": " + ", ".join(inline[c.name])
        if c.null_rate >= _NULL_NOTE_THRESHOLD:
            note += f"; {round(c.null_rate * 100)}% null"
        by_kind[_kind(c)].append(f"{c.name} [{note}]")

    out = ["Each column is listed as `name [distinct values]`. Columns with at most "
           f"{_MAX_LISTED_VALUES} values list them; columns used in the breakdown tables below "
           "show their values there. Null rates are shown when 20% or more.", ""]
    for kind in _KIND_ORDER:
        if by_kind.get(kind):
            out.append(f"- **{kind}** ({len(by_kind[kind])}): " + "; ".join(by_kind[kind]))
    if constant:
        out.append(f"- **constant** ({len(constant)}): " + "; ".join(constant))
    if empty:
        out.append(f"- **empty** ({len(empty)}): " + "; ".join(empty))
    return out


def _listed_values(card: DataCard, rows: list[dict], skip: set[str]) -> dict[str, list[str]]:
    """Distinct values of low-cardinality columns not already shown elsewhere."""
    names = {c.name for c in card.columns}
    out: dict[str, list[str]] = {}
    for c in card.columns:
        if c.name in skip or _kind(c) not in ("categorical", "entity") or _is_pii(c.name):
            continue
        if not (2 <= c.cardinality <= _MAX_LISTED_VALUES):
            continue
        # Skip code columns that have a readable twin.
        if c.name.endswith(" Code") and c.name[:-5] + " Name" in names:
            continue
        if c.name + " Description" in names:
            continue
        vals = _column_values(rows, c.name)
        if 2 <= len(vals) <= _MAX_LISTED_VALUES:
            out[c.name] = vals
    return out


# ── keywords ──────────────────────────────────────────────────────────────────

def _keywords(card: DataCard, metrics: list[str], value_sets: list[list[str]]) -> list[str]:
    words: list[str] = list(card.data_themes) + metrics
    for vals in value_sets:
        words += vals
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        k = w.strip()
        if len(k) >= 3 and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out[:_MAX_KEYWORDS]


# ── per-sheet view ────────────────────────────────────────────────────────────

def _make_plan(card: DataCard, rows: list[dict]) -> Plan:
    """Decide what to summarise from the sample rows of one sheet."""
    safe = [m for m in card.metric_columns if not _is_pii(m) and not _RATIO_RE.search(m)]
    ratio = [m for m in card.metric_columns if _RATIO_RE.search(m)]
    metrics, twins = _dedupe_metrics(rows, safe)
    exp_col, ren_col = _pick_pair(metrics)
    primary = exp_col or (metrics[0] if metrics else None)
    breakdowns = _pick_breakdowns(card, rows) if (rows and primary) else []
    customer = _pick_customer(card) if (rows and primary) else None
    shown = {col for _, col in breakdowns} | ({customer} if customer else set())
    listed = list(_listed_values(card, rows, shown)) if rows else []
    return Plan(
        metrics=metrics, twins=twins, ratio_metrics=ratio,
        exp_col=exp_col, ren_col=ren_col, primary=primary,
        breakdowns=breakdowns, customer=customer, listed=listed,
        value_cols=[col for _, col in breakdowns] + listed,
    )


@dataclass
class _View:
    """A scanned sheet with the figures that are rendered from it."""
    scan: SheetScan
    metrics: list[str]               # metrics to total, in order
    twins: dict[str, list[str]]      # confirmed identical copies
    dollar_cols: list[str]
    inline: dict[str, list[str]]     # small columns whose values are listed in the schema
    breakdown_values: dict[str, list[str]]


def _distinct(scan: SheetScan, col: str) -> list[str] | None:
    acc = scan.acc
    if acc is None or col in acc.overflow or col not in acc.values:
        return None
    return sorted(acc.values[col])


def _view(scan: SheetScan) -> _View:
    plan, acc = scan.plan, scan.acc
    assert acc is not None
    metrics = list(plan.metrics)
    twins: dict[str, list[str]] = {}
    for m, copies in plan.twins.items():
        for t in copies:
            if acc.sig.get(t) == acc.sig.get(m):
                twins.setdefault(m, []).append(t)
            else:                      # looked identical in the sample only
                metrics.append(t)
    dollar = [m for m in metrics if _UNIT_M_RE.search(m) and acc.max_abs.get(m, 0.0) >= _UNIT_M_IMPLAUSIBLE]
    inline: dict[str, list[str]] = {}
    for col in plan.listed:
        vals = _distinct(scan, col)
        if vals is not None and 2 <= len(vals) <= _MAX_LISTED_VALUES:
            inline[col] = vals
    bvals = {col: (_distinct(scan, col) or []) for _, col in plan.breakdowns}
    return _View(scan, metrics, twins, dollar, inline, bvals)


def _names_line(card: DataCard) -> list[str]:
    names = [c.name for c in card.columns]
    shown = ", ".join(names[:60]) + (f", … and {len(names) - 60} more" if len(names) > 60 else "")
    return [f"Columns ({len(names)}): {shown}"]


def _sheet_body(v: _View, h: str, brk_rows: int, top_n: int, schema: str) -> list[str]:
    """What it is / Schema / Pre-computed aggregates for one sheet."""
    scan = v.scan
    card, plan, acc = scan.card, scan.plan, scan.acc
    assert card is not None and acc is not None
    primary, exp_col, ren_col = plan.primary, plan.exp_col, plan.ren_col
    body: list[str] = [f"{h} What it is", "", card.summary, ""]
    if scan.partial:
        body += [f"Only {scan.rows_read:,} of about {scan.rows_total:,} rows were read; figures cover those rows.", ""]
    if card.warnings:
        body += ["Data quality warnings:", ""] + [f"- {w}" for w in card.warnings] + [""]

    body += [f"{h} Schema", ""]
    body += _schema_lines(card, [], v.inline) if schema == "full" else _names_line(card)
    body.append("")

    body += [f"{h} Pre-computed aggregates", ""]
    if not (v.metrics and primary):
        return body + ["No numeric metric columns were detected.", ""]
    if v.dollar_cols:
        ex = acc.totals[v.dollar_cols[0]]
        body.append("Units: values are shown exactly as stored. Columns labelled `($M)` hold "
                    f"whole dollars, not millions (for example {_num(ex)} means {_gloss(ex)}).")
    else:
        body.append("Values are shown exactly as stored, in the units of each column header.")
    body += ["", "Totals over the rows read:" if scan.partial else "Totals over all rows:", ""]
    for m in v.metrics[:5]:
        gloss = f" (= {_gloss(acc.totals[m])})" if m in v.dollar_cols else ""
        line = f"- {m}: {_num(acc.totals[m])}{gloss} (non-null rows: {acc.counts[m]})"
        if m in v.twins:
            line += f"; identical copy stored as {', '.join(v.twins[m])}"
        body.append(line)
    if plan.ratio_metrics:
        body.append(f"- Ratio columns not totalled (summing ratios is meaningless): {', '.join(plan.ratio_metrics)}")
    with_rate = bool(exp_col and ren_col)
    if with_rate and acc.totals[exp_col]:
        body.append(f"- Renewal rate ({ren_col} ÷ {exp_col}): {_pct(acc.totals[ren_col] / acc.totals[exp_col])}")
    body.append("")

    for label, col in plan.breakdowns if brk_rows else []:
        exp_t = acc.groups.get((col, primary), {})
        if not exp_t:
            continue
        ren_t = acc.groups.get((col, ren_col), {}) if with_rate else {}
        top = sorted(exp_t.items(), key=lambda kv: (-kv[1], kv[0]))[:brk_rows]
        body += [f"By {label} (`{col}`):", ""]
        if with_rate:
            body += [f"| {col} | {exp_col} | {ren_col} | Renewal rate |", "|---|---|---|---|"]
            for k, val in top:
                rv = ren_t.get(k, 0.0)
                body.append(f"| {k} | {_num(val)} | {_num(rv)} | {_pct(rv / val) if val else 'n/a'} |")
        else:
            body += [f"| {col} | {primary} |", "|---|---|"]
            body += [f"| {k} | {_num(val)} |" for k, val in top]
        body.append("")

    if plan.customer and top_n:
        top = sorted(acc.groups.get((plan.customer, primary), {}).items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        if top:
            body += [f"Top {len(top)} by `{plan.customer}` ({primary}):", ""]
            body += [f"- {k}: {_num(val)}" for k, val in top]
            body.append("")
    return body


def _answers(v: _View, prefix: str) -> list[str]:
    plan = v.scan.plan
    primary = plan.primary
    if not primary:
        return [f"- {prefix}What does this sheet contain?"] if prefix else []
    out = [f"- {prefix}What is the total {primary}?"]
    if plan.exp_col and plan.ren_col:
        out.append(f"- {prefix}What is the renewal rate ({plan.ren_col} ÷ {plan.exp_col}), overall and per group below?")
    if plan.breakdowns:
        dims = ", ".join(f"{lb} ({c})" for lb, c in plan.breakdowns)
        out.append(f"- {prefix}How does {primary} split by: {dims}?")
    if plan.customer:
        out.append(f"- {prefix}Which {plan.customer} has the highest {primary}?")
    return out


# ── main entry point ──────────────────────────────────────────────────────────

# Detail levels tried in order until the digest fits its size budget:
# (rows per breakdown table, top customers, schema style)
_LEVELS = [(_BREAKDOWN_ROWS, _TOP_CUSTOMERS, "full"), (5, 3, "full"), (3, 0, "names"), (0, 0, "names")]


def _scan_file(p: Path, time_budget: float) -> tuple[list[SheetScan], list[str], str]:
    """Stream every sheet. Returns (scans, sheets skipped for time, failure reason)."""
    deadline = time.monotonic() + time_budget
    scans: list[SheetScan] = []
    skipped: list[str] = []
    try:
        with open_table(p) as src:
            n = len(src.names)
            for i, name in enumerate(src.names):
                left = deadline - time.monotonic()
                if left <= 0:
                    skipped.append(name)
                    continue
                share = time.monotonic() + left / (n - i)
                scans.append(scan_sheet(src, i, p, share, _make_plan))
    except Exception as exc:  # corrupt, encrypted or legacy file: record, do not crash
        if p.suffix.lower() == ".xls" and type(exc).__name__ == "BadZipFile":
            return [], [], "legacy binary .xls files are not supported; convert to .xlsx"
        return [], [], f"the file could not be read ({type(exc).__name__})"
    if not any(s.card for s in scans):
        return scans, skipped, "the file has no data rows" if not skipped else "the time limit was reached before any data was read"
    return scans, skipped, ""


def build_digest(path: str | Path, root: str | Path | None = None,
                 time_budget: float = _TIME_BUDGET_S) -> str:
    """Return the markdown digest for one tabular file."""
    p = Path(path).resolve()
    rel = str(p.relative_to(Path(root).resolve())) if root else p.name
    scans, skipped, reason = _scan_file(p, time_budget)
    sha = sha256_of(p)
    ext = p.suffix.lstrip(".").lower()
    if reason:
        return _empty_digest(rel, p, sha, ext, reason, [s.name for s in scans] + skipped)

    views = [_view(s) for s in scans if s.card and s.acc]
    multi = len(views) > 1 or len(scans) + len(skipped) > 1
    partial = bool(skipped) or any(s.partial for s in scans)
    first = views[0].scan.card
    assert first is not None

    sets: list[str] = []
    for v in views:
        card = v.scan.card
        assert card is not None
        vsets = [x for x in v.breakdown_values.values() if len(x) <= 12] + list(v.inline.values())
        sets += _keywords(card, v.metrics, vsets)
    names = [s.name for s in scans + [SheetScan(name=n) for n in skipped]]
    kw_src = ([n for n in names if not re.fullmatch(r"(?i)sheet\d*", n)] if multi else []) + sets
    seen: set[str] = set()
    keywords: list[str] = []
    for w in kw_src:
        if w.lower() not in seen:
            seen.add(w.lower())
            keywords.append(w)
    keywords = keywords[:_MAX_KEYWORDS]

    by_size = sorted((v for v in views if v.scan.card and v.scan.card.time_range),
                     key=lambda v: -v.scan.card.total_rows)  # type: ignore[union-attr]
    tr = by_size[0].scan.card.time_range if by_size else {}  # type: ignore[union-attr]
    period = f"{tr.get('min')} to {tr.get('max')}" if tr else ""
    rows_total = sum(v.scan.card.total_rows for v in views if v.scan.card)
    cols = max(v.scan.card.total_columns for v in views if v.scan.card)
    any_dollar = any(v.dollar_cols for v in views)

    fm = [
        "---",
        f"path: {rel}",
        f"sha256: {sha}",
        f"type: {ext}",
        f"size_bytes: {p.stat().st_size}",
        f"sheets: {len(names)}",
        f"rows: {rows_total}",
        f"columns: {cols}",
        f"period: {period or 'unknown'}",
        f"grain: {first.grain_hint}",
        "extraction: ok",
        f"partial: {'true' if partial else 'false'}",
    ]
    if any_dollar:
        fm.append("units: columns labelled ($M) hold whole dollars")
    fm += ["keywords: [" + ", ".join(f'"{k}"' for k in keywords) + "]", "---"]

    limits: list[str] = []
    for v in views:
        s = v.scan
        tag = f"Sheet {s.name}: " if multi else ""
        if s.partial:
            why = f" ({s.error})" if s.error else " (time limit)"
            limits.append(f"- {tag}only {s.rows_read:,} of about {s.rows_total:,} rows were read{why}; figures are partial.")
    if skipped:
        limits.append(f"- Sheets not read (time limit): {', '.join(skipped)}.")
    empty = [s.name for s in scans if not s.card]
    if empty:
        limits.append(f"- Sheets with no data rows: {', '.join(empty)}.")
    for v in views:
        card = v.scan.card
        assert card is not None
        pii = [c.name for c in card.columns if _is_pii(c.name)]
        if pii:
            tag = f"Sheet {v.scan.name}: " if multi else ""
            limits.append(f"- {tag}Personal-data columns are not summarised here: {', '.join(pii)}.")
    limits.append("- Row-level detail: open the source file or use the analyst tools for exact figures.")

    budget = _MAX_BYTES_MULTI if multi else _MAX_BYTES
    text = ""
    for brk_rows, top_n, schema in _LEVELS:
        body: list[str] = [f"# {p.name}", ""]
        if multi:
            body += ["## Sheets", ""]
            for s in scans:
                if s.card:
                    note = " (partial)" if s.partial else ""
                    body.append(f"- **{s.name}**: {s.card.total_rows:,} rows, {s.card.total_columns} columns{note}")
                else:
                    body.append(f"- **{s.name}**: no data rows")
            body += [f"- **{n}**: not read (time limit)" for n in skipped]
            body.append("")
            for v in views:
                body += [f"## Sheet: {v.scan.name}", ""] + _sheet_body(v, "###", brk_rows, top_n, schema)
        else:
            body += _sheet_body(views[0], "##", brk_rows, top_n, schema)
        body += ["## Answers these questions", ""]
        ans: list[str] = []
        for v in views:
            ans += _answers(v, f"[{v.scan.name}] " if multi else "")
        body += ans or [f"- What does {p.name} contain?"]
        body += ["", "## Does not answer", ""] + limits + [""]
        text = "\n".join(fm) + "\n\n" + "\n".join(body)
        if len(text.encode("utf-8")) <= budget:
            break
    return text


def _empty_digest(rel: str, p: Path, sha: str, ext: str, reason: str, sheet_names: list[str]) -> str:
    fm = [
        "---",
        f"path: {rel}",
        f"sha256: {sha}",
        f"type: {ext}",
        f"size_bytes: {p.stat().st_size}",
        f"sheets: {len(sheet_names)}",
        "rows: 0",
        "columns: 0",
        "period: unknown",
        "grain: unknown",
        "extraction: empty",
        "partial: false",
        "keywords: []",
        "---",
    ]
    body = [
        f"# {p.name}", "",
        "## What it is", "",
        f"No data could be extracted: {reason}. Open the original file to read it.", "",
        "## Does not answer", "",
        "- Everything: no figures were read from this file.",
        "- Row-level detail: open the source file or use the analyst tools for exact figures.", "",
    ]
    return "\n".join(fm) + "\n\n" + "\n".join(body)
