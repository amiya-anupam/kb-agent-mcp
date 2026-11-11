"""Tests for the context-store tabular digest (Phase 3, task 3.2)."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from kb_agent_mcp.context_store.digest import build_digest, sha256_of
from kb_agent_mcp.context_store.frontmatter import parse_front_matter

SIZE_BUDGET = 10_000  # bytes; the BizOps sample is ~8 KB with 66 columns

_HEADER = [
    "Product", "Region", "Customer Name", "Fiscal Month",
    "Expired ($M)", "Expired", "Renewed ($M)", "Rate", "Email Address", "Account Owner", "Tier",
]


def _write_csv(path: Path, n: int = 60) -> Path:
    products = ["Alpha", "Beta", "Gamma"]
    regions = ["EMEA", "APAC"]
    months = ["Jan 2026", "Feb 2026", "Mar 2026"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(_HEADER)
        for i in range(n):
            exp = 1_000_000 + (i % 7) * 100_000  # whole dollars despite the "($M)" header
            w.writerow([
                products[i % 3], regions[i % 2], f"Customer {i % 20}", months[(i // 2) % 3],
                exp, exp, exp * 0.8, 0.8, f"user{i}@example.com", f"Owner {i}",
                ["Gold", "Silver"][(i // 5) % 2],
            ])
    return path


@pytest.fixture()
def sample(tmp_path: Path) -> Path:
    return _write_csv(tmp_path / "renewals.csv")


def test_deterministic(sample: Path) -> None:
    assert build_digest(sample, sample.parent) == build_digest(sample, sample.parent)


def test_front_matter_round_trip(sample: Path) -> None:
    fm = parse_front_matter(build_digest(sample, sample.parent))
    assert fm["path"] == "renewals.csv"
    assert fm["sha256"] == sha256_of(sample)
    assert fm["type"] == "csv"
    assert fm["rows"] == "60"
    assert fm["partial"] == "false"
    assert isinstance(fm["keywords"], list) and fm["keywords"]
    assert "Alpha" in fm["keywords"]


def test_parse_front_matter_without_block() -> None:
    assert parse_front_matter("# just a heading\n") == {}
    assert parse_front_matter("---\npath: x\n") == {}  # unterminated


def test_size_budget(sample: Path) -> None:
    assert len(build_digest(sample, sample.parent).encode()) <= SIZE_BUDGET


def test_pii_columns_not_summarised(sample: Path) -> None:
    text = build_digest(sample, sample.parent)
    assert "user1@example.com" not in text
    assert "Owner 1" not in text
    assert "Personal-data columns are not summarised here" in text
    assert "Email Address" in text.split("## Does not answer")[1]


def test_values_are_not_converted(sample: Path) -> None:
    text = build_digest(sample, sample.parent)
    # Stored total is shown verbatim; the M-suffixed gloss is only an addition.
    total = sum(1_000_000 + (i % 7) * 100_000 for i in range(60))
    assert f"{total:,}" in text
    assert f"{total / 1e6:.1f}M" in text  # gloss, beside the stored value
    assert "whole dollars" in text
    assert "units: columns labelled ($M) hold whole dollars" in text


def test_ratio_column_not_totalled(sample: Path) -> None:
    text = build_digest(sample, sample.parent)
    assert "Ratio columns not totalled" in text
    assert "Rate" in text.split("Ratio columns not totalled")[1].split("\n")[0]


def test_duplicate_metric_noted(sample: Path) -> None:
    text = build_digest(sample, sample.parent)
    assert "identical copy stored as Expired" in text


def test_breakdowns_and_renewal_rate(sample: Path) -> None:
    text = build_digest(sample, sample.parent)
    assert "By product (`Product`)" in text
    assert "By region (`Region`)" in text
    assert "Renewal rate (Renewed ($M) ÷ Expired ($M)): 80.0%" in text
    assert "| EMEA |" in text and "| APAC |" in text


def test_small_columns_list_values_inline(sample: Path) -> None:
    text = build_digest(sample, sample.parent)
    schema = text.split("## Schema")[1].split("## Pre-computed")[0]
    assert "Tier [2: Gold, Silver]" in schema


def test_non_date_column_with_year_in_name_is_not_time(tmp_path: Path) -> None:
    p = tmp_path / "t.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["2025 Product Leadership", "Region", "Amount"])
        for i in range(30):
            w.writerow([["Core", "Other"][i % 2], ["EMEA", "APAC"][i % 2], 100 + i])
    schema = build_digest(p, tmp_path).split("## Schema")[1]
    time_line = next((ln for ln in schema.split("\n") if ln.startswith("- **time**")), "")
    assert "2025 Product Leadership" not in time_line


def test_xlsx_digest(tmp_path: Path) -> None:
    # xlsxwriter writes shared strings, like Excel; the analyst loader needs them.
    xlsxwriter = pytest.importorskip("xlsxwriter")
    csv_path = _write_csv(tmp_path / "src.csv")
    xlsx = tmp_path / "renewals.xlsx"
    wb = xlsxwriter.Workbook(str(xlsx))
    ws = wb.add_worksheet()
    with open(csv_path, newline="") as f:
        for r, row in enumerate(csv.reader(f)):
            for c, cell in enumerate(row):
                try:
                    ws.write_number(r, c, float(cell)) if r else ws.write_string(r, c, cell)
                except ValueError:
                    ws.write_string(r, c, cell)
    wb.close()
    text = build_digest(xlsx, tmp_path)
    fm = parse_front_matter(text)
    assert fm["type"] == "xlsx"
    assert fm["rows"] == "60"
    assert "By product (`Product`)" in text
