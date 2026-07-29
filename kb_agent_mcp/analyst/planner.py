"""
kb_agent_mcp/analyst/planner.py
─────────────────────────────────
Question planner — turns a DataCard into a menu of analytical questions.

Given a DataCard produced by inspector.py, this module generates a dict of
analytical questions grouped by theme.  Each question entry carries:

    question    — the natural-language question text
    theme       — high-level category (revenue, attrition, growth, …)
    requires    — list of column kinds needed to answer it
    clarifications — list of clarifying-question dicts the engine will ask
                     before running, if those parameters are not yet known

The output is intentionally over-inclusive: it suggests everything the data
*could* answer, letting the AI (and the user) pick what is relevant.

No I/O.  No external calls.  Pure logic over the DataCard.
"""

from __future__ import annotations

import logging
from typing import Any

from kb_agent_mcp.analyst.inspector import DataCard

logger = logging.getLogger(__name__)


# ── Types ──────────────────────────────────────────────────────────────────────

# A single analytical question with metadata
Question = dict[str, Any]
# {theme_name: [Question, …]}
QuestionMenu = dict[str, list[Question]]


# ── Clarification templates ────────────────────────────────────────────────────

def _clq(id_: str, text: str, kind: str = "choice", choices: list[str] | None = None) -> dict:
    """Build a clarifying-question dict."""
    q: dict[str, Any] = {"id": id_, "text": text, "kind": kind}
    if choices:
        q["choices"] = choices
    return q


def _time_filter_clqs(time_cols: list[str]) -> list[dict]:
    """Common clarifying questions for time-filtered queries."""
    clqs = []
    if time_cols:
        clqs.append(_clq(
            "time_col",
            f"Which time column should I filter on? Options: {', '.join(time_cols)}",
            kind="choice",
            choices=time_cols,
        ))
        clqs.append(_clq(
            "time_range",
            "What time range? (e.g. 'FY2025', 'Q1 2026', 'last 12 months', 'all')",
            kind="freetext",
        ))
    return clqs


def _entity_filter_clqs(entity_cols: list[str]) -> list[dict]:
    """Common clarifying questions for entity-scoped queries."""
    if not entity_cols:
        return []
    return [_clq(
        "entity_filter",
        f"Should I filter to a specific {' / '.join(entity_cols[:3])}? "
        "(Leave blank for all)",
        kind="freetext",
    )]


def _metric_clqs(metric_cols: list[str]) -> list[dict]:
    """Ask which metric to use when multiple candidates exist."""
    if len(metric_cols) <= 1:
        return []
    return [_clq(
        "metric_col",
        f"Which metric should I use? Options: {', '.join(metric_cols)}",
        kind="choice",
        choices=metric_cols,
    )]


def _top_n_clq() -> dict:
    return _clq("top_n", "How many top results should I return? (default: 10)", kind="freetext")


# ── Theme builders ─────────────────────────────────────────────────────────────

def _revenue_questions(card: DataCard) -> list[Question]:
    m = card.metric_columns
    t = card.time_columns
    e = card.entity_columns
    if not m:
        return []
    questions: list[Question] = []

    questions.append({
        "question": f"What is the total {m[0]} across all records?",
        "theme": "revenue",
        "requires": ["metric"],
        "clarifications": _time_filter_clqs(t) + _entity_filter_clqs(e),
    })

    if e:
        questions.append({
            "question": f"What are the top customers/entities by {m[0]}?",
            "theme": "revenue",
            "requires": ["metric", "entity"],
            "clarifications": [_top_n_clq()] + _time_filter_clqs(t) + _metric_clqs(m),
        })

    if t:
        questions.append({
            "question": f"How has {m[0]} changed over time?",
            "theme": "revenue",
            "requires": ["metric", "time"],
            "clarifications": _time_filter_clqs(t) + _metric_clqs(m) + _entity_filter_clqs(e),
        })

    if e:
        questions.append({
            "question": f"What is the {m[0]} breakdown by {e[0]}?",
            "theme": "revenue",
            "requires": ["metric", "entity"],
            "clarifications": _metric_clqs(m) + _time_filter_clqs(t),
        })

    return questions


def _attrition_questions(card: DataCard) -> list[Question]:
    m = card.metric_columns
    t = card.time_columns
    e = card.entity_columns
    if not (m and t and e):
        return []
    questions: list[Question] = [
        {
            "question": "Which customers appear in an earlier period but not the most recent one? "
                        "(potential churned / at-risk customers)",
            "theme": "attrition",
            "requires": ["metric", "entity", "time"],
            "clarifications": _time_filter_clqs(t) + _metric_clqs(m),
        },
        {
            "question": "What is the total revenue at risk from customers who did not renew?",
            "theme": "attrition",
            "requires": ["metric", "entity", "time"],
            "clarifications": _time_filter_clqs(t) + _metric_clqs(m),
        },
        {
            "question": "Which customer segments have the highest attrition rate?",
            "theme": "attrition",
            "requires": ["metric", "entity", "time"],
            "clarifications": _time_filter_clqs(t) + _metric_clqs(m) + [
                _clq("segment_col",
                     f"Which column defines the segment? Options: {', '.join(e[:5])}",
                     kind="choice", choices=e[:5]),
            ],
        },
    ]
    return questions


