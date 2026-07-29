"""
kb_agent_mcp/analyst/inspector.py
──────────────────────────────────
Schema profiler — the foundation of the Data Analyst layer.

Reads any supported file and returns a DataCard: a structured description
of what the file contains, what kind of data it is, and what analytical
angles are possible.  Everything downstream (planner, engine) works from
the DataCard — it is computed once and cached per (path, mtime).

Supported formats
─────────────────
Tabular  : .xlsx, .xls, .csv, .tsv, .json (list-of-dicts), .jsonl
Document : .pdf, .docx, .pptx, .txt, .md, .boxnote, .rtf
Mixed    : PDF files with embedded tables are profiled as tabular
           when ≥1 table with ≥3 columns and ≥5 rows is detected.

Column classification
─────────────────────
Every column is classified into one of:

    metric      — numeric, meaningful to aggregate (revenue, count, qty)
    id          — high-cardinality integer (customer #, SAP #)
    entity      — low-to-mid cardinality string (customer name, product, geo)
    time        — year, quarter, month, date
    categorical — low-cardinality string (status, type, flag)
    text        — free-form prose (description, notes)
    unknown     — could not determine

Grain detection
───────────────
Infers "one row = one WHAT" by finding the combination of entity + time
columns with the lowest duplicity rate.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Column-name substrings → likely column kind
_METRIC_HINTS = {
    "rev", "revenue", "amount", "sales", "cost", "price", "qty", "quantity",
    "count", "total", "sum", "value", "budget", "spend", "income", "profit",
    "loss", "margin", "arr", "mrr", "churn", "rate", "score", "pc", "act",
}
_ID_HINTS = {
    "id", "num", "number", "#", "code", "key", "ref", "sap", "enterprise",
    "site", "zip", "postal",
}
_TIME_HINTS = {
    "year", "yr", "quarter", "qtr", "month", "mo", "week", "wk", "date",
    "period", "fiscal", "fy", "q1", "q2", "q3", "q4",
}
_ENTITY_HINTS = {
    "name", "customer", "client", "product", "geo", "geography", "country",
    "region", "market", "segment", "channel", "industry", "partner", "vendor",
    "rep", "owner", "team", "division", "vertical", "brand", "category",
}
_CATEGORICAL_HINTS = {
    "type", "status", "flag", "label", "tier", "level", "class", "group",
    "mode", "kind", "on-prem", "saas", "stream",
}

# Max rows to sample for profiling (streaming parse respects this)
_SAMPLE_ROWS = 2_000
# Cardinality threshold: above this → id or text, not entity
_HIGH_CARD_RATIO = 0.95
# Metric column: fraction of non-null values that parse as float
_NUMERIC_RATIO_THRESHOLD = 0.85
# Cache TTL in seconds
_CACHE_TTL = 300


# ── DataCard ───────────────────────────────────────────────────────────────────

@dataclass
class ColumnProfile:
    name: str
    kind: str                    # metric | id | entity | time | categorical | text | unknown
    sample_values: list[Any]     # up to 5 distinct sample values
    null_rate: float             # 0.0–1.0
    cardinality: int             # number of distinct non-null values in sample
    numeric_total: float | None  # sum across sample rows (metrics only)


@dataclass
class DataCard:
    """
    Structured profile of a file — the single source of truth for all
    downstream analyst operations.
    """
    path: str                        # absolute path
    file_name: str
    file_format: str                 # tabular | document | mixed
    file_type: str                   # xlsx | csv | pdf | docx | …
    total_rows: int                  # -1 for documents
    total_columns: int               # -1 for documents
    columns: list[ColumnProfile]     # empty for pure-document files
    time_columns: list[str]          # column names classified as "time"
    entity_columns: list[str]        # column names classified as "entity"
    metric_columns: list[str]        # column names classified as "metric"
    time_range: dict[str, Any]       # {"column": str, "min": val, "max": val}
    grain_hint: str                  # "one row = one <X>"
    data_themes: list[str]           # e.g. ["customer_revenue", "time_series"]
    summary: str                     # one-paragraph plain-English description
    warnings: list[str]              # data quality observations
    profiled_at: float               # time.monotonic() snapshot


# ── Module-level cache: (path, mtime) → DataCard ──────────────────────────────

_CARD_CACHE: dict[str, tuple[float, DataCard]] = {}   # path → (mtime, card)


def _cache_key(path: Path) -> str:
    return str(path.resolve())


def _cached_card(path: Path) -> DataCard | None:
    key = _cache_key(path)
    entry = _CARD_CACHE.get(key)
    if entry is None:
        return None
    cached_mtime, card = entry
    try:
        current_mtime = path.stat().st_mtime
    except OSError:
        return None
    if abs(current_mtime - cached_mtime) > 1.0:
        return None  # file changed
    if time.monotonic() - card.profiled_at > _CACHE_TTL:
        return None  # TTL expired
    return card


def _store_card(path: Path, card: DataCard) -> None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    _CARD_CACHE[_cache_key(path)] = (mtime, card)


# ── Column kind classifier ─────────────────────────────────────────────────────

def _classify_column(
    name: str,
    values: list[Any],
    total_rows: int,
) -> ColumnProfile:
    """Classify a single column by name hints and value statistics."""
    name_lower = name.lower().strip()
    non_null = [v for v in values if v is not None and str(v).strip() != ""]
    null_rate = 1.0 - len(non_null) / max(len(values), 1)
    distinct = list({str(v) for v in non_null})
    cardinality = len(distinct)

    # Sample values (up to 5 distinct, short)
    sample_vals: list[Any] = []
    seen: set[str] = set()
    for v in non_null:
        sv = str(v)
        if sv not in seen:
            seen.add(sv)
            sample_vals.append(v)
        if len(sample_vals) >= 5:
            break

    # Check numeric ratio
    numeric_vals: list[float] = []
    for v in non_null:
        try:
            numeric_vals.append(float(v))
        except (TypeError, ValueError):
            pass
    numeric_ratio = len(numeric_vals) / max(len(non_null), 1)

    # Determine kind ───────────────────────────────────────────────────────────
    # 1. Name-hint based
    words = set(re.split(r"[\s_/\-#@]+", name_lower))

    if words & _TIME_HINTS or bool(
        re.search(r"\b(20\d{2}|19\d{2}|q[1-4]|fy\d{2})\b", name_lower)
    ):
        kind = "time"
    elif words & _METRIC_HINTS and numeric_ratio >= _NUMERIC_RATIO_THRESHOLD:
        kind = "metric"
    elif words & _ID_HINTS and numeric_ratio >= _NUMERIC_RATIO_THRESHOLD:
        kind = "id"
    elif words & _ENTITY_HINTS:
        kind = "entity"
    elif words & _CATEGORICAL_HINTS:
        kind = "categorical"
    # 2. Value-statistics fallback
    elif numeric_ratio >= _NUMERIC_RATIO_THRESHOLD:
        # Pure numeric — distinguish metric vs id by magnitude of values
        avg = sum(numeric_vals) / max(len(numeric_vals), 1)
        if avg > 1_000_000 and cardinality > 50:
            kind = "id"     # large integers → likely an ID
        else:
            kind = "metric"
    elif cardinality <= 20 and len(non_null) > 0:
        kind = "categorical"
    elif cardinality / max(total_rows, 1) >= _HIGH_CARD_RATIO:
        # Nearly unique per row → text or id
        kind = "text" if any(len(str(v)) > 40 for v in non_null[:20]) else "id"
    elif len(non_null) > 0:
        kind = "entity"
    else:
        kind = "unknown"

    numeric_total = round(sum(numeric_vals), 4) if kind == "metric" and numeric_vals else None

    return ColumnProfile(
        name=name,
        kind=kind,
        sample_values=sample_vals,
        null_rate=round(null_rate, 3),
        cardinality=cardinality,
        numeric_total=numeric_total,
    )


# ── Grain heuristic ────────────────────────────────────────────────────────────

def _infer_grain(columns: list[ColumnProfile]) -> str:
    """
    Produce a human-readable grain hint: "one row = one <entity> × <time>".
    Falls back to "one row = one record" when unable to determine.
    """
    entities = [c.name for c in columns if c.kind == "entity"]
    times    = [c.name for c in columns if c.kind == "time"]
    metrics  = [c.name for c in columns if c.kind == "metric"]

    parts: list[str] = []
    if entities:
        parts.append(entities[0])   # primary entity
    if times:
        parts.append(times[0])      # primary time dimension
    if metrics:
        parts.append(metrics[0])    # value dimension

    if parts:
        return "one row = one " + " × ".join(parts)
    return "one row = one record"


# ── Theme detector ─────────────────────────────────────────────────────────────

def _detect_themes(columns: list[ColumnProfile], file_name: str) -> list[str]:
    """Detect what analytical themes this dataset supports."""
    themes: list[str] = []
    kinds = {c.kind for c in columns}
    names_lower = {c.name.lower() for c in columns}

    has_time   = "time" in kinds
    has_entity = "entity" in kinds
    has_metric = "metric" in kinds

    # Revenue / financial
    if has_metric and any(h in " ".join(names_lower) for h in ("rev", "amount", "sales", "cost")):
        themes.append("revenue_analysis")

    # Customer / account analysis
    if any("customer" in n or "client" in n for n in names_lower):
        if has_metric:
            themes.append("customer_revenue")
        themes.append("customer_analysis")

    # Time series
    if has_time and has_metric:
        themes.append("time_series")

    # Attrition / renewal
    if has_entity and has_time and has_metric:
        themes.append("attrition_risk")
        themes.append("renewal_tracking")

    # Pipeline / deals
    if any(w in " ".join(names_lower) for w in ("deal", "pipeline", "opportunity", "stage")):
        themes.append("pipeline_analysis")

    # Geographic
    if any(w in " ".join(names_lower) for w in ("geo", "country", "region", "market")):
        themes.append("geographic_breakdown")

    # Product breakdown
    if any(w in " ".join(names_lower) for w in ("product", "sku", "part", "category")):
        themes.append("product_breakdown")

    return themes if themes else ["general_analysis"]


# ── Tabular parsers ────────────────────────────────────────────────────────────

def _col_letter_to_idx(ref: str) -> int:
    letters = re.sub(r"[0-9]", "", ref).upper()
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _load_xlsx_sample(path: Path) -> tuple[list[str], list[list[Any]], int]:
    """
    Return (headers, sample_rows, estimated_total_rows) from an XLSX file.
    Uses streaming XML iterparse — never loads full workbook into memory.
    """
    headers: list[str] = []
    rows: list[list[Any]] = []
    total_rows = 0
    ns_uri = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    with zipfile.ZipFile(str(path)) as zf:
        # Load shared strings
        shared: list[str] = []
        try:
            ss = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss.findall(f"{{{ns_uri}}}si"):
                shared.append("".join(t.text or "" for t in si.findall(f".//{{{ns_uri}}}t")))
        except Exception:
            pass

        # Find first sheet
        sheet_path = None
        for cand in ["xl/worksheets/Sheet1.xml", "xl/worksheets/sheet1.xml"]:
            if cand in zf.namelist():
                sheet_path = cand
                break
        if sheet_path is None:
            for name in zf.namelist():
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                    sheet_path = name
                    break
        if sheet_path is None:
            return [], [], 0

        def _cv(c: ET.Element) -> Any:
            t = c.get("t", "")
            v = c.find(f"{{{ns_uri}}}v")
            raw = v.text if v is not None else None
            if raw is None:
                return None
            if t == "s":
                try:
                    return shared[int(raw)]
                except (IndexError, ValueError):
                    return raw
            try:
                f = float(raw)
                return int(f) if f == int(f) else round(f, 4)
            except ValueError:
                return raw

        with zf.open(sheet_path) as f:
            for _, elem in ET.iterparse(f, events=("end",)):
                if elem.tag != f"{{{ns_uri}}}row":
                    continue
                # Sparse row parsing using cell references
                row_data: dict[int, Any] = {}
                for c in elem:
                    ref = c.get("r", "")
                    if ref:
                        row_data[_col_letter_to_idx(ref)] = _cv(c)

                if not row_data:
                    elem.clear()
                    continue

                mx = max(row_data.keys())
                row_vals = [row_data.get(i) for i in range(mx + 1)]

                if not headers:
                    headers = [str(v) if v is not None else f"col_{i}" for i, v in enumerate(row_vals)]
                    elem.clear()
                    continue

                total_rows += 1
                if len(rows) < _SAMPLE_ROWS:
                    # Pad / trim to header length
                    while len(row_vals) < len(headers):
                        row_vals.append(None)
                    rows.append(row_vals[:len(headers)])
                elem.clear()

    return headers, rows, total_rows


def _load_csv_sample(path: Path) -> tuple[list[str], list[list[Any]], int]:
    headers: list[str] = []
    rows: list[list[Any]] = []
    total_rows = 0
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    headers = row
                    continue
                total_rows += 1
                if len(rows) < _SAMPLE_ROWS:
                    rows.append(row)
    except Exception as exc:
        logger.warning("CSV parse error %s: %s", path.name, exc)
    return headers, rows, total_rows


def _load_json_sample(path: Path) -> tuple[list[str], list[list[Any]], int]:
    """Handle JSON array-of-objects or JSONL."""
    headers: list[str] = []
    rows: list[list[Any]] = []
    total_rows = 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        # Try JSONL first
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        records: list[dict] = []
        is_jsonl = False
        try:
            for line in lines[:10]:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    is_jsonl = True
                break
        except Exception:
            is_jsonl = False

        if is_jsonl:
            for line in lines:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        records.append(obj)
                        total_rows += 1
                except Exception:
                    pass
        else:
            data = json.loads(text)
            if isinstance(data, list):
                records = [r for r in data if isinstance(r, dict)]
                total_rows = len(records)
            elif isinstance(data, dict):
                records = [data]
                total_rows = 1

        if records:
            # Collect all keys
            all_keys: list[str] = []
            seen: set[str] = set()
            for r in records[:200]:
                for k in r.keys():
                    if k not in seen:
                        seen.add(k)
                        all_keys.append(k)
            headers = all_keys
            for r in records[:_SAMPLE_ROWS]:
                rows.append([r.get(k) for k in headers])
    except Exception as exc:
        logger.warning("JSON parse error %s: %s", path.name, exc)
    return headers, rows, total_rows


def _profile_tabular(
    path: Path,
    headers: list[str],
    rows: list[list[Any]],
    total_rows: int,
) -> DataCard:
    """Build a DataCard from already-parsed tabular data."""
    n_cols = len(headers)
    warnings: list[str] = []

    # Per-column sampling
    col_values: list[list[Any]] = [[] for _ in range(n_cols)]
    for row in rows:
        for i, v in enumerate(row):
            if i < n_cols:
                col_values[i].append(v)

    columns = [
        _classify_column(headers[i], col_values[i], total_rows)
        for i in range(n_cols)
    ]

    time_cols   = [c.name for c in columns if c.kind == "time"]
    entity_cols = [c.name for c in columns if c.kind == "entity"]
    metric_cols = [c.name for c in columns if c.kind == "metric"]

    # Time range
    time_range: dict[str, Any] = {}
    if time_cols and col_values:
        tc_idx = headers.index(time_cols[0])
        non_null_t = [v for v in col_values[tc_idx] if v is not None]
        if non_null_t:
            time_range = {
                "column": time_cols[0],
                "min": min(str(v) for v in non_null_t),
                "max": max(str(v) for v in non_null_t),
            }

    # Warnings
    high_null = [c.name for c in columns if c.null_rate > 0.5]
    if high_null:
        warnings.append(f"High null rate (>50%) in: {', '.join(high_null[:5])}")

    # Detect duplicate customer names (possible deduplication issue)
    for c in columns:
        if c.kind == "entity" and c.cardinality > 0:
            if c.null_rate > 0.05:
                warnings.append(
                    f"Column '{c.name}' has {c.null_rate:.0%} nulls — "
                    "some entities may be unattributed."
                )

    grain = _infer_grain(columns)
    themes = _detect_themes(columns, path.name)

    # Summary
    tr_str = f"{total_rows:,}" if total_rows >= 0 else "unknown"
    time_str = ""
    if time_range:
        time_str = f" covering {time_range['min']}–{time_range['max']}"
    metric_str = ""
    if metric_cols:
        metric_str = f" Key metric(s): {', '.join(metric_cols[:3])}."
    entity_str = ""
    if entity_cols:
        entity_str = f" Primary entity dimension(s): {', '.join(entity_cols[:3])}."

    summary = (
        f"Tabular dataset with {tr_str} rows and {n_cols} columns{time_str}. "
        f"Grain: {grain}.{metric_str}{entity_str} "
        f"Analytical themes: {', '.join(themes)}."
    )

    return DataCard(
        path=str(path.resolve()),
        file_name=path.name,
        file_format="tabular",
        file_type=path.suffix.lstrip(".").lower(),
        total_rows=total_rows,
        total_columns=n_cols,
        columns=columns,
        time_columns=time_cols,
        entity_columns=entity_cols,
        metric_columns=metric_cols,
        time_range=time_range,
        grain_hint=grain,
        data_themes=themes,
        summary=summary,
        warnings=warnings,
        profiled_at=time.monotonic(),
    )


# ── Document profiler ──────────────────────────────────────────────────────────

def _profile_document(path: Path) -> DataCard:
    """Minimal DataCard for non-tabular documents."""
    ext = path.suffix.lstrip(".").lower()
    try:
        size_kb = path.stat().st_size // 1024
    except OSError:
        size_kb = 0

    summary = (
        f"Document file ({ext.upper()}, ~{size_kb} KB). "
        "Use the knowledge base ask() tool for semantic questions about this document."
    )
    return DataCard(
        path=str(path.resolve()),
        file_name=path.name,
        file_format="document",
        file_type=ext,
        total_rows=-1,
        total_columns=-1,
        columns=[],
        time_columns=[],
        entity_columns=[],
        metric_columns=[],
        time_range={},
        grain_hint="",
        data_themes=["document_retrieval"],
        summary=summary,
        warnings=[],
        profiled_at=time.monotonic(),
    )


# ── Public entry point ─────────────────────────────────────────────────────────

_TABULAR_EXTS = {".xlsx", ".xls", ".csv", ".tsv", ".json", ".jsonl"}


def _inspect_file_sync(path: str | Path) -> DataCard:
    """
    Profile any file and return a DataCard (synchronous implementation).

    Results are cached per (path, mtime) with a 5-minute TTL.
    Safe to call on every query — repeated calls for the same unchanged
    file return the cached card with no I/O.

    Args:
        path: Absolute or workspace-relative path to the file.

    Returns:
        DataCard with schema, grain, themes, and a plain-English summary.

    Raises:
        FileNotFoundError: When the file does not exist.
        ValueError: When the file format cannot be determined.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    cached = _cached_card(p)
    if cached is not None:
        return cached

    ext = p.suffix.lower()

    if ext in _TABULAR_EXTS:
        if ext in {".xlsx", ".xls"}:
            headers, rows, total_rows = _load_xlsx_sample(p)
        elif ext in {".csv", ".tsv"}:
            headers, rows, total_rows = _load_csv_sample(p)
        elif ext in {".json", ".jsonl"}:
            headers, rows, total_rows = _load_json_sample(p)
        else:
            headers, rows, total_rows = [], [], 0

        if headers:
            card = _profile_tabular(p, headers, rows, total_rows)
        else:
            # Tabular extension but no parseable content — treat as document
            card = _profile_document(p)
    else:
        card = _profile_document(p)

    _store_card(p, card)
    return card


