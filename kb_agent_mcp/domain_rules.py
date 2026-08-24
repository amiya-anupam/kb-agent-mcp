"""
kb_agent_mcp/domain_rules.py
─────────────────────────────
Load and apply per-domain retrieval rules from domain_config.yaml.

domain_config.yaml schema (inside each knowledge folder):
──────────────────────────────────────────────────────────
folder_name:  BizOps
agent_name:   BizOps Agent
description:  …
keywords:     [revenue, ACE, CP4I, …]
top_n:        5
max_chars:    8000
system_prompt: |
  You are the BizOps Agent …
# system_prompt_extra: |           # optional — appended after system_prompt
#   Always cite the contract reference number.

retrieval_rules:
  pin_files:            # glob patterns — matching files always included
    - "*Revenue*.xlsx"
  boost_keywords:       # file names containing these are scored higher
    - revenue
  question_classifier:
    data_patterns:      # regex → force raw-file RAG (skip README-first)
      - "\\brevenue\\b"
    complex_patterns:   # regex → use full README (not just index block)
      - "\\barchitecture\\b"
──────────────────────────────────────────────────────────

All fields are optional — sensible defaults are used when absent.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml  # type: ignore
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

from kb_agent_mcp.config import cfg

logger = logging.getLogger(__name__)


# ── Domain config dataclass ────────────────────────────────────────────────────

@dataclass
class DomainConfig:
    """Parsed and validated domain_config.yaml for one knowledge folder."""

    folder_name: str
    agent_name: str
    description: str
    keywords: list[str]
    top_n: int
    max_chars: int
    system_prompt: str
    system_prompt_extra: str      = field(default="")

    # retrieval_rules sub-fields
    pin_files: list[str]          = field(default_factory=list)
    boost_keywords: list[str]     = field(default_factory=list)
    data_patterns: list[str]      = field(default_factory=list)
    complex_patterns: list[str]   = field(default_factory=list)

    # Compiled regex (built lazily)
    _data_re: re.Pattern | None   = field(default=None, init=False, repr=False)
    _complex_re: re.Pattern | None = field(default=None, init=False, repr=False)

    def _compile(self) -> None:
        if self.data_patterns and self._data_re is None:
            try:
                self._data_re = re.compile("|".join(self.data_patterns), re.IGNORECASE)
            except re.error:
                self._data_re = None
        if self.complex_patterns and self._complex_re is None:
            try:
                self._complex_re = re.compile("|".join(self.complex_patterns), re.IGNORECASE)
            except re.error:
                self._complex_re = None

    def is_data_question(self, question: str) -> bool:
        """Return True if this question matches domain-specific data patterns."""
        self._compile()
        if self._data_re:
            return bool(self._data_re.search(question))
        return False

    def is_complex_question(self, question: str) -> bool:
        """Return True if this question matches domain-specific complex patterns."""
        self._compile()
        if self._complex_re:
            return bool(self._complex_re.search(question))
        return False


def _default_system_prompt(folder_name: str, agent_name: str, description: str) -> str:
    return (
        f"You are the {agent_name}, a specialist in the {folder_name} knowledge domain.\n"
        f"Domain description: {description}\n"
        f"You answer questions strictly based on the provided document context.\n"
        f"Be concise, accurate, and cite which document your answer came from.\n"
        f"If the answer is not in the provided context, say so clearly — do not guess.\n"
        f"Format your answer in clean markdown."
    )


# ── YAML loader ────────────────────────────────────────────────────────────────

def _parse_yaml(text: str) -> dict[str, Any]:
    """Parse YAML text. Falls back to an empty dict if yaml not installed."""
    if _HAS_YAML:
        try:
            result = _yaml.safe_load(text)
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            logger.warning("Failed to parse YAML (%s); returning empty config", exc)
            return {}
    # Minimal fallback: key: value pairs only (no nested keys)
    data: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        data[k.strip()] = v.strip()
    return data


def load_domain_config(folder_name: str) -> DomainConfig | None:
    """
    Load domain_config.yaml from inside a knowledge folder.
    Returns None if the file does not exist.
    """
    config_path = cfg.kb_root_path / folder_name / "domain_config.yaml"
    if not config_path.exists():
        return None
    try:
        raw = _parse_yaml(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "Failed to read domain config at %s (%s); skipping domain",
            config_path, exc,
        )
        return None
    return _build_config(folder_name, raw)


def load_domain_config_from_dict(folder_name: str, raw: dict[str, Any]) -> DomainConfig:
    """Build a DomainConfig from an already-parsed dict (used by generate CLI)."""
    return _build_config(folder_name, raw)


def _build_config(folder_name: str, raw: dict[str, Any]) -> DomainConfig:
    fname   = raw.get("folder_name", folder_name)
    aname   = raw.get("agent_name",  fname + " Agent")
    desc    = raw.get("description", f"Knowledge domain: {fname}")
    kws     = raw.get("keywords",    [])
    top_n   = int(raw.get("top_n",   4))
    mx      = int(raw.get("max_chars", cfg.KB_BUDGET_RAG_FILE))
    sp      = raw.get("system_prompt", "") or _default_system_prompt(fname, aname, desc)
    sp_extra = raw.get("system_prompt_extra", "") or ""

    rules   = raw.get("retrieval_rules", {}) or {}
    pins    = rules.get("pin_files",       [])
    boosts  = rules.get("boost_keywords",  [])
    qc      = rules.get("question_classifier", {}) or {}
    d_pats  = qc.get("data_patterns",     [])
    c_pats  = qc.get("complex_patterns",  [])

    return DomainConfig(
        folder_name=fname,
        agent_name=aname,
        description=desc,
        keywords=kws if isinstance(kws, list) else str(kws).split(","),
        top_n=top_n,
        max_chars=mx,
        system_prompt=sp.strip(),
        system_prompt_extra=sp_extra.strip(),
        pin_files=pins if isinstance(pins, list) else [pins],
        boost_keywords=boosts if isinstance(boosts, list) else [boosts],
        data_patterns=d_pats if isinstance(d_pats, list) else [d_pats],
        complex_patterns=c_pats if isinstance(c_pats, list) else [c_pats],
    )


# ── Retrieval rule application ─────────────────────────────────────────────────

def apply_pin_rules(
    results: list[dict],
    folder_name: str,
    domain_cfg: DomainConfig,
) -> list[dict]:
    """
    Apply pin_files and boost_keywords rules to a search result list.

    pin_files:      Force-include files whose names match any glob pattern —
                    they are prepended at score=1.0 if not already in results.
    boost_keywords: Move files whose names contain a boost keyword to the front
                    of the non-pinned results (stable sort).

    Returns a new list; the original is not mutated.
    """
    if not domain_cfg.pin_files and not domain_cfg.boost_keywords:
        return results

    result_paths = {r["path"] for r in results}
    pinned: list[dict] = []

    # ── Pin files ──────────────────────────────────────────────────────────────
    if domain_cfg.pin_files:
        folder_path = cfg.kb_root_path / folder_name
        try:
            all_files = list(folder_path.rglob("*"))
        except Exception as exc:
            logger.debug(
                "rglob failed on %s when applying pin rules (%s); skipping pins",
                folder_path, exc,
            )
            all_files = []
        for fpath in all_files:
            if not fpath.is_file():
                continue
            for pattern in domain_cfg.pin_files:
                if fnmatch.fnmatch(fpath.name, pattern):
                    rel = str(fpath.relative_to(cfg.kb_root_path))
                    if rel not in result_paths:
                        pinned.append({
                            "path":   rel,
                            "name":   fpath.name,
                            "score":  1.0,
                            "folder": folder_name,
                        })
                        result_paths.add(rel)
                    break

    # ── Boost keywords ─────────────────────────────────────────────────────────
    if domain_cfg.boost_keywords:
        def _boosted(r: dict) -> bool:
            name = r.get("name", "").lower()
            return any(kw.lower() in name for kw in domain_cfg.boost_keywords)

        boosted  = [r for r in results if _boosted(r)]
        rest     = [r for r in results if not _boosted(r)]
        results  = boosted + rest

    return pinned + results
