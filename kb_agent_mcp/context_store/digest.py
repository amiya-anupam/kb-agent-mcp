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
import zipfile
from collections import defaultdict
from pathlib import Path

from kb_agent_mcp.analyst.engine import _MAX_COMPUTE_ROWS, _load_rows, _to_float
from kb_agent_mcp.analyst.inspector import ColumnProfile, DataCard, _inspect_file_sync

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


def _dollar_columns(rows: list[dict], metrics: list[str]) -> list[str]:
    """'($M)' columns whose values are really whole dollars."""
    out = []
    for m in metrics:
        if not _UNIT_M_RE.search(m):
            continue
        vals = [abs(v) for v in (_to_float(r.get(m)) for r in rows) if v is not None]
        if vals and max(vals) >= _UNIT_M_IMPLAUSIBLE:
            out.append(m)
    return out


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


def _sheet_count(path: Path) -> int:
    if path.suffix.lower() not in (".xlsx", ".xls"):
        return 1
    try:
        with zipfile.ZipFile(path) as zf:
            return sum(1 for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    except Exception:
        return 1


def _is_pii(name: str) -> bool:
    return bool(_PII_RE.search(name))


def _profile(card: DataCard, name: str) -> ColumnProfile:
    return next(c for c in card.columns if c.name == name)


def _column_values(rows: list[dict], col: str) -> list[str]:
    return sorted({str(r.get(col)).strip() for r in rows if r.get(col) not in (None, "")})


def _group_sum(rows: list[dict], group: str, metric: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        v = _to_float(r.get(metric))
        g = str(r.get(group, "")).strip()
        if v is not None and g:
            totals[g] += v
    return totals


def _total(rows: list[dict], metric: str) -> tuple[float, int]:
    vals = [v for v in (_to_float(r.get(metric)) for r in rows) if v is not None]
    return sum(vals), len(vals)


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


# ── main entry point ──────────────────────────────────────────────────────────

def build_digest(path: str | Path, root: str | Path | None = None) -> str:
    """Return the markdown digest for one tabular file."""
    p = Path(path).resolve()
    card = _inspect_file_sync(p)
    rows = _load_rows(p)
    partial = len(rows) >= _MAX_COMPUTE_ROWS
    rel = str(p.relative_to(Path(root).resolve())) if root else p.name

    safe_metrics = [m for m in card.metric_columns
                    if not _is_pii(m) and not _RATIO_RE.search(m)]
    ratio_metrics = [m for m in card.metric_columns if _RATIO_RE.search(m)]
    metrics, twins = _dedupe_metrics(rows, safe_metrics)
    exp_col, ren_col = _pick_pair(metrics)
    primary = exp_col or (metrics[0] if metrics else None)

    breakdowns = _pick_breakdowns(card, rows) if (rows and primary) else []
    customer = _pick_customer(card) if (rows and primary) else None
    shown = {col for _, col in breakdowns} | ({customer} if customer else set())
    listed = _listed_values(card, rows, shown) if rows else {}

    dollar_cols = _dollar_columns(rows, metrics) if rows else []
    breakdown_values = {col: _column_values(rows, col) for _, col in breakdowns}
    keyword_sets = [v for v in breakdown_values.values() if len(v) <= 12] + list(listed.values())
    keywords = _keywords(card, metrics, keyword_sets)

    period = ""
    if card.time_range:
        period = f"{card.time_range.get('min')} to {card.time_range.get('max')}"

    fm = [
        "---",
        f"path: {rel}",
        f"sha256: {sha256_of(p)}",
        f"type: {card.file_type}",
        f"size_bytes: {p.stat().st_size}",
        f"sheets: {_sheet_count(p)}",
        f"rows: {card.total_rows}",
        f"columns: {card.total_columns}",
        f"period: {period or 'unknown'}",
        f"grain: {card.grain_hint}",
        f"partial: {'true' if partial else 'false'}",
    ]
    if dollar_cols:
        fm.append("units: columns labelled ($M) hold whole dollars")
    fm += [
        "keywords: [" + ", ".join(f'"{k}"' for k in keywords) + "]",
        "---",
    ]

    body: list[str] = [f"# {p.name}", ""]

    # What it is
    body += ["## What it is", "", card.summary, ""]
    if card.warnings:
        body += ["Data quality warnings:", ""] + [f"- {w}" for w in card.warnings] + [""]

    # Schema
    body += ["## Schema", ""] + _schema_lines(card, rows, listed) + [""]

    # Aggregates
    body += ["## Pre-computed aggregates", ""]
    if rows and metrics:
        if dollar_cols:
            ex_tot, _ = _total(rows, dollar_cols[0])
            body.append("Units: values are shown exactly as stored. Columns labelled `($M)` hold "
                        f"whole dollars, not millions (for example {_num(ex_tot)} means {_gloss(ex_tot)}).")
        else:
            body.append("Values are shown exactly as stored, in the units of each column header.")
        body.append("")
        body.append("Totals over all rows:")
        body.append("")
        for m in metrics[:5]:
            tot, n = _total(rows, m)
            gloss = f" (= {_gloss(tot)})" if m in dollar_cols else ""
            line = f"- {m}: {_num(tot)}{gloss} (non-null rows: {n})"
            if m in twins:
                line += f"; identical copy stored as {', '.join(twins[m])}"
            body.append(line)
        if ratio_metrics:
            body.append(f"- Ratio columns not totalled (summing ratios is meaningless): {', '.join(ratio_metrics)}")
        if exp_col and ren_col:
            e, _ = _total(rows, exp_col)
            r, _ = _total(rows, ren_col)
            if e:
                body.append(f"- Renewal rate ({ren_col} ÷ {exp_col}): {_pct(r / e)}")
        body.append("")

        with_rate = bool(exp_col and ren_col)
        for label, col in breakdowns:
            exp_t = _group_sum(rows, col, primary)
            if not exp_t:
                continue
            ren_t = _group_sum(rows, col, ren_col) if with_rate else {}
            top = sorted(exp_t.items(), key=lambda kv: (-kv[1], kv[0]))[:_BREAKDOWN_ROWS]
            body.append(f"By {label} (`{col}`):")
            body.append("")
            if with_rate:
                body += [f"| {col} | {exp_col} | {ren_col} | Renewal rate |", "|---|---|---|---|"]
                for k, v in top:
                    rv = ren_t.get(k, 0.0)
                    body.append(f"| {k} | {_num(v)} | {_num(rv)} | {_pct(rv / v) if v else 'n/a'} |")
            else:
                body += [f"| {col} | {primary} |", "|---|---|"]
                body += [f"| {k} | {_num(v)} |" for k, v in top]
            body.append("")

        if customer:
            exp_t = _group_sum(rows, customer, primary)
            top = sorted(exp_t.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_CUSTOMERS]
            if top:
                body += [f"Top {len(top)} by `{customer}` ({primary}):", ""]
                body += [f"- {k}: {_num(v)}" for k, v in top]
                body.append("")
    else:
        body += ["No numeric metric columns were detected.", ""]

    # Questions
    body += ["## Answers these questions", ""]
    if primary:
        body.append(f"- What is the total {primary}?")
        if exp_col and ren_col:
            body.append(f"- What is the renewal rate ({ren_col} ÷ {exp_col}), overall and per group below?")
        if breakdowns:
            dims = ", ".join(f"{l} ({c})" for l, c in breakdowns)
            body.append(f"- How does {primary} split by: {dims}?")
        if customer:
            body.append(f"- Which {customer} has the highest {primary}?")
    else:
        body.append(f"- What does {p.name} contain?")
    body.append("")

    # Limits
    body += ["## Does not answer", ""]
    if _sheet_count(p) > 1:
        body.append(f"- Only the first of {_sheet_count(p)} sheets was profiled.")
    if partial:
        body.append(f"- Only the first {_MAX_COMPUTE_ROWS:,} rows were read; figures are partial.")
    pii = [c.name for c in card.columns if _is_pii(c.name)]
    if pii:
        body.append(f"- Personal-data columns are not summarised here: {', '.join(pii)}.")
    body.append("- Row-level detail: open the source file or use the analyst tools for exact figures.")
    body.append("")

    return "\n".join(fm) + "\n\n" + "\n".join(body)
