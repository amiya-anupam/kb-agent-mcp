"""
kb-agent-mcp: A zero-config, pip-installable MCP server that turns any folder
of documents into a queryable knowledge base. Any MCP-compatible AI tool
(Claude, Cursor, Bob, etc.) can use it as a tool.
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("kb-agent-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0"  # fallback when running from source without installing

__author__ = "KnowledgeBase Agent Contributors"
