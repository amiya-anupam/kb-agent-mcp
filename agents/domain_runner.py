#!/usr/bin/env python3
"""
agents/domain_runner.py — Parameterised domain-ask runner
----------------------------------------------------------
Single implementation of domain_ask() shared by every generated
agents/agent_<safe>.py shim.  Domain-specific retrieval overrides
are keyed by safe_name rather than being copied into each file.

Call via the generated shim:
    from domain_runner import run
    result = run(safe_name, folder_name, agent_name, system_prompt,
                 top_n, max_chars, question, history, format_instruction)

Or via the convenience wrapper emitted by generate_sub_agent():
    domain_ask(question, history, format_instruction="")
"""

import sys
import json
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from agent_base import (
    ask as _base_ask,
    _is_data_question,
    _apply_format_instruction,
    folder_to_safe_name,
    KB_ROOT,
    VECTOR_STORE,
)

# ── Revenue-pinning logic (BizOps override) ───────────────────────────────────
# Domains whose data questions should have Revenue*.xlsx files pinned to the top
# of the retrieval context so authoritative Rev Act @ PC numbers are read first.
_REVENUE_DOMAINS: frozenset[str] = frozenset({"bizops"})


def _bizops_ask(
    folder_name: str,
    agent_name: str,
    system_prompt: str,
    top_n: int,
    max_chars: int,
    question: str,
    history: list,
) -> dict:
    """BizOps-specific retrieval: pin Revenue*.xlsx to front for data questions."""
    from embeddings import search  # noqa: PLC0415 — lazy import

    if not _is_data_question(question):
        return _base_ask(
            question=question,
            folder_name=folder_name,
            agent_name=agent_name,
            system_prompt=system_prompt,
            conversation_history=history,
            top_n=top_n,
            max_chars=max_chars,
        )

    results = search(question, folder_name, top_n=top_n)
    if results:
        result_paths = {r["path"] for r in results}
        safe_name = folder_to_safe_name(folder_name)
        idx_path = VECTOR_STORE / f"{safe_name}_index.json"
        if idx_path.exists():
            try:
                idx_data = json.loads(idx_path.read_text())
                for entry in idx_data.get("entries", []):
                    name = entry.get("name", "")
                    if (
                        "revenue" in name.lower()
                        and name.lower().endswith(".xlsx")
                        and entry.get("path") not in result_paths
                    ):
                        results.append(
                            {
                                "path": entry["path"],
                                "name": name,
                                "score": 1.0,
                                "folder": folder_name,
                            }
                        )
                        result_paths.add(entry["path"])
            except Exception:
                pass

        def _rev_priority(r: dict) -> int:
            n = r.get("name", "").lower()
            return 0 if ("revenue" in n and n.endswith(".xlsx")) else 1

        results = sorted(results, key=_rev_priority)

    return _base_ask(
        question=question,
        folder_name=folder_name,
        agent_name=agent_name,
        system_prompt=system_prompt,
        conversation_history=history,
        top_n=top_n,
        max_chars=max_chars,
        _pre_ranked_results=results,
    )


# ── Public entry point ────────────────────────────────────────────────────────

def run(
    safe_name: str,
    folder_name: str,
    agent_name: str,
    system_prompt: str,
    top_n: int,
    max_chars: int,
    question: str,
    history: list,
    format_instruction: str = "",
) -> dict:
    """
    Dispatch a question to the correct domain handler.

    For most domains this delegates directly to agent_base.ask().
    Revenue-domain overrides (e.g. BizOps) are handled inline here
    so the logic lives in one place instead of being copied per-domain.
    """
    fmt_prompt = _apply_format_instruction(system_prompt, format_instruction)

    if safe_name in _REVENUE_DOMAINS:
        return _bizops_ask(
            folder_name=folder_name,
            agent_name=agent_name,
            system_prompt=fmt_prompt,
            top_n=top_n,
            max_chars=max_chars,
            question=question,
            history=history,
        )

    return _base_ask(
        question=question,
        folder_name=folder_name,
        agent_name=agent_name,
        system_prompt=fmt_prompt,
        conversation_history=history,
        top_n=top_n,
        max_chars=max_chars,
    )
