"""
kb_agent_mcp/analyst/engine.py
────────────────────────────────
Query engine — the core of the Data Analyst capability.

Workflow
────────
1. inspect_file()  → DataCard (cached)
2. Decide if clarification is needed for this question + current session params
3a. If clarification needed  → return clarifying questions; save to session
3b. If all params known      → load the file, compute the answer, return answer + reasoning
4. Save session; return structured result

The computation step loads only the rows needed:
  • Tabular files  → pandas-free streaming via the existing file_parser helpers
  • Document files → calls base_agent.call_llm with extracted text as context

Returned dict (always)
──────────────────────
{
    "status":           "clarifying" | "answered" | "error",
    "session_id":       str,
    "question":         str,           # original question
    "clarifications":   list[dict],    # only when status == "clarifying"
    "answer":           str,           # only when status == "answered"
    "reasoning":        str,           # only when status == "answered"
    "suggested_followups": list[str],  # only when status == "answered"
    "warnings":         list[str],
    "error":            str,           # only when status == "error"
}

compare_data() return dict
──────────────────────────
{
    "status":           "answered" | "error",
    "session_id":       str,
    "question":         str,
    "answer":           str,           # markdown diff table
    "reasoning":        str,
    "suggested_followups": list[str],
    "warnings":         list[str],
    "file_a":           str,           # resolved absolute path
    "file_b":           str,
    "error":            str,           # only when status == "error"
}
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

from kb_agent_mcp.analyst.inspector import inspect_file, data_card_to_dict, DataCard
from kb_agent_mcp.analyst.session import (
    AnalystSession,
    load_session,
    save_session,
    add_turn,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Maximum rows to load for computation (streaming; beyond this we sample)
_MAX_COMPUTE_ROWS = 200_000
# Maximum characters of document text to feed to the LLM
_MAX_DOC_CHARS = 12_000
# Words that strongly suggest "all time" intent (skip time-filter clq)
_ALL_TIME_HINTS = re.compile(
    r"\b(all|every|entire|total|overall|across all|any period|all periods|all time)\b",
    re.IGNORECASE,
)


# ── Clarification logic ────────────────────────────────────────────────────────

def _needs_clarification(
    question: str,
    card: DataCard,
    params: dict[str, Any],
) -> list[dict]:
    """
    Return a list of clarifying questions that must be answered before the
    computation can run.  Empty list → can answer now.

    Rules:
      • If the question implies "all" data, skip time/entity filters.
      • Only ask clarifying questions when there is genuine ambiguity
        (e.g. multiple metric columns, time present but no period specified).
    """
    clqs = []

    # ── Metric ambiguity ──────────────────────────────────────────────────────
    if len(card.metric_columns) > 1 and "metric_col" not in params:
        # Only ask if the question does not already name a metric column
        named = any(
            col.lower() in question.lower() for col in card.metric_columns
        )
        if not named:
            clqs.append({
                "id": "metric_col",
                "text": (
                    f"Which metric should I use? Options: "
                    f"{', '.join(card.metric_columns)}"
                ),
                "kind": "choice",
                "choices": card.metric_columns,
            })

    # ── Time period ambiguity ─────────────────────────────────────────────────
    if (
        card.time_columns
        and "time_range" not in params
        and not _ALL_TIME_HINTS.search(question)
    ):
        # Check if a specific period is already mentioned
        period_mentioned = bool(re.search(
            r"\b(q[1-4]|fy\s*20\d\d|20\d\d|h[12]|jan|feb|mar|apr|may|jun|"
            r"jul|aug|sep|oct|nov|dec)\b",
            question, re.IGNORECASE,
        ))
        if not period_mentioned:
            clqs.append({
                "id": "time_range",
                "text": (
                    "What time range should I use? "
                    "(e.g. 'FY2025', 'Q1 2026', 'last year', 'all')"
                ),
                "kind": "freetext",
            })

    return clqs


# ── File loading helpers ───────────────────────────────────────────────────────

def _load_xlsx_rows(path: Path, max_rows: int = _MAX_COMPUTE_ROWS) -> list[dict]:
    """
    Stream an xlsx file into a list of row-dicts.
    Handles sparse rows (cell-reference encoding) for large files.
    Returns at most max_rows rows.
    """
    rows: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            # Shared strings
            ss_map: list[str] = []
            if "xl/sharedStrings.xml" in names:
                with zf.open("xl/sharedStrings.xml") as f:
                    ss_root = ET.parse(f).getroot()
                ns = _xlsx_ns(ss_root)
                for si in ss_root.iter(f"{ns}si"):
                    parts = [t.text or "" for t in si.iter(f"{ns}t")]
                    ss_map.append("".join(parts))

            # First worksheet
            sheet_files = sorted(
                n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml", n)
            )
            if not sheet_files:
                return rows
            with zf.open(sheet_files[0]) as f:
                ws_root = ET.parse(f).getroot()
            ns = _xlsx_ns(ws_root)

            # Parse header row first
            all_rows = list(ws_root.iter(f"{ns}row"))
            if not all_rows:
                return rows

            header_row = all_rows[0]
            headers = _parse_xlsx_header(header_row, ss_map, ns)

            for row_el in all_rows[1:]:
                if len(rows) >= max_rows:
                    break
                row_dict = _parse_xlsx_row(row_el, headers, ss_map, ns)
                if row_dict:
                    rows.append(row_dict)
    except Exception as exc:
        logger.warning("xlsx load failed for %s: %s", path, exc)
    return rows


def _xlsx_ns(root: ET.Element) -> str:
    """Extract the namespace URI from an xlsx XML element."""
    m = re.match(r"\{(.+?)\}", root.tag)
    return f"{{{m.group(1)}}}" if m else ""


def _col_letter_to_index(col_str: str) -> int:
    """Convert Excel column letter(s) to 0-based index (A→0, B→1, Z→25, AA→26)."""
    idx = 0
    for ch in col_str.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _parse_xlsx_header(row_el: ET.Element, ss_map: list[str], ns: str) -> list[str]:
    """Return ordered header names from the first worksheet row."""
    cells: dict[int, str] = {}
    for c in row_el.iter(f"{ns}c"):
        r_attr = c.get("r", "")
        col_letters = re.match(r"([A-Z]+)", r_attr)
        if not col_letters:
            continue
        col_idx = _col_letter_to_index(col_letters.group(1))
        t_attr = c.get("t", "")
        v_el = c.find(f"{ns}v")
        val = ""
        if v_el is not None and v_el.text:
            if t_attr == "s":
                try:
                    val = ss_map[int(v_el.text)]
                except (IndexError, ValueError):
                    val = v_el.text
            else:
                val = v_el.text
        cells[col_idx] = val
    if not cells:
        return []
    max_idx = max(cells)
    return [cells.get(i, f"col_{i}") for i in range(max_idx + 1)]


def _parse_xlsx_row(
    row_el: ET.Element,
    headers: list[str],
    ss_map: list[str],
    ns: str,
) -> dict | None:
    """Parse a data row into a dict keyed by header name."""
    cells: dict[int, Any] = {}
    for c in row_el.iter(f"{ns}c"):
        r_attr = c.get("r", "")
        col_letters = re.match(r"([A-Z]+)", r_attr)
        if not col_letters:
            continue
        col_idx = _col_letter_to_index(col_letters.group(1))
        t_attr = c.get("t", "")
        v_el = c.find(f"{ns}v")
        val: Any = None
        if v_el is not None and v_el.text:
            if t_attr == "s":
                try:
                    val = ss_map[int(v_el.text)]
                except (IndexError, ValueError):
                    val = v_el.text
            else:
                raw = v_el.text
                try:
                    val = int(float(raw)) if "." not in raw else float(raw)
                except ValueError:
                    val = raw
        cells[col_idx] = val

    if not cells:
        return None

    row_dict: dict[str, Any] = {}
    for i, header in enumerate(headers):
        row_dict[header] = cells.get(i)
    return row_dict


def _load_csv_rows(path: Path, max_rows: int = _MAX_COMPUTE_ROWS) -> list[dict]:
    import csv
    rows = []
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(dict(row))
    except Exception as exc:
        logger.warning("csv load failed for %s: %s", path, exc)
    return rows


def _load_json_rows(path: Path, max_rows: int = _MAX_COMPUTE_ROWS) -> list[dict]:
    rows = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".jsonl":
            for line in text.splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
                    if len(rows) >= max_rows:
                        break
        else:
            data = json.loads(text)
            if isinstance(data, list):
                rows = data[:max_rows]
            elif isinstance(data, dict):
                rows = [data]
    except Exception as exc:
        logger.warning("json load failed for %s: %s", path, exc)
    return rows


def _load_rows(path: Path) -> list[dict]:
    """Load tabular data from any supported format into list[dict]."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return _load_xlsx_rows(path)
    if suffix in (".csv", ".tsv"):
        return _load_csv_rows(path)
    if suffix in (".json", ".jsonl"):
        return _load_json_rows(path)
    return []


