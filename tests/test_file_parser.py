"""
tests/test_file_parser.py — File parser tests
"""
from __future__ import annotations

import pytest
import asyncio


@pytest.mark.asyncio
async def test_extract_plain_text(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("Hello, world!", encoding="utf-8")
    from kb_agent_mcp.file_parser import extract
    text = await extract(f)
    assert "Hello, world!" in text


@pytest.mark.asyncio
async def test_extract_markdown(tmp_path):
    f = tmp_path / "readme.md"
    f.write_text("# Title\n\nSome content here.", encoding="utf-8")
    from kb_agent_mcp.file_parser import extract
    text = await extract(f)
    assert "Title" in text
    assert "Some content here" in text


@pytest.mark.asyncio
async def test_extract_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("name,value\nalice,100\nbob,200\n", encoding="utf-8")
    from kb_agent_mcp.file_parser import extract
    text = await extract(f)
    assert "alice" in text
    assert "100" in text


@pytest.mark.asyncio
async def test_extract_max_chars(tmp_path):
    f = tmp_path / "long.txt"
    f.write_text("a" * 5000, encoding="utf-8")
    from kb_agent_mcp.file_parser import extract
    text = await extract(f, max_chars=100)
    assert len(text) <= 100


@pytest.mark.asyncio
async def test_extract_unsupported_returns_label(tmp_path):
    f = tmp_path / "file.xyz"
    f.write_text("binary data", encoding="utf-8")
    from kb_agent_mcp.file_parser import extract
    text = await extract(f)
    assert "[Unsupported" in text or text == ""  # graceful fallback


def test_snippet_returns_string(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Quick brown fox.", encoding="utf-8")
    from kb_agent_mcp.file_parser import snippet
    s = snippet(f)
    assert isinstance(s, str)
    assert len(s) > 0
