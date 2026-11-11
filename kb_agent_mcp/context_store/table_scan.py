"""
One streaming pass over a worksheet or CSV for the digest builder.

The first SAMPLE_ROWS rows are kept to classify columns and choose what to
summarise (a Plan). Every row read, including the sample, then feeds bounded
accumulators (totals, group sums, distinct values), so memory stays flat no
matter how large the sheet is. When the time budget runs out the scan stops and
the result is marked partial.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from kb_agent_mcp.analyst.engine import _to_float
from kb_agent_mcp.analyst.inspector import DataCard, _profile_tabular
from kb_agent_mcp.context_store.table_stream import CsvSource, XlsxSource

SAMPLE_ROWS = 2000
VALUE_CAP = 1000          # distinct values tracked per column
GROUP_CAP = 200_000       # distinct group keys tracked per breakdown
_CHECK_EVERY = 256        # rows between deadline checks


@dataclass
class Plan:
    """What to summarise, decided from the sample."""
    metrics: list[str] = field(default_factory=list)
    twins: dict[str, list[str]] = field(default_factory=dict)
    ratio_metrics: list[str] = field(default_factory=list)
    exp_col: str | None = None
    ren_col: str | None = None
    primary: str | None = None
    breakdowns: list[tuple[str, str]] = field(default_factory=list)
    customer: str | None = None
    listed: list[str] = field(default_factory=list)
    value_cols: list[str] = field(default_factory=list)   # columns whose distinct values are tracked


def _fnum(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        f = _to_float(v)
        if f is None:
            return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


class Acc:
    """Bounded accumulators fed one row at a time."""

    def __init__(self, headers: list[str], plan: Plan, time_col: str | None) -> None:
        pos = {h: i for i, h in enumerate(headers)}
        sum_cols = list(plan.metrics) + [t for ts in plan.twins.values() for t in ts]
        self._sum = [(c, pos[c]) for c in sum_cols if c in pos]
        pairs: list[tuple[str, str]] = []
        for _, col in plan.breakdowns:
            for m in (plan.primary, plan.ren_col if plan.exp_col and plan.ren_col else None):
                if m:
                    pairs.append((col, m))
        if plan.customer and plan.primary:
            pairs.append((plan.customer, plan.primary))
        self._pairs = [(g, m, pos[g]) for g, m in pairs if g in pos]
        self._values = [(c, pos[c]) for c in plan.value_cols if c in pos]
        self._time = pos.get(time_col) if time_col else None

        self.totals: dict[str, float] = {c: 0.0 for c, _ in self._sum}
        self.counts: dict[str, int] = {c: 0 for c, _ in self._sum}
        self.max_abs: dict[str, float] = {c: 0.0 for c, _ in self._sum}
        self.sig: dict[str, int] = {c: 0 for c, _ in self._sum}
        self.groups: dict[tuple[str, str], dict[str, float]] = {(g, m): {} for g, m, _ in self._pairs}
        self.values: dict[str, set[str]] = {c: set() for c, _ in self._values}
        self.overflow: set[str] = set()
        self.tmin: str | None = None
        self.tmax: str | None = None

    def add(self, row: list[Any]) -> None:
        n = len(row)
        nums: dict[str, float | None] = {}
        for col, i in self._sum:
            f = _fnum(row[i]) if i < n else None
            nums[col] = f
            self.sig[col] = hash((self.sig[col], -0.0 if f is None else f, f is None))
            if f is not None:
                self.totals[col] += f
                self.counts[col] += 1
                a = abs(f)
                if a > self.max_abs[col]:
                    self.max_abs[col] = a
        for g, m, gi in self._pairs:
            f = nums.get(m)
            if f is None or gi >= n or row[gi] is None:
                continue
            key = str(row[gi]).strip()
            if not key:
                continue
            d = self.groups[(g, m)]
            if key in d:
                d[key] += f
            elif len(d) < GROUP_CAP:
                d[key] = f
        for col, i in self._values:
            if col in self.overflow or i >= n or row[i] is None:
                continue
            s = str(row[i]).strip()
            if s:
                vs = self.values[col]
                vs.add(s)
                if len(vs) > VALUE_CAP:
                    self.overflow.add(col)
        if self._time is not None and self._time < n and row[self._time] is not None:
            s = str(row[self._time])
            if self.tmin is None or s < self.tmin:
                self.tmin = s
            if self.tmax is None or s > self.tmax:
                self.tmax = s


@dataclass
class SheetScan:
    name: str
    headers: list[str] = field(default_factory=list)
    card: DataCard | None = None        # None when the sheet has no data
    plan: Plan = field(default_factory=Plan)
    acc: Acc | None = None
    rows_read: int = 0
    rows_total: int = 0                 # estimate of all data rows when partial
    partial: bool = False
    error: str = ""


def _clean_headers(row: list[Any]) -> list[str]:
    out: list[str] = []
    used: set[str] = set()
    for i, v in enumerate(row):
        name = str(v).strip() if v is not None else ""
        if not name:
            name = f"col_{i}"
        base, k = name, 2
        while name in used:
            name = f"{base} ({k})"
            k += 1
        used.add(name)
        out.append(name)
    return out


def scan_sheet(
    src: XlsxSource | CsvSource,
    index: int,
    path: Any,
    deadline: float,
    make_plan: Callable[[DataCard, list[dict]], Plan],
) -> SheetScan:
    scan = SheetScan(name=src.names[index])
    try:
        est = src.estimated_rows(index)
    except Exception:
        est = None
    it = src.rows(index)
    sample: list[list[Any]] = []
    count = 0
    try:
        first = next(it, None)
        if first is None:
            return scan
        headers = _clean_headers(first)
        n = len(headers)
        scan.headers = headers

        def finish_sample(exact: bool = False) -> None:
            plan_total = est if (not exact and est and est >= count) else count
            dicts = [dict(zip(headers, r)) for r in sample]
            scan.card = _profile_tabular(path, headers, sample, plan_total)
            scan.plan = make_plan(scan.card, dicts)
            scan.acc = Acc(headers, scan.plan, scan.card.time_columns[0] if scan.card.time_columns else None)
            for r in sample:
                scan.acc.add(r)

        try:
            for row in it:
                if len(row) > n:
                    row = row[:n]
                count += 1
                if scan.acc is None:
                    sample.append(row + [None] * (n - len(row)))
                    if len(sample) >= SAMPLE_ROWS:
                        finish_sample()
                else:
                    scan.acc.add(row)
                if count % _CHECK_EVERY == 0 and time.monotonic() > deadline:
                    if next(it, None) is not None:
                        scan.partial = True
                    break
        except Exception as exc:   # truncated or corrupt data: keep what was read
            scan.partial = True
            scan.error = type(exc).__name__
        if scan.acc is None:
            if count == 0:
                return scan        # header row only
            finish_sample(exact=not scan.partial)
    finally:
        it.close()

    card, acc = scan.card, scan.acc
    assert card is not None and acc is not None
    scan.rows_read = count
    scan.rows_total = max(est or 0, count) if scan.partial else count

    # Refresh figures the sample could only approximate.
    if count > len(sample):
        for c in card.columns:
            if c.name in acc.values:
                c.cardinality = max(len(acc.values[c.name]), c.cardinality)
        if acc.tmin is not None and card.time_range:
            old = f"{card.time_range['min']}–{card.time_range['max']}"
            card.time_range["min"], card.time_range["max"] = acc.tmin, acc.tmax
            card.summary = card.summary.replace(old, f"{acc.tmin}–{acc.tmax}")
    if card.total_rows != scan.rows_total:
        card.summary = card.summary.replace(f"{card.total_rows:,} rows", f"{scan.rows_total:,} rows", 1)
        card.total_rows = scan.rows_total
    return scan
