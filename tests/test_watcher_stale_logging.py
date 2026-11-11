"""
tests/test_watcher_stale_logging.py
───────────────────────────────────
Task 1.1 — the watcher must not re-print every stale file on every hourly check.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT / "agents"))

import watch_kb  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state():
    watch_kb._last_stale_keys = frozenset()
    yield
    watch_kb._last_stale_keys = frozenset()


def _warns(n: int, age: int = 100) -> list[str]:
    return [f"⚠ BizOps: file{i}.xlsx was last updated {age} days ago." for i in range(n)]


def test_first_report_lists_every_file(capsys):
    watch_kb.report_stale(_warns(3))
    out = capsys.readouterr().out
    assert "3 stale files" in out
    assert out.count(".xlsx") == 3


def test_repeat_with_same_set_prints_one_line(capsys):
    watch_kb.report_stale(_warns(50))
    capsys.readouterr()
    watch_kb.report_stale(_warns(50))
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert "50 stale files (unchanged)" in out


def test_age_change_alone_is_not_a_change(capsys):
    watch_kb.report_stale(_warns(5, age=100))
    capsys.readouterr()
    watch_kb.report_stale(_warns(5, age=101))
    assert "(unchanged)" in capsys.readouterr().out


def test_changed_set_lists_detail_again(capsys):
    watch_kb.report_stale(_warns(2))
    capsys.readouterr()
    watch_kb.report_stale(_warns(3))
    out = capsys.readouterr().out
    assert "3 stale files" in out
    assert "(unchanged)" not in out
    assert out.count(".xlsx") == 3


def test_empty_reports_clean_and_resets(capsys):
    watch_kb.report_stale(_warns(2))
    capsys.readouterr()
    watch_kb.report_stale([])
    assert "no stale files" in capsys.readouterr().out
    watch_kb.report_stale(_warns(2))
    assert "(unchanged)" not in capsys.readouterr().out
