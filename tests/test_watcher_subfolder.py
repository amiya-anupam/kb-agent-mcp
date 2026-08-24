"""
tests/test_watcher_subfolder.py
────────────────────────────────
Smoke tests for scripts/watch_kb.py — focusing on:

  1. top_folder_name()            — extracts correct domain from any depth
  2. is_knowledge_folder()        — correctly classifies folders
  3. should_skip()                — correctly gates files
  4. KBHandler.on_created()       — sub-folder file schedules generate + index
  5. KBHandler.on_deleted()       — sub-folder file schedules generate + deindex
  6. KBHandler.on_modified()      — sub-folder file schedules generate + index
  7. KBHandler.on_created()       — root-level file does NOT schedule generate
  8. KBHandler.on_modified()      — root-level file does NOT schedule generate
  9. KBHandler.on_created()       — new top-level folder schedules generate
 10. KBHandler.on_moved() rename  — top-level folder rename does NOT schedule generate
 11. _schedule_generate()         — coalesces multiple sub-folder events into one run
 12. dispatch_pending()           — fires generate after debounce expires
 13. dispatch_pending()           — does NOT fire generate before debounce expires
"""
from __future__ import annotations

import pathlib
import sys
import time
import types
from unittest.mock import MagicMock, patch, call

import pytest

# ── Import the module under test ──────────────────────────────────────────────
# watch_kb.py lives in scripts/ at the repo root.
_REPO_ROOT = pathlib.Path(__file__).parent.parent
_SCRIPTS   = _REPO_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_REPO_ROOT / "agents"))

import watch_kb  # noqa: E402  (import after sys.path manipulation)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_event(src_path: str, is_directory: bool = False):
    """Build a minimal watchdog-style event object."""
    ev = types.SimpleNamespace(
        src_path=src_path,
        dest_path="",
        is_directory=is_directory,
    )
    return ev


def _make_handler(watch_root: pathlib.Path, known_folders: set[str] | None = None):
    """
    Construct a KBHandler whose WATCH_ROOT and _known_folders are overridden
    to point at a tmp directory.  All expensive side-effects (summary cache,
    LLM, file-system reads) are patched out.
    """
    with (
        patch.object(watch_kb, "WATCH_ROOT", watch_root),
        patch.object(watch_kb, "_load_summary_cache", return_value={}),
        patch.object(watch_kb, "discover_knowledge_folders", return_value=[]),
        patch("time.time", return_value=1_000_000.0),
    ):
        handler = watch_kb.KBHandler()

    # Override WATCH_ROOT on the instance level as well (KBHandler references
    # the module global at event time — we patch it at module level in each test).
    if known_folders is not None:
        handler._known_folders = known_folders
    return handler


# ═════════════════════════════════════════════════════════════════════════════
# 1. top_folder_name
# ═════════════════════════════════════════════════════════════════════════════

class TestTopFolderName:

    def test_direct_child(self, tmp_path):
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            result = watch_kb.top_folder_name(str(tmp_path / "BizOps" / "file.xlsx"))
        assert result == "BizOps"

    def test_nested_two_levels(self, tmp_path):
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            result = watch_kb.top_folder_name(
                str(tmp_path / "BizOps" / "Renewal Tracking" / "Q1.xlsx")
            )
        assert result == "BizOps"

    def test_nested_three_levels(self, tmp_path):
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            result = watch_kb.top_folder_name(
                str(tmp_path / "ACE Docs" / "Sub" / "Deep" / "doc.pdf")
            )
        assert result == "ACE Docs"

    def test_returns_none_for_watch_root_itself(self, tmp_path):
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            result = watch_kb.top_folder_name(str(tmp_path))
        assert result is None

    def test_returns_none_for_path_outside_root(self, tmp_path):
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            result = watch_kb.top_folder_name("/some/other/path/file.txt")
        assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# 2. is_knowledge_folder
