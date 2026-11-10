"""
Streaming readers for tabular files (xlsx, csv, tsv).

The analyst loaders parse a whole sheet into memory, which does not work for
the multi-GB revenue workbooks. These readers yield one row at a time, so the
caller decides how much to keep and when to stop.

    with open_table(path) as src:
        for i, name in enumerate(src.names):
            for row in src.rows(i):      # list of cell values, header first
                ...

Rows are lists indexed by column position; trailing empty cells are omitted and
empty rows are skipped. Numbers come back as int (when whole) or float; shared
and inline strings come back as str.
"""
from __future__ import annotations

import csv
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Iterator

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_T_ROW = f"{{{_NS}}}row"
_T_C = f"{{{_NS}}}c"
_T_V = f"{{{_NS}}}v"
_T_IS = f"{{{_NS}}}is"
_T_SI = f"{{{_NS}}}si"
_T_T = f"{{{_NS}}}t"
_T_R = f"{{{_NS}}}r"
_T_SHEET = f"{{{_NS}}}sheet"

_DIMENSION_RE = re.compile(rb'<(?:\w+:)?dimension\s+ref="[A-Za-z]+(\d+)(?::[A-Za-z]+(\d+))?"')
_PEEK_BYTES = 1 << 20


# ── xlsx ──────────────────────────────────────────────────────────────────────

def _col_idx(ref: str) -> int:
    n = 0
    for ch in ref:
        if "A" <= ch <= "Z":
            n = n * 26 + ord(ch) - 64
        elif "a" <= ch <= "z":
            n = n * 26 + ord(ch) - 96
        else:
            break
    return n - 1


def _si_text(el: ET.Element) -> str:
    """Text of a shared-string or inline-string element (phonetic runs ignored)."""
    parts: list[str] = []
    for ch in el:
        if ch.tag == _T_T:
            parts.append(ch.text or "")
        elif ch.tag == _T_R:
            t = ch.find(_T_T)
            if t is not None:
                parts.append(t.text or "")
    return "".join(parts)


def _cell_value(c: ET.Element, shared: list[str]) -> Any:
    t = c.get("t")
    if t == "inlineStr":
        el = c.find(_T_IS)
        return _si_text(el) if el is not None else None
    v = c.find(_T_V)
    raw = v.text if v is not None else None
    if raw is None:
        return None
    if t == "s":
        try:
            return shared[int(raw)]
        except (IndexError, ValueError):
            return raw
    if t == "str":
        return raw
    if t == "b":
        return "TRUE" if raw == "1" else "FALSE"
    if t == "e":
        return None
    try:
        f = float(raw)
    except ValueError:
        return raw
    return int(f) if f.is_integer() else f


def _row_values(row: ET.Element, shared: list[str]) -> list[Any] | None:
    vals: dict[int, Any] = {}
    nxt = 0
    for c in row:
        if c.tag != _T_C:
            continue
        ref = c.get("r")
        idx = _col_idx(ref) if ref else nxt
        nxt = idx + 1
        v = _cell_value(c, shared)
        if v is not None:
            vals[idx] = v
    if not vals:
        return None
    return [vals.get(i) for i in range(max(vals) + 1)]


class XlsxSource:
    def __init__(self, path: Path) -> None:
        self._zf = zipfile.ZipFile(str(path))
        self._members = {n.lower(): n for n in self._zf.namelist()}
        self._sheets = self._discover()
        self._shared: list[str] | None = None
        self.names = [name for name, _ in self._sheets]

    def _discover(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        try:
            wb = ET.fromstring(self._zf.read(self._members["xl/workbook.xml"]))
            rels = ET.fromstring(self._zf.read(self._members["xl/_rels/workbook.xml.rels"]))
            targets = {r.get("Id"): r.get("Target") or "" for r in rels}
            for s in wb.iter(_T_SHEET):
                target = targets.get(s.get(f"{{{_REL_NS}}}id"), "")
                member = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
                actual = self._members.get(member.lower())
                if actual and "/worksheets/" in actual.lower():
                    out.append((s.get("name") or posixpath.basename(actual), actual))
        except Exception:
            out = []
        if out:
            return out
        found = sorted(
            (n for n in self._zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n, re.I)),
            key=lambda n: int(re.search(r"(\d+)\.xml$", n, re.I).group(1)),  # type: ignore[union-attr]
        )
        return [(posixpath.splitext(posixpath.basename(n))[0], n) for n in found]

    def _shared_strings(self) -> list[str]:
        if self._shared is None:
            out: list[str] = []
            member = self._members.get("xl/sharedstrings.xml")
            if member:
                with self._zf.open(member) as f:
                    for _, el in ET.iterparse(f, events=("end",)):
                        if el.tag == _T_SI:
                            out.append(_si_text(el))
                            el.clear()
            self._shared = out
        return self._shared

    def estimated_rows(self, index: int) -> int | None:
        """Data rows according to the sheet's <dimension> tag (header excluded)."""
        with self._zf.open(self._sheets[index][1]) as f:
            m = _DIMENSION_RE.search(f.read(_PEEK_BYTES))
        if not m or not m.group(2):
            return None
        return max(int(m.group(2)) - int(m.group(1)), 0)

    def rows(self, index: int) -> Iterator[list[Any]]:
        shared = self._shared_strings()
        with self._zf.open(self._sheets[index][1]) as f:
            for _, el in ET.iterparse(f, events=("end",)):
                if el.tag != _T_ROW:
                    continue
                vals = _row_values(el, shared)
                el.clear()
                if vals is not None:
                    yield vals

    def close(self) -> None:
        self._zf.close()


# ── csv / tsv ─────────────────────────────────────────────────────────────────

class CsvSource:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        self.names = [path.stem]

    def estimated_rows(self, index: int) -> int | None:
        """File size divided by the average line length of the first megabyte."""
        try:
            size = self._path.stat().st_size
            with open(self._path, "rb") as f:
                head = f.read(_PEEK_BYTES)
        except OSError:
            return None
        lines = head.count(b"\n")
        if not lines:
            return None
        return max(int(size / (len(head) / lines)) - 1, 0)

    def rows(self, index: int) -> Iterator[list[Any]]:
        with open(self._path, newline="", encoding="utf-8-sig", errors="replace") as f:
            try:
                for row in csv.reader(f, delimiter=self._delimiter):
                    if row:
                        yield row
            except csv.Error:
                return

    def close(self) -> None:
        pass


# ── entry point ───────────────────────────────────────────────────────────────

class _Opened:
    def __init__(self, src: XlsxSource | CsvSource) -> None:
        self._src = src

    def __enter__(self) -> XlsxSource | CsvSource:
        return self._src

    def __exit__(self, *exc: object) -> None:
        self._src.close()


def open_table(path: str | Path) -> _Opened:
    """Open a table file for streaming. Raises on unreadable or unsupported files."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return _Opened(XlsxSource(p))  # legacy binary .xls raises BadZipFile
    if ext in (".csv", ".tsv"):
        return _Opened(CsvSource(p))
    raise ValueError(f"Unsupported table format: {ext}")
