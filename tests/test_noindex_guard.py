"""
tests/test_noindex_guard.py
───────────────────────────
Tests for the .noindex sentinel enforcement across all three agents-layer
modules:

  1. agents/agent_base._has_noindex_ancestor()  — guard helper
  2. agents/agent_base.extract_full_text()      — query-time read guard
  3. agents/embeddings.should_skip()            — index-time skip guard
  4. scripts/watch_kb.should_skip()             — watcher-time skip guard

These tests verify that a file whose ancestor folder contains a `.noindex`
file is correctly excluded at every layer where content could leak.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

# ── resolve the agents/ and scripts/ directories ──────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "agents"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))


# ═════════════════════════════════════════════════════════════════════════════
# 1 & 2.  agents/agent_base — _has_noindex_ancestor + extract_full_text guard
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentBaseNoindex:

    def test_has_noindex_ancestor_direct_parent(self, tmp_path):
        """File inside a folder that has .noindex must return True."""
        from agent_base import _has_noindex_ancestor
        protected = tmp_path / "Secret"
        protected.mkdir()
        (protected / ".noindex").touch()
        target = protected / "confidential.pdf"
        target.touch()
        assert _has_noindex_ancestor(target) is True

    def test_has_noindex_ancestor_nested(self, tmp_path):
        """File two levels deep under a .noindex folder must still return True."""
        from agent_base import _has_noindex_ancestor
        protected = tmp_path / "Domain" / "Secret"
        protected.mkdir(parents=True)
        (protected / ".noindex").touch()
        deep = protected / "sub" / "doc.docx"
        deep.parent.mkdir()
        deep.touch()
        assert _has_noindex_ancestor(deep) is True

    def test_has_noindex_ancestor_no_sentinel(self, tmp_path):
        """File in a clean folder must return False."""
        from agent_base import _has_noindex_ancestor
        folder = tmp_path / "Domain"
        folder.mkdir()
        target = folder / "report.pdf"
        target.touch()
        assert _has_noindex_ancestor(target) is False

    def test_has_noindex_ancestor_sibling_folder(self, tmp_path):
        """A .noindex in a sibling folder must NOT affect other folders."""
        from agent_base import _has_noindex_ancestor
        protected = tmp_path / "Secret"
        protected.mkdir()
        (protected / ".noindex").touch()

        clean = tmp_path / "Public"
        clean.mkdir()
        clean_file = clean / "guide.pdf"
        clean_file.touch()

        assert _has_noindex_ancestor(clean_file) is False

    def test_extract_full_text_blocked_by_noindex(self, tmp_path, monkeypatch):
        """extract_full_text must return the exclusion sentinel for .noindex files."""
        import agent_base
        monkeypatch.setattr(agent_base, "KB_ROOT", tmp_path)

        protected = tmp_path / "Secret"
        protected.mkdir()
        (protected / ".noindex").touch()
        secret_file = protected / "secret.txt"
        secret_file.write_text("top secret content", encoding="utf-8")

        result = agent_base.extract_full_text(secret_file)
        assert result.startswith("[Excluded:")
        assert "secret.txt" in result
        # Crucially — the actual content must NOT appear in the result
        assert "top secret content" not in result

    def test_extract_full_text_normal_file_readable(self, tmp_path, monkeypatch):
        """extract_full_text must still work for files with no .noindex ancestor."""
        import agent_base
        monkeypatch.setattr(agent_base, "KB_ROOT", tmp_path)

        folder = tmp_path / "Domain"
        folder.mkdir()
        normal = folder / "guide.txt"
        normal.write_text("This is the guide.", encoding="utf-8")

        result = agent_base.extract_full_text(normal)
        assert "This is the guide." in result


# ═════════════════════════════════════════════════════════════════════════════
# 3.  agents/embeddings — should_skip guard
# ═════════════════════════════════════════════════════════════════════════════

class TestEmbeddingsNoindex:

    def test_should_skip_noindex_direct(self, tmp_path, monkeypatch):
        """should_skip must return True for a file inside a .noindex folder."""
        import embeddings
        monkeypatch.setattr(embeddings, "KB_ROOT", tmp_path)

        protected = tmp_path / "Domain"
        protected.mkdir()
        (protected / ".noindex").touch()
        target = protected / "data.xlsx"
        target.touch()
        assert embeddings.should_skip(target) is True

    def test_should_skip_clean_file(self, tmp_path, monkeypatch):
        """should_skip must return False for a normal file (no .noindex)."""
        import embeddings
        monkeypatch.setattr(embeddings, "KB_ROOT", tmp_path)

        folder = tmp_path / "Domain"
        folder.mkdir()
        target = folder / "data.xlsx"
        target.touch()
        assert embeddings.should_skip(target) is False

    def test_should_skip_readme_still_skipped(self, tmp_path, monkeypatch):
        """Existing SKIP_PATTERNS behaviour must be preserved."""
        import embeddings
        monkeypatch.setattr(embeddings, "KB_ROOT", tmp_path)

        folder = tmp_path / "Domain"
        folder.mkdir()
        readme = folder / "README.md"
        readme.touch()
        assert embeddings.should_skip(readme) is True


# ═════════════════════════════════════════════════════════════════════════════
# 4.  scripts/watch_kb — should_skip guard
# ═════════════════════════════════════════════════════════════════════════════

class TestWatchKbNoindex:

    def test_should_skip_noindex_direct(self, tmp_path, monkeypatch):
        """watch_kb.should_skip must return True for files in .noindex folders."""
        import watch_kb
        monkeypatch.setattr(watch_kb, "WATCH_ROOT", tmp_path)

        protected = tmp_path / "Domain"
        protected.mkdir()
        (protected / ".noindex").touch()
        target = protected / "private.pdf"
        target.touch()
        assert watch_kb.should_skip(target) is True

    def test_should_skip_clean_file(self, tmp_path, monkeypatch):
        """watch_kb.should_skip must return False for a clean file."""
        import watch_kb
        monkeypatch.setattr(watch_kb, "WATCH_ROOT", tmp_path)

        folder = tmp_path / "Domain"
        folder.mkdir()
        target = folder / "report.pdf"
        target.touch()
        assert watch_kb.should_skip(target) is False

    def test_should_skip_ds_store_still_skipped(self, tmp_path):
        """Existing SKIP_PATTERNS behaviour must be preserved in watch_kb."""
        import watch_kb
        assert watch_kb.should_skip(pathlib.Path("ACE Docs/.DS_Store")) is True