import asyncio as _asyncio


async def inspect_file(path: str | Path) -> DataCard:
    """Async wrapper around _inspect_file_sync (runs in thread pool)."""
    return await _asyncio.to_thread(_inspect_file_sync, path)


def data_card_to_dict(card: DataCard) -> dict[str, Any]:
    """
    Serialise a DataCard to a plain dict for JSON output or LLM context.
    Strips internal fields (profiled_at) and flattens column profiles.
    """
    return {
        "path":           card.path,
        "file_name":      card.file_name,
        "file_format":    card.file_format,
        "file_type":      card.file_type,
        "total_rows":     card.total_rows,
        "total_columns":  card.total_columns,
        "time_columns":   card.time_columns,
        "entity_columns": card.entity_columns,
        "metric_columns": card.metric_columns,
        "time_range":     card.time_range,
        "grain_hint":     card.grain_hint,
        "data_themes":    card.data_themes,
        "summary":        card.summary,
        "warnings":       card.warnings,
        "profiled_at":    card.profiled_at,
        "columns": [
            {
                "name":          c.name,
                "kind":          c.kind,
                "cardinality":   c.cardinality,
                "null_rate":     c.null_rate,
                "sample_values": [str(v) for v in c.sample_values[:3]],
                "numeric_total": c.numeric_total,
            }
            for c in card.columns
        ],
    }
