"""Tests for document digests (pptx, docx, pdf, boxnote, md) and the dispatcher."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_agent_mcp.context_store import build_digest_for, digestable
from kb_agent_mcp.context_store import doc_digest
from kb_agent_mcp.context_store.doc_digest import build_doc_digest
from kb_agent_mcp.context_store.frontmatter import parse_front_matter


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_pptx(path: Path) -> Path:
    from pptx import Presentation

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = "Renewal Outlook 2026"
    s1.placeholders[1].text = "Annuity renewals are forecast to grow in the second half."
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Churn drivers"
    s2.placeholders[1].text = "Pricing changes drive most cancellations.\nSupport gaps follow."
    s2.notes_slide.notes_text_frame.text = "Mention the EMEA outliers."
    prs.slides.add_slide(prs.slide_layouts[6])      # blank slide: skipped
    prs.save(path)
    return path


def _make_docx(path: Path) -> Path:
    from docx import Document

    d = Document()
    d.add_heading("Deployment playbook", level=1)
    d.add_paragraph("This playbook explains how large deals are tracked after signing.")
    d.add_heading("Contacting sellers", level=2)
    d.add_paragraph("Use Slack to reach the seller. Include the customer name.")
    d.save(path)
    return path


def _make_boxnote(path: Path) -> Path:
    def text(t):
        return {"type": "text", "text": t}

    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [text("One-stop page for product operations.")]},
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Cadence reporting")]},
        {"type": "paragraph", "content": [text("Weekly readouts go to leadership every Monday.")]},
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Focus areas")]},
        {"type": "bullet_list", "content": [
            {"type": "list_item", "content": [{"type": "paragraph", "content": [text("Renewal risk review")]}]},
        ]},
    ]}
    path.write_text(json.dumps({"version": 1, "doc": doc}), encoding="utf-8")
    return path


def _make_md(path: Path) -> Path:
    path.write_text(
        "# Setup guide\n\nInstall the package first.\n\n```\n# not a heading\n```\n\n## Usage\n\nRun the tool.\n",
        encoding="utf-8",
    )
    return path


def _make_pdf(path: Path, lines: list[str]) -> Path:
    """Write a one-page PDF with the given text lines (no external library)."""
    stream = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def _make_blank_pdf(path: Path) -> Path:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        w.write(f)
    return path


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "kb"
    (root / "BizOps").mkdir(parents=True)
    return root, {
        "pptx": _make_pptx(root / "BizOps" / "deck.pptx"),
        "docx": _make_docx(root / "BizOps" / "playbook.docx"),
        "boxnote": _make_boxnote(root / "BizOps" / "ops.boxnote"),
        "md": _make_md(root / "BizOps" / "guide.md"),
        "pdf": _make_pdf(root / "BizOps" / "brief.pdf",
                         ["Quarterly pricing brief", "Prices rise four percent in March."]),
    }


# ── per-type content ──────────────────────────────────────────────────────────

def test_pptx_uses_slide_titles_and_notes(docs):
    root, files = docs
    text = build_doc_digest(files["pptx"], root)
    fm = parse_front_matter(text)
    assert fm["type"] == "pptx" and fm["slides"] == "3" and fm["extraction"] == "ok"
    assert "- Slide 1: Renewal Outlook 2026" in text
    assert "- Slide 2: Churn drivers" in text
    assert "Pricing changes drive most cancellations." in text
    assert "Slide 3" not in text.split("## Outline")[1].split("##")[0]   # blank slide skipped


def test_docx_uses_heading_styles(docs):
    root, files = docs
    text = build_doc_digest(files["docx"], root)
    outline = text.split("## Outline")[1].split("##")[0]
    assert "- Deployment playbook" in outline
    assert "  - Contacting sellers" in outline          # level 2 is indented
    assert "large deals are tracked after signing." in text


def test_boxnote_uses_heading_nodes(docs):
    root, files = docs
    text = build_doc_digest(files["boxnote"], root)
    fm = parse_front_matter(text)
    assert fm["sections"] == "2"
    assert "Cadence reporting" in text and "Focus areas" in text
    assert "Weekly readouts go to leadership every Monday." in text
    assert "Opens with: One-stop page for product operations." in text


def test_markdown_skips_code_fences(docs):
    root, files = docs
    text = build_doc_digest(files["md"], root)
    assert "Setup guide" in text and "Usage" in text
    assert "not a heading" not in text


def test_pdf_page_text(docs):
    root, files = docs
    text = build_doc_digest(files["pdf"], root)
    fm = parse_front_matter(text)
    assert fm["pages"] == "1" and fm["extraction"] == "ok"
    assert "Quarterly pricing brief" in text
    assert "Prices rise four percent in March." in text


# ── front-matter, determinism, size ───────────────────────────────────────────

def test_front_matter_shared_keys_round_trip(docs):
    root, files = docs
    for ext, path in files.items():
        fm = parse_front_matter(build_doc_digest(path, root))
        for key in ("path", "sha256", "type", "size_bytes", "partial", "keywords"):
            assert key in fm, (ext, key)
        assert fm["type"] == ext
        assert fm["path"] == f"BizOps/{path.name}"
        assert len(fm["sha256"]) == 64
        assert isinstance(fm["keywords"], list) and fm["keywords"]


def test_deterministic(docs):
    root, files = docs
    for path in files.values():
        assert build_doc_digest(path, root) == build_doc_digest(path, root)


def test_size_cap_on_large_document(tmp_path):
    from docx import Document

    d = Document()
    for i in range(400):
        d.add_heading(f"Section number {i} about renewals and pipeline", level=1 + i % 3)
        d.add_paragraph(f"Body text for section {i}. It has a second sentence.")
    path = tmp_path / "big.docx"
    d.save(path)
    text = build_doc_digest(path, tmp_path)
    assert len(text.encode("utf-8")) <= doc_digest._MAX_BYTES
    assert "and " in text.split("## Outline")[1] and "more" in text    # outline is truncated, says so


# ── empty / failing extraction ────────────────────────────────────────────────

def test_empty_boxnote_records_reason_not_filename(tmp_path):
    path = tmp_path / "Q2 churn analysis.boxnote"
    path.write_text("", encoding="utf-8")
    text = build_doc_digest(path, tmp_path)
    fm = parse_front_matter(text)
    assert fm["extraction"] == "empty"
    assert "No text could be extracted: the Box Note is empty." in text
    assert "## Outline" not in text and "## Key points" not in text


def test_scanned_pdf_has_no_text(tmp_path):
    path = _make_blank_pdf(tmp_path / "scan.pdf")
    text = build_doc_digest(path, tmp_path)
    assert parse_front_matter(text)["extraction"] == "empty"
    assert "likely scanned images" in text


def test_corrupt_file_does_not_raise(tmp_path):
    path = tmp_path / "broken.pptx"
    path.write_bytes(b"not a zip file")
    text = build_doc_digest(path, tmp_path)
    assert parse_front_matter(text)["extraction"] == "empty"
    assert "could not be read" in text


def test_invalid_boxnote_json(tmp_path):
    path = tmp_path / "bad.boxnote"
    path.write_text("{oops", encoding="utf-8")
    assert "not valid JSON" in build_doc_digest(path, tmp_path)


def test_time_budget_marks_partial(docs):
    root, files = docs
    text = build_doc_digest(files["pptx"], root, time_budget=-1)
    assert parse_front_matter(text)["partial"] == "true"


def test_unsupported_type_raises(tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(b"x")
    with pytest.raises(ValueError):
        build_doc_digest(path, tmp_path)


# ── dispatcher ────────────────────────────────────────────────────────────────

def test_dispatcher_routes_by_extension(docs):
    root, files = docs
    csv = root / "BizOps" / "t.csv"
    csv.write_text("Region,Revenue\nEMEA,10\nAPAC,20\nEMEA,5\n", encoding="utf-8")
    assert "slides:" in build_digest_for(files["pptx"], root)
    assert "rows:" in build_digest_for(csv, root)
    assert digestable(csv) and digestable(files["pdf"])
    assert not digestable(root / "x.png")