# ── Time filtering ─────────────────────────────────────────────────────────────

def _parse_time_filter(time_range: str) -> dict[str, Any]:
    """
    Parse a natural-language time range string into filter parameters.

    Returns a dict with keys:
        mode:  "all" | "year" | "quarter" | "period_label"
        years: list[int]   (for year/quarter)
        qtrs:  list[int]   (1-4, for quarter)
        label: str         (original input, always)
    """
    t = time_range.strip().lower()
    result: dict[str, Any] = {"mode": "all", "years": [], "qtrs": [], "label": time_range}

    if not t or t in ("all", "all time", "everything", "any"):
        return result

    # FY2025 or 2025
    fy_match = re.search(r"(?:fy\s*)?(\d{4})", t)
    yr = int(fy_match.group(1)) if fy_match else None

    # Q1/Q2/Q3/Q4
    q_match = re.search(r"q([1-4])", t)
    q = int(q_match.group(1)) if q_match else None

    if yr and q:
        result["mode"] = "quarter"
        result["years"] = [yr]
        result["qtrs"] = [q]
    elif yr:
        result["mode"] = "year"
        result["years"] = [yr]
    elif q:
        result["mode"] = "quarter"
        result["qtrs"] = [q]

    return result


def _coerce_year(raw: Any) -> int | None:
    """Coerce a raw year cell value to int, handling float-encoded ints."""
    if raw is None:
        return None
    try:
        return int(float(str(raw)))
    except (ValueError, TypeError):
        return None


