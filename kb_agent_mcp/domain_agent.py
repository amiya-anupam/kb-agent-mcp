"""
kb_agent_mcp/domain_agent.py
─────────────────────────────
DomainAgent: wraps a single knowledge folder with its domain_config.yaml
rules and delegates to the base_agent async RAG pipeline.

The orchestrator instantiates one DomainAgent per discovered domain and
calls `domain_agent.run(question, history, format_instruction)`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from kb_agent_mcp.config import cfg
from kb_agent_mcp.base_agent import (
    ask as _base_ask,
    is_data_question as _global_data_q,
)
from kb_agent_mcp.domain_rules import (
    DomainConfig,
    load_domain_config,
    apply_pin_rules,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Format instruction helpers ─────────────────────────────────────────────────

def _apply_format_instruction(system_prompt: str, format_instruction: str) -> str:
    if not format_instruction:
        return system_prompt
    return (
        system_prompt
        + f"\n\n**OUTPUT FORMAT DIRECTIVE (highest priority):**\n{format_instruction}"
    )


# ── DomainAgent ────────────────────────────────────────────────────────────────

class DomainAgent:
    """
    Manages retrieval and answering for a single knowledge domain.

    Attributes:
        folder_name: Top-level folder name under KB_ROOT.
        config:      Loaded DomainConfig (or a generated default if no YAML).
    """

    def __init__(self, folder_name: str, config: DomainConfig | None = None):
        self.folder_name = folder_name
        self.config: DomainConfig = config or _default_config(folder_name)

    # ── Public interface ───────────────────────────────────────────────────────

    async def run(
        self,
        question: str,
        history: list[dict],
        format_instruction: str = "",
        top_n_override: int | None = None,
    ) -> dict:
        """
        Run the full RAG pipeline for this domain.

        Args:
            top_n_override: When set by the orchestrator (e.g. budget reduction),
                            overrides self.config.top_n for this call only.

        Returns the same dict shape as base_agent.ask():
            { agent, answer, sources, found, passthrough, … }
        """
        system_prompt = _apply_format_instruction(
            self.config.system_prompt, format_instruction
        )

        # Resolve effective top_n — orchestrator may reduce it for budget control.
        effective_top_n = top_n_override if top_n_override is not None else self.config.top_n

        # Check if domain-specific data patterns match (extends global patterns)
        needs_raw_rag = (
            _global_data_q(question)
            or self.config.is_data_question(question)
        )

        if needs_raw_rag:
            # Bypass README-first: go directly to vector search + pin rules
            pre_ranked = await self._pre_rank(question, top_n=effective_top_n)
            return await _base_ask(
                question=question,
                folder_name=self.folder_name,
                agent_name=self.config.agent_name,
                system_prompt=system_prompt,
                conversation_history=history,
                top_n=effective_top_n,
                max_chars=self.config.max_chars,
                pre_ranked_results=pre_ranked,
            )

        # Normal path: README-first with optional fallback
        return await _base_ask(
            question=question,
            folder_name=self.folder_name,
            agent_name=self.config.agent_name,
            system_prompt=system_prompt,
            conversation_history=history,
            top_n=effective_top_n,
            max_chars=self.config.max_chars,
        )

    # ── Stale-index check ──────────────────────────────────────────────────────

    def stale_file_count(self) -> tuple[int, int]:
        """Return (files_on_disk, files_indexed) for this domain.

        Uses a lightweight directory walk (no embedding, no ChromaDB query
        beyond a count) so it adds negligible latency to a query call.

        Returns (0, 0) on any error to avoid masking real query failures.
        """
        from kb_agent_mcp.file_parser import INCLUDE_EXTS, should_skip
        from kb_agent_mcp.vector_store import get_or_create_collection

        try:
            # Import cfg fresh so tests that monkeypatch KB_ROOT and reload
            # config pick up the updated value rather than the module singleton.
            from kb_agent_mcp.config import cfg as _cfg
            folder = _cfg.kb_root_path / self.folder_name
            files_on_disk = sum(
                1
                for f in folder.rglob("*")
                if f.is_file()
                and f.suffix.lower() in INCLUDE_EXTS
                and not should_skip(f)
            )
            col = get_or_create_collection(self.folder_name)
            files_indexed = col.count()
            return files_on_disk, files_indexed
        except Exception as exc:
            logger.warning(
                "stale_file_count for domain %r failed (%s); returning (0, 0)",
                self.folder_name, exc,
            )
            return 0, 0

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _pre_rank(self, question: str, top_n: int | None = None) -> list[dict]:
        """
        Run vector search then apply domain pin/boost rules.
        Returns the re-ordered results list.
        """
        from kb_agent_mcp.vector_store import search as _vs_search

        effective_top_n = top_n if top_n is not None else self.config.top_n
        results = await _vs_search(self.folder_name, question, top_n=effective_top_n)
        if self.config.pin_files or self.config.boost_keywords:
            results = await asyncio.to_thread(
                apply_pin_rules, results, self.folder_name, self.config
            )
        return results


# ── Factory helpers ────────────────────────────────────────────────────────────

def _default_config(folder_name: str) -> DomainConfig:
    """Create a minimal DomainConfig from folder name alone (no YAML file)."""
    from kb_agent_mcp.domain_rules import _default_system_prompt
    # Import cfg fresh so tests that monkeypatch KB_ROOT and reload config
    # pick up the updated singleton rather than the module-level binding.
    from kb_agent_mcp.config import cfg as _cfg
    agent_name = folder_name + " Agent"
    desc = f"Knowledge domain: {folder_name}"
    return DomainConfig(
        folder_name=folder_name,
        agent_name=agent_name,
        description=desc,
        keywords=[],
        top_n=4,
        max_chars=_cfg.KB_BUDGET_RAG_FILE,
        system_prompt=_default_system_prompt(folder_name, agent_name, desc),
    )


def build_domain_agent(folder_name: str) -> DomainAgent:
    """
    Build a DomainAgent for the given folder name.

    Loads domain_config.yaml when present, falls back to generated defaults.
    """
    domain_cfg = load_domain_config(folder_name)
    return DomainAgent(folder_name, config=domain_cfg)


async def build_all_domain_agents() -> dict[str, DomainAgent]:
    """
    Discover all knowledge domains under KB_ROOT and build their agents.

    Returns a dict mapping folder_name → DomainAgent.
    Ignores folders in cfg.BUILTIN_IGNORE or cfg.KB_IGNORE_FOLDERS.
    """
    # Import cfg fresh so tests that monkeypatch KB_ROOT and reload config
    # pick up the updated singleton rather than the module-level binding.
    from kb_agent_mcp.config import cfg as _cfg
    agents: dict[str, DomainAgent] = {}
    kb_root = _cfg.kb_root_path
    try:
        entries = list(kb_root.iterdir())
    except Exception:
        return agents
    for entry in sorted(entries, key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if _cfg.is_ignored(entry.name):
            continue
        agents[entry.name] = await asyncio.to_thread(build_domain_agent, entry.name)
    return agents
