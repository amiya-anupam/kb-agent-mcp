"""
kb_agent_mcp/analyst
─────────────────────
Data Analyst capability add-on.

Exposes four entry points consumed by server.py as MCP tools:

    inspect_file(path)                   → DataCard (schema profile of any file)
    suggest_questions(path)              → analytical questions grouped by theme
    query_data(path, question, session)  → clarifying questions OR answer + reasoning
    refine_query(session_id, feedback)   → updated answer based on user feedback

All four work on any file format the file_parser supports:
    .xlsx  .xls  .csv  .json  .jsonl  .pdf  .docx  .pptx  .txt  .md  .boxnote

The analyst layer does NOT replace the vector index — it runs live computation
over raw file data and is only invoked when the question requires aggregation,
trending, filtering, or comparison rather than semantic retrieval.
"""

from kb_agent_mcp.analyst.inspector import inspect_file, DataCard
from kb_agent_mcp.analyst.planner import suggest_questions
from kb_agent_mcp.analyst.engine import query_data, refine_query

__all__ = [
    "inspect_file",
    "DataCard",
    "suggest_questions",
    "query_data",
    "refine_query",
]