def _quarter_of(raw: Any) -> int | None:
    """Infer quarter from a quarter string like 'Q1' or 'Q3 FY2026'."""
    if raw is None:
        return None
    m = re.search(r"q([1-4])", str(raw), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _filter_rows(
    rows: list[dict],
    time_col: str | None,
    time_filter: dict,
    entity_col: str | None,
    entity_value: str | None,
) -> list[dict]:
    """Apply time + entity filters to a list of row-dicts."""
    filtered = rows

    if time_col and time_filter["mode"] != "all":
        years = set(time_filter.get("years", []))
        qtrs = set(time_filter.get("qtrs", []))

        def _matches_time(row: dict) -> bool:
            val = row.get(time_col)
            if val is None:
                return False
            val_str = str(val).strip().lower()

            # Year column (integer)
            yr = _coerce_year(val)
            if yr is not None:
                if years and yr not in years:
                    return False
                return True

            # Quarter label column e.g. "Q1 FY2025"
            row_yr_m = re.search(r"(\d{4})", val_str)
            row_yr = int(row_yr_m.group(1)) if row_yr_m else None
            row_q = _quarter_of(val_str)

            if years and row_yr not in years:
                return False
            if qtrs and row_q not in qtrs:
                return False
            return True

        filtered = [r for r in filtered if _matches_time(r)]

    if entity_col and entity_value:
        ev = entity_value.strip().lower()
        filtered = [r for r in filtered if str(r.get(entity_col, "")).lower() == ev]

    return filtered


# ── Computation ────────────────────────────────────────────────────────────────

def _to_float(val: Any) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _aggregate(
    rows: list[dict],
    metric_col: str,
    group_col: str | None,
) -> dict[str, float]:
    """Sum metric_col, optionally grouped by group_col."""
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        val = _to_float(row.get(metric_col))
        if val is None:
            continue
        key = str(row.get(group_col, "__total__")) if group_col else "__total__"
        totals[key] += val
    return dict(totals)


def _top_n_by(totals: dict[str, float], n: int = 10) -> list[tuple[str, float]]:
    return sorted(totals.items(), key=lambda x: x[1], reverse=True)[:n]


def _attrition_pivot(
    rows: list[dict],
    entity_col: str,
    time_col: str,
    metric_col: str,
) -> dict[str, Any]:
    """
    Identify entities present in an earlier period but absent in the latest.
    Returns {"churned": [(entity, last_revenue), …], "at_risk_total": float}
    """
    # Collect unique time values and sort them
    time_vals: list[Any] = sorted(
        set(_coerce_year(r.get(time_col)) or str(r.get(time_col, "")) for r in rows),
        key=lambda x: (str(x), ),
    )
    if len(time_vals) < 2:
        return {"churned": [], "at_risk_total": 0.0, "note": "Need at least 2 time periods"}

    latest = time_vals[-1]
    previous_periods = set(time_vals[:-1])

    entities_in_latest: set[str] = set()
    entities_in_previous: dict[str, float] = {}

    for row in rows:
        entity = str(row.get(entity_col, ""))
        tv = _coerce_year(row.get(time_col)) or str(row.get(time_col, ""))
        rev = _to_float(row.get(metric_col)) or 0.0

        if tv == latest:
            entities_in_latest.add(entity)
        if tv in previous_periods:
            entities_in_previous[entity] = entities_in_previous.get(entity, 0.0) + rev

    churned = [
        (e, entities_in_previous[e])
        for e in entities_in_previous
        if e not in entities_in_latest
    ]
    churned.sort(key=lambda x: x[1], reverse=True)
    at_risk_total = sum(v for _, v in churned)

    return {
        "churned": churned,
        "at_risk_total": at_risk_total,
        "latest_period": latest,
        "previous_periods": list(previous_periods),
    }


def _trend_pivot(
    rows: list[dict],
    metric_col: str,
    time_col: str,
    include_deltas: bool = True,
) -> dict[str, Any]:
    """
    Build a period × metric table and optionally append period-over-period
    delta columns (absolute and percentage change).

    Returns:
        {
            "periods":        list[str]          — sorted period labels
            "values":         list[float]         — metric total per period
            "delta_abs":      list[float | None]  — absolute PoP change
                                                     (None for first period)
            "delta_pct":      list[float | None]  — percentage PoP change
                                                     (None for first period or
                                                      zero base)
            "period_col":     str                 — time column used
            "metric_col":     str                 — metric column used
            "note":           str                 — human-readable note
        }
    """
    # Accumulate totals keyed by period label
    period_totals: dict[str, float] = defaultdict(float)
    for row in rows:
        val = _to_float(row.get(metric_col))
        if val is None:
            continue
        period_key = str(row.get(time_col, "")).strip()
        if period_key:
            period_totals[period_key] += val

    if not period_totals:
        return {
            "periods": [],
            "values": [],
            "delta_abs": [],
            "delta_pct": [],
            "period_col": time_col,
            "metric_col": metric_col,
            "note": "No data found for trend calculation.",
        }

    # Sort periods: numeric years first, then quarter labels, then alpha
    def _period_sort_key(p: str) -> tuple:
        # Try pure year
        yr_m = re.fullmatch(r"\d{4}", p.strip())
        if yr_m:
            return (0, int(p.strip()), 0, p)
        # Quarter label: "Q1 2025", "Q3 FY2026"
        q_m = re.search(r"q([1-4]).*?(\d{4})", p, re.IGNORECASE)
        if q_m:
            return (0, int(q_m.group(2)), int(q_m.group(1)), p)
        # Year first: "2025 Q3"
        yq_m = re.search(r"(\d{4}).*?q([1-4])", p, re.IGNORECASE)
        if yq_m:
            return (0, int(yq_m.group(1)), int(yq_m.group(2)), p)
        # Half-year: "H1 2025"
        h_m = re.search(r"h([12]).*?(\d{4})", p, re.IGNORECASE)
        if h_m:
            return (0, int(h_m.group(2)), int(h_m.group(1)), p)
        # Bare number
        try:
            return (0, float(p.strip()), 0, p)
        except ValueError:
            return (1, 0, 0, p)

    sorted_periods = sorted(period_totals.keys(), key=_period_sort_key)
    values = [period_totals[p] for p in sorted_periods]

    delta_abs: list[float | None] = [None]
    delta_pct: list[float | None] = [None]

    if include_deltas:
        for i in range(1, len(values)):
            prev = values[i - 1]
            curr = values[i]
            d_abs = curr - prev
            delta_abs.append(d_abs)
            delta_pct.append((d_abs / prev * 100) if prev != 0 else None)
    else:
        delta_abs = [None] * len(values)
        delta_pct = [None] * len(values)

    return {
        "periods": sorted_periods,
        "values": values,
        "delta_abs": delta_abs,
        "delta_pct": delta_pct,
        "period_col": time_col,
        "metric_col": metric_col,
        "note": f"{len(sorted_periods)} periods found.",
    }


def _format_number(n: float) -> str:
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:,.2f}M"
    if abs(n) >= 1_000:
        return f"${n/1_000:,.1f}K"
    return f"${n:,.2f}"


# ── Chart-data builder ─────────────────────────────────────────────────────────

def _make_chart_data(
    chart_type: str,
    labels: list[str],
    datasets: list[dict],
) -> dict[str, Any]:
    """
    Produce a host-agnostic chart-data block alongside a CSV attachment and a
    Mermaid xychart-beta snippet.

    Args:
        chart_type: "bar" | "line" | "bar_horizontal"
        labels:     Category / period labels (x-axis for bar/line).
        datasets:   [{"label": str, "data": [float, …]}, …]

    Returns:
        {
            "type":     str,
            "labels":   list[str],
            "datasets": list[{"label": str, "data": list[float]}],
            "csv":      str,       # inline CSV of the same data
            "mermaid":  str,       # xychart-beta fenced block (omitted when
                                   # the data exceeds Mermaid's practical limits)
        }

    The "csv" field uses comma-separated values with a header row so it can be
    saved directly as a .csv file or passed to a spreadsheet tool.

    The "mermaid" field is best-effort: Mermaid xychart-beta does not support
    negative values or more than one y-axis, so it is omitted when those
    conditions arise.  Callers should fall back to the "csv" field in those
    cases.
    """
    import csv as _csv

    # ── CSV ───────────────────────────────────────────────────────────────────
    buf = io.StringIO()
    writer = _csv.writer(buf)
    ds_labels = [ds["label"] for ds in datasets]
    writer.writerow(["period"] + ds_labels)
    for i, label in enumerate(labels):
        row_vals = [ds["data"][i] if i < len(ds["data"]) else "" for ds in datasets]
        writer.writerow([label] + row_vals)
    csv_str = buf.getvalue()

    # ── Mermaid xychart-beta ──────────────────────────────────────────────────
    mermaid_str = ""
    # xychart-beta only handles a single y-dataset cleanly; skip multi-series
    # and skip when any value is negative (Mermaid renders those incorrectly).
    if len(datasets) == 1:
        data_vals = datasets[0]["data"]
        if all(v >= 0 for v in data_vals) and labels:
            # Mermaid x-axis items must be quoted strings; cap at 12 labels for
            # readability — beyond that the axis text overlaps.
            trunc = labels[:12]
            trunc_vals = data_vals[:12]
            suffix = " (truncated to 12 periods)" if len(labels) > 12 else ""
            x_items = " ".join(f'"{lbl}"' for lbl in trunc)
            y_items = " ".join(str(round(v, 2)) for v in trunc_vals)
            chart_kw = "bar" if chart_type in ("bar", "bar_horizontal") else "line"
            ds_title = datasets[0]["label"]
            mermaid_str = (
                f"```mermaid\n"
                f"xychart-beta\n"
                f'  title "{ds_title}{suffix}"\n'
                f"  x-axis [{x_items}]\n"
                f'  y-axis "{ds_title}"\n'
                f"  {chart_kw} [{y_items}]\n"
                f"```"
            )

    return {
        "type": chart_type,
        "labels": labels,
        "datasets": datasets,
        "csv": csv_str,
        "mermaid": mermaid_str,
    }