# ═════════════════════════════════════════════════════════════════════════════

class TestIsKnowledgeFolder:

    def test_valid_top_level_folder(self, tmp_path):
        folder = tmp_path / "BizOps"
        folder.mkdir()
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            assert watch_kb.is_knowledge_folder(folder) is True

    def test_blocklisted_folder_excluded(self, tmp_path):
        folder = tmp_path / "agents"
        folder.mkdir()
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            assert watch_kb.is_knowledge_folder(folder) is False

    def test_nested_folder_excluded(self, tmp_path):
        nested = tmp_path / "BizOps" / "Renewal Tracking"
        nested.mkdir(parents=True)
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            # is_knowledge_folder checks parent == WATCH_ROOT
            assert watch_kb.is_knowledge_folder(nested) is False

    def test_file_is_not_a_folder(self, tmp_path):
        f = tmp_path / "file.txt"
        f.touch()
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            assert watch_kb.is_knowledge_folder(f) is False


# ═════════════════════════════════════════════════════════════════════════════
# 3. should_skip
# ═════════════════════════════════════════════════════════════════════════════

class TestShouldSkip:

    def test_readme_skipped(self):
        assert watch_kb.should_skip(pathlib.Path("ACE Docs/readme file.md")) is True

    def test_ds_store_skipped(self):
        assert watch_kb.should_skip(pathlib.Path(".DS_Store")) is True

    def test_normal_pdf_not_skipped(self):
        assert watch_kb.should_skip(pathlib.Path("ACE Docs/Guide.pdf")) is False

    def test_normal_xlsx_not_skipped(self):
        assert watch_kb.should_skip(pathlib.Path("BizOps/Revenue.xlsx")) is False

    def test_watch_log_skipped(self):
        assert watch_kb.should_skip(pathlib.Path(".watch.log")) is True


# ═════════════════════════════════════════════════════════════════════════════
# 4. on_created — sub-folder file schedules generate AND index
# ═════════════════════════════════════════════════════════════════════════════

