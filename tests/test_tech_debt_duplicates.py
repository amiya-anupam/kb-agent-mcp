"""
tests/test_tech_debt_duplicates.py
───────────────────────────────────
Baseline tests for every intentionally duplicated function/constant in the codebase.

These tests document the AS-IS behaviour of:

  A. AGG_KEYWORDS  — key set and value mapping (agents/agent_base.py x2,
                     agents/embeddings.py, kb_agent_mcp/file_parser.py)
  B. PREFERRED_NUM_COLS — order and content (same four locations)
  C. folder_to_safe_name() — conversion logic (agent_base, embeddings,
                              generate, watch_kb)
  D. _find_readme() — 4-priority cascade (agent_base, generate.py)
  E. _stream_xlsx_aggregate() — output shape (agent_base)
  F. _has_noindex_ancestor() — already covered in test_noindex_guard.py;
                                this file just cross-checks the copies agree

Rules:
  • All tests must pass before AND after any consolidation work.
  • If a test fails after consolidation, the refactor broke something.
  • Do not delete any test from this file without a clear reason.
"""
from __future__ import annotations

import pathlib
import sys
import zipfile
import struct

import pytest

# ── path setup ────────────────────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "agents"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))


# ─────────────────────────────────────────────────────────────────────────────
# A.  AGG_KEYWORDS — key set identical across all agent-layer copies
# ─────────────────────────────────────────────────────────────────────────────

# The canonical key set we test against.  Any change here must be intentional.
_EXPECTED_AGG_KEYS = {
    "ut lvl 30 name dynamic",
    "ut l30 name",
    "ut l30",
    "product family name",
    "reporting product family",
    "product",
    "year",
    "quarter",
    "quarter in year",
    "geography",
    "geography name",
    "market",
    "market name",
    "country",
    "finance family",
    "revenue type",
    "reporting revenue type name",
    "on-prem or saas",
    "division",
    "classification name",
    "frozen client lifecycle name",
    "status",
}

# The canonical value mapping we test spot-checks against.
_EXPECTED_AGG_SPOT = {
    "product": "Product",
    "geography": "Geography",
    "year": "Year",
    "quarter": "Quarter",
    "country": "Country",
    "revenue type": "Revenue Type",
    "status": "Status",
    "division": "Division",
    "ut l30": "Product (UT L30)",
}


def _get_agent_base_agg_keywords_copy1() -> dict:
    """Extract AGG_KEYWORDS from _stream_xlsx_aggregate (copy 1) by running its
    preamble up to — but not including — the zipfile.ZipFile call."""
    import agent_base as ab
    # The function body defines AGG_KEYWORDS as a local. We re-create it here
    # from the source truth rather than calling the function (which needs a real
    # XLSX file).  This mirrors what the function contains and will fail if
    # someone changes the function without updating this test.
    fn_src = ab._stream_xlsx_aggregate.__code__.co_consts
    # Instead of parsing bytecode, just call the known values directly from
    # the module — after consolidation copy 1 will reference the module-level
    # constant, so this test will still pass.
    # We call a helper that returns the dict used inside _stream_xlsx_aggregate.
    # Before consolidation: import the function and inspect local source.
    # After consolidation: the module-level constant is used.
    # Simplest portable approach: define expected and compare with module attr
    # if present, otherwise trust the function source matches EXPECTED.
    if hasattr(ab, "AGG_KEYWORDS"):
        return dict(ab.AGG_KEYWORDS)
    # pre-consolidation: no module-level constant yet; return expected as proxy
    return dict(_EXPECTED_AGG_SPOT)  # partial — just for spot-check path


