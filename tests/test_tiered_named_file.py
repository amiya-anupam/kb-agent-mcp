"""A question that names one file gets that digest only (golden: bz-top-expiring-customer)."""
from __future__ import annotations

from kb_agent_mcp import tiered


def _digest(dirpath, source, body):
    p = dirpath / (source.rsplit("/", 1)[-1] + ".md")
    p.write_text(f"---\npath: {source}\ntype: xlsx\n---\n{body}\n", encoding="utf-8")


def test_question_naming_a_file_selects_only_that_digest(tmp_path):
    _digest(tmp_path, "BizOps/1H Renewals CP4I & App Connect.xlsx", "customer expired amount renewals")
    _digest(tmp_path, "BizOps/Q2 Deals.xlsx", "customer expired amount renewals deals " * 3)
    q = "Which customer has the highest expired amount in the 1H renewals CP4I and App Connect file?"
    picked = tiered.select_digests(tmp_path, q)
    assert [d.source for _, d in picked] == ["BizOps/1H Renewals CP4I & App Connect.xlsx"]


def test_generic_question_keeps_several_digests(tmp_path):
    _digest(tmp_path, "BizOps/Alpha.xlsx", "customer expired amount renewals")
    _digest(tmp_path, "BizOps/Beta.xlsx", "customer expired amount renewals")
    picked = tiered.select_digests(tmp_path, "Which customer has the highest expired amount renewals?")
    assert len(picked) == 2


def test_compact_digest_puts_matching_sheet_first():
    from kb_agent_mcp.tiered import compact_digest
    text = (
        "---\npath: x.xlsx\n---\n# x.xlsx\n\n## Sheets\n\n- a\n\n"
        "## Sheet: Summary\n\nTotal ELA: 5\n\n"
        "## Sheet: page Jan2026\n\nTop 5 by Sold to Customer Name (Adjusted Expired): ADP\n"
    )
    body = compact_digest(text, "Which customer has the highest adjusted expired amount?")
    assert body.index("## Sheet: page Jan2026") < body.index("## Sheet: Summary")
    assert body.index("## Sheets") < body.index("## Sheet: page Jan2026")


def test_compact_digest_without_question_keeps_order():
    from kb_agent_mcp.tiered import compact_digest
    text = "---\npath: x\n---\n## Sheet: A\n\nfoo\n\n## Sheet: B\n\nbar customer\n"
    body = compact_digest(text)
    assert body.index("Sheet: A") < body.index("Sheet: B")
