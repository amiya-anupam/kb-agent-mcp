"""
tests/test_watcher_log_rotation.py
──────────────────────────────────
Task 1.2 — .watch.log must be rotated so it cannot grow without bound.
"""
from __future__ import annotations

import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT / "agents"))

import watch_kb  # noqa: E402


def test_small_log_not_rotated(tmp_path):
    log = tmp_path / ".watch.log"
    log.write_text("x" * 10)
    assert watch_kb.rotate_log(log, max_bytes=100) is False
    assert log.read_text() == "x" * 10
    assert not (tmp_path / ".watch.log.1").exists()


def test_missing_log_is_noop(tmp_path):
    assert watch_kb.rotate_log(tmp_path / "nope.log", max_bytes=1) is False


def test_large_log_rotated_and_truncated(tmp_path):
    log = tmp_path / ".watch.log"
    log.write_text("a" * 200)
    assert watch_kb.rotate_log(log, max_bytes=100) is True
    assert log.stat().st_size == 0
    assert (tmp_path / ".watch.log.1").read_text() == "a" * 200


def test_open_append_handle_keeps_working_after_rotation(tmp_path):
    """launchd holds the file open in append mode; writes must land in the new log."""
    log = tmp_path / ".watch.log"
    with log.open("a") as fh:
        fh.write("b" * 200)
        fh.flush()
        assert watch_kb.rotate_log(log, max_bytes=100) is True
        fh.write("after")
        fh.flush()
    assert log.read_text() == "after"


def test_backups_shift_and_are_capped(tmp_path):
    log = tmp_path / ".watch.log"
    for ch in "abcde":
        log.write_text(ch * 200)
        watch_kb.rotate_log(log, max_bytes=100, backups=3)
    assert (tmp_path / ".watch.log.1").read_text() == "e" * 200
    assert (tmp_path / ".watch.log.2").read_text() == "d" * 200
    assert (tmp_path / ".watch.log.3").read_text() == "c" * 200
    assert not (tmp_path / ".watch.log.4").exists()


def test_disabled_when_max_bytes_zero(tmp_path):
    log = tmp_path / ".watch.log"
    log.write_text("a" * 500)
    assert watch_kb.rotate_log(log, max_bytes=0) is False


def test_rotated_backups_are_skipped_by_watcher():
    """.watch.log.1 etc. contain '.watch.log' so SKIP_PATTERNS must ignore them."""
    assert watch_kb.should_skip(pathlib.Path(".watch.log.1")) is True
