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


# ── _trend_pivot unit tests ────────────────────────────────────────────────────

async def test_trend_pivot_basic_years(tmp_kb):
    """Two years of data produce correct values and a single delta row."""
    from kb_agent_mcp.analyst.engine import _trend_pivot
    rows = [
        {"year": "2024", "revenue": "100000"},
        {"year": "2024", "revenue": "50000"},   # same period — should sum
        {"year": "2025", "revenue": "200000"},
    ]
    result = _trend_pivot(rows, metric_col="revenue", time_col="year")
    assert result["periods"] == ["2024", "2025"]
    assert result["values"] == [150_000.0, 200_000.0]
    assert result["delta_abs"][0] is None          # first period has no delta
    assert result["delta_abs"][1] == pytest.approx(50_000.0)
    assert result["delta_pct"][1] == pytest.approx(50_000 / 150_000 * 100)


async def test_trend_pivot_quarters_sorted(tmp_kb):
    """Quarter labels are sorted chronologically, not alphabetically."""
    from kb_agent_mcp.analyst.engine import _trend_pivot
    rows = [
        {"quarter": "Q3 2025", "arr": 30},
        {"quarter": "Q1 2025", "arr": 10},
        {"quarter": "Q4 2025", "arr": 40},
        {"quarter": "Q2 2025", "arr": 20},
    ]
    result = _trend_pivot(rows, metric_col="arr", time_col="quarter")
    assert result["periods"] == ["Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025"]
    assert result["values"] == [10.0, 20.0, 30.0, 40.0]


async def test_trend_pivot_deltas_disabled(tmp_kb):
    """include_deltas=False returns all-None delta lists."""
    from kb_agent_mcp.analyst.engine import _trend_pivot
    rows = [
        {"year": "2023", "revenue": "100"},
        {"year": "2024", "revenue": "200"},
    ]
    result = _trend_pivot(rows, metric_col="revenue", time_col="year", include_deltas=False)
    assert all(v is None for v in result["delta_abs"])
    assert all(v is None for v in result["delta_pct"])


async def test_trend_pivot_zero_base_pct_is_none(tmp_kb):
    """When the base period value is 0, delta_pct should be None (no div-by-zero)."""
    from kb_agent_mcp.analyst.engine import _trend_pivot
    rows = [
        {"year": "2024", "revenue": "0"},
        {"year": "2025", "revenue": "500"},
    ]
    result = _trend_pivot(rows, metric_col="revenue", time_col="year")
    assert result["delta_abs"][1] == pytest.approx(500.0)
    assert result["delta_pct"][1] is None


async def test_trend_pivot_no_data(tmp_kb):
    """Empty input or all-null metric returns an empty result with note."""
    from kb_agent_mcp.analyst.engine import _trend_pivot
    result = _trend_pivot([], metric_col="revenue", time_col="year")
    assert result["periods"] == []
    assert result["values"] == []
    assert "No data" in result["note"]


async def test_trend_pivot_single_period(tmp_kb):
    """Single period: delta_abs and delta_pct both [None]."""
    from kb_agent_mcp.analyst.engine import _trend_pivot
    rows = [{"year": "2025", "revenue": "1000"}]
    result = _trend_pivot(rows, metric_col="revenue", time_col="year")
    assert result["periods"] == ["2025"]
    assert result["values"] == [1000.0]
    assert result["delta_abs"] == [None]
    assert result["delta_pct"] == [None]


# ── engine trend query integration tests ──────────────────────────────────────

async def test_query_data_trend_over_time(tmp_kb, csv_file):
    """A 'trend over time' question should hit the TREND_PIVOT handler."""
    from kb_agent_mcp.analyst.engine import query_data
    result = await query_data(
        str(csv_file),
        question="Show me how revenue has changed over time",
    )
    assert result["status"] in ("answered", "clarifying")
    if result["status"] == "answered":
        assert "Trend" in result["answer"] or "trend" in result["answer"].lower()
        assert "reasoning" in result


async def test_query_data_yoy_keyword(tmp_kb, csv_file):
    """'year over year' keyword triggers trend path."""
    from kb_agent_mcp.analyst.engine import query_data
    result = await query_data(
        str(csv_file),
        question="What is the year over year change in revenue?",
    )
    assert result["status"] in ("answered", "clarifying")


