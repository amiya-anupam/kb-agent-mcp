#!/usr/bin/env python3
"""Golden-question evaluation: legacy retrieval vs tiered context-store retrieval.

Runs each question in tests/golden_questions.json through DomainAgent.run() with
KB_CONTEXT_STORE off and on, then reports

  * recall - share of `expected_facts` present in the text under test
  * chars  - length of the context handed to the LLM
  * routing (--routing) - which domain the orchestrator picks for each question

Modes
  default            passthrough (no LLM), security gate off  -> retrieval only
  --llm              real LLM; recall is measured on the LLM's answer
  --gate blocked     gate on, session NOT acknowledged        -> redaction effect
  --gate ack         gate on, session acknowledged            -> confidential visible
  --routing          also score domain routing (top-1 / confident / matched set)

Usage:  python3 scripts/golden_eval.py [--llm] [--gate {off,blocked,ack}] [--routing]
                                       [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kb_agent_mcp import base_agent, orchestrator         # noqa: E402
from kb_agent_mcp.config import cfg                       # noqa: E402
from kb_agent_mcp.domain_agent import DomainAgent         # noqa: E402

GOLDEN = ROOT / "tests" / "golden_questions.json"
SESSION = "golden-eval"
CONTEXT_MARK = "Use the following knowledge base content"


def recall(text: str, facts: list[str]) -> float:
    low = text.lower()
    return sum(f.lower() in low for f in facts) / len(facts) if facts else 1.0


def set_flag(value: bool) -> None:
    object.__setattr__(cfg, "KB_CONTEXT_STORE", value)


class ContextTap:
    """Records the context sent to the LLM (the only honest 'chars' under --llm)."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._orig = base_agent.call_llm

    async def _call(self, messages, *a, **kw):
        user = messages[-1]["content"]
        if CONTEXT_MARK in user:
            self.sent.append(user)
        return await self._orig(messages, *a, **kw)

    def __enter__(self):
        base_agent.call_llm = self._call
        return self

    def __exit__(self, *exc):
        base_agent.call_llm = self._orig


async def run_one(q: dict, flag: bool, llm: bool) -> dict:
    set_flag(flag)
    tap = ContextTap()
    with tap:
        res = await DomainAgent(q["domain"]).run(q["question"], [], session_id=SESSION)
    if llm:
        text = res.get("answer") or ""
        ctx_chars = len(tap.sent[0]) if tap.sent else 0
    else:
        text = res.get("passthrough_block") or res.get("answer") or ""
        ctx_chars = len(text)
    return {
        "recall": recall(text, q["expected_facts"]),
        "chars": ctx_chars,
        "sources": [s.get("name", "") for s in res.get("sources", [])][:3],
        "excluded": "excluded" in text.lower() or "confidential" in text.lower(),
    }


async def route_one(q: dict, flag: bool, agents: dict) -> dict:
    set_flag(flag)
    _, confident = orchestrator._keyword_confidence(q["question"], agents)
    domains, _ = await orchestrator._resolve_domains(q["question"], [], agents)
    return {
        "domains": domains,
        "top1": bool(domains) and domains[0] == q["domain"],
        "in_set": q["domain"] in domains,
        "confident": confident and domains == [q["domain"]],
    }


def mean(rows, side, key):
    return sum(r[side][key] for r in rows) / len(rows)


async def main(args) -> None:
    from kb_agent_mcp import security_gate
    original_flag = cfg.KB_CONTEXT_STORE
    gate_enabled = cfg.KB_SECURITY_GATE_ENABLED
    base_agent._passthrough_cache = None if args.llm else True
    gate_on = args.gate != "off"
    object.__setattr__(cfg, "KB_SECURITY_GATE_ENABLED", gate_on)
    if args.gate == "ack":      # dedicated session; removed in `finally`
        security_gate.save_gate_session(security_gate.GateSession(
            session_id=SESSION, status="acknowledged", ack_token="eval", confidential_files=[]))

    questions = json.loads(GOLDEN.read_text())
    rows, routing = [], []
    try:
        if args.llm and await base_agent.is_passthrough():
            sys.exit("--llm requested but no LLM is reachable (passthrough detected)")
        agents = await orchestrator._get_agents() if args.routing else {}
        for q in questions:
            rows.append({"id": q["id"], "off": await run_one(q, False, args.llm),
                         "on": await run_one(q, True, args.llm)})
            if args.routing:
                routing.append({"id": q["id"], "domain": q["domain"],
                                "off": await route_one(q, False, agents),
                                "on": await route_one(q, True, agents)})
    finally:
        set_flag(original_flag)
        object.__setattr__(cfg, "KB_SECURITY_GATE_ENABLED", gate_enabled)
        if args.gate == "ack":
            security_gate.clear_gate_session(SESSION)

    mode = f"{'llm' if args.llm else 'passthrough'} / gate={args.gate}"
    print(f"mode: {mode}")
    print(f"{'question':32} {'recall off':>10} {'recall on':>10} {'chars off':>10} {'chars on':>10}")
    for r in rows:
        print(f"{r['id']:32} {r['off']['recall']:>10.2f} {r['on']['recall']:>10.2f} "
              f"{r['off']['chars']:>10} {r['on']['chars']:>10}")
    n = len(rows)
    summary = {
        "mode": mode,
        "questions": n,
        "recall_off": round(mean(rows, "off", "recall"), 3),
        "recall_on": round(mean(rows, "on", "recall"), 3),
        "avg_chars_off": round(mean(rows, "off", "chars")),
        "avg_chars_on": round(mean(rows, "on", "chars")),
        "excluded_note_off": sum(r["off"]["excluded"] for r in rows),
        "excluded_note_on": sum(r["on"]["excluded"] for r in rows),
    }
    if args.routing:
        for side in ("off", "on"):
            for key in ("top1", "in_set", "confident"):
                summary[f"routing_{key}_{side}"] = f"{sum(r[side][key] for r in routing)}/{n}"
        print(f"\n{'routing':32} {'off':>28} {'on':>28}")
        for r in routing:
            print(f"{r['id']:32} {str(r['off']['domains']):>28} {str(r['on']['domains']):>28}")
    print("\n" + json.dumps(summary, indent=2))
    if args.json:
        args.json.write_text(json.dumps({"summary": summary, "rows": rows, "routing": routing}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--llm", action="store_true", help="use the configured LLM (not passthrough)")
    ap.add_argument("--gate", choices=["off", "blocked", "ack"], default="off")
    ap.add_argument("--routing", action="store_true", help="also evaluate domain routing")
    asyncio.run(main(ap.parse_args()))
