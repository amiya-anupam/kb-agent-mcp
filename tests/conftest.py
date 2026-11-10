"""Shared pytest fixtures.

The autouse fixture below keeps the test-suite away from the real ChromaDB
index in ``.kb_index/chroma``.  Without it, tests that index fixture
documents (domains such as ``mydomain`` or ``emptydomainxyz``) leave junk
collections in the live index.
"""
from __future__ import annotations

import pytest


class _IsolatedCfg:
    """Delegates to the real cfg but redirects ``kb_index_path`` to a temp dir."""

    def __init__(self, real, index_path):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_index_path", index_path)

    @property
    def kb_index_path(self):
        return self._index_path

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture(autouse=True)
def _isolate_chroma_index(tmp_path_factory, monkeypatch):
    import kb_agent_mcp.vector_store as vs

    index_path = tmp_path_factory.mktemp("kb_index")
    monkeypatch.setattr(vs, "cfg", _IsolatedCfg(vs.cfg, index_path))
    monkeypatch.setattr(vs, "_client", None)
    yield
    vs._client = None