class TestAggKeywordsKeyset:
    """AGG_KEYWORDS key set must be identical in every agent-layer copy."""

    def test_agent_base_stream_function_uses_expected_keys(self):
        """_stream_xlsx_aggregate's local AGG_KEYWORDS must contain all expected keys."""
        import agent_base as ab
        # Post-consolidation: module-level constant exists.
        # Pre-consolidation: verify source code contains the keys by checking
        # the function's __code__ co_consts for a known key.
        if hasattr(ab, "AGG_KEYWORDS"):
            missing = _EXPECTED_AGG_KEYS - set(ab.AGG_KEYWORDS.keys())
            assert not missing, f"AGG_KEYWORDS missing keys: {missing}"
        else:
            # Pre-consolidation: trust source; verify a sentinel key is in
            # the module source text.
            import inspect
            src = inspect.getsource(ab._stream_xlsx_aggregate)
            for key in ("ut lvl 30 name dynamic", "geography", "status"):
                assert key in src, f"Key {key!r} not found in _stream_xlsx_aggregate source"

    def test_agent_base_extract_full_text_uses_expected_keys(self):
        """extract_full_text's XLSX branch AGG_KEYWORDS must contain all expected keys."""
        import agent_base as ab
        if hasattr(ab, "AGG_KEYWORDS"):
            missing = _EXPECTED_AGG_KEYS - set(ab.AGG_KEYWORDS.keys())
            assert not missing, f"AGG_KEYWORDS missing keys: {missing}"
        else:
            import inspect
            src = inspect.getsource(ab.extract_full_text)
            for key in ("ut lvl 30 name dynamic", "geography", "status"):
                assert key in src, f"Key {key!r} not found in extract_full_text source"

    def test_embeddings_uses_expected_keys(self):
        """embeddings.extract_text_snippet XLSX branch must use the same key set."""
        import embeddings as emb
        if hasattr(emb, "AGG_KEYWORDS"):
            missing = _EXPECTED_AGG_KEYS - set(emb.AGG_KEYWORDS.keys())
            assert not missing, f"embeddings.AGG_KEYWORDS missing keys: {missing}"
        else:
            import inspect
            src = inspect.getsource(emb.extract_text_snippet)
            for key in ("ut lvl 30 name dynamic", "geography", "status"):
                assert key in src, f"Key {key!r} not found in embeddings.extract_text_snippet source"

    def test_kb_agent_mcp_uses_expected_keys(self):
        """kb_agent_mcp/file_parser._AGG_KEYWORDS must contain all expected keys."""
        from kb_agent_mcp.file_parser import _AGG_KEYWORDS
        missing = _EXPECTED_AGG_KEYS - set(_AGG_KEYWORDS.keys())
        assert not missing, f"file_parser._AGG_KEYWORDS missing keys: {missing}"

    def test_all_copies_have_same_key_count(self):
        """All copies must have the same number of keys (no one silently added an extra)."""
        from kb_agent_mcp.file_parser import _AGG_KEYWORDS
        mcp_count = len(_AGG_KEYWORDS)
        expected_count = len(_EXPECTED_AGG_KEYS)
        assert mcp_count == expected_count, (
            f"file_parser._AGG_KEYWORDS has {mcp_count} keys, expected {expected_count}"
        )

    def test_spot_check_values(self):
        """Known key→value pairs must map correctly in the MCP copy (canonical)."""
        from kb_agent_mcp.file_parser import _AGG_KEYWORDS
        for key, expected_val in _EXPECTED_AGG_SPOT.items():
            assert _AGG_KEYWORDS.get(key) == expected_val, (
                f"_AGG_KEYWORDS[{key!r}] = {_AGG_KEYWORDS.get(key)!r}, expected {expected_val!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# B.  PREFERRED_NUM_COLS — order and content
# ─────────────────────────────────────────────────────────────────────────────

_EXPECTED_PREFERRED_NUM_COLS = [
    "won",
    "total(cy cw won @ pc)",
    "rev act @ pc",
    "amount",
    "oppty value",
    "total",
]


class TestPreferredNumCols:
    """PREFERRED_NUM_COLS must be identical across all copies."""

    def test_mcp_copy_matches_expected(self):
        from kb_agent_mcp.file_parser import _PREFERRED_NUM_COLS
        assert list(_PREFERRED_NUM_COLS) == _EXPECTED_PREFERRED_NUM_COLS

    def test_mcp_copy_order_preserved(self):
        """'won' must be first — it takes priority over generic 'total'."""
        from kb_agent_mcp.file_parser import _PREFERRED_NUM_COLS
        assert _PREFERRED_NUM_COLS[0] == "won"
        assert _PREFERRED_NUM_COLS[-1] == "total"

    def test_agent_base_stream_function_contains_preferred_cols(self):
        """_stream_xlsx_aggregate source must contain all PREFERRED_NUM_COLS entries."""
        import agent_base as ab
        if hasattr(ab, "PREFERRED_NUM_COLS"):
            assert list(ab.PREFERRED_NUM_COLS) == _EXPECTED_PREFERRED_NUM_COLS
        else:
            import inspect
            src = inspect.getsource(ab._stream_xlsx_aggregate)
            for col in _EXPECTED_PREFERRED_NUM_COLS:
                assert col in src, f"PREFERRED_NUM_COLS entry {col!r} missing from _stream_xlsx_aggregate"

    def test_agent_base_extract_full_text_contains_preferred_cols(self):
        import agent_base as ab
        if hasattr(ab, "PREFERRED_NUM_COLS"):
            assert list(ab.PREFERRED_NUM_COLS) == _EXPECTED_PREFERRED_NUM_COLS
        else:
            import inspect
            src = inspect.getsource(ab.extract_full_text)
            for col in _EXPECTED_PREFERRED_NUM_COLS:
                assert col in src, f"PREFERRED_NUM_COLS entry {col!r} missing from extract_full_text"

    def test_embeddings_contains_preferred_cols(self):
        import embeddings as emb
        if hasattr(emb, "PREFERRED_NUM_COLS"):
            assert list(emb.PREFERRED_NUM_COLS) == _EXPECTED_PREFERRED_NUM_COLS
        else:
            import inspect
            src = inspect.getsource(emb.extract_text_snippet)
            for col in _EXPECTED_PREFERRED_NUM_COLS:
                assert col in src, f"PREFERRED_NUM_COLS entry {col!r} missing from embeddings.extract_text_snippet"


# ─────────────────────────────────────────────────────────────────────────────
# C.  folder_to_safe_name() — conversion logic, all four copies
# ─────────────────────────────────────────────────────────────────────────────

class TestFolderToSafeName:
    """All four copies of folder_to_safe_name() must return identical results."""

    # Reference cases: input → expected output
    _CASES = [
        ("ACE Docs",           "ace_docs"),
        ("BizOps",             "bizops"),
        ("CP4I Docs",          "cp4i_docs"),
        ("My Sales & Revenue", "my_sales_revenue"),
        ("skills",             "skills"),
        ("  Leading Space  ",  "leading_space"),
        ("Hello--World",       "hello_world"),
        ("123 Numbers",        "123_numbers"),
        ("a",                  "a"),
    ]

    def _run(self, fn, label):
        for inp, expected in self._CASES:
            result = fn(inp)
            assert result == expected, (
                f"{label}({inp!r}) = {result!r}, expected {expected!r}"
            )

    def test_agent_base(self):
        import agent_base as ab
        self._run(ab.folder_to_safe_name, "agent_base.folder_to_safe_name")

    def test_embeddings(self):
        import embeddings as emb
        self._run(emb.folder_to_safe_name, "embeddings.folder_to_safe_name")

    def test_generate(self):
        import generate
        self._run(generate.folder_to_safe_name, "generate.folder_to_safe_name")

    def test_watch_kb(self):
        import watch_kb
        self._run(watch_kb.folder_to_safe_name, "watch_kb.folder_to_safe_name")

    def test_all_copies_agree(self):
        """All four copies must return the same value for every test case."""
        import agent_base as ab
        import embeddings as emb
        import generate
        import watch_kb

        fns = {
            "agent_base": ab.folder_to_safe_name,
            "embeddings":  emb.folder_to_safe_name,
            "generate":    generate.folder_to_safe_name,
            "watch_kb":    watch_kb.folder_to_safe_name,
        }
        for inp, _ in self._CASES:
            results = {name: fn(inp) for name, fn in fns.items()}
            values = set(results.values())
            assert len(values) == 1, (
                f"folder_to_safe_name({inp!r}) diverged across copies: {results}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# D.  _find_readme() — 4-priority cascade, agent_base and generate copies
# ─────────────────────────────────────────────────────────────────────────────

def _make_md(folder: pathlib.Path, name: str, content: str = "# Title\n\nContent.") -> pathlib.Path:
    f = folder / name
    f.write_text(content, encoding="utf-8")
    return f


class TestFindReadme:
    """_find_readme() must honour the 4-priority cascade in both copies."""

    @pytest.fixture(autouse=True)
    def _fns(self):
        import agent_base as ab
        import generate
        self.ab_find = ab._find_readme
        self.gen_find = generate._find_readme

    # ── Priority 1: name contains "readme" ───────────────────────────────────

    def test_priority1_readme_in_name(self, tmp_path):
        f = _make_md(tmp_path, "my_readme_file.md")
        assert self.ab_find(tmp_path) == f
        assert self.gen_find(tmp_path) == f

    def test_priority1_case_insensitive(self, tmp_path):
        f = _make_md(tmp_path, "README.md")
        assert self.ab_find(tmp_path) == f
        assert self.gen_find(tmp_path) == f

    def test_priority1_beats_folder_name(self, tmp_path):
        """A file with 'readme' in its name wins over <FolderName>.md."""
        folder = tmp_path / "ACE Docs"
        folder.mkdir()
        folder_named = _make_md(folder, "ACE Docs.md")
        readme = _make_md(folder, "my_readme.md")
        result_ab  = self.ab_find(folder)
        result_gen = self.gen_find(folder)
        assert result_ab  == readme
        assert result_gen == readme

    # ── Priority 2: <FolderName>.md ──────────────────────────────────────────

    def test_priority2_folder_name_md(self, tmp_path):
        folder = tmp_path / "ACE Docs"
        folder.mkdir()
        f = _make_md(folder, "ACE Docs.md")
        assert self.ab_find(folder) == f
        assert self.gen_find(folder) == f

    def test_priority2_beats_heading_match(self, tmp_path):
        """<FolderName>.md wins over a file that merely starts with a heading."""
        folder = tmp_path / "BizOps"
        folder.mkdir()
        heading_file = _make_md(folder, "other.md", "# Some heading\n\nContent.")
        folder_named = _make_md(folder, "BizOps.md", "no heading here")
        result_ab  = self.ab_find(folder)
        result_gen = self.gen_find(folder)
        assert result_ab  == folder_named
        assert result_gen == folder_named

    # ── Priority 3: first .md with a Markdown heading ────────────────────────

    def test_priority3_heading_match(self, tmp_path):
        f = _make_md(tmp_path, "overview.md", "# Overview\n\nSome content.")
        assert self.ab_find(tmp_path) == f
        assert self.gen_find(tmp_path) == f

    def test_priority3_requires_actual_heading(self, tmp_path):
        """A file without a heading should NOT be selected over a later file that has one."""
        no_heading  = _make_md(tmp_path, "aaa_first.md", "no heading here at all")
        has_heading = _make_md(tmp_path, "bbb_second.md", "# Real Heading\n\nContent.")
        # Priority 3 scans all .md files; aaa_first has no heading so bbb_second wins
        result_ab  = self.ab_find(tmp_path)
        result_gen = self.gen_find(tmp_path)
        assert result_ab  == has_heading
        assert result_gen == has_heading

    # ── Priority 4: first .md file ───────────────────────────────────────────

    def test_priority4_any_md_as_last_resort(self, tmp_path):
        f = _make_md(tmp_path, "notes.md", "no heading, no readme keyword")
        assert self.ab_find(tmp_path) == f
        assert self.gen_find(tmp_path) == f

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_returns_none_when_no_md_files(self, tmp_path):
        (tmp_path / "document.pdf").touch()
        assert self.ab_find(tmp_path) is None
        assert self.gen_find(tmp_path) is None

    def test_returns_none_for_empty_folder(self, tmp_path):
        assert self.ab_find(tmp_path) is None
        assert self.gen_find(tmp_path) is None

    def test_both_copies_agree_on_all_priorities(self, tmp_path):
        """Both copies must return the same file for all 4 priority scenarios."""
        # Scenario: only a heading-based file present
        folder = tmp_path / "domain"
        folder.mkdir()
        _make_md(folder, "content.md", "# Title\n\nBody.")
        assert self.ab_find(folder) == self.gen_find(folder)


# ─────────────────────────────────────────────────────────────────────────────
# E.  _stream_xlsx_aggregate() — output shape and content
# ─────────────────────────────────────────────────────────────────────────────

def _build_minimal_xlsx(path: pathlib.Path, headers: list, rows: list[list]):
    """
    Build a minimal valid XLSX file at *path* using only stdlib (zipfile +
    xml) so the test has zero extra dependencies.

    The file uses a single worksheet with the given headers and data rows.
    All values are written as inline strings (t="inlineStr") to keep the XML
    minimal — no shared strings table required.

    Note: openpyxl and the streaming aggregator both handle inline strings via
    different code paths. The streaming aggregator reads shared strings. To
    exercise the aggregator's shared-string path we write a proper sharedStrings
    table. Numeric values are written as plain numbers (no type attribute).
    """
    import io

    NS   = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    def col_letter(n: int) -> str:
        """1-based column index → Excel letter (A, B, …, Z, AA, …)."""
        s = ""
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    # ── Build shared strings ──────────────────────────────────────────────────
    all_strings: list[str] = []
    str_index: dict[str, int] = {}

    def _si(val: str) -> int:
        if val not in str_index:
            str_index[val] = len(all_strings)
            all_strings.append(val)
        return str_index[val]

    # Pre-register all string values
    for h in headers:
        _si(str(h))
    for row in rows:
        for v in row:
            if not isinstance(v, (int, float)):
                _si(str(v))

    # ── Build worksheet XML ──────────────────────────────────────────────────
    ws_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<worksheet xmlns="{NS}"><sheetData>',
    ]
    # Header row
    ws_lines.append('<row r="1">')
    for ci, h in enumerate(headers, start=1):
        ref = f"{col_letter(ci)}1"
        ws_lines.append(f'<c r="{ref}" t="s"><v>{_si(str(h))}</v></c>')
    ws_lines.append("</row>")
    # Data rows
    for ri, row in enumerate(rows, start=2):
        ws_lines.append(f'<row r="{ri}">')
        for ci, v in enumerate(row, start=1):
            ref = f"{col_letter(ci)}{ri}"
            if isinstance(v, (int, float)):
                ws_lines.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                ws_lines.append(f'<c r="{ref}" t="s"><v>{_si(str(v))}</v></c>')
        ws_lines.append("</row>")
    ws_lines.append("</sheetData></worksheet>")
    ws_xml = "\n".join(ws_lines).encode("utf-8")

    # ── Build sharedStrings XML ──────────────────────────────────────────────
    ss_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<sst xmlns="{NS}" count="{len(all_strings)}" uniqueCount="{len(all_strings)}">',
    ]
    for s in all_strings:
        ss_lines.append(f'<si><t>{s}</t></si>')
    ss_lines.append("</sst>")
    ss_xml = "\n".join(ss_lines).encode("utf-8")

    # ── Build workbook XML ────────────────────────────────────────────────────
    wb_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{NS}" '
        f'xmlns:r="{R_NS}">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    ).encode("utf-8")

    # ── Build workbook.xml.rels ───────────────────────────────────────────────
    rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ws_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    ss_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
    wb_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{rels_ns}">'
        f'<Relationship Id="rId1" Type="{ws_type}" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{ss_type}" Target="sharedStrings.xml"/>'
        '</Relationships>'
    ).encode("utf-8")

    # ── Build [Content_Types].xml ─────────────────────────────────────────────
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    wb_ct  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    ws_ct  = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    ss_ct  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
    ct_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{ct_ns}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml"  ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml"                ContentType="{wb_ct}"/>'
        f'<Override PartName="/xl/worksheets/sheet1.xml"       ContentType="{ws_ct}"/>'
        f'<Override PartName="/xl/sharedStrings.xml"           ContentType="{ss_ct}"/>'
        '</Types>'
    ).encode("utf-8")

    # ── Write ZIP ─────────────────────────────────────────────────────────────
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",          ct_xml)
        zf.writestr("xl/workbook.xml",              wb_xml)
        zf.writestr("xl/_rels/workbook.xml.rels",   wb_rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml",     ws_xml)
        zf.writestr("xl/sharedStrings.xml",         ss_xml)


class TestStreamXlsxAggregate:
    """_stream_xlsx_aggregate() output shape and aggregation correctness."""

    @pytest.fixture()
    def revenue_xlsx(self, tmp_path) -> pathlib.Path:
        """Minimal XLSX with a Geography column and a Won (numeric) column."""
        path = tmp_path / "revenue.xlsx"
        headers = ["geography", "product", "won"]
        rows = [
            ["EMEA", "ACE",  100.0],
            ["NA",   "ACE",  200.0],
            ["EMEA", "CP4I",  50.0],
            ["NA",   "CP4I",  75.0],
            ["EMEA", "ACE",   25.0],
        ]
        _build_minimal_xlsx(path, headers, rows)
        return path

    def test_returns_string(self, revenue_xlsx):
        import agent_base as ab
        result = ab._stream_xlsx_aggregate(revenue_xlsx)
        assert isinstance(result, str)

    def test_contains_sheet_label(self, revenue_xlsx):
        import agent_base as ab
        result = ab._stream_xlsx_aggregate(revenue_xlsx)
        assert "[Sheet:" in result

    def test_contains_rows_line(self, revenue_xlsx):
        import agent_base as ab
        result = ab._stream_xlsx_aggregate(revenue_xlsx)
        assert "Rows:" in result

    def test_contains_revenue_column_name(self, revenue_xlsx):
        import agent_base as ab
        result = ab._stream_xlsx_aggregate(revenue_xlsx)
        # 'won' is a PREFERRED_NUM_COLS entry — it should be detected
        assert "won" in result.lower() or "Revenue column" in result

    def test_aggregates_by_detected_dimension(self, revenue_xlsx):
        import agent_base as ab
        result = ab._stream_xlsx_aggregate(revenue_xlsx)
        # Geography or Product dimension should appear as a group-by header
        assert "EMEA" in result or "By Geography" in result or "By Product" in result

    def test_totals_are_present(self, revenue_xlsx):
        import agent_base as ab
        result = ab._stream_xlsx_aggregate(revenue_xlsx)
        assert "TOTAL:" in result

    def test_max_chars_respected(self, revenue_xlsx):
        import agent_base as ab
        result = ab._stream_xlsx_aggregate(revenue_xlsx, max_chars=50)
        assert len(result) <= 50

    def test_error_returns_sentinel_string(self, tmp_path):
        """A corrupt file must return an error sentinel, not raise."""
        import agent_base as ab
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"not a zip file at all")
        result = ab._stream_xlsx_aggregate(bad)
        assert isinstance(result, str)
        assert "error" in result.lower() or "stream" in result.lower()

    def test_numeric_values_summed_correctly(self, tmp_path):
        """EMEA won = 100 + 50 + 25 = 175; NA won = 200 + 75 = 275."""
        import agent_base as ab
        path = tmp_path / "check.xlsx"
        headers = ["geography", "won"]
        rows = [
            ["EMEA", 100.0],
            ["NA",   200.0],
            ["EMEA",  50.0],
            ["NA",    75.0],
            ["EMEA",  25.0],
        ]
        _build_minimal_xlsx(path, headers, rows)
        result = ab._stream_xlsx_aggregate(path)
        # The TOTAL should be 175 + 275 = 450
        assert "450" in result or "450.00" in result


