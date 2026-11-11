"""
kb_agent_mcp/format_instruction.py
──────────────────────────────────
Single definition of apply_format_instruction(); dependency-free so both
kb_agent_mcp.domain_agent and agents/agent_base.py can import it cheaply.
"""

from __future__ import annotations


def apply_format_instruction(system_prompt: str, format_instruction: str) -> str:
    """Append a format instruction to a system prompt (no-op when empty)."""
    if not format_instruction:
        return system_prompt
    return (
        system_prompt
        + f"\n\n**OUTPUT FORMAT DIRECTIVE (highest priority):**\n{format_instruction}"
    )
