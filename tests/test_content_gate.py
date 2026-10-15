"""Tests for agents/content_gate.py — the pre-description gatekeeper."""
from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "agents"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import content_gate as g  # noqa: E402


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ── classification ────────────────────────────────────────────────────────────

def test_ok_file_is_usable_and_has_terms(tmp_path):
    p = _write(tmp_path, "ace.md", "App Connect migration guide\n" + "integration server flows " * 10)
    ev = g.inspect_file(p)
    assert ev.status == g.OK and ev.usable
    assert "integration" in ev.terms
    assert ev.title.startswith("App Connect")


def test_empty_file_is_failed(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "empty.txt", "   \n"))
    assert ev.status == g.FAILED and not ev.usable


def test_thin_file_flagged(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "tiny.txt", "hello"))
    assert ev.status == g.THIN


def test_extractor_error_is_failed_not_raised(tmp_path):
    def boom(_):
        raise RuntimeError("bad")
    ev = g.inspect_file(_write(tmp_path, "x.txt", "text"), boom)
    assert ev.status == g.FAILED and "bad" in ev.reason


def test_extraction_error_marker_is_failed(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "x.txt", "t"), lambda p: "PPTX: x.pptx")
    assert ev.status == g.FAILED


# ── PPTX regression: prs.slides[:N] used to raise and yield "PPTX: name" ──────

def test_pptx_snippet_reads_real_text(tmp_path):
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Migrating IIB to ACE"
    s.placeholders[1].text = "Plan the migration of integration servers to App Connect Enterprise"
    f = tmp_path / "deck.pptx"
    prs.save(str(f))
    ev = g.inspect_file(f)
    assert ev.status == g.OK, ev.reason
    assert "Migrating IIB to ACE" in ev.text


# ── extractive descriptions ───────────────────────────────────────────────────

def test_extractive_domain_meta_uses_content_not_placeholder(tmp_path):
    evs = [
        g.inspect_file(_write(tmp_path, f"renewal{i}.md",
                              "Renewal pipeline forecast\n" + "renewal pipeline customer " * 10))
        for i in range(3)
    ]
    meta = g.extractive_domain_meta("BizOps", evs)
    assert not g.is_placeholder(meta["description"])
    assert "renewal" in meta["description"].lower()
    assert "renewal" in meta["keywords"]
    assert len(meta["description"]) <= 200
    assert g.grounding_score(meta["description"], evs) >= g.MIN_GROUNDING


# ── accuracy check ────────────────────────────────────────────────────────────

def test_grounded_description_scores_high_and_invented_low(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "d.md", "Kubernetes operator installs App Connect dashboards " * 5))
    good = "Kubernetes operator installs App Connect dashboards"
    bad = "Quarterly cryptocurrency payroll compliance spreadsheets"
    assert g.grounding_score(good, [ev]) >= 0.9
    assert g.grounding_score(bad, [ev]) < g.MIN_GROUNDING


def test_verified_or_extractive_rejects_hallucination(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "d.md", "Kubernetes operator installs dashboards " * 5))
    text, source, _ = g.verified_or_extractive(
        "Quarterly cryptocurrency payroll compliance", [ev], "FALLBACK")
    assert (text, source) == ("FALLBACK", "extractive")


def test_verified_or_extractive_accepts_grounded(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "d.md", "Kubernetes operator installs dashboards " * 5))
    text, source, _ = g.verified_or_extractive(
        "Kubernetes operator installs dashboards", [ev], "FALLBACK")
    assert source == "llm" and text.startswith("Kubernetes")


# ── placeholder detection ─────────────────────────────────────────────────────

@pytest.mark.parametrize("s", ["XLSX file", "PPTX file", "pdf file", "PPTX: deck.pptx", "", "deck"])
def test_placeholder_summaries(s):
    assert g.is_placeholder_summary(s, pathlib.Path("deck.pptx"))


def test_real_summary_not_placeholder():
    assert not g.is_placeholder_summary("Migration plan from IIB to ACE v13", pathlib.Path("deck.pptx"))


def test_is_placeholder_description():
    assert g.is_placeholder("Knowledge domain: BizOps")
    assert not g.is_placeholder("BizOps: 117 documents covering renewal")


# ── report ────────────────────────────────────────────────────────────────────

def test_gate_report_counts_and_flags(tmp_path):
    evs = [
        g.inspect_file(_write(tmp_path, "a.md", "real content here " * 10)),
        g.inspect_file(_write(tmp_path, "b.txt", "")),
    ]
    r = g.gate_report(evs)
    assert r["total"] == 2 and r["ok"] == 1 and r["failed"] == 1
    assert r["flagged"][0]["file"] == "b.txt"


# ── generate.py wiring (no-LLM path must not emit placeholders) ───────────────