def _growth_questions(card: DataCard) -> list[Question]:
    m = card.metric_columns
    t = card.time_columns
    e = card.entity_columns
    if not (m and t):
        return []
    questions: list[Question] = [
        {
            "question": f"What is the period-over-period growth rate for {m[0]}?",
            "theme": "growth",
            "requires": ["metric", "time"],
            "clarifications": _time_filter_clqs(t) + _metric_clqs(m),
        },
        {
            "question": f"Which {e[0] if e else 'groups'} are growing fastest?",
            "theme": "growth",
            "requires": ["metric", "time", "entity"],
            "clarifications": _time_filter_clqs(t) + _metric_clqs(m) + _entity_filter_clqs(e),
        },
    ]
    return questions


def _concentration_questions(card: DataCard) -> list[Question]:
    m = card.metric_columns
    e = card.entity_columns
    if not (m and e):
        return []
    return [
        {
            "question": f"What share of total {m[0]} comes from the top 10 {e[0]}?",
            "theme": "concentration",
            "requires": ["metric", "entity"],
            "clarifications": _metric_clqs(m) + [_top_n_clq()] + _entity_filter_clqs(e[1:]),
        },
        {
            "question": f"Is {m[0]} concentrated in a few {e[0]} or spread evenly? "
                        "(Gini / 80/20 analysis)",
            "theme": "concentration",
            "requires": ["metric", "entity"],
            "clarifications": _metric_clqs(m),
        },
    ]


def _anomaly_questions(card: DataCard) -> list[Question]:
    m = card.metric_columns
    t = card.time_columns
    if not m:
        return []
    questions: list[Question] = [
        {
            "question": f"Are there any outliers or anomalies in {m[0]}?",
            "theme": "anomaly",
            "requires": ["metric"],
            "clarifications": _metric_clqs(m) + _time_filter_clqs(t),
        },
    ]
    if t:
        questions.append({
            "question": "Are there any periods with unusually high or low values?",
            "theme": "anomaly",
            "requires": ["metric", "time"],
            "clarifications": _time_filter_clqs(t) + _metric_clqs(m),
        })
    return questions


def _summary_questions(card: DataCard) -> list[Question]:
    """Always-available questions that work on any tabular file."""
    questions: list[Question] = [
        {
            "question": "Give me a summary of this file — what does it contain and what are the key numbers?",
            "theme": "summary",
            "requires": [],
            "clarifications": [],
        },
        {
            "question": "What data quality issues should I be aware of? "
                        "(nulls, duplicates, outliers)",
            "theme": "summary",
            "requires": [],
            "clarifications": [],
        },
    ]
    if card.file_format == "tabular" and card.total_rows > 0:
        questions.append({
            "question": f"How many unique values are there in each key column?",
            "theme": "summary",
            "requires": ["entity"],
            "clarifications": [],
        })
    return questions


def _document_questions(card: DataCard) -> list[Question]:
    """Questions specific to document (non-tabular) files."""
    if card.file_format == "tabular":
        return []
    return [
        {
            "question": "What are the key topics and themes in this document?",
            "theme": "document",
            "requires": [],
            "clarifications": [],
        },
        {
            "question": "What are the main conclusions or recommendations?",
            "theme": "document",
            "requires": [],
            "clarifications": [],
        },
        {
            "question": "Are there any numbers, metrics, or targets mentioned?",
            "theme": "document",
            "requires": [],
            "clarifications": [],
        },
    ]


# ── Filtering / dedup ──────────────────────────────────────────────────────────

def _deduplicate(questions: list[Question]) -> list[Question]:
    """Remove questions with identical text (can happen when themes overlap)."""
    seen: set[str] = set()
    out = []
    for q in questions:
        key = q["question"].lower().strip()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


# ── Public entry point ─────────────────────────────────────────────────────────

async def suggest_questions(card_or_dict: DataCard | dict) -> QuestionMenu:
    """
    Given a DataCard (or its dict representation), return a QuestionMenu:
    a dict keyed by theme name, each containing a list of Question dicts.

    This function is sync-safe (no I/O) but declared async to match the
    MCP tool calling convention.
    """
    if isinstance(card_or_dict, dict):
        # Re-hydrate from the serialised form returned by data_card_to_dict()
        from kb_agent_mcp.analyst.inspector import DataCard, ColumnProfile
        cols = [ColumnProfile(**c) for c in card_or_dict.get("columns", [])]
        card = DataCard(
            path=card_or_dict.get("path", ""),
            file_name=card_or_dict.get("file_name", ""),
            file_format=card_or_dict.get("file_format", "tabular"),
            file_type=card_or_dict.get("file_type", ""),
            total_rows=card_or_dict.get("total_rows", 0),
            total_columns=card_or_dict.get("total_columns", 0),
            columns=cols,
            time_columns=card_or_dict.get("time_columns", []),
            entity_columns=card_or_dict.get("entity_columns", []),
            metric_columns=card_or_dict.get("metric_columns", []),
            time_range=card_or_dict.get("time_range", {}),
            grain_hint=card_or_dict.get("grain_hint", ""),
            data_themes=card_or_dict.get("data_themes", []),
            summary=card_or_dict.get("summary", ""),
            warnings=card_or_dict.get("warnings", []),
            profiled_at=card_or_dict.get("profiled_at", 0.0),
        )
    else:
        card = card_or_dict

    all_questions = (
        _summary_questions(card)
        + _document_questions(card)
        + _revenue_questions(card)
        + _attrition_questions(card)
        + _growth_questions(card)
        + _concentration_questions(card)
        + _anomaly_questions(card)
    )

    all_questions = _deduplicate(all_questions)

    # Group by theme
    menu: QuestionMenu = {}
    for q in all_questions:
        theme = q["theme"]
        menu.setdefault(theme, []).append(q)

    return menu
