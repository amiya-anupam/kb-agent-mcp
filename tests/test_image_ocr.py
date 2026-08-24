"""
tests/test_image_ocr.py
───────────────────────
Tests for image OCR indexing in both the agents-layer (agent_base) and the
MCP-layer (kb_agent_mcp/file_parser).

Coverage:
  _extract_image_text()  — all three tiers (OCR / PIL fallback / filename-only)
  KB_OCR_ENABLED=false   — disabled path returns [Image: name] without importing deps
  KB_OCR_ENGINE=none     — skips pytesseract, falls through to PIL
  extract_full_text()    — image extensions routed correctly (not [Unsupported])
  file_parser._extract_image()  — same three tiers via MCP path (smoke test)
  file_parser._extract_sync()   — image ext dispatches to _extract_image()
"""
from __future__ import annotations

import pathlib
import sys
import types
import importlib
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fresh_agent_base(monkeypatch, env: dict[str, str]):
    """Import agent_base with a clean sys.path and the given env vars."""
    # Ensure agents/ is on sys.path
    agents_dir = pathlib.Path(__file__).parent.parent / "agents"
    if str(agents_dir) not in sys.path:
        sys.path.insert(0, str(agents_dir))

    for k, v in env.items():
        monkeypatch.setenv(k, v)

    # Force reimport so module-level constants pick up new env vars.
    for mod_name in list(sys.modules.keys()):
        if "agent_base" in mod_name and "agent_knowledgebase" not in mod_name:
            del sys.modules[mod_name]

    import agent_base as ab
    return ab


# ── _extract_image_text(): KB_OCR_ENABLED=false ────────────────────────────────

class TestExtractImageTextDisabled:
    def test_ocr_disabled_returns_filename_tag(self, tmp_path, monkeypatch):
        """When KB_OCR_ENABLED=false, returns [Image: name] without importing PIL."""
        ab = _fresh_agent_base(monkeypatch, {"KB_OCR_ENABLED": "false"})

        img = tmp_path / "diagram.png"
        img.write_bytes(b"")  # content irrelevant — OCR disabled

        result = ab._extract_image_text(img, max_chars=500)
        assert result == "[Image: diagram.png]"

    def test_ocr_disabled_zero_variant(self, tmp_path, monkeypatch):
        """KB_OCR_ENABLED=0 is also treated as disabled."""
        ab = _fresh_agent_base(monkeypatch, {"KB_OCR_ENABLED": "0"})
        img = tmp_path / "chart.jpg"
        img.write_bytes(b"")
        assert ab._extract_image_text(img, max_chars=500) == "[Image: chart.jpg]"


# ── _extract_image_text(): pytesseract path ────────────────────────────────────

class TestExtractImageTextOCR:
    def _install_fake_tesseract(self, monkeypatch, ocr_text: str):
        """
        Install minimal pytesseract + PIL stubs so no real Tesseract is needed.
        Stubs are injected into sys.modules before agent_base is re-imported.
        """
        # PIL stub
        fake_pil = types.ModuleType("PIL")
        fake_image_mod = types.ModuleType("PIL.Image")
        class FakeImage:
            size = (100, 80)
            mode = "RGB"
            @classmethod
            def open(cls, path):
                return cls()
        fake_image_mod.Image = FakeImage
        fake_pil.Image = FakeImage
        monkeypatch.setitem(sys.modules, "PIL", fake_pil)
        monkeypatch.setitem(sys.modules, "PIL.Image", fake_image_mod)

        # pytesseract stub
        fake_tess = types.ModuleType("pytesseract")
        fake_tess.image_to_string = lambda img: ocr_text
        monkeypatch.setitem(sys.modules, "pytesseract", fake_tess)

    def test_ocr_text_returned(self, tmp_path, monkeypatch):
        """pytesseract result is returned when non-empty."""
        self._install_fake_tesseract(monkeypatch, "Hello from OCR")
        ab = _fresh_agent_base(monkeypatch, {
            "KB_OCR_ENABLED": "true", "KB_OCR_ENGINE": "auto",
        })
        img = tmp_path / "scan.png"
        img.write_bytes(b"fake png bytes")
        result = ab._extract_image_text(img, max_chars=500)
        assert result == "Hello from OCR"

    def test_ocr_max_chars_truncation(self, tmp_path, monkeypatch):
        """OCR result is truncated to max_chars."""
        long_text = "A" * 1000
        self._install_fake_tesseract(monkeypatch, long_text)
        ab = _fresh_agent_base(monkeypatch, {
            "KB_OCR_ENABLED": "true", "KB_OCR_ENGINE": "tesseract",
        })
        img = tmp_path / "doc.jpg"
        img.write_bytes(b"bytes")
        result = ab._extract_image_text(img, max_chars=100)
        assert len(result) == 100
        assert result == "A" * 100

    def test_ocr_empty_string_falls_to_pil(self, tmp_path, monkeypatch):
        """When pytesseract returns empty string, falls through to PIL metadata."""
        self._install_fake_tesseract(monkeypatch, "")  # empty → skip to PIL
        ab = _fresh_agent_base(monkeypatch, {
            "KB_OCR_ENABLED": "true", "KB_OCR_ENGINE": "auto",
        })
        img = tmp_path / "blank.png"
        img.write_bytes(b"bytes")
        result = ab._extract_image_text(img, max_chars=500)
        # PIL stub returns 100×80 RGB
        assert "blank.png" in result
        assert "100" in result and "80" in result