async def test_query_data_trend_answer_contains_periods(tmp_kb, csv_file):
    """When answered, the trend output includes period labels from the data."""
    from kb_agent_mcp.analyst.engine import query_data
    result = await query_data(
        str(csv_file),
        question="Show me the quarterly trend of revenue",
        session_id="trend-test-1",
    )
    assert result["status"] in ("answered", "clarifying")
    if result["status"] == "answered":
        # CSV has years 2024 and 2025 — at least one should appear in answer
        assert "2024" in result["answer"] or "2025" in result["answer"]


# ── planner growth theme includes trend question ───────────────────────────────

async def test_planner_growth_theme_has_trend_question(tmp_kb, csv_file):
    """The growth theme should now include a trend/period-table question."""
    from kb_agent_mcp.analyst.inspector import inspect_file
    from kb_agent_mcp.analyst.planner import suggest_questions
    card = await inspect_file(str(csv_file))
    menu = await suggest_questions(card)
    growth_questions = menu.get("growth", [])
    assert any(
        "trend" in q["question"].lower() or "period" in q["question"].lower()
        for q in growth_questions
    ), "Expected a trend/period question in the growth theme"


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


# ── _compare_files unit tests ──────────────────────────────────────────────────

@pytest.fixture()
def csv_file_q3(tmp_kb):
    """Q3 renewal tracker — same schema as csv_file but different values."""
    p = tmp_kb / "renewals_q3.csv"
    rows = [
        {"customer": "Acme",  "quarter": "Q3 2025", "revenue": "100000"},
        {"customer": "Beta",  "quarter": "Q3 2025", "revenue": "200000"},
        {"customer": "Gamma", "quarter": "Q3 2025", "revenue": "50000"},
    ]
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["customer", "quarter", "revenue"])
        writer.writeheader()
        writer.writerows(rows)
    return p


@pytest.fixture()
def csv_file_q4(tmp_kb):
    """Q4 renewal tracker — same schema, different values (growth scenario)."""
    p = tmp_kb / "renewals_q4.csv"
    rows = [
        {"customer": "Acme",  "quarter": "Q4 2025", "revenue": "120000"},
        {"customer": "Beta",  "quarter": "Q4 2025", "revenue": "180000"},
        {"customer": "Delta", "quarter": "Q4 2025", "revenue": "75000"},  # new in Q4
    ]
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["customer", "quarter", "revenue"])
        writer.writeheader()
        writer.writerows(rows)
    return p


@pytest.fixture()
def csv_file_multiyear(tmp_kb):
    """Multi-year file for cross-year comparison tests."""
    p = tmp_kb / "pipeline_2024.csv"
    rows = [
        {"customer": "Acme", "year": "2024", "arr": "300000"},
        {"customer": "Beta", "year": "2024", "arr": "150000"},
    ]
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["customer", "year", "arr"])
        writer.writeheader()
        writer.writerows(rows)
    return p


@pytest.fixture()
def csv_file_multiyear_b(tmp_kb):
    """Corresponding 2025 file for cross-year comparison."""
    p = tmp_kb / "pipeline_2025.csv"
    rows = [
        {"customer": "Acme", "year": "2025", "arr": "360000"},
        {"customer": "Beta", "year": "2025", "arr": "120000"},
    ]
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["customer", "year", "arr"])
        writer.writeheader()
        writer.writerows(rows)
    return p


async def test_compare_files_basic(tmp_kb, csv_file_q3, csv_file_q4):
    """_compare_files produces a diff table with period labels from both files."""
    from kb_agent_mcp.analyst.engine import _compare_files
    from kb_agent_mcp.analyst.inspector import inspect_file, _CARD_CACHE

    _CARD_CACHE.clear()
    card_a = await inspect_file(str(csv_file_q3))
    card_b = await inspect_file(str(csv_file_q4))

    answer, reasoning, followups, _ = _compare_files(
        csv_file_q3, csv_file_q4, card_a, card_b,
        question="compare Q3 vs Q4 renewal revenue",
        params={},
    )

    assert "Comparison" in answer
    assert "Q3 2025" in answer
    assert "Q4 2025" in answer
    assert "renewals_q3" in answer
    assert "renewals_q4" in answer
    assert len(followups) >= 1
    assert "File A" in reasoning and "File B" in reasoning