def test_generate_domain_meta_no_llm_is_content_based(tmp_path):
    import generate  # scripts/generate.py
    folder = tmp_path / "Docs"
    folder.mkdir()
    for i in range(2):
        (folder / f"n{i}.md").write_text("Entitlement licensing parts guide " * 10, encoding="utf-8")
    meta = generate.generate_domain_meta("Docs", folder, use_llm=False)
    assert meta["source"] == "extractive"
    assert not g.is_placeholder(meta["description"])
    assert "entitlement" in meta["description"].lower()


# ── regressions from the thorough-testing pass ────────────────────────────────

def _folder(tmp_path, files: dict[str, str]):
    folder = tmp_path / "Docs"
    for rel, text in files.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return folder


def test_llm_keywords_as_string_not_split_into_characters(tmp_path, monkeypatch):
    import generate
    folder = _folder(tmp_path, {"r.md": "Renewal tracking entitlement licensing guide " * 10})
    monkeypatch.setattr(
        generate, "call_llm_generate",
        lambda _p: '{"description": "Renewal tracking and entitlement licensing", "keywords": "renewal, licensing"}',
    )
    meta = generate.generate_domain_meta("Docs", folder, use_llm=True)
    assert meta["keywords"] and all(len(k) > 1 for k in meta["keywords"])


def test_llm_keywords_wrong_type_falls_back_to_extractive(tmp_path, monkeypatch):
    import generate
    folder = _folder(tmp_path, {"r.md": "Renewal tracking entitlement licensing guide " * 10})
    monkeypatch.setattr(
        generate, "call_llm_generate",
        lambda _p: '{"description": "Renewal tracking and entitlement licensing", "keywords": 5}',
    )
    meta = generate.generate_domain_meta("Docs", folder, use_llm=True)
    assert meta["keywords"] and all(isinstance(k, str) and len(k) > 1 for k in meta["keywords"])


def test_non_latin_document_is_not_thin_and_has_terms(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "jp.txt", "更新管理とライセンス契約に関する手順書です。" * 4))
    assert ev.status == g.OK and ev.terms


def test_one_character_file_summary_is_not_key_terms(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "tiny.txt", "x"))
    assert "Key terms" not in g.extractive_file_summary(ev)


def test_generic_subfolder_not_in_description(tmp_path):
    folder = _folder(tmp_path, {
        "sub/a.md": "Deployment runbook for integration servers " * 10,
        "b.md": "Deployment runbook for integration servers " * 10,
    })
    evs = g.scan_folder(folder, sorted(folder.rglob("*.md")))
    meta = g.extractive_domain_meta("Docs", evs)
    assert "sub" not in [s.lower() for s in g._subfolders("Docs", evs)]
    assert "sub" not in meta["keywords"]


def test_filename_fragments_are_not_keywords(tmp_path):
    folder = _folder(tmp_path, {"mig.md": "Migration of integration flows to the new runtime " * 10})
    evs = g.scan_folder(folder, sorted(folder.rglob("*.md")))
    assert "mig" not in g.domain_keywords(evs)


def test_generated_stub_detection(tmp_path):
    new = _write(tmp_path, "Docs.md", f"{g.STUB_MARKER}\n# Docs\n\ntext")
    legacy = _write(tmp_path, "skills.md", "# s\n\n_Add your own notes about this domain above this line._\n")
    real = _write(tmp_path, "real.md", "# Real notes\n\nactual content " * 5)
    assert g.is_generated_stub_file(new) and g.is_generated_stub_file(legacy)
    assert not g.is_generated_stub_file(real)
    assert g.is_generated_stub(g.inspect_file(new))
    assert g.without_generated([g.inspect_file(new), g.inspect_file(real)])[0].path == real


def test_stub_not_counted_and_count_stable_across_runs(tmp_path, monkeypatch):
    import generate
    monkeypatch.setattr(generate, "llm_available", lambda: False)
    folder = _folder(tmp_path, {"a.txt": "Entitlement licensing parts guide " * 10})
    assert generate.count_files(folder) == 1
    stub = generate.generate_readme_stub("Docs", folder, "A description")
    assert g.STUB_MARKER in stub.read_text(encoding="utf-8")
    assert generate.count_files(folder) == 1
    assert stub not in generate.list_indexable_files(folder)


def test_extractive_summaries_reused_without_rebuild(tmp_path):
    import generate
    kb = tmp_path
    folder = _folder(kb, {"a.md": "Entitlement licensing parts guide " * 10})
    cache: dict = {}
    first = generate.build_file_summaries("Docs", folder, kb, cache, use_llm=False)
    cache.update(first)
    marker = {k: dict(v, summary=v["summary"] + " ") for k, v in first.items()}  # detect reuse by identity of content
    cache.update(marker)
    second = generate.build_file_summaries("Docs", folder, kb, cache, use_llm=False)
    assert second == marker  # cached entries returned untouched, not rebuilt


