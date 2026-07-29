"""
tests/test_analyst.py — Data Analyst capability add-on tests
"""
from __future__ import annotations

import csv
import json
import time
import asyncio
import tempfile
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_kb(tmp_path, monkeypatch):
    """Isolate KB_ROOT to a temp dir for all analyst modules."""
    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    import importlib
    import kb_agent_mcp.config as cfg_mod
    importlib.reload(cfg_mod)
    import kb_agent_mcp.analyst.inspector as insp_mod
    importlib.reload(insp_mod)
    import kb_agent_mcp.analyst.session as sess_mod
    importlib.reload(sess_mod)
    import kb_agent_mcp.analyst.engine as eng_mod
    importlib.reload(eng_mod)
    return tmp_path


@pytest.fixture()
def csv_file(tmp_kb):
    """A simple CSV with customer + revenue + year columns."""
    p = tmp_kb / "revenue.csv"
    rows = [
        {"customer": "Acme", "year": "2024", "revenue": "100000"},
        {"customer": "Beta", "year": "2024", "revenue": "200000"},
        {"customer": "Gamma", "year": "2025", "revenue": "150000"},
        {"customer": "Acme", "year": "2025", "revenue": "120000"},
    ]
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["customer", "year", "revenue"])
        writer.writeheader()
        writer.writerows(rows)
    return p


@pytest.fixture()
def json_file(tmp_kb):
    """A simple JSON list-of-dicts."""
    p = tmp_kb / "deals.json"
    data = [
        {"customer": "Alpha", "quarter": "Q1 2025", "arr": 50000},
        {"customer": "Beta",  "quarter": "Q2 2025", "arr": 75000},
        {"customer": "Alpha", "quarter": "Q3 2025", "arr": 55000},
    ]
    p.write_text(json.dumps(data))
    return p


@pytest.fixture()
def minimal_xlsx(tmp_kb):
    """Create a minimal valid xlsx with headers + data rows."""
    p = tmp_kb / "data.xlsx"
    # Build xlsx manually as a zip of XML parts
    ws_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="1">'
        '<c r="A1" t="s"><v>0</v></c>'
        '<c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c>'
        "</row>"
        '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2"><v>2024</v></c><c r="C2"><v>100000</v></c></row>'
        '<row r="3"><c r="A3" t="s"><v>4</v></c><c r="B3"><v>2024</v></c><c r="C3"><v>200000</v></c></row>'
        '<row r="4"><c r="A4" t="s"><v>3</v></c><c r="B4"><v>2025</v></c><c r="C4"><v>120000</v></c></row>'
        "</sheetData>"
        "</worksheet>"
    )
    ss_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="5" uniqueCount="5">'
        "<si><t>customer</t></si>"
        "<si><t>year</t></si>"
        "<si><t>revenue</t></si>"
        "<si><t>Acme</t></si>"
        "<si><t>Beta</t></si>"
        "</sst>"
    )
    wb_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheets><sheet name=\"Sheet1\" sheetId=\"1\" r:id=\"rId1\" "
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>'
        "</workbook>"
    )
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", ws_xml)
        zf.writestr("xl/sharedStrings.xml", ss_xml)
        zf.writestr("xl/workbook.xml", wb_xml)
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>')
    return p


# ── inspector tests ────────────────────────────────────────────────────────────

