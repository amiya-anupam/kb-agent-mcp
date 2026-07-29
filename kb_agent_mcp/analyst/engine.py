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


def _format_number(n: float) -> str:
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:,.2f}M"
    if abs(n) >= 1_000:
        return f"${n/1_000:,.1f}K"
    return f"${n:,.2f}"


# ── Answer builder ─────────────────────────────────────────────────────────────

def _build_answer(
    question: str,
    rows: list[dict],
    card: DataCard,
    params: dict[str, Any],
) -> tuple[str, str, list[str]]:
    """
    Compute an answer from raw rows + resolved params.

    Returns (answer_text, reasoning_text, suggested_followups).
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
            return answer, "\n".join(reasoning_parts), followups

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
            return answer, "\n".join(reasoning_parts), followups

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
            return answer, "\n".join(reasoning_parts), followups

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
            return answer, "\n".join(reasoning_parts), followups

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
        return answer, "\n".join(reasoning_parts), followups

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
        return answer, "\n".join(reasoning_parts), followups

    # ── Pure document fallback ────────────────────────────────────────────────
    reasoning_parts.append("Operation: DOCUMENT PASSTHROUGH (no tabular data)")
    return (
        "This file does not contain tabular data that can be computed directly. "
        "Try using the main KB search tool to query this document semantically.",
        "\n".join(reasoning_parts),
        [],
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
        answer, reasoning, followups = await asyncio.to_thread(
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
