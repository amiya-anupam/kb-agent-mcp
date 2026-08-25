"""
_xlsx_stream.py — Shared streaming XLSX aggregation logic
----------------------------------------------------------
Used by both agents/agent_base.py and kb_agent_mcp/file_parser.py.

Provides a single canonical implementation of stream_xlsx_aggregate().
Callers pass their own agg_keywords and preferred_num_cols dicts so this
module has zero dependency on either the agents/ config constants or the
kb_agent_mcp cfg object.

Do NOT import this module directly from application code — use agent_base or
file_parser, which wire up the keyword dicts and export _stream_xlsx_aggregate.
"""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any


def stream_xlsx_aggregate(
    path: "pathlib.Path",
    max_chars: int,
    agg_keywords: dict[str, str],
    preferred_num_cols: list[str],
) -> str:
    """
    Stream-aggregate a large XLSX file using raw XML iterparse.
    Never loads the full workbook into memory.

    Args:
        path:               Path to the XLSX file.
        max_chars:          Maximum characters in the returned string.
        agg_keywords:       Mapping from lower-case column-header substring → display label.
        preferred_num_cols: Ordered list of lower-case column headers to use as the
                            numeric (revenue/value) column, tried in order.

    Returns a markdown summary of totals by detected group-by dimensions.
    """
    import pathlib  # local import to avoid top-level dep on pathlib (always available)

    try:
        with zipfile.ZipFile(str(path), "r") as zf:
            # ── Resolve sheet names ───────────────────────────────────────────
            sheet_names: list[tuple[str, str]] = []
            try:
                wb_xml = ET.fromstring(zf.read("xl/workbook.xml"))
                ns = {"w": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for s in wb_xml.findall(".//w:sheet", ns):
                    r_id = s.get(
                        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
                        "",
                    )
                    sheet_names.append((s.get("name", r_id), r_id))
            except Exception:
                sheet_names = [("Sheet1", "rId1")]

            rid_to_path: dict[str, str] = {}
            try:
                rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
                for rel in rels:
                    rid_to_path[rel.get("Id", "")] = "xl/" + rel.get("Target", "").lstrip("/")
            except Exception:
                pass

            # ── Load shared strings ───────────────────────────────────────────
            shared: list[str] = []
            try:
                ss_xml = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                ns_ss = {"w": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in ss_xml.findall("w:si", ns_ss):
                    parts = [t.text or "" for t in si.findall(".//w:t", ns_ss)]
                    shared.append("".join(parts))
            except Exception:
                pass

            def cell_value(cell_el: Any) -> Any:
                t = cell_el.get("t", "")
                ns_v = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                v_el = cell_el.find(f"{{{ns_v}}}v")
                raw = v_el.text if v_el is not None else None
                if raw is None:
                    return None
                if t == "s":
                    try:
                        return shared[int(raw)]
                    except (IndexError, ValueError):
                        return raw
                try:
                    f = float(raw)
                    return int(f) if f == int(f) else f
                except ValueError:
                    return raw

            text_parts: list[str] = []

            for sheet_name, r_id in sheet_names:
                zip_path = rid_to_path.get(r_id, "")
                if not zip_path or zip_path not in zf.namelist():
                    for cand in [
                        "xl/worksheets/sheet1.xml",
                        f"xl/worksheets/{sheet_name}.xml",
                    ]:
                        if cand in zf.namelist():
                            zip_path = cand
                            break
                if not zip_path or zip_path not in zf.namelist():
                    continue

                text_parts.append(f"[Sheet: {sheet_name}]")

                headers: list[str] = []
                agg: dict[int, dict[str, float]] = {}
                num_ci: int | None = None
                group_cols: list[tuple[int, str]] = []
                row_count = 0

                ns_ws = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                with zf.open(zip_path) as ws_f:
                    for event, elem in ET.iterparse(ws_f, events=("end",)):
                        if elem.tag != f"{{{ns_ws}}}row":
                            continue
                        vals = [cell_value(c) for c in list(elem)]

                        if row_count == 0:
                            # Header row
                            headers = [str(v) if v is not None else "" for v in vals]
                            h_lower = [h.lower().strip() for h in headers]

                            for pref in preferred_num_cols:
                                if pref in h_lower:
                                    num_ci = h_lower.index(pref)
                                    break

                            _agg_order = list(agg_keywords.keys())
                            group_cols = sorted(
                                [
                                    (ci, agg_keywords[h])
                                    for ci, h in enumerate(h_lower)
                                    if h in agg_keywords
                                ],
                                key=lambda x: _agg_order.index(
                                    next(k for k in _agg_order if agg_keywords[k] == x[1])
                                ),
                            )
                            _seen: set[str] = set()
                            group_cols = [
                                (ci, lbl)
                                for ci, lbl in group_cols
                                if lbl not in _seen and not _seen.add(lbl)  # type: ignore[func-returns-value]
                            ]
                            agg = {g_idx: defaultdict(float) for g_idx, _ in group_cols}
                            row_count += 1
                            elem.clear()
                            continue

                        row_count += 1

                        num_val: float | None = None
                        if num_ci is not None and num_ci < len(vals):
                            v = vals[num_ci]
                            if isinstance(v, (int, float)):
                                num_val = float(v)
                        if num_val is None:
                            for v in reversed(vals):
                                if isinstance(v, (int, float)):
                                    num_val = float(v)
                                    break

                        if num_val is not None:
                            for g_idx, _ in group_cols:
                                gval = (
                                    str(vals[g_idx])
                                    if g_idx < len(vals) and vals[g_idx] is not None
                                    else "(blank)"
                                )
                                agg[g_idx][gval] += num_val

                        elem.clear()

                rev_col = (
                    headers[num_ci]
                    if num_ci is not None and num_ci < len(headers)
                    else "numeric"
                )
                text_parts.append(f"Rows: {row_count - 1}  |  Revenue column: '{rev_col}'")

                if group_cols and agg:
                    for g_idx, g_label in group_cols:
                        totals = dict(agg[g_idx])
                        if not totals:
                            continue
                        grand = sum(totals.values())
                        text_parts.append(f"--- By {g_label} ---")
                        for k, v in sorted(totals.items(), key=lambda x: -x[1])[:50]:
                            text_parts.append(f"  {k}: {v:,.2f}")
                        text_parts.append(f"  TOTAL: {grand:,.2f}\n")
                else:
                    text_parts.append(f"Columns: {', '.join(h for h in headers[:20] if h)}")
                text_parts.append("")

        return "\n".join(text_parts)[:max_chars]

    except Exception as e:
        return f"[Large XLSX stream error: {e}] File: {path.name}"