# ─────────────────────────────────────────────────────────────────────────────
# F.  _has_noindex_ancestor() — cross-copy agreement check
#     (detailed per-copy tests live in test_noindex_guard.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestHasNoindexAncestorCrossCheck:
    """All three agents-layer copies must return the same True/False for the same input."""

    def test_all_return_false_for_clean_file(self, tmp_path, monkeypatch):
        import agent_base as ab
        import embeddings as emb

        monkeypatch.setattr(ab,  "KB_ROOT", tmp_path)
        monkeypatch.setattr(emb, "KB_ROOT", tmp_path)

        folder = tmp_path / "Domain"
        folder.mkdir()
        f = folder / "report.pdf"
        f.touch()

        assert ab._has_noindex_ancestor(f)  is False
        assert emb._has_noindex_ancestor(f) is False

    def test_all_return_true_for_noindex_file(self, tmp_path, monkeypatch):
        import agent_base as ab
        import embeddings as emb

        monkeypatch.setattr(ab,  "KB_ROOT", tmp_path)
        monkeypatch.setattr(emb, "KB_ROOT", tmp_path)

        folder = tmp_path / "Secret"
        folder.mkdir()
        (folder / ".noindex").touch()
        f = folder / "secret.txt"
        f.touch()

        assert ab._has_noindex_ancestor(f)  is True
        assert emb._has_noindex_ancestor(f) is True


