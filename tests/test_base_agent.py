"""
tests/test_base_agent.py — Base agent tests (question classifiers, README helpers)
"""
from __future__ import annotations

import pytest


def test_is_data_question():
    from kb_agent_mcp.base_agent import is_data_question
    assert is_data_question("What is the total revenue for Q3 2024?")
    assert is_data_question("How many deals did we close this quarter?")
    assert is_data_question("Show me all renewals by country")
    assert not is_data_question("What is ACE?")
    assert not is_data_question("How does IBM Integration Bus work?")


def test_is_complex_question():
    from kb_agent_mcp.base_agent import is_complex_question
    assert is_complex_question("Compare the architecture of ACE vs CP4I")
    assert is_complex_question("Give me a deep dive into the integration patterns")
    assert is_complex_question("Walk me through the migration steps")
    assert not is_complex_question("What is ACE?")
    assert not is_complex_question("How much did we sell in Q1?")


def test_readme_auto_index_extraction():
    from kb_agent_mcp.base_agent import _extract_auto_index, _MARKER_START, _MARKER_END
    text = f"""
# My Domain

Some intro text.

{_MARKER_START}
| File | Summary |
|---|---|
| `doc.pdf` | Some summary |
{_MARKER_END}

More text.
"""
    result = _extract_auto_index(text)
    assert result is not None
    assert "doc.pdf" in result
    assert "Some summary" in result


def test_readme_non_index_chars():
    from kb_agent_mcp.base_agent import _non_index_chars, _MARKER_START, _MARKER_END
    text = f"Intro body text here.\n\n{_MARKER_START}\nindex\n{_MARKER_END}\n\nTrailing text."
    chars = _non_index_chars(text)
    assert chars > 0  # intro + trailing count
    # Index block itself should not count
    assert chars < len(text)


def test_non_index_chars_no_markers():
    from kb_agent_mcp.base_agent import _non_index_chars
    text = "Just some plain text without markers."
    assert _non_index_chars(text) == len(text.strip())


def test_format_confidence_footer_high():
    from kb_agent_mcp.base_agent import format_confidence_footer
    sources = [{"name": "doc.pdf", "path": "domain/doc.pdf", "score": 0.92}]
    footer = format_confidence_footer(sources)
    assert "High" in footer
    assert "doc.pdf" in footer


def test_format_confidence_footer_readme():
    from kb_agent_mcp.base_agent import format_confidence_footer
    sources = [{"name": "README.md", "path": "domain/README", "score": 1.0}]
    footer = format_confidence_footer(sources)
    # README-first: no confidence label
    assert "📄" in footer
    assert "README.md" in footer


def test_format_confidence_footer_empty():
    from kb_agent_mcp.base_agent import format_confidence_footer
    assert format_confidence_footer([]) == ""


def test_passthrough_block_structure():
    from kb_agent_mcp.base_agent import _build_passthrough_block, _PASSTHROUGH_MARKER, _PASSTHROUGH_END
    block = _build_passthrough_block(
        question="What is ACE?",
        context="ACE is an integration platform.",
        system_prompt="You are a specialist.",
        agent_name="ACE Agent",
        source_label="ACE Docs.md",
    )
    assert _PASSTHROUGH_MARKER in block
    assert _PASSTHROUGH_END in block
    assert "AGENT: ACE Agent" in block
    assert "QUESTION: What is ACE?" in block
    assert "SOURCE: ACE Docs.md" in block
    assert "ACE is an integration platform" in block
