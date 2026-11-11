"""Streaming readers and the scan-based tabular digest."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
import xlsxwriter

from kb_agent_mcp.context_store import build_digest_for
from kb_agent_mcp.context_store.digest import build_digest
from kb_agent_mcp.context_store.frontmatter import parse_front_matter
from kb_agent_mcp.context_store.table_stream import open_table

HEADER = ["Product", "Region", "Customer Name", "Fiscal Month", "Expired ($M)", "Renewed ($M)"]


def _row(i: int) -> list:
    exp = 1_000_000 + (i % 7) * 100_000
    return [["Alpha", "Beta", "Gamma"][i % 3], ["EMEA", "APAC"][i % 2], f"Customer {i % 60}",
            ["Jan 2026", "Feb 2026", "Mar 2026"][(i // 2) % 3], exp, exp * 0.8]


def _csv(path: Path, n: int) -> Path:
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i in range(n):
            w.writerow(_row(i))
    return path


def _xlsx(path: Path, sheets: dict[str, int]) -> Path:
    wb = xlsxwriter.Workbook(str(path))
    for name, n in sheets.items():
        ws = wb.add_worksheet(name)
        ws.write_row(0, 0, HEADER)
        for i in range(n):
            ws.write_row(i + 1, 0, _row(i))
    wb.close()
    return path


# ── reader ────────────────────────────────────────────────────────────────────

def test_reader_multi_sheet_names_and_rows(tmp_path):
    p = _xlsx(tmp_path / "wb.xlsx", {"Renewals": 5, "Other Data": 3})
    with open_table(p) as src:
        assert src.names == ["Renewals", "Other Data"]
        rows = list(src.rows(0))
        assert rows[0] == HEADER
        assert len(rows) == 6
        assert rows[1][:2] == ["Alpha", "EMEA"]
        assert rows[1][4] == 1_000_000
        assert len(list(src.rows(1))) == 4
        assert src.estimated_rows(0) == 5


def test_reader_inline_strings(tmp_path):
    """Workbooks written without a shared-strings table (inlineStr cells)."""
    p = _xlsx(tmp_path / "wb.xlsx", {"S": 4})
    q = tmp_path / "inline.xlsx"
    with zipfile.ZipFile(p) as zin, zipfile.ZipFile(q, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "xl/sharedStrings.xml":
                shared = re.findall(r"<si><t[^>]*>(.*?)</t></si>", data.decode())
                continue
            zout.writestr(item, data)
    # Rebuild the sheet with inline strings.
    with zipfile.ZipFile(q) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        members = {n: z.read(n) for n in z.namelist()}
    sheet = re.sub(r'<c r="(\w+)"([^>]*) t="s"><v>(\d+)</v></c>',
                   lambda m: f'<c r="{m.group(1)}"{m.group(2)} t="inlineStr"><is><t>{shared[int(m.group(3))]}</t></is></c>',
                   sheet)
    members["xl/worksheets/sheet1.xml"] = sheet.encode()
    with zipfile.ZipFile(q, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    with open_table(q) as src:
        rows = list(src.rows(0))
    assert rows[0] == HEADER
    assert rows[1][0] == "Alpha"


def test_reader_member_names_are_case_insensitive(tmp_path):
    p = _xlsx(tmp_path / "wb.xlsx", {"S": 3})
    q = tmp_path / "caps.xlsx"
    with zipfile.ZipFile(p) as zin, zipfile.ZipFile(q, "w") as zout:
        for item in zin.namelist():
            name = item.replace("worksheets/sheet1.xml", "worksheets/Sheet1.xml")
            data = zin.read(item)
            if item == "xl/_rels/workbook.xml.rels":
                data = data.replace(b"worksheets/sheet1.xml", b"worksheets/Sheet1.xml")
            zout.writestr(name, data)
    with open_table(q) as src:
        assert len(list(src.rows(0))) == 4


def test_reader_csv_and_tsv(tmp_path):
    c = _csv(tmp_path / "a.csv", 10)
    with open_table(c) as src:
        assert src.names == ["a"]
        assert len(list(src.rows(0))) == 11
    t = tmp_path / "b.tsv"
    t.write_text("A\tB\n1\t2\n3\t4\n")
    with open_table(t) as src:
        assert list(src.rows(0)) == [["A", "B"], ["1", "2"], ["3", "4"]]


def test_reader_rejects_unsupported(tmp_path):
    with pytest.raises(ValueError):
        open_table(tmp_path / "x.txt")


# ── digest ────────────────────────────────────────────────────────────────────

def test_streaming_matches_exact_totals_beyond_sample(tmp_path):
    n = 5000                                  # larger than the 2000-row sample
    p = _csv(tmp_path / "big.csv", n)
    text = build_digest(p, tmp_path)
    fm = parse_front_matter(text)
    assert fm["rows"] == str(n)
    assert fm["partial"] == "false"
    expected = sum(1_000_000 + (i % 7) * 100_000 for i in range(n))
    assert f"{expected:,}" in text
    assert "| Alpha |" in text and "| Beta |" in text
    assert "80.0%" in text


def test_group_totals_use_every_row(tmp_path):
    n = 4001
    p = _csv(tmp_path / "big.csv", n)
    text = build_digest(p, tmp_path)
    alpha = sum(1_000_000 + (i % 7) * 100_000 for i in range(n) if i % 3 == 0)
    assert f"| Alpha | {alpha:,} |" in text


def test_deterministic_and_size_budget(tmp_path):
    p = _csv(tmp_path / "big.csv", 3000)
    a, b = build_digest(p, tmp_path), build_digest(p, tmp_path)
    assert a == b
    assert len(a.encode()) <= 10_000


def test_time_budget_marks_partial(tmp_path):
    p = _csv(tmp_path / "big.csv", 20_000)
    text = build_digest(p, tmp_path, time_budget=0.0)
    fm = parse_front_matter(text)
    # With no time at all nothing is read.
    assert fm["extraction"] == "empty"
    assert "time limit" in text


def test_partial_scan_is_marked(tmp_path, monkeypatch):
    from kb_agent_mcp.context_store import table_scan
    monkeypatch.setattr(table_scan, "_CHECK_EVERY", 16)
    monkeypatch.setattr(table_scan, "SAMPLE_ROWS", 50)
    p = _csv(tmp_path / "big.csv", 20_000)
    # Fake clock shared by both modules (they use the same time.monotonic attribute).
    ticks = iter(range(100_000))
    monkeypatch.setattr(table_scan.time, "monotonic", lambda: next(ticks) * 0.001)
    text = build_digest(p, tmp_path, time_budget=0.2)
    fm = parse_front_matter(text)
    assert fm["partial"] == "true"
    assert "rows were read" in text
    assert fm["rows"] != "0"


def test_multi_sheet_workbook(tmp_path):
    p = _xlsx(tmp_path / "wb.xlsx", {"Renewals": 60, "Archive": 30})
    text = build_digest(p, tmp_path)
    fm = parse_front_matter(text)
    assert fm["sheets"] == "2"
    assert fm["rows"] == "90"
    assert "## Sheet: Renewals" in text and "## Sheet: Archive" in text
    assert "Only the first" not in text
    assert "Renewals" in fm["keywords"]
    assert len(text.encode()) <= 16_000


def test_header_only_and_empty_files(tmp_path):
    h = tmp_path / "h.csv"
    h.write_text(",".join(HEADER) + "\n")
    t = build_digest(h, tmp_path)
    assert parse_front_matter(t)["extraction"] == "empty"
    assert "no data rows" in t
    e = tmp_path / "e.csv"
    e.write_text("")
    assert parse_front_matter(build_digest(e, tmp_path))["extraction"] == "empty"


def test_corrupt_and_legacy_xls_do_not_crash(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a zip")
    t = build_digest(bad, tmp_path)
    assert parse_front_matter(t)["extraction"] == "empty"
    assert "BadZipFile" in t
    xls = tmp_path / "old.xls"
    xls.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 100)
    t = build_digest(xls, tmp_path)
    assert "legacy binary .xls" in t


def test_dispatch_routes_tables(tmp_path):
    p = _csv(tmp_path / "a.csv", 20)
    assert "## Pre-computed aggregates" in build_digest_for(p, tmp_path)