def test_old_gate_version_summaries_are_rebuilt(tmp_path):
    import generate
    kb = tmp_path
    folder = _folder(kb, {"a.md": "Entitlement licensing parts guide " * 10})
    cache: dict = {}
    first = generate.build_file_summaries("Docs", folder, kb, cache, use_llm=False)
    for v in first.values():
        v["gate_version"] = g.GATE_VERSION - 1
        v["summary"] = "stale"
    again = generate.build_file_summaries("Docs", folder, kb, first, use_llm=False)
    assert all(v["summary"] != "stale" and v["gate_version"] == g.GATE_VERSION for v in again.values())


def test_short_real_spreadsheet_is_not_failed(tmp_path):
    """'[Sheet: X]\\n100 | EMEA' is real content, not an extraction-error marker."""
    ev = g.inspect_file(_write(tmp_path, "rev.csv", "x"), lambda p: "[Sheet: Sheet]\n100 | EMEA")
    assert ev.status != g.FAILED and ev.chars > 0


def test_domain_keywords_deterministic_across_hash_seeds(tmp_path):
    import subprocess
    folder = _folder(tmp_path, {
        "a.md": "Renewal tracking entitlement licensing guide " * 5,
        "b.md": "Deployment runbook integration servers flows " * 5,
    })
    code = (
        "import sys,pathlib;sys.path.insert(0,%r);import content_gate as g;"
        "f=pathlib.Path(%r);print(g.extractive_domain_meta('Docs',g.scan_folder(f,sorted(f.glob('*.md'))))['keywords'])"
        % (str(_REPO_ROOT / "agents"), str(folder))
    )
    outs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={"PYTHONHASHSEED": str(s), "PATH": "/usr/bin:/bin"}).stdout
        for s in (1, 2, 3, 4)
    }
    assert len(outs) == 1 and outs != {""}


def test_binary_garbage_does_not_yield_giant_keyword(tmp_path):
    ev = g.inspect_file(_write(tmp_path, "blob.txt", "d" * 3000))
    assert all(len(t) <= g.MAX_TOKEN_CHARS for t in ev.terms)


# ── coverage gaps found by tracing ────────────────────────────────────────────

def test_missing_file_is_failed_not_raised(tmp_path):
    ev = g.inspect_file(tmp_path / "gone.txt")
    assert ev.status == g.FAILED and not ev.usable


def test_large_xlsx_stub_is_thin_and_never_content(tmp_path):
    p = _write(tmp_path, "big.xlsx", "x")
    ev = g.inspect_file(p, lambda _p: "XLSX (large file — 160 MB): big.xlsx\nToo large.")
    assert ev.status == g.THIN and ev.text == "" and not ev.usable


def test_spreadsheet_summary_lists_sheets_and_key_terms(tmp_path):
    text = "[Sheet: Renewals]\nCustomer | Region | Entitlement\n" + "Acme | EMEA | licensing renewal\n" * 6
    ev = g.inspect_file(_write(tmp_path, "r.xlsx", "x"), lambda _p: text)
    s = g.extractive_file_summary(ev)
    assert "Sheets: Renewals" in s and "Key terms:" in s


def test_subfolders_counted_most_populated_first(tmp_path):
    folder = _folder(tmp_path, {
        "deployment/a.md": "Deployment runbook servers " * 10,
        "deployment/b.md": "Deployment runbook servers " * 10,
        "migration/c.md": "Migration plan flows " * 10,
        "root.md": "Root document content " * 10,
    })
    evs = g.scan_folder(folder, sorted(folder.rglob("*.md")))
    subs = g._subfolders("Docs", evs)
    assert subs[0] == "deployment" and "migration" in subs


def test_stub_file_check_handles_oversize_and_unreadable(tmp_path):
    big = _write(tmp_path, "big.md", g.STUB_MARKER + "x" * 30_000)
    assert g.is_generated_stub_file(big) is False          # too large to be a stub
    assert g.is_generated_stub_file(tmp_path / "nope.md") is False
    assert g.is_generated_stub_file(tmp_path) is False     # a directory
    assert g.is_generated_stub_file(_write(tmp_path, "s.txt", g.STUB_MARKER)) is False  # not .md


def test_grounding_with_no_checkable_claims_is_zero():
    assert g.grounding_score("", []) == 0.0
    assert g.grounding_score("the and for", []) == 0.0


def test_evidence_for_prompt_samples_real_content_only(tmp_path):
    good = g.inspect_file(_write(tmp_path, "a.md", "Entitlement licensing parts guide " * 10))
    bad = g.inspect_file(_write(tmp_path, "b.txt", ""))
    out = g.evidence_for_prompt([good, bad])
    assert "a.md" in out and "b.txt" not in out