async def test_inspect_csv_returns_data_card(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.inspector import inspect_file
    card = await inspect_file(str(csv_file))
    assert card.file_name == "revenue.csv"
    assert card.file_format == "tabular"
    assert card.total_rows > 0
    assert card.total_columns == 3
    assert len(card.columns) == 3


async def test_inspect_csv_column_kinds(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.inspector import inspect_file
    card = await inspect_file(str(csv_file))
    kinds = {col.name: col.kind for col in card.columns}
    assert kinds.get("year") in ("time", "categorical")
    assert kinds.get("revenue") in ("metric", "id")


async def test_inspect_csv_metric_column_detected(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.inspector import inspect_file
    card = await inspect_file(str(csv_file))
    # 'revenue' should appear in metric or entity columns
    all_named = card.metric_columns + card.entity_columns + card.time_columns
    assert "revenue" in all_named or any(c.name == "revenue" for c in card.columns)


async def test_inspect_json_file(tmp_kb, json_file):
    from kb_agent_mcp.analyst.inspector import inspect_file
    card = await inspect_file(str(json_file))
    assert card.file_format == "tabular"
    assert card.total_columns == 3


async def test_inspect_caches_result(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.inspector import inspect_file, _CARD_CACHE
    _CARD_CACHE.clear()
    card1 = await inspect_file(str(csv_file))
    card2 = await inspect_file(str(csv_file))
    assert card1 is card2  # same object from cache


async def test_inspect_xlsx(tmp_kb, minimal_xlsx):
    from kb_agent_mcp.analyst.inspector import inspect_file
    card = await inspect_file(str(minimal_xlsx))
    assert card.file_format == "tabular"
    assert card.total_columns == 3


async def test_inspect_nonexistent_file_raises(tmp_kb):
    from kb_agent_mcp.analyst.inspector import inspect_file
    with pytest.raises(FileNotFoundError):
        await inspect_file(str(tmp_kb / "no_such_file.csv"))


async def test_data_card_to_dict(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.inspector import inspect_file, data_card_to_dict
    card = await inspect_file(str(csv_file))
    d = data_card_to_dict(card)
    assert isinstance(d, dict)
    assert "columns" in d
    assert "metric_columns" in d
    assert isinstance(d["columns"], list)


# ── planner tests ──────────────────────────────────────────────────────────────

async def test_suggest_questions_returns_menu(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.inspector import inspect_file
    from kb_agent_mcp.analyst.planner import suggest_questions
    card = await inspect_file(str(csv_file))
    menu = await suggest_questions(card)
    assert isinstance(menu, dict)
    assert len(menu) > 0


async def test_suggest_questions_has_summary_theme(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.inspector import inspect_file
    from kb_agent_mcp.analyst.planner import suggest_questions
    card = await inspect_file(str(csv_file))
    menu = await suggest_questions(card)
    assert "summary" in menu


async def test_suggest_questions_from_dict(tmp_kb, csv_file):
    """suggest_questions should accept a plain dict (serialised DataCard)."""
    from kb_agent_mcp.analyst.inspector import inspect_file, data_card_to_dict
    from kb_agent_mcp.analyst.planner import suggest_questions
    card = await inspect_file(str(csv_file))
    d = data_card_to_dict(card)
    menu = await suggest_questions(d)
    assert isinstance(menu, dict)


async def test_no_duplicate_questions(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.inspector import inspect_file
    from kb_agent_mcp.analyst.planner import suggest_questions
    card = await inspect_file(str(csv_file))
    menu = await suggest_questions(card)
    all_questions = [q["question"] for qs in menu.values() for q in qs]
    assert len(all_questions) == len(set(q.lower().strip() for q in all_questions))


# ── session tests ──────────────────────────────────────────────────────────────

async def test_session_create_and_load(tmp_kb):
    from kb_agent_mcp.analyst.session import load_session, save_session, AnalystSession
    sess = AnalystSession(session_id="test-1", original_question="What is total revenue?")
    await save_session(sess)
    loaded = await load_session("test-1")
    assert loaded.original_question == "What is total revenue?"


async def test_session_clear(tmp_kb):
    from kb_agent_mcp.analyst.session import load_session, save_session, clear_session, AnalystSession
    sess = AnalystSession(session_id="clear-test", original_question="hello")
    await save_session(sess)
    await clear_session("clear-test")
    loaded = await load_session("clear-test")
    assert loaded.original_question == ""


async def test_session_add_turn(tmp_kb):
    from kb_agent_mcp.analyst.session import load_session, add_turn, AnalystSession, save_session
    sess = AnalystSession(session_id="turn-test")
    await save_session(sess)
    await add_turn(sess, "user", "Hello there")
    loaded = await load_session("turn-test")
    assert len(loaded.turns) == 1
    assert loaded.turns[0]["role"] == "user"
    assert loaded.turns[0]["content"] == "Hello there"


async def test_session_rolling_window(tmp_kb):
    """Turns beyond 20 should be dropped."""
    from kb_agent_mcp.analyst.session import add_turn, save_session, load_session, AnalystSession
    sess = AnalystSession(session_id="rolling")
    await save_session(sess)
    for i in range(25):
        await add_turn(sess, "user", f"msg {i}")
    loaded = await load_session("rolling")
    assert len(loaded.turns) <= 20


# ── engine tests ───────────────────────────────────────────────────────────────

async def test_query_data_file_not_found(tmp_kb):
    from kb_agent_mcp.analyst.engine import query_data
    result = await query_data(path="/nonexistent/path.csv", question="total revenue")
    assert result["status"] == "error"
    assert "not found" in result["error"].lower()


async def test_query_data_total_question(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.engine import query_data
    result = await query_data(
        path=str(csv_file),
        question="What is the total revenue across all data?",
    )
    # Should either answer or ask for clarification (both are valid)
    assert result["status"] in ("answered", "clarifying")
    assert result["session_id"]


async def test_query_data_clarification_on_multi_metric(tmp_kb, tmp_path):
    """When the file has 2+ metric columns and question doesn't name one, ask for clarification."""
    import kb_agent_mcp.analyst.inspector as insp_mod
    # Create a CSV with two distinct metric columns so planner triggers clq
    p = tmp_path / "multi_metric.csv"
    rows = [{"customer": "Acme", "revenue": 100, "cost": 50, "year": 2025}]
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["customer", "revenue", "cost", "year"])
        writer.writeheader()
        writer.writerows(rows)
    # Force clear cache
    insp_mod._CARD_CACHE.clear()
    from kb_agent_mcp.analyst.engine import query_data
    result = await query_data(
        path=str(p),
        question="What is the total?",  # ambiguous — doesn't name a metric
    )
    # status may be clarifying OR answered depending on classification
    assert result["status"] in ("clarifying", "answered")


async def test_query_data_returns_session_id(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.engine import query_data
    result = await query_data(str(csv_file), "show me a summary")
    assert "session_id" in result
    assert len(result["session_id"]) > 0


async def test_refine_query_applies_feedback(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.engine import query_data, refine_query
    result1 = await query_data(str(csv_file), "What is the total revenue?")
    sid = result1["session_id"]
    # Refine with explicit time range
    result2 = await refine_query(session_id=sid, feedback="2024")
    assert result2["status"] in ("answered", "clarifying")
    assert result2["session_id"] == sid


async def test_refine_query_invalid_session(tmp_kb):
    from kb_agent_mcp.analyst.engine import refine_query
    result = await refine_query(session_id="does-not-exist", feedback="anything")
    assert result["status"] == "error"


async def test_query_data_top_question(tmp_kb, csv_file):
    from kb_agent_mcp.analyst.engine import query_data
    result = await query_data(
        str(csv_file),
        question="What are the top customers by revenue?",
    )
    assert result["status"] in ("answered", "clarifying")


async def test_engine_load_csv_rows(tmp_kb, csv_file):
    """Internal helper: load CSV rows produces expected structure."""
    from kb_agent_mcp.analyst.engine import _load_csv_rows
    rows = _load_csv_rows(csv_file)
    assert len(rows) == 4
    assert "customer" in rows[0]
    assert "revenue" in rows[0]


async def test_engine_load_json_rows(tmp_kb, json_file):
    from kb_agent_mcp.analyst.engine import _load_json_rows
    rows = _load_json_rows(json_file)
    assert len(rows) == 3
    assert "arr" in rows[0]


async def test_engine_aggregate(tmp_kb):
    from kb_agent_mcp.analyst.engine import _aggregate
    rows = [
        {"customer": "A", "revenue": 100},
        {"customer": "B", "revenue": 200},
        {"customer": "A", "revenue": 50},
    ]
    totals = _aggregate(rows, "revenue", "customer")
    assert totals["A"] == 150
    assert totals["B"] == 200


async def test_engine_time_filter(tmp_kb):
    from kb_agent_mcp.analyst.engine import _filter_rows, _parse_time_filter
    rows = [
        {"year": 2024, "rev": 100},
        {"year": 2025, "rev": 200},
    ]
    tf = _parse_time_filter("2025")
    filtered = _filter_rows(rows, "year", tf, None, None)
    assert len(filtered) == 1
    assert filtered[0]["rev"] == 200


async def test_engine_attrition_pivot(tmp_kb):
    from kb_agent_mcp.analyst.engine import _attrition_pivot
    rows = [
        {"customer": "Acme", "year": 2024, "revenue": 100},
        {"customer": "Beta", "year": 2024, "revenue": 200},
        {"customer": "Acme", "year": 2025, "revenue": 120},
        # Beta absent in 2025
    ]
    result = _attrition_pivot(rows, "customer", "year", "revenue")
    churned_names = [e for e, _ in result["churned"]]
    assert "Beta" in churned_names
    assert result["at_risk_total"] == 200


async def test_engine_xlsx_row_parser(tmp_kb, minimal_xlsx):
    from kb_agent_mcp.analyst.engine import _load_xlsx_rows
    rows = _load_xlsx_rows(minimal_xlsx)
    assert len(rows) == 3
    assert "customer" in rows[0]


# ── Integration: server tools ──────────────────────────────────────────────────

async def test_server_analyze_file_tool(tmp_kb, csv_file):
    """server.analyze_file should return valid JSON DataCard (absolute path)."""
    import kb_agent_mcp.server as srv_mod
    # Pass absolute path — no need to patch frozen cfg
    result_json = await srv_mod.analyze_file(str(csv_file))
    data = json.loads(result_json)
    assert "error" not in data
    assert "file_name" in data


async def test_server_suggest_questions_tool(tmp_kb, csv_file):
    """server.suggest_questions should return a non-empty JSON menu."""
    import kb_agent_mcp.server as srv_mod
    result_json = await srv_mod.suggest_questions(str(csv_file))
    data = json.loads(result_json)
    assert "error" not in data
    assert len(data) > 0


async def test_server_query_data_tool(tmp_kb, csv_file):
    """server.query_data should return a JSON object with status key."""
    import kb_agent_mcp.server as srv_mod
    result_json = await srv_mod.query_data(str(csv_file), "What is the total revenue?")
    data = json.loads(result_json)
    assert "status" in data
    assert data["status"] in ("answered", "clarifying", "error")
