#!/usr/bin/env python3
"""Golden-question evaluation: legacy retrieval vs tiered context-store retrieval.

Runs each question in tests/golden_questions.json through DomainAgent.run() in
passthrough mode (no LLM) with KB_CONTEXT_STORE off and on, then reports

  * recall - share of `expected_facts` present in the context handed to the LLM
  * chars  - length of the passthrough block (same fixed overhead in both modes)

Usage:  python3 scripts/golden_eval.py [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kb_agent_mcp import base_agent                      # noqa: E402
from kb_agent_mcp.config import cfg                      # noqa: E402
from kb_agent_mcp.domain_agent import DomainAgent        # noqa: E402

GOLDEN = ROOT / "tests" / "golden_questions.json"


def recall(text: str, facts: list[str]) -> float:
    low = text.lower()
    return sum(f.lower() in low for f in facts) / len(facts) if facts else 1.0


async def run_one(q: dict, flag: bool) -> dict:
    object.__setattr__(cfg, "KB_CONTEXT_STORE", flag)
    res = await DomainAgent(q["domain"]).run(q["question"], [])
    block = res.get("passthrough_block") or res.get("answer") or ""
    return {
        "recall": recall(block, q["expected_facts"]),
        "chars": len(block),
        "sources": [s.get("name", "") for s in res.get("sources", [])][:3],
    }


async def main(out: Path | None) -> None:
    base_agent._passthrough_cache = True                # never call an LLM
    original = cfg.KB_CONTEXT_STORE
    gate = cfg.KB_SECURITY_GATE_ENABLED
    object.__setattr__(cfg, "KB_SECURITY_GATE_ENABLED", False)   # measure retrieval, not gating
    questions = json.loads(GOLDEN.read_text())
    rows = []
    try:
        for q in questions:
            off = await run_one(q, False)
            on = await run_one(q, True)
            rows.append({"id": q["id"], "off": off, "on": on})
    finally:
        object.__setattr__(cfg, "KB_CONTEXT_STORE", original)
        object.__setattr__(cfg, "KB_SECURITY_GATE_ENABLED", gate)

    print(f"{'question':32} {'recall off':>10} {'recall on':>10} {'chars off':>10} {'chars on':>10}")
    for r in rows:
        print(f"{r['id']:32} {r['off']['recall']:>10.2f} {r['on']['recall']:>10.2f} "
              f"{r['off']['chars']:>10} {r['on']['chars']:>10}")
    n = len(rows)
    summary = {
        "questions": n,
        "recall_off": round(sum(r["off"]["recall"] for r in rows) / n, 3),
        "recall_on": round(sum(r["on"]["recall"] for r in rows) / n, 3),
        "avg_chars_off": round(sum(r["off"]["chars"] for r in rows) / n),
        "avg_chars_on": round(sum(r["on"]["chars"] for r in rows) / n),
    }
    print("\n" + json.dumps(summary, indent=2))
    if out:
        out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    asyncio.run(main(args.json))