class TestOnCreatedSubFolder:

    def test_subfolder_file_schedules_generate(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "Renewal Tracking" / "Q1.xlsx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_created(ev)

        assert handler._pending_generate is not None, \
            "generate.py should be scheduled for sub-folder file creation"

    def test_subfolder_file_schedule_reason_contains_subfolder(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "Renewal Tracking" / "Q1.xlsx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_created(ev)

        assert "sub-folder" in handler._pending_generate_reason

    def test_subfolder_file_also_schedules_index(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "Renewal Tracking" / "Q1.xlsx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_created(ev)

        assert "BizOps" in handler._pending_index, \
            "File should also be queued for index update"


# ═════════════════════════════════════════════════════════════════════════════
# 5. on_deleted — sub-folder file schedules generate AND deindex
# ═════════════════════════════════════════════════════════════════════════════

class TestOnDeletedSubFolder:

    def test_subfolder_file_deleted_schedules_generate(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "CoE" / "report.pdf"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_deleted(ev)

        assert handler._pending_generate is not None

    def test_subfolder_file_deleted_reason(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "CoE" / "report.pdf"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_deleted(ev)

        assert "sub-folder" in handler._pending_generate_reason

    def test_subfolder_file_deleted_schedules_deindex(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "CoE" / "report.pdf"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_deleted(ev)

        assert "BizOps" in handler._pending_deindex


# ═════════════════════════════════════════════════════════════════════════════
# 6. on_modified — sub-folder file schedules generate AND index
# ═════════════════════════════════════════════════════════════════════════════

class TestOnModifiedSubFolder:

    def test_subfolder_file_modified_schedules_generate(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"ACE Docs"})
        ev = _fake_event(str(tmp_path / "ACE Docs" / "Migration" / "guide.docx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_modified(ev)

        assert handler._pending_generate is not None

    def test_subfolder_file_modified_reason(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"ACE Docs"})
        ev = _fake_event(str(tmp_path / "ACE Docs" / "Migration" / "guide.docx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_modified(ev)

        assert "sub-folder" in handler._pending_generate_reason

    def test_subfolder_file_modified_schedules_index(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"ACE Docs"})
        ev = _fake_event(str(tmp_path / "ACE Docs" / "Migration" / "guide.docx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_modified(ev)

        assert "ACE Docs" in handler._pending_index


# ═════════════════════════════════════════════════════════════════════════════
# 7 & 8. Root-level file events do NOT schedule generate
# ═════════════════════════════════════════════════════════════════════════════

class TestRootLevelFileNoGenerate:

    def test_root_file_created_no_generate(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "Revenue.xlsx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_created(ev)

        assert handler._pending_generate is None, \
            "Root-level file creation should NOT schedule generate.py"

    def test_root_file_modified_no_generate(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "Revenue.xlsx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_modified(ev)

        assert handler._pending_generate is None

    def test_root_file_created_still_indexes(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        ev = _fake_event(str(tmp_path / "BizOps" / "Revenue.xlsx"))

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_created(ev)

        assert "BizOps" in handler._pending_index


# ═════════════════════════════════════════════════════════════════════════════
# 9. New top-level folder creation still schedules generate
# ═════════════════════════════════════════════════════════════════════════════

class TestNewTopLevelFolder:

    def test_new_top_folder_schedules_generate(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        new_folder = tmp_path / "NewDomain"
        new_folder.mkdir()
        ev = _fake_event(str(new_folder), is_directory=True)

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_created(ev)

        assert handler._pending_generate is not None

    def test_new_top_folder_reason(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        new_folder = tmp_path / "NewDomain"
        new_folder.mkdir()
        ev = _fake_event(str(new_folder), is_directory=True)

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_created(ev)

        assert "new folder" in handler._pending_generate_reason.lower()

    def test_sub_folder_creation_does_not_schedule_generate(self, tmp_path):
        """A sub-folder being created (not top-level) should not trigger generate."""
        handler = _make_handler(tmp_path, known_folders={"BizOps"})
        sub = tmp_path / "BizOps" / "NewSub"
        sub.mkdir(parents=True)
        ev = _fake_event(str(sub), is_directory=True)

        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            handler.on_created(ev)

        # Directory events for non-root dirs are returned early — no generate scheduled
        assert handler._pending_generate is None


# ═════════════════════════════════════════════════════════════════════════════
# 10. Top-level folder rename does NOT double-schedule generate
# ═════════════════════════════════════════════════════════════════════════════

class TestFolderRename:

    def test_rename_does_not_schedule_generate(self, tmp_path):
        old = tmp_path / "OldDomain"
        new = tmp_path / "NewDomain"
        old.mkdir(); new.mkdir()
        handler = _make_handler(tmp_path, known_folders={"OldDomain"})
        ev = _fake_event(str(old), is_directory=True)
        ev.dest_path = str(new)

        with (
            patch.object(watch_kb, "WATCH_ROOT", tmp_path),
            patch.object(watch_kb, "_rename_folder_artifacts", return_value=False),
            patch.object(watch_kb, "_save_summary_cache"),
        ):
            handler.on_moved(ev)

        assert handler._pending_generate is None, \
            "Folder rename should NOT trigger generate.py (inline rename handles it)"

    def test_rename_updates_known_folders(self, tmp_path):
        old = tmp_path / "OldDomain"
        new = tmp_path / "NewDomain"
        old.mkdir(); new.mkdir()
        handler = _make_handler(tmp_path, known_folders={"OldDomain"})
        ev = _fake_event(str(old), is_directory=True)
        ev.dest_path = str(new)

        with (
            patch.object(watch_kb, "WATCH_ROOT", tmp_path),
            patch.object(watch_kb, "_rename_folder_artifacts", return_value=False),
            patch.object(watch_kb, "_save_summary_cache"),
        ):
            handler.on_moved(ev)

        assert "OldDomain" not in handler._known_folders
        assert "NewDomain" in handler._known_folders


# ═════════════════════════════════════════════════════════════════════════════
# 11. _schedule_generate coalesces multiple calls into one pending entry
# ═════════════════════════════════════════════════════════════════════════════

class TestScheduleGenerateCoalescing:

    def test_second_call_does_not_overwrite_first(self, tmp_path):
        handler = _make_handler(tmp_path)
        with patch("time.time", return_value=1_000_000.0):
            handler._schedule_generate("reason A")
        first_deadline = handler._pending_generate
        first_reason   = handler._pending_generate_reason

        with patch("time.time", return_value=1_000_001.0):
            handler._schedule_generate("reason B")

        # Deadline and reason should remain from the FIRST call
        assert handler._pending_generate  == first_deadline
        assert handler._pending_generate_reason == first_reason

    def test_multiple_subfolder_events_one_generate(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})

        files = [
            tmp_path / "BizOps" / "Sub" / f"file{i}.pdf"
            for i in range(5)
        ]
        with patch.object(watch_kb, "WATCH_ROOT", tmp_path):
            for f in files:
                handler.on_created(_fake_event(str(f)))

        # Still exactly one pending generate — not five
        assert handler._pending_generate is not None
        # Confirm only the first reason was kept
        assert "sub-folder" in handler._pending_generate_reason


# ═════════════════════════════════════════════════════════════════════════════
# 12. dispatch_pending fires generate after debounce expires
# ═════════════════════════════════════════════════════════════════════════════

class TestDispatchPendingFiresGenerate:

    def test_fires_when_debounce_passed(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})

        # Plant a pending generate whose deadline is in the past
        handler._pending_generate        = time.time() - 1.0
        handler._pending_generate_reason = "sub-folder content changed: BizOps"

        called_reasons: list[str] = []

        with (
            patch.object(watch_kb, "WATCH_ROOT", tmp_path),
            patch.object(watch_kb, "run_generate", side_effect=lambda r: called_reasons.append(r)),
            patch.object(watch_kb, "discover_knowledge_folders", return_value=[]),
            patch.object(watch_kb, "check_stale_files", return_value=[]),
            patch.object(watch_kb, "_RESYNC_INTERVAL", 0),   # disable 24h resync
        ):
            handler._next_stale_check = time.time() + 9999  # skip stale check
            handler._next_resync      = time.time() + 9999  # skip resync
            handler.dispatch_pending()

        assert called_reasons == ["sub-folder content changed: BizOps"]
        assert handler._pending_generate is None  # cleared after firing


# ═════════════════════════════════════════════════════════════════════════════
# 13. dispatch_pending does NOT fire generate before debounce expires
# ═════════════════════════════════════════════════════════════════════════════

class TestDispatchPendingRespectsDebounce:

    def test_does_not_fire_before_deadline(self, tmp_path):
        handler = _make_handler(tmp_path, known_folders={"BizOps"})

        # Deadline is far in the future
        handler._pending_generate        = time.time() + 9999.0
        handler._pending_generate_reason = "sub-folder content changed: BizOps"

        called: list[str] = []

        with (
            patch.object(watch_kb, "WATCH_ROOT", tmp_path),
            patch.object(watch_kb, "run_generate", side_effect=lambda r: called.append(r)),
            patch.object(watch_kb, "discover_knowledge_folders", return_value=[]),
            patch.object(watch_kb, "check_stale_files", return_value=[]),
            patch.object(watch_kb, "_RESYNC_INTERVAL", 0),
        ):
            handler._next_stale_check = time.time() + 9999
            handler._next_resync      = time.time() + 9999
            handler.dispatch_pending()

        assert called == [], "generate.py must not fire before debounce expires"
        assert handler._pending_generate is not None  # still pending