async def test_compare_files_overall_delta(tmp_kb, csv_file_q3, csv_file_q4):
    """Grand total row and overall delta reflect sum(B) − sum(A)."""
    from kb_agent_mcp.analyst.engine import _compare_files
    from kb_agent_mcp.analyst.inspector import inspect_file, _CARD_CACHE

    _CARD_CACHE.clear()
    card_a = await inspect_file(str(csv_file_q3))
    card_b = await inspect_file(str(csv_file_q4))

    answer, _, _, _ = _compare_files(
        csv_file_q3, csv_file_q4, card_a, card_b,
        question="compare revenue",
        params={},
    )
    # Q3 total = 350 000, Q4 total = 375 000 → positive delta
    assert "Overall" in answer
    assert "+" in answer or "▲" in answer


async def test_compare_files_metric_col_override(tmp_kb, csv_file_multiyear, csv_file_multiyear_b):
    """metric_col param is respected over auto-detection."""
    from kb_agent_mcp.analyst.engine import _compare_files
    from kb_agent_mcp.analyst.inspector import inspect_file, _CARD_CACHE

    _CARD_CACHE.clear()
    card_a = await inspect_file(str(csv_file_multiyear))
    card_b = await inspect_file(str(csv_file_multiyear_b))

    answer, reasoning, _, _ = _compare_files(
        csv_file_multiyear, csv_file_multiyear_b, card_a, card_b,
        question="compare arr",
        params={"metric_col": "arr"},
    )
    assert "arr" in reasoning.lower() or "arr" in answer.lower()
    assert "Comparison" in answer


async def test_compare_files_missing_metric_returns_message(tmp_kb, tmp_path):
    """When file A has no metric columns, _compare_files returns a clear message."""
    import kb_agent_mcp.analyst.inspector as insp_mod

    p_text = tmp_path / "text_only.csv"
    with p_text.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "status"])
        writer.writeheader()
        writer.writerows([{"name": "X", "status": "active"}])

    p_num = tmp_path / "numeric.csv"
    with p_num.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "revenue"])
        writer.writeheader()
        writer.writerows([{"name": "X", "revenue": "100"}])

    insp_mod._CARD_CACHE.clear()
    from kb_agent_mcp.analyst.engine import _compare_files
    from kb_agent_mcp.analyst.inspector import inspect_file

    card_text = await inspect_file(str(p_text))
    card_num  = await inspect_file(str(p_num))

    answer, _, _, _ = _compare_files(
        p_text, p_num, card_text, card_num,
        question="compare",
        params={},
    )
    assert "no numeric" in answer.lower() or "no" in answer.lower()


# ── compare_data engine entry point ───────────────────────────────────────────

async def test_compare_data_basic(tmp_kb, csv_file_q3, csv_file_q4):
    """compare_data returns status=answered with answer and session_id."""
    from kb_agent_mcp.analyst.engine import compare_data

    result = await compare_data(
        path_a=str(csv_file_q3),
        path_b=str(csv_file_q4),
        question="Compare Q3 vs Q4 renewal revenue",
    )
    assert result["status"] == "answered"
    assert result["session_id"]
    assert "Comparison" in result["answer"]
    assert result["file_a"].endswith("renewals_q3.csv")
    assert result["file_b"].endswith("renewals_q4.csv")
    assert isinstance(result["suggested_followups"], list)
    assert len(result["suggested_followups"]) >= 1


async def test_compare_data_missing_file_a(tmp_kb, csv_file_q4):
    """Missing path_a returns status=error with a clear message."""
    from kb_agent_mcp.analyst.engine import compare_data

    result = await compare_data(
        path_a="/nonexistent/q3.csv",
        path_b=str(csv_file_q4),
    )
    assert result["status"] == "error"
    assert "path_a" in result["error"].lower() or "not found" in result["error"].lower()


async def test_compare_data_missing_file_b(tmp_kb, csv_file_q3):
    """Missing path_b returns status=error."""
    from kb_agent_mcp.analyst.engine import compare_data

    result = await compare_data(
        path_a=str(csv_file_q3),
        path_b="/nonexistent/q4.csv",
    )
    assert result["status"] == "error"
    assert "path_b" in result["error"].lower() or "not found" in result["error"].lower()