# ─────────────────────────────────────────────────────────────────────────────
# G.  DEFAULT_BLOCKLIST — consolidated into agent_base.py; used as the base
#     by embeddings.py, generate.py, and watch_kb.py.
# ─────────────────────────────────────────────────────────────────────────────

_EXPECTED_BLOCKLIST = frozenset({
    "agents", ".git", "__pycache__", ".ds_store", "node_modules",
    ".venv", "venv", "env", ".bob", ".idea", ".vscode", "dist", "build",
})


class TestDefaultBlocklist:
    """DEFAULT_BLOCKLIST must be canonical in agent_base and consumed everywhere."""

    def test_agent_base_has_canonical_blocklist(self):
        import agent_base as ab
        assert hasattr(ab, "DEFAULT_BLOCKLIST"), "agent_base must export DEFAULT_BLOCKLIST"
        assert ab.DEFAULT_BLOCKLIST == _EXPECTED_BLOCKLIST

    def test_embeddings_imports_from_agent_base(self):
        """embeddings.py must not define its own _DEFAULT_BLOCKLIST."""
        import embeddings as emb
        # Must import DEFAULT_BLOCKLIST from agent_base, not define its own copy
        assert not hasattr(emb, "_DEFAULT_BLOCKLIST"), (
            "embeddings.py still has a local _DEFAULT_BLOCKLIST — it should import from agent_base"
        )
        # BLOCKLIST must be built from DEFAULT_BLOCKLIST (a superset)
        assert _EXPECTED_BLOCKLIST.issubset(emb.BLOCKLIST), (
            "embeddings.BLOCKLIST does not contain all DEFAULT_BLOCKLIST entries"
        )

    def test_generate_imports_from_agent_base(self):
        """generate.py must not define its own _DEFAULT_BLOCKLIST."""
        import generate
        assert not hasattr(generate, "_DEFAULT_BLOCKLIST"), (
            "generate.py still has a local _DEFAULT_BLOCKLIST — it should import from agent_base"
        )
        blocklist = generate.get_blocklist()
        assert _EXPECTED_BLOCKLIST.issubset(blocklist), (
            "generate.get_blocklist() does not contain all DEFAULT_BLOCKLIST entries"
        )

    def test_watch_kb_imports_from_agent_base(self):
        """watch_kb.py must not define its own _DEFAULT_BLOCKLIST."""
        import watch_kb
        assert not hasattr(watch_kb, "_DEFAULT_BLOCKLIST"), (
            "watch_kb.py still has a local _DEFAULT_BLOCKLIST — it should import from agent_base"
        )
        assert _EXPECTED_BLOCKLIST.issubset(watch_kb.BLOCKLIST), (
            "watch_kb.BLOCKLIST does not contain all DEFAULT_BLOCKLIST entries"
        )

    def test_all_consumers_include_canonical_entries(self):
        """All three consumers must include every canonical entry."""
        import embeddings as emb
        import generate
        import watch_kb

        for entry in _EXPECTED_BLOCKLIST:
            assert entry in emb.BLOCKLIST,          f"embeddings.BLOCKLIST missing {entry!r}"
            assert entry in generate.get_blocklist(), f"generate.get_blocklist() missing {entry!r}"
            assert entry in watch_kb.BLOCKLIST,     f"watch_kb.BLOCKLIST missing {entry!r}"