# ── Answer builder ─────────────────────────────────────────────────────────────

def _build_answer(
    question: str,
    rows: list[dict],
    card: DataCard,
    params: dict[str, Any],
) -> tuple[str, str, list[str], dict[str, Any] | None]:
    """
    Compute an answer from raw rows + resolved params.

    Returns (answer_text, reasoning_text, suggested_followups, chart_data).
    chart_data is None when the answer type has no meaningful visualisation
    (scalar totals, summaries, document passthrough, attrition lists).
    """
    q_lower = question.lower()
    metric_col: str = params.get("metric_col") or (card.metric_columns[0] if card.metric_columns else "")
    time_col: str = params.get("time_col") or (card.time_columns[0] if card.time_columns else "")
    entity_col: str = params.get("entity_col") or (card.entity_columns[0] if card.entity_columns else "")
    time_range_str: str = params.get("time_range", "all")
    entity_filter: str = params.get("entity_filter", "")
    top_n: int = int(params.get("top_n", 10))

    time_filter = _parse_time_filter(time_range_str)

    # Apply filters
    filtered = _filter_rows(rows, time_col or None, time_filter, entity_col or None, entity_filter or None)
    n_rows = len(filtered)
    filter_desc_parts = []
    if time_filter["mode"] != "all" and time_col:
        filter_desc_parts.append(f"time={time_range_str}")
    if entity_filter:
        filter_desc_parts.append(f"{entity_col}={entity_filter}")
    filter_desc = f" (filtered: {', '.join(filter_desc_parts)})" if filter_desc_parts else " (all data)"

    reasoning_parts: list[str] = [
        f"File: {card.file_name}",
        f"Rows after filter: {n_rows:,} of {card.total_rows:,}{filter_desc}",
        f"Metric column: {metric_col or '(none)'}",
    ]

    followups: list[str] = []

    # ── Attrition / churn detection ───────────────────────────────────────────
    if any(w in q_lower for w in ("churn", "attrition", "at-risk", "at risk", "not renew", "did not appear", "missing")):
        if metric_col and time_col and entity_col:
            result = _attrition_pivot(filtered, entity_col, time_col, metric_col)
            churned = result["churned"]
            total = result["at_risk_total"]
            latest = result["latest_period"]
            prev = result["previous_periods"]
            reasoning_parts += [
                f"Method: compared entity sets across periods",
                f"Latest period: {latest}",
                f"Previous periods: {prev}",
                f"Churned / at-risk count: {len(churned)}",
            ]
            top_list = churned[:top_n]
            rows_txt = "\n".join(
                f"  {i+1}. {e} — {_format_number(v)}"
                for i, (e, v) in enumerate(top_list)
            )
            answer = (
                f"**Attrition analysis{filter_desc}**\n\n"
                f"Found **{len(churned):,} {entity_col}(s)** present in earlier periods "
                f"but absent in the latest period ({latest}).\n\n"
                f"**Total revenue at risk:** {_format_number(total)}\n\n"
                f"**Top {len(top_list)} at-risk by {metric_col}:**\n{rows_txt}"
            )
            followups = [
                f"Which segment (industry, geo, product) has the most attrition?",
                f"What was the revenue trend for the top at-risk customers before they churned?",
                f"How does this compare to the previous period's attrition?",
            ]
            # Attrition: bar chart of at-risk entities, capped at top_n
            if top_list:
                chart_data: dict[str, Any] | None = _make_chart_data(
                    "bar_horizontal",
                    [e for e, _ in top_list],
                    [{"label": f"At-risk {metric_col}", "data": [v for _, v in top_list]}],
                )
            else:
                chart_data = None
            return answer, "\n".join(reasoning_parts), followups, chart_data

    # ── Trend / time-series ───────────────────────────────────────────────────
    if any(w in q_lower for w in (
        "trend", "over time", "over q", "quarter by quarter", "quarterly",
        "year over year", "yoy", "qoq", "period over period", "each quarter",
        "each year", "by quarter", "by year", "growth rate", "how has",
        "how did", "compare periods", "compare quarters",
    )):
        if metric_col and time_col:
            pivot = _trend_pivot(filtered, metric_col, time_col, include_deltas=True)
            periods = pivot["periods"]
            values = pivot["values"]
            delta_abs = pivot["delta_abs"]
            delta_pct = pivot["delta_pct"]

            reasoning_parts += [
                f"Operation: TREND_PIVOT({metric_col}, {time_col})",
                f"Periods found: {len(periods)}",
            ]

            if not periods:
                return (
                    f"No data found to build a trend for **{metric_col}** over **{time_col}**{filter_desc}.",
                    "\n".join(reasoning_parts),
                    [f"Try a broader time range or check your filters."],
                    None,
                )

            # Build the period × metric table with delta columns
            header = f"{'Period':<18} {'Value':>14}  {'Δ Abs':>14}  {'Δ %':>8}"
            sep = "─" * len(header)
            rows_txt_parts = [header, sep]
            for i, (p, v) in enumerate(zip(periods, values)):
                d_abs = delta_abs[i]
                d_pct = delta_pct[i]
                d_abs_str = _format_number(d_abs) if d_abs is not None else "—"
                if d_pct is not None:
                    arrow = "▲" if d_pct >= 0 else "▼"
                    d_pct_str = f"{arrow} {abs(d_pct):.1f}%"
                else:
                    d_pct_str = "—"
                rows_txt_parts.append(
                    f"{p:<18} {_format_number(v):>14}  {d_abs_str:>14}  {d_pct_str:>8}"
                )

            table = "\n".join(rows_txt_parts)
            overall_change = values[-1] - values[0] if len(values) > 1 else 0.0
            overall_pct = (overall_change / values[0] * 100) if values[0] != 0 else None
            pct_summary = (
                f" ({'+' if overall_change >= 0 else ''}{overall_pct:.1f}% overall)"
                if overall_pct is not None else ""
            )
            answer = (
                f"**Trend: {metric_col} by {time_col}{filter_desc}**\n\n"
                f"```\n{table}\n```\n\n"
                f"**{periods[0]} → {periods[-1]}:** "
                f"{_format_number(values[0])} → {_format_number(values[-1])}"
                f"{pct_summary}"
            )
            followups = [
                f"Which {entity_col} drove the biggest change?" if entity_col else
                "Which segment drove the biggest change?",
                f"Show the trend broken down by {entity_col}." if entity_col else
                "Can you break this trend down by category?",
                f"Are there any customers at risk based on this trend?" if entity_col else
                "What is causing the trend?",
            ]
            # Trend: line chart — periods on x, values on y
            chart_data = _make_chart_data(
                "line",
                periods,
                [{"label": metric_col, "data": values}],
            )
            return answer, "\n".join(reasoning_parts), followups, chart_data

    # ── Total / sum ───────────────────────────────────────────────────────────
    if any(w in q_lower for w in ("total", "sum", "how much", "overall", "aggregate")):
        if metric_col:
            totals = _aggregate(filtered, metric_col, None)
            grand_total = totals.get("__total__", 0.0)
            reasoning_parts.append(f"Operation: SUM({metric_col})")
            answer = (
                f"**Total {metric_col}{filter_desc}:** {_format_number(grand_total)}\n\n"
                f"Computed across {n_rows:,} rows."
            )
            followups = [
                f"Break down by {entity_col}?" if entity_col else "Break this down by category?",
                f"How has this changed over time?" if time_col else "How does this compare to other periods?",
            ]
            # Scalar total — no chart
            return answer, "\n".join(reasoning_parts), followups, None

    # ── Top N by entity ───────────────────────────────────────────────────────
    if any(w in q_lower for w in ("top", "biggest", "largest", "highest", "ranking", "rank")):
        if metric_col and entity_col:
            totals = _aggregate(filtered, metric_col, entity_col)
            top_list = _top_n_by(totals, top_n)
            reasoning_parts += [
                f"Operation: GROUP BY {entity_col}, SUM({metric_col}), ORDER DESC",
                f"Distinct {entity_col} values: {len(totals):,}",
            ]
            rows_txt = "\n".join(
                f"  {i+1}. {e} — {_format_number(v)}"
                for i, (e, v) in enumerate(top_list)
            )
            grand_total = sum(totals.values())
            top_share = sum(v for _, v in top_list) / grand_total * 100 if grand_total else 0.0
            answer = (
                f"**Top {len(top_list)} {entity_col} by {metric_col}{filter_desc}**\n\n"
                f"{rows_txt}\n\n"
                f"These top {len(top_list)} account for "
                f"**{top_share:.1f}%** of total {_format_number(grand_total)}."
            )
            followups = [
                f"Which of these customers are at risk of churning?",
                f"Show me the year-over-year trend for the top 3.",
                f"How does {entity_col} concentration compare to last year?",
            ]
            # Top-N: horizontal bar (many labels → better readability)
            chart_data = _make_chart_data(
                "bar_horizontal",
                [e for e, _ in top_list],
                [{"label": metric_col, "data": [v for _, v in top_list]}],
            )
            return answer, "\n".join(reasoning_parts), followups, chart_data

    # ── Breakdown / group-by ──────────────────────────────────────────────────
    if any(w in q_lower for w in ("breakdown", "by ", "split", "group", "per ", "each")):
        # Identify the most likely group column from question text
        group_col = entity_col
        for col in card.entity_columns + card.time_columns:
            if col.lower() in q_lower:
                group_col = col
                break
        if metric_col and group_col:
            totals = _aggregate(filtered, metric_col, group_col)
            sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
            reasoning_parts += [
                f"Operation: GROUP BY {group_col}, SUM({metric_col})",
                f"Distinct groups: {len(totals):,}",
            ]
            rows_txt = "\n".join(
                f"  {g}: {_format_number(v)}"
                for g, v in sorted_items[:25]
            )
            answer = (
                f"**{metric_col} breakdown by {group_col}{filter_desc}**\n\n"
                f"{rows_txt}"
                + (f"\n\n_(showing top 25 of {len(sorted_items):,} groups)_" if len(sorted_items) > 25 else "")
            )
            followups = [
                f"What is the period-over-period change per {group_col}?",
                f"Which {group_col} is growing fastest?",
            ]
            # Breakdown: vertical bar for first 25 groups
            visible = sorted_items[:25]
            chart_data = _make_chart_data(
                "bar",
                [g for g, _ in visible],
                [{"label": metric_col, "data": [v for _, v in visible]}],
            )
            return answer, "\n".join(reasoning_parts), followups, chart_data

    # ── Summary / data quality ────────────────────────────────────────────────
    if any(w in q_lower for w in ("summary", "overview", "describe", "what is this", "data quality", "quality")):
        reasoning_parts.append("Operation: PROFILE (summary)")
        answer = (
            f"**File summary: {card.file_name}**\n\n"
            f"{card.summary}\n\n"
            f"**Key facts:**\n"
            f"  • Rows: {card.total_rows:,}\n"
            f"  • Columns: {card.total_columns}\n"
            f"  • Time range: {card.time_range}\n"
            f"  • Metric columns: {', '.join(card.metric_columns) or 'none'}\n"
            f"  • Entity columns: {', '.join(card.entity_columns) or 'none'}\n"
        )
        if card.warnings:
            answer += "\n**Warnings:**\n" + "\n".join(f"  ⚠ {w}" for w in card.warnings)
        followups = [
            "What are the top customers by revenue?",
            "Are there any data quality issues I should know about?",
        ]
        return answer, "\n".join(reasoning_parts), followups, None

    # ── Fallback: total of first metric ──────────────────────────────────────
    if metric_col:
        totals = _aggregate(filtered, metric_col, None)
        grand_total = totals.get("__total__", 0.0)
        reasoning_parts.append(f"Operation: SUM({metric_col}) [fallback]")
        answer = (
            f"**{metric_col}{filter_desc}:** {_format_number(grand_total)}\n\n"
            f"Computed across {n_rows:,} rows."
        )
        followups = [
            f"Break this down by {entity_col}?" if entity_col else "Can you break this down further?",
        ]
        return answer, "\n".join(reasoning_parts), followups, None

    # ── Pure document fallback ────────────────────────────────────────────────
    reasoning_parts.append("Operation: DOCUMENT PASSTHROUGH (no tabular data)")
    return (
        "This file does not contain tabular data that can be computed directly. "
        "Try using the main KB search tool to query this document semantically.",
        "\n".join(reasoning_parts),
        [],
        None,
    )