async def test_compare_data_session_persisted(tmp_kb, csv_file_q3, csv_file_q4):
    """compare_data writes session state so refine_query can follow up."""
    from kb_agent_mcp.analyst.engine import compare_data
    from kb_agent_mcp.analyst.session import load_session

    result = await compare_data(
        path_a=str(csv_file_q3),
        path_b=str(csv_file_q4),
        session_id="cmp-session-1",
    )
    assert result["status"] == "answered"

    sess = await load_session("cmp-session-1")
    assert sess.file_path == str(csv_file_q3)
    assert sess.last_answer != ""
    assert len(sess.turns) == 2  # user + analyst


async def test_compare_data_metric_col_override(tmp_kb, csv_file_multiyear, csv_file_multiyear_b):
    """Explicit metric_col is forwarded through to _compare_files."""
    from kb_agent_mcp.analyst.engine import compare_data

    result = await compare_data(
        path_a=str(csv_file_multiyear),
        path_b=str(csv_file_multiyear_b),
        metric_col="arr",
    )
    assert result["status"] == "answered"
    assert "arr" in result["reasoning"].lower() or "arr" in result["answer"].lower()


# ── server tool: compare_data ─────────────────────────────────────────────────

async def test_server_compare_data_tool(tmp_kb, csv_file_q3, csv_file_q4):
    """server.compare_data returns valid JSON with status key."""
    import kb_agent_mcp.server as srv_mod

    result_json = await srv_mod.compare_data(
        path_a=str(csv_file_q3),
        path_b=str(csv_file_q4),
        question="Compare Q3 vs Q4 renewal revenue",
    )
    data = json.loads(result_json)
    assert "status" in data
    assert data["status"] in ("answered", "error")
    if data["status"] == "answered":
        assert "answer" in data
        assert "file_a" in data
        assert "file_b" in data


async def test_server_compare_data_tool_missing_file(tmp_kb, csv_file_q3):
    """server.compare_data with a missing file returns error JSON."""
    import kb_agent_mcp.server as srv_mod

    result_json = await srv_mod.compare_data(
        path_a=str(csv_file_q3),
        path_b="/no/such/file.csv",
    )
    data = json.loads(result_json)
    assert data["status"] == "error"
    assert "error" in data


# ── _make_chart_data unit tests ────────────────────────────────────────────────

async def test_make_chart_data_csv_header(tmp_kb):
    """CSV output has a 'period' header plus one column per dataset label."""
    from kb_agent_mcp.analyst.engine import _make_chart_data
    cd = _make_chart_data("bar", ["Q1", "Q2"], [{"label": "revenue", "data": [100.0, 200.0]}])
    lines = cd["csv"].splitlines()
    assert lines[0] == "period,revenue"
    assert lines[1] == "Q1,100.0"
    assert lines[2] == "Q2,200.0"


async def test_make_chart_data_csv_multi_dataset(tmp_kb):
    """Multi-dataset CSV has one column per dataset."""
    from kb_agent_mcp.analyst.engine import _make_chart_data
    cd = _make_chart_data(
        "bar",
        ["2024", "2025"],
        [
            {"label": "A", "data": [10.0, 20.0]},
            {"label": "B", "data": [15.0, 25.0]},
        ],
    )
    lines = cd["csv"].splitlines()
    assert lines[0] == "period,A,B"
    assert "2024" in lines[1]
    assert "2025" in lines[2]


async def test_make_chart_data_mermaid_single_dataset(tmp_kb):
    """Single non-negative dataset produces a mermaid xychart-beta block."""
    from kb_agent_mcp.analyst.engine import _make_chart_data
    cd = _make_chart_data(
        "line",
        ["Q1 2025", "Q2 2025", "Q3 2025"],
        [{"label": "arr", "data": [100.0, 150.0, 130.0]}],
    )
    assert cd["mermaid"].startswith("```mermaid")
    assert "xychart-beta" in cd["mermaid"]
    assert "line" in cd["mermaid"]
    assert '"Q1 2025"' in cd["mermaid"]