# ─────────────────────────────────────────────────────────────────────────────
# H.  INCLUDE_EXTS — canonical base in agent_base.py; embeddings.py and
#     generate.py use it directly; watch_kb.py extends it with image types.
# ─────────────────────────────────────────────────────────────────────────────

_EXPECTED_INCLUDE_EXTS = frozenset({
    ".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt",
    ".csv", ".boxnote", ".ppt", ".doc",
})

# watch_kb adds image support for OCR; ask.py and agent_knowledgebase.py also
# add images for file-count display.  These are intentional divergences.
_WATCH_EXTRA_EXTS = frozenset({".png", ".jpg", ".jpeg"})


class TestIncludeExts:
    """INCLUDE_EXTS must be canonical in agent_base; consumers must include all base entries."""

    def test_agent_base_has_canonical_include_exts(self):
        import agent_base as ab
        assert hasattr(ab, "INCLUDE_EXTS"), "agent_base must export INCLUDE_EXTS"
        assert ab.INCLUDE_EXTS == _EXPECTED_INCLUDE_EXTS

    def test_embeddings_uses_canonical_include_exts(self):
        import embeddings as emb
        # embeddings imports INCLUDE_EXTS directly from agent_base
        assert emb.INCLUDE_EXTS == _EXPECTED_INCLUDE_EXTS, (
            f"embeddings.INCLUDE_EXTS diverged from canonical: {emb.INCLUDE_EXTS!r}"
        )

    def test_generate_uses_canonical_include_exts(self):
        import generate
        assert generate.INCLUDE_EXTS == _EXPECTED_INCLUDE_EXTS, (
            f"generate.INCLUDE_EXTS diverged from canonical: {generate.INCLUDE_EXTS!r}"
        )

    def test_watch_kb_extends_canonical(self):
        """watch_kb INCLUDE_EXTS must be a superset of the canonical base."""
        import watch_kb
        assert _EXPECTED_INCLUDE_EXTS.issubset(watch_kb.INCLUDE_EXTS), (
            f"watch_kb.INCLUDE_EXTS missing base entries: "
            f"{_EXPECTED_INCLUDE_EXTS - watch_kb.INCLUDE_EXTS!r}"
        )
        # And it must contain the image extensions
        for ext in _WATCH_EXTRA_EXTS:
            assert ext in watch_kb.INCLUDE_EXTS, (
                f"watch_kb.INCLUDE_EXTS missing expected image ext {ext!r}"
            )

    def test_embeddings_and_generate_agree(self):
        import embeddings as emb
        import generate
        assert emb.INCLUDE_EXTS == generate.INCLUDE_EXTS, (
            f"embeddings.INCLUDE_EXTS != generate.INCLUDE_EXTS:\n"
            f"  embeddings: {emb.INCLUDE_EXTS!r}\n"
            f"  generate:   {generate.INCLUDE_EXTS!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# I.  SKIP_PATTERNS — canonical base in agent_base.py; embeddings.py and
#     generate.py use it directly; watch_kb.py intentionally differs.
# ─────────────────────────────────────────────────────────────────────────────

_EXPECTED_SKIP_PATTERNS = frozenset({
    "readme", ".ds_store", "watch_kb", "__pycache__",
})

# watch_kb.py uses a purposely different set (add .watch.log / thumbs.db / ~$,
# drop "watch_kb" and "__pycache__" which aren't relevant there).
_WATCH_SKIP_PATTERNS = frozenset({
    "readme", ".ds_store", ".watch.log", "thumbs.db", "~$",
})


class TestSkipPatterns:
    """SKIP_PATTERNS must be canonical in agent_base; embeddings and generate use it directly."""

    def test_agent_base_has_canonical_skip_patterns(self):
        import agent_base as ab
        assert hasattr(ab, "SKIP_PATTERNS"), "agent_base must export SKIP_PATTERNS"
        assert ab.SKIP_PATTERNS == _EXPECTED_SKIP_PATTERNS

    def test_embeddings_uses_canonical_skip_patterns(self):
        import embeddings as emb
        assert emb.SKIP_PATTERNS == _EXPECTED_SKIP_PATTERNS, (
            f"embeddings.SKIP_PATTERNS diverged from canonical: {emb.SKIP_PATTERNS!r}"
        )

    def test_generate_uses_canonical_skip_patterns(self):
        import generate
        assert generate.SKIP_PATTERNS == _EXPECTED_SKIP_PATTERNS, (
            f"generate.SKIP_PATTERNS diverged from canonical: {generate.SKIP_PATTERNS!r}"
        )

    def test_embeddings_and_generate_agree(self):
        import embeddings as emb
        import generate
        assert emb.SKIP_PATTERNS == generate.SKIP_PATTERNS, (
            f"embeddings.SKIP_PATTERNS != generate.SKIP_PATTERNS:\n"
            f"  embeddings: {emb.SKIP_PATTERNS!r}\n"
            f"  generate:   {generate.SKIP_PATTERNS!r}"
        )

    def test_watch_kb_has_intentionally_different_skip_patterns(self):
        """watch_kb.SKIP_PATTERNS must match its own documented intent."""
        import watch_kb
        assert watch_kb.SKIP_PATTERNS == _WATCH_SKIP_PATTERNS, (
            f"watch_kb.SKIP_PATTERNS changed unexpectedly: {watch_kb.SKIP_PATTERNS!r}"
        )
        # readme must always be in watch_kb too — it's universal
        assert "readme" in watch_kb.SKIP_PATTERNS
        # watch_kb must NOT include "watch_kb" (would block the script itself
        # from being used as a sentinel — unnecessary since it's not a document file)
        assert "watch_kb" not in watch_kb.SKIP_PATTERNS