# ── _extract_image_text(): PIL-only path (no pytesseract) ─────────────────────

class TestExtractImageTextPILFallback:
    def _install_fake_pil_only(self, monkeypatch):
        """PIL present, pytesseract absent."""
        fake_pil = types.ModuleType("PIL")
        fake_image_mod = types.ModuleType("PIL.Image")
        class FakeImage:
            size = (640, 480)
            mode = "RGBA"
            @classmethod
            def open(cls, path):
                return cls()
        fake_image_mod.Image = FakeImage
        fake_pil.Image = FakeImage
        monkeypatch.setitem(sys.modules, "PIL", fake_pil)
        monkeypatch.setitem(sys.modules, "PIL.Image", fake_image_mod)
        # Remove pytesseract so the ImportError path is taken
        monkeypatch.delitem(sys.modules, "pytesseract", raising=False)

    def test_pil_fallback_metadata(self, tmp_path, monkeypatch):
        self._install_fake_pil_only(monkeypatch)
        ab = _fresh_agent_base(monkeypatch, {
            "KB_OCR_ENABLED": "true", "KB_OCR_ENGINE": "auto",
        })
        img = tmp_path / "photo.jpeg"
        img.write_bytes(b"bytes")
        result = ab._extract_image_text(img, max_chars=500)
        assert "photo.jpeg" in result
        assert "640" in result
        assert "480" in result
        assert "RGBA" in result

    def test_pil_engine_none_skips_tesseract(self, tmp_path, monkeypatch):
        """KB_OCR_ENGINE=none skips pytesseract entirely, uses PIL."""
        self._install_fake_pil_only(monkeypatch)
        ab = _fresh_agent_base(monkeypatch, {
            "KB_OCR_ENABLED": "true", "KB_OCR_ENGINE": "none",
        })
        img = tmp_path / "image.gif"
        img.write_bytes(b"bytes")
        result = ab._extract_image_text(img, max_chars=500)
        # PIL metadata fallback
        assert "image.gif" in result
        assert "640" in result


# ── _extract_image_text(): filename-only last resort ──────────────────────────

class TestExtractImageTextFilenameOnly:
    def test_no_pil_no_tesseract(self, tmp_path, monkeypatch):
        """When neither PIL nor pytesseract is present, returns filename tag."""
        monkeypatch.delitem(sys.modules, "pytesseract", raising=False)
        monkeypatch.delitem(sys.modules, "PIL", raising=False)
        monkeypatch.delitem(sys.modules, "PIL.Image", raising=False)
        ab = _fresh_agent_base(monkeypatch, {
            "KB_OCR_ENABLED": "true", "KB_OCR_ENGINE": "auto",
        })
        img = tmp_path / "fallback.webp"
        img.write_bytes(b"bytes")
        result = ab._extract_image_text(img, max_chars=500)
        assert result == "[Image: fallback.webp]"


# ── extract_full_text(): image extensions routed correctly ────────────────────

class TestExtractFullTextImageRouting:
    """
    Verifies that extract_full_text() dispatches .png/.jpg/.jpeg/.gif/.webp
    to _extract_image_text() and does NOT return [Unsupported: …].
    """

    @pytest.mark.parametrize("ext", [".png", ".jpg", ".jpeg", ".gif", ".webp"])
    def test_image_not_unsupported(self, ext, tmp_path, monkeypatch):
        """No image extension should produce [Unsupported: …]."""
        ab = _fresh_agent_base(monkeypatch, {"KB_OCR_ENABLED": "false"})
        img = tmp_path / f"test{ext}"
        img.write_bytes(b"bytes")
        result = ab.extract_full_text(img, max_chars=500)
        assert not result.startswith("[Unsupported")
        assert result == f"[Image: test{ext}]"  # OCR disabled → filename tag


# ── MCP-layer smoke test (file_parser._extract_image) ─────────────────────────

class TestFileparserExtractImage:
    """Smoke-tests for the MCP-layer path; mirrors the agents-layer logic."""

    def test_ocr_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KB_OCR_ENABLED", "false")
        # Reload config and file_parser so env var is picked up
        for mod in ["kb_agent_mcp.config", "kb_agent_mcp.file_parser"]:
            sys.modules.pop(mod, None)
        import kb_agent_mcp.config as cfg_mod
        importlib.reload(cfg_mod)
        import kb_agent_mcp.file_parser as fp
        importlib.reload(fp)

        img = tmp_path / "img.png"
        img.write_bytes(b"bytes")
        result = fp._extract_image(img, max_chars=500)
        assert result == "[Image: img.png]"

    def test_sync_dispatch_to_image(self, tmp_path, monkeypatch):
        """_extract_sync routes .png to _extract_image (not [Unsupported])."""
        monkeypatch.setenv("KB_OCR_ENABLED", "false")
        for mod in ["kb_agent_mcp.config", "kb_agent_mcp.file_parser"]:
            sys.modules.pop(mod, None)
        import kb_agent_mcp.config as cfg_mod
        importlib.reload(cfg_mod)
        import kb_agent_mcp.file_parser as fp
        importlib.reload(fp)

        img = tmp_path / "diagram.png"
        img.write_bytes(b"bytes")
        result = fp._extract_sync(img, max_chars=500)
        assert not result.startswith("[Unsupported")
        assert result == "[Image: diagram.png]"