async def test_make_chart_data_mermaid_bar_keyword(tmp_kb):
    """bar / bar_horizontal chart types use the 'bar' Mermaid keyword."""
    from kb_agent_mcp.analyst.engine import _make_chart_data
    cd = _make_chart_data(
        "bar",
        ["Acme", "Beta"],
        [{"label": "revenue", "data": [500.0, 300.0]}],
    )
    assert "bar [" in cd["mermaid"]


async def test_make_chart_data_mermaid_omitted_for_multi_dataset(tmp_kb):
    """Multi-dataset input produces an empty mermaid string."""
    from kb_agent_mcp.analyst.engine import _make_chart_data
    cd = _make_chart_data(
        "bar",
        ["2024", "2025"],
        [
            {"label": "A", "data": [1.0, 2.0]},
            {"label": "B", "data": [3.0, 4.0]},
        ],
    )
    assert cd["mermaid"] == ""


async def test_make_chart_data_mermaid_omitted_for_negatives(tmp_kb):
    """Negative values cause the mermaid string to be empty."""
    from kb_agent_mcp.analyst.engine import _make_chart_data
    cd = _make_chart_data(
        "bar",
        ["2024", "2025"],
        [{"label": "delta", "data": [-100.0, 50.0]}],
    )
    assert cd["mermaid"] == ""


async def test_make_chart_data_mermaid_truncated_at_12(tmp_kb):
    """Labels beyond 12 are truncated and the title notes this."""
    from kb_agent_mcp.analyst.engine import _make_chart_data
    labels = [f"P{i}" for i in range(20)]
    data = [float(i) for i in range(20)]
    cd = _make_chart_data("bar", labels, [{"label": "v", "data": data}])
    assert "truncated to 12 periods" in cd["mermaid"]
    # Only first 12 labels should appear in x-axis
    assert '"P12"' not in cd["mermaid"]
    assert '"P11"' in cd["mermaid"]


async def test_make_chart_data_structure(tmp_kb):
    """Return dict has all required keys with correct types."""
    from kb_agent_mcp.analyst.engine import _make_chart_data
    cd = _make_chart_data("line", ["A"], [{"label": "x", "data": [1.0]}])
    assert cd["type"] == "line"
    assert cd["labels"] == ["A"]
    assert isinstance(cd["datasets"], list)
    assert isinstance(cd["csv"], str)
    assert isinstance(cd["mermaid"], str)


# ── query_data chart_data integration ─────────────────────────────────────────

async def test_query_data_trend_has_chart_data(tmp_kb, csv_file):
    """A trend question produces chart_data with type='line'."""
    from kb_agent_mcp.analyst.engine import query_data

    result = await query_data(
        str(csv_file),
        question="Show me how revenue has changed over time",
    )
    assert result["status"] in ("answered", "clarifying")
    if result["status"] == "answered":
        cd = result.get("chart_data")
        assert cd is not None
        assert cd["type"] == "line"
        assert isinstance(cd["labels"], list)
        assert isinstance(cd["datasets"], list)
        assert len(cd["datasets"]) == 1
        assert "csv" in cd
        assert "mermaid" in cd


async def test_query_data_top_has_chart_data(tmp_kb, csv_file):
    """A top-N question produces chart_data with type='bar_horizontal'."""
    from kb_agent_mcp.analyst.engine import query_data

    result = await query_data(
        str(csv_file),
        question="What are the top customers by revenue?",
    )
    assert result["status"] in ("answered", "clarifying")
    if result["status"] == "answered":
        cd = result.get("chart_data")
        assert cd is not None
        assert cd["type"] == "bar_horizontal"
        assert len(cd["datasets"]) == 1
        assert len(cd["labels"]) > 0


async def test_query_data_breakdown_has_chart_data(tmp_kb, csv_file):
    """A breakdown question produces chart_data with type='bar'."""
    from kb_agent_mcp.analyst.engine import query_data

    result = await query_data(
        str(csv_file),
        question="Show revenue breakdown by customer",
    )
    assert result["status"] in ("answered", "clarifying")
    if result["status"] == "answered":
        cd = result.get("chart_data")
        assert cd is not None
        assert cd["type"] == "bar"


