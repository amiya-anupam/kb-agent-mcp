"""
tests/test_memory.py — Memory module tests
"""
from __future__ import annotations

import time
import pytest
import asyncio

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def isolated_memory(tmp_path, monkeypatch):
    """Point session_memory_path at a temp dir so tests don't pollute the real store."""
    monkeypatch.setenv("KB_ROOT", str(tmp_path))
    monkeypatch.setenv("KB_LLM_PROVIDER", "passthrough")
    import importlib
    import kb_agent_mcp.config as cfg_mod
    importlib.reload(cfg_mod)
    import kb_agent_mcp.memory as mem_mod
    importlib.reload(mem_mod)
    return mem_mod


async def test_empty_session(isolated_memory):
    mem = isolated_memory
    hist = await mem.get_history("test-session-1")
    assert hist == []


async def test_add_and_retrieve_turn(isolated_memory):
    mem = isolated_memory
    await mem.add_turn("Hello", "Hi there!", session_id="t1")
    hist = await mem.get_history("t1")
    assert len(hist) == 2
    assert hist[0]["role"] == "user"
    assert hist[0]["content"] == "Hello"
    assert hist[1]["role"] == "assistant"
    assert hist[1]["content"] == "Hi there!"


async def test_answer_truncation(isolated_memory):
    mem = isolated_memory
    long_answer = "x" * 1000  # much longer than default MAX_ANSWER_CHARS=400
    await mem.add_turn("q", long_answer, session_id="t2")
    hist = await mem.get_history("t2")
    stored = hist[1]["content"]
    assert len(stored) <= 401  # truncated + "…"
    assert stored.endswith("…")


async def test_clear(isolated_memory):
    mem = isolated_memory
    await mem.add_turn("a", "b", session_id="t3")
    await mem.clear("t3")
    hist = await mem.get_history("t3")
    assert hist == []


async def test_summary_shows_turns(isolated_memory):
    mem = isolated_memory
    await mem.add_turn("q1", "a1", session_id="t4")
    await mem.add_turn("q2", "a2", session_id="t4")
    s = await mem.summary("t4")
    assert "2 turn" in s


async def test_separate_sessions(isolated_memory):
    mem = isolated_memory
    await mem.add_turn("q", "a", session_id="session_A")
    hist_b = await mem.get_history("session_B")
    assert hist_b == []


async def test_max_turns_limit(isolated_memory, monkeypatch):
    mem = isolated_memory
    # Push the limit to 3 turns
    import kb_agent_mcp.config as cfg_mod
    import importlib
    monkeypatch.setenv("KB_SESSION_MAX_TURNS", "3")
    importlib.reload(cfg_mod)
    importlib.reload(mem)

    for i in range(5):
        await mem.add_turn(f"q{i}", f"a{i}", session_id="t5")

    hist = await mem.get_history("t5")
    assert len(hist) == 6  # 3 turns × 2 messages