# ── Public entry points ────────────────────────────────────────────────────────

async def query_data(
    path: str,
    question: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Main entry point.  Given a file path and a natural-language question:

      1. Inspect the file (cached DataCard).
      2. Check if clarification is needed.
      3a. Return clarifying questions if yes.
      3b. Load data, compute answer, return answer + reasoning if no.

    session_id is created automatically if not provided.
    """
    sid = session_id or str(uuid.uuid4())
    sess = await load_session(sid)

    warnings: list[str] = []
    file_path = Path(path)
    if not file_path.is_absolute():
        # Try resolving relative to the KB root
        from kb_agent_mcp.config import cfg as _cfg
        file_path = _cfg.kb_root_path / path

    if not file_path.exists():
        return {
            "status": "error",
            "session_id": sid,
            "question": question,
            "error": f"File not found: {path}",
        }

    # ── DataCard ──────────────────────────────────────────────────────────────
    try:
        card = await inspect_file(str(file_path))
    except Exception as exc:
        logger.exception("inspect_file failed for %s", file_path)
        return {
            "status": "error",
            "session_id": sid,
            "question": question,
            "error": f"Could not profile file: {exc}",
        }

    # Persist file context in session
    sess.file_path = str(file_path)
    sess.original_question = sess.original_question or question
    if not sess.data_card:
        sess.data_card = data_card_to_dict(card)

    await add_turn(sess, "user", question)

    # ── Clarification check ───────────────────────────────────────────────────
    clqs = _needs_clarification(question, card, sess.params)
    if clqs:
        sess.pending_clarifications = clqs
        await save_session(sess)
        clq_text = "\n".join(
            f"  {i+1}. {q['text']}" for i, q in enumerate(clqs)
        )
        clarification_summary = (
            f"Before I can answer, I need a few details:\n{clq_text}"
        )
        await add_turn(sess, "analyst", clarification_summary)
        return {
            "status": "clarifying",
            "session_id": sid,
            "question": question,
            "clarifications": clqs,
            "message": clarification_summary,
            "warnings": warnings,
        }

    # ── Load data ─────────────────────────────────────────────────────────────
    try:
        rows = await asyncio.to_thread(_load_rows, file_path)
    except Exception as exc:
        logger.exception("_load_rows failed for %s", file_path)
        return {
            "status": "error",
            "session_id": sid,
            "question": question,
            "error": f"Could not load file data: {exc}",
        }

    if not rows and card.file_format != "tabular":
        warnings.append("No tabular data found; file appears to be a document.")

    if card.total_rows > _MAX_COMPUTE_ROWS:
        warnings.append(
            f"File has {card.total_rows:,} rows; loaded {min(len(rows), _MAX_COMPUTE_ROWS):,} for computation."
        )

    # ── Compute ───────────────────────────────────────────────────────────────
    try:
        answer, reasoning, followups, chart_data = await asyncio.to_thread(
            _build_answer, question, rows, card, sess.params
        )
    except Exception as exc:
        logger.exception("_build_answer failed")
        return {
            "status": "error",
            "session_id": sid,
            "question": question,
            "error": f"Computation failed: {exc}",
        }

    sess.last_answer = answer
    sess.last_reasoning = reasoning
    sess.suggested_followups = followups
    await add_turn(sess, "analyst", answer)

    return {
        "status": "answered",
        "session_id": sid,
        "question": question,
        "answer": answer,
        "reasoning": reasoning,
        "suggested_followups": followups,
        "warnings": warnings,
        "chart_data": chart_data,
    }


async def refine_query(
    session_id: str,
    feedback: str,
) -> dict[str, Any]:
    """
    Re-run the last query with updated parameters extracted from user feedback.

    Feedback can be:
      • A clarification answer (e.g. "FY2025", "Rev Act @ PC", "top 20")
      • A correction (e.g. "actually use the Q4 data only")
      • A follow-up (e.g. "now group by geography instead")
    """
    sess = await load_session(session_id)
    if not sess.file_path:
        return {
            "status": "error",
            "session_id": session_id,
            "question": feedback,
            "error": "No active analyst session found for this session_id.",
        }

    # ── Apply clarification answers from feedback ─────────────────────────────
    _apply_clarification_feedback(feedback, sess)

    # Re-run with updated params
    return await query_data(
        path=sess.file_path,
        question=sess.original_question,
        session_id=session_id,
    )


def _apply_clarification_feedback(feedback: str, sess: AnalystSession) -> None:
    """
    Parse free-text feedback and update sess.params with any recognised values.
    Called before re-running the query.
    """
    fb = feedback.strip()

    # Year pattern: "FY2025", "2025", "2026"
    fy_m = re.search(r"(?:fy\s*)?(\d{4})", fb, re.IGNORECASE)
    if fy_m and "time_range" not in sess.params:
        sess.params["time_range"] = fb

    # Quarter pattern: "Q1", "Q3 2025"
    q_m = re.search(r"q([1-4])", fb, re.IGNORECASE)
    if q_m and "time_range" not in sess.params:
        sess.params["time_range"] = fb

    # "all" / "all time"
    if re.match(r"\ball(\s+time)?\b", fb, re.IGNORECASE) and "time_range" not in sess.params:
        sess.params["time_range"] = "all"

    # Top N: "top 20", "20", "show me 50"
    top_m = re.search(r"(?:top\s+)?(\d+)(?:\s+results?)?", fb, re.IGNORECASE)
    if top_m and len(fb.split()) <= 4:
        sess.params["top_n"] = int(top_m.group(1))

    # Pending clarification answers in order
    if sess.pending_clarifications:
        clq = sess.pending_clarifications[0]
        cid = clq["id"]
        if cid not in sess.params:
            if clq.get("kind") == "choice":
                # Match against available choices (case-insensitive substring)
                choices = clq.get("choices", [])
                for ch in choices:
                    if ch.lower() in fb.lower():
                        sess.params[cid] = ch
                        break
                else:
                    # Store as-is if no exact match
                    sess.params[cid] = fb
            else:
                sess.params[cid] = fb
            sess.pending_clarifications = sess.pending_clarifications[1:]


# ── Multi-file comparison ──────────────────────────────────────────────────────

def _resolve_col(
    preferred: str | None,
    candidates: list[str],
    question: str,
) -> str | None:
    """
    Pick a column name from *candidates*.

    Priority:
      1. *preferred* if it is non-empty (caller-supplied param).
      2. Any candidate whose name appears verbatim in *question*.
      3. First candidate.
    """
    if preferred:
        return preferred
    q = question.lower()
    for col in candidates:
        if col.lower() in q:
            return col
    return candidates[0] if candidates else None


def _compare_files(
    path_a: Path,
    path_b: Path,
    card_a: DataCard,
    card_b: DataCard,
    question: str,
    params: dict[str, Any],
) -> tuple[str, str, list[str]]:
    """
    Load both files, aggregate each by time period, and produce a side-by-side
    diff table with absolute and percentage delta columns (B − A).

    Returns (answer_text, reasoning_text, suggested_followups).
    """
    # ── Resolve columns ───────────────────────────────────────────────────────
    metric_col_a = _resolve_col(
        params.get("metric_col"), card_a.metric_columns, question
    )
    metric_col_b = _resolve_col(
        params.get("metric_col_b") or params.get("metric_col"),
        card_b.metric_columns,
        question,
    )
    time_col_a = _resolve_col(
        params.get("time_col"), card_a.time_columns, question
    )
    time_col_b = _resolve_col(
        params.get("time_col_b") or params.get("time_col"),
        card_b.time_columns,
        question,
    )

    warnings: list[str] = []

    if not metric_col_a:
        return (
            f"File A ({path_a.name}) has no numeric metric columns to compare.",
            f"File A metric columns: {card_a.metric_columns}",
            [],
            None,
        )
    if not metric_col_b:
        return (
            f"File B ({path_b.name}) has no numeric metric columns to compare.",
            f"File B metric columns: {card_b.metric_columns}",
            [],
            None,
        )

    # ── Load rows ─────────────────────────────────────────────────────────────
    rows_a = _load_rows(path_a)
    rows_b = _load_rows(path_b)

    reasoning_parts: list[str] = [
        f"File A: {path_a.name}  ({len(rows_a):,} rows)",
        f"File B: {path_b.name}  ({len(rows_b):,} rows)",
        f"Metric A: {metric_col_a}   Metric B: {metric_col_b}",
        f"Time A:   {time_col_a or '(none)'}   Time B: {time_col_b or '(none)'}",
    ]

    # ── Aggregate each file by period ─────────────────────────────────────────
    def _period_totals(
        rows: list[dict],
        metric: str,
        time_col: str | None,
        label: str,
    ) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for row in rows:
            val = _to_float(row.get(metric))
            if val is None:
                continue
            if time_col:
                key = str(row.get(time_col, "")).strip() or f"(no {time_col})"
            else:
                key = label            # single bucket when no time column
            totals[key] += val
        return dict(totals)

    totals_a = _period_totals(rows_a, metric_col_a, time_col_a, path_a.stem)
    totals_b = _period_totals(rows_b, metric_col_b, time_col_b, path_b.stem)

    # ── Align periods ─────────────────────────────────────────────────────────
    def _period_sort_key(p: str) -> tuple:
        yr_m = re.fullmatch(r"\d{4}", p.strip())
        if yr_m:
            return (0, int(p.strip()), 0, p)
        q_m = re.search(r"q([1-4]).*?(\d{4})", p, re.IGNORECASE)
        if q_m:
            return (0, int(q_m.group(2)), int(q_m.group(1)), p)
        yq_m = re.search(r"(\d{4}).*?q([1-4])", p, re.IGNORECASE)
        if yq_m:
            return (0, int(yq_m.group(1)), int(yq_m.group(2)), p)
        h_m = re.search(r"h([12]).*?(\d{4})", p, re.IGNORECASE)
        if h_m:
            return (0, int(h_m.group(2)), int(h_m.group(1)), p)
        try:
            return (0, float(p.strip()), 0, p)
        except ValueError:
            return (1, 0, 0, p)

    all_periods = sorted(
        set(totals_a) | set(totals_b),
        key=_period_sort_key,
    )

    if not all_periods:
        return (
            "No data found in either file for comparison.",
            "\n".join(reasoning_parts),
            [],
        )

    if len(totals_a) == 0:
        warnings.append(f"File A ({path_a.name}) had no rows with a valid {metric_col_a} value.")
    if len(totals_b) == 0:
        warnings.append(f"File B ({path_b.name}) had no rows with a valid {metric_col_b} value.")

    # ── Build diff table ──────────────────────────────────────────────────────
    col_w = 18
    val_w = 14
    header = (
        f"{'Period':<{col_w}} "
        f"{'A: ' + path_a.stem:>{val_w}}  "
        f"{'B: ' + path_b.stem:>{val_w}}  "
        f"{'Δ Abs':>{val_w}}  "
        f"{'Δ %':>8}"
    )
    sep = "─" * len(header)
    table_lines = [header, sep]

    grand_a = grand_b = 0.0
    for period in all_periods:
        val_a = totals_a.get(period)
        val_b = totals_b.get(period)

        va_f = val_a if val_a is not None else 0.0
        vb_f = val_b if val_b is not None else 0.0

        grand_a += va_f
        grand_b += vb_f

        d_abs = vb_f - va_f
        d_pct: float | None = (d_abs / va_f * 100) if va_f != 0 else None

        va_str = _format_number(va_f) if val_a is not None else "—"
        vb_str = _format_number(vb_f) if val_b is not None else "—"
        d_abs_str = _format_number(d_abs)
        if d_pct is not None:
            arrow = "▲" if d_pct >= 0 else "▼"
            d_pct_str = f"{arrow} {abs(d_pct):.1f}%"
        else:
            d_pct_str = "n/a"

        table_lines.append(
            f"{period:<{col_w}} "
            f"{va_str:>{val_w}}  "
            f"{vb_str:>{val_w}}  "
            f"{d_abs_str:>{val_w}}  "
            f"{d_pct_str:>8}"
        )

    # ── Grand total row ───────────────────────────────────────────────────────
    if len(all_periods) > 1:
        table_lines.append(sep)
        gt_d = grand_b - grand_a
        gt_pct: float | None = (gt_d / grand_a * 100) if grand_a != 0 else None
        gt_pct_str = (
            f"{'▲' if gt_pct >= 0 else '▼'} {abs(gt_pct):.1f}%"
            if gt_pct is not None else "n/a"
        )
        table_lines.append(
            f"{'TOTAL':<{col_w}} "
            f"{_format_number(grand_a):>{val_w}}  "
            f"{_format_number(grand_b):>{val_w}}  "
            f"{_format_number(gt_d):>{val_w}}  "
            f"{gt_pct_str:>8}"
        )

    table = "\n".join(table_lines)

    # ── Narrative summary ─────────────────────────────────────────────────────
    overall_d = grand_b - grand_a
    overall_pct = (overall_d / grand_a * 100) if grand_a != 0 else None
    pct_text = (
        f" ({'+' if overall_d >= 0 else ''}{overall_pct:.1f}%)"
        if overall_pct is not None else ""
    )

    label_a = f"{path_a.name}"
    label_b = f"{path_b.name}"
    if metric_col_a == metric_col_b:
        metric_label = metric_col_a
    else:
        metric_label = f"{metric_col_a} vs {metric_col_b}"

    answer = (
        f"**Comparison: {label_a} vs {label_b}**  \n"
        f"Metric: `{metric_label}` · Periods: {len(all_periods)}\n\n"
        f"```\n{table}\n```\n\n"
        f"**Overall:** {_format_number(grand_a)} → {_format_number(grand_b)}{pct_text}"
    )

    reasoning_parts.append(f"Periods aligned: {len(all_periods)}")
    if warnings:
        reasoning_parts += [f"Warning: {w}" for w in warnings]

    followups = [
        "Which specific customers or entities drove the biggest change between the two files?",
        f"Show the top movers (entities with the largest Δ) between {path_a.stem} and {path_b.stem}.",
        "Are there any periods present in one file but missing from the other?",
    ]

    # ── Chart for comparison: grouped bar — one dataset per file ─────────────
    # Build per-file value lists aligned to all_periods (0 for absent periods).
    vals_a = [totals_a.get(p, 0.0) for p in all_periods]
    vals_b = [totals_b.get(p, 0.0) for p in all_periods]
    compare_chart = _make_chart_data(
        "bar",
        all_periods,
        [
            {"label": f"A: {path_a.stem}", "data": vals_a},
            {"label": f"B: {path_b.stem}", "data": vals_b},
        ],
    )

    return answer, "\n".join(reasoning_parts), followups, compare_chart


async def compare_data(
    path_a: str,
    path_b: str,
    question: str = "",
    session_id: str | None = None,
    metric_col: str = "",
    time_col: str = "",
) -> dict[str, Any]:
    """
    Compare two tabular files side-by-side.

    Aggregates each file by time period (if a time column exists) or as a
    single total, then emits a diff table showing absolute and percentage
    change (B − A) for each period plus a grand-total row.

    Args:
        path_a:     First file path (absolute or relative to KB_ROOT).
        path_b:     Second file path (absolute or relative to KB_ROOT).
        question:   Optional natural-language question to guide column selection.
        session_id: Optional session ID; auto-created if blank.
        metric_col: Override metric column (must exist in both files, or use
                    metric_col_b in params for per-file override).
        time_col:   Override time column (same rules as metric_col).

    Returns a dict with keys:
        status, session_id, question, answer, reasoning,
        suggested_followups, warnings, file_a, file_b, chart_data
        (plus "error" when status == "error").
    """
    sid = session_id or str(uuid.uuid4())
    warnings: list[str] = []

    def _resolve_path(p: str) -> Path:
        fp = Path(p)
        if not fp.is_absolute():
            from kb_agent_mcp.config import cfg as _cfg
            fp = _cfg.kb_root_path / p
        return fp

    file_a = _resolve_path(path_a)
    file_b = _resolve_path(path_b)

    for label, fp in (("path_a", file_a), ("path_b", file_b)):
        if not fp.exists():
            return {
                "status": "error",
                "session_id": sid,
                "question": question,
                "error": f"File not found ({label}): {fp}",
                "file_a": str(file_a),
                "file_b": str(file_b),
                "warnings": warnings,
            }

    # Inspect both files (cached)
    try:
        card_a, card_b = await asyncio.gather(
            inspect_file(str(file_a)),
            inspect_file(str(file_b)),
        )
    except Exception as exc:
        logger.exception("inspect_file failed during compare_data")
        return {
            "status": "error",
            "session_id": sid,
            "question": question,
            "error": f"Could not profile files: {exc}",
            "file_a": str(file_a),
            "file_b": str(file_b),
            "warnings": warnings,
        }

    params: dict[str, Any] = {}
    if metric_col:
        params["metric_col"] = metric_col
    if time_col:
        params["time_col"] = time_col

    try:
        answer, reasoning, followups, chart_data = await asyncio.to_thread(
            _compare_files,
            file_a, file_b, card_a, card_b,
            question or f"Compare {file_a.name} vs {file_b.name}",
            params,
        )
    except Exception as exc:
        logger.exception("_compare_files failed")
        return {
            "status": "error",
            "session_id": sid,
            "question": question,
            "error": f"Comparison failed: {exc}",
            "file_a": str(file_a),
            "file_b": str(file_b),
            "warnings": warnings,
        }

    # Persist in session so refine_query can follow up
    sess = await load_session(sid)
    sess.file_path = str(file_a)          # primary file for any follow-up query
    sess.original_question = question or f"Compare {file_a.name} vs {file_b.name}"
    sess.params = params
    sess.last_answer = answer
    sess.last_reasoning = reasoning
    sess.suggested_followups = followups
    if not sess.data_card:
        sess.data_card = data_card_to_dict(card_a)
    await add_turn(sess, "user", sess.original_question)
    await add_turn(sess, "analyst", answer)

    return {
        "status": "answered",
        "session_id": sid,
        "question": sess.original_question,
        "answer": answer,
        "reasoning": reasoning,
        "suggested_followups": followups,
        "warnings": warnings,
        "file_a": str(file_a),
        "file_b": str(file_b),
        "chart_data": chart_data,
    }