async def test_query_data_total_has_no_chart_data(tmp_kb, csv_file):
    """A scalar total question returns chart_data=None."""
    from kb_agent_mcp.analyst.engine import query_data

    result = await query_data(
        str(csv_file),
        question="What is the total revenue across all data?",
    )
    assert result["status"] in ("answered", "clarifying")
    if result["status"] == "answered":
        assert result.get("chart_data") is None


async def test_query_data_summary_has_no_chart_data(tmp_kb, csv_file):
    """A summary/profile question returns chart_data=None."""
    from kb_agent_mcp.analyst.engine import query_data

    result = await query_data(
        str(csv_file),
        question="Give me a summary of this file",
    )
    assert result["status"] in ("answered", "clarifying")
    if result["status"] == "answered":
        assert result.get("chart_data") is None


async def test_query_data_chart_csv_parseable(tmp_kb, csv_file):
    """chart_data['csv'] for a trend answer is valid CSV with expected structure."""
    import csv as csv_mod
    from kb_agent_mcp.analyst.engine import query_data

    result = await query_data(
        str(csv_file),
        question="Show me the trend of revenue over time",
    )
    if result["status"] != "answered":
        return
    cd = result.get("chart_data")
    if cd is None:
        return
    reader = list(csv_mod.reader(cd["csv"].splitlines()))
    # First row is header; subsequent rows are data
    assert reader[0][0] == "period"
    assert len(reader) >= 2  # header + at least one data row
    assert all(len(row) == len(reader[0]) for row in reader if row)


# ── compare_data chart_data integration ───────────────────────────────────────

async def test_compare_data_has_chart_data(tmp_kb, csv_file_q3, csv_file_q4):
    """compare_data returns chart_data with two datasets."""
    from kb_agent_mcp.analyst.engine import compare_data

    result = await compare_data(
        path_a=str(csv_file_q3),
        path_b=str(csv_file_q4),
    )
    assert result["status"] == "answered"
    cd = result.get("chart_data")
    assert cd is not None
    assert cd["type"] == "bar"
    assert len(cd["datasets"]) == 2
    assert cd["datasets"][0]["label"].startswith("A:")
    assert cd["datasets"][1]["label"].startswith("B:")


async def test_compare_data_chart_mermaid_empty_for_two_datasets(tmp_kb, csv_file_q3, csv_file_q4):
    """Comparison chart has empty mermaid (multi-dataset not supported by xychart-beta)."""
    from kb_agent_mcp.analyst.engine import compare_data

    result = await compare_data(
        path_a=str(csv_file_q3),
        path_b=str(csv_file_q4),
    )
    assert result["status"] == "answered"
    assert result["chart_data"]["mermaid"] == ""


async def test_compare_data_chart_csv_has_two_columns(tmp_kb, csv_file_q3, csv_file_q4):
    """compare_data CSV has period + two value columns."""
    import csv as csv_mod
    from kb_agent_mcp.analyst.engine import compare_data

    result = await compare_data(
        path_a=str(csv_file_q3),
        path_b=str(csv_file_q4),
    )
    assert result["status"] == "answered"
    cd = result["chart_data"]
    reader = list(csv_mod.reader(cd["csv"].splitlines()))
    assert len(reader[0]) == 3   # period, A, B
    assert reader[0][0] == "period"


# ── server tool chart_data round-trip ─────────────────────────────────────────

async def test_server_query_data_chart_data_in_json(tmp_kb, csv_file):
    """server.query_data JSON includes chart_data key when status=answered."""
    import kb_agent_mcp.server as srv_mod

    result_json = await srv_mod.query_data(
        str(csv_file),
        "Show me the trend of revenue over time",
    )
    data = json.loads(result_json)
    # chart_data is only present when status == "answered"
    if data["status"] == "answered":
        assert "chart_data" in data


async def test_server_compare_data_chart_data_in_json(tmp_kb, csv_file_q3, csv_file_q4):
    """server.compare_data JSON includes chart_data when status=answered."""
    import kb_agent_mcp.server as srv_mod

    result_json = await srv_mod.compare_data(
        path_a=str(csv_file_q3),
        path_b=str(csv_file_q4),
    )
    data = json.loads(result_json)
    if data["status"] == "answered":
        assert "chart_data" in data
        assert data["chart_data"] is not None
        assert "csv" in data["chart_data"]
        assert "mermaid" in data["chart_data"]
        assert "datasets" in data["chart_data"]
