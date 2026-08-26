"""
kb_agent_mcp/base_agent.py
──────────────────────────
Async README-first RAG pipeline.

Strategy (per domain):
  1. Try README-first:
     - Simple questions  → AUTO-INDEX block + brief intro (~2 000 chars)
     - Complex questions → full README body (up to KB_BUDGET_FULL_README chars)
  2. Fallback to raw-file RAG when README is absent / too thin, or the question
     is a data/numeric question that needs actual file content.

Passthrough mode (KB_LLM_PROVIDER=passthrough, or auto-detected):
  Returns a structured dict with a `passthrough_block` key instead of calling
  the LLM.  The MCP server embeds this block in the tool response so the
  client's Claude can answer using the retrieved context.

LLM providers: ollama | openai | anthropic | custom | passthrough
All config from kb_agent_mcp.config.cfg.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading as _threading
import time as _time
from pathlib import Path
from typing import Any, TypedDict

import httpx

from kb_agent_mcp.config import cfg, ANTHROPIC_API_VERSION
from kb_agent_mcp.context_budget import (
    trim as _cb_trim,
    build_context as _cb_build_context,
    get as _cb_get,
)
from kb_agent_mcp.file_parser import extract as _extract_file

logger = logging.getLogger(__name__)


# ── AgentResult TypedDict ──────────────────────────────────────────────────────

class AgentResult(TypedDict, total=False):
    """Typed return shape for base_agent.ask() and DomainAgent.run()."""
    agent:             str    # required
    answer:            str    # required
    sources:           list   # required — list[dict]
    found:             bool   # required
    passthrough:       bool
    passthrough_block: str
    confidence_footer: str
    truncated:         bool


# ── Shared HTTP client (connection pool reused across all LLM calls) ──────────
# httpx.Client keeps TCP connections alive — avoids a fresh TCP+TLS handshake
# per LLM request (saves 100–500 ms per call on HTTPS endpoints).
_http_client: httpx.Client | None = None
_http_client_tlock = _threading.Lock()


def _get_http_client() -> httpx.Client:
    """Return (or lazily create) the shared sync httpx.Client.

    Uses a threading.Lock (not asyncio.Lock) because this function is called
    from sync worker threads via asyncio.to_thread — asyncio primitives are
    not safe to use outside the event loop.
    """
    global _http_client
    if _http_client is None:
        with _http_client_tlock:
            if _http_client is None:
                _http_client = httpx.Client(
                    timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0),
                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                )
    return _http_client


# ── Passthrough detection ──────────────────────────────────────────────────────

async def _check_passthrough() -> bool:
    """
    Return True when the agent should emit a passthrough block instead of
    calling a local LLM.

    Conditions (any of):
      1. KB_LLM_PROVIDER is explicitly "passthrough"
      2. KB_LLM_PROVIDER is "ollama", KB_API_KEY is empty, and Ollama is
         not reachable (auto-detect; disabled by KB_PASSTHROUGH_FALLBACK=false)
    """
    if cfg.KB_LLM_PROVIDER == "passthrough":
        return True

    if cfg.KB_LLM_PROVIDER != "ollama" or cfg.KB_API_KEY:
        return False

    if not cfg.KB_PASSTHROUGH_FALLBACK:
        return False

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{cfg.KB_LLM_BASE_URL}/api/tags")
            return r.status_code >= 400
    except Exception as exc:
        logger.debug("Ollama reachability check failed (%s); treating as passthrough", exc)
        return True  # unreachable → passthrough


# Evaluated once at import; re-run only if the server is restarted.
# We use a module-level cache so we don't check on every `ask` call.
_passthrough_cache: bool | None = None
_passthrough_lock = asyncio.Lock()


async def is_passthrough() -> bool:
    """Cached passthrough check (checks Ollama at most once per process)."""
    global _passthrough_cache
    if _passthrough_cache is None:
        async with _passthrough_lock:
            if _passthrough_cache is None:
                _passthrough_cache = await _check_passthrough()
    return _passthrough_cache


def reset_passthrough_cache() -> None:
    """Force re-detection on next call (used by tests or reindex)."""
    global _passthrough_cache
    _passthrough_cache = None


# ── Question classifiers ────────────────────────────────────────────────────────

_COMPLEX_QUESTION_RE = re.compile(
    r"\b(compare|contrast|difference between|differences between|"
    r"walk me through|step[- ]by[- ]step|deep dive|in[- ]depth|"
    r"comprehensive|explain in detail|elaborate on|how does .{3,40} work|"
    r"pros and cons|trade[- ]off|architecture of|internals of|"
    r"full breakdown|everything about)\b",
    re.IGNORECASE,
)

_DATA_QUESTION_RE = re.compile(
    r"\b(revenue|total revenue|arr|mrr|acv|tcv|quota|attainment|"
    r"how much|how many|what is the (number|count|total|sum|amount|value|"
    r"figure|balance|price|cost|rate|percentage|percent|ratio|score|metric)|"
    r"what (are|were) the (number|count|total|sum|figures|numbers|metrics|results|"
    r"revenue|sales|deals|renewals|bookings|customers|accounts)|"
    r"list (all|every|the|each)|show me (all|the|every)|give me (all|the)|"
    r"breakdown|by (quarter|region|country|geography|market|segment|"
    r"product|customer|account|industry|channel)|"
    r"q[1-4]\s*20\d\d|20\d\d\s*q[1-4]|fy\s*20\d\d|"
    r"ytd|yoy|qoq|mom|r4q|trailing|rolling)\b",
    re.IGNORECASE,
)


def is_complex_question(question: str) -> bool:
    return bool(_COMPLEX_QUESTION_RE.search(question))


def is_data_question(question: str) -> bool:
    return bool(_DATA_QUESTION_RE.search(question))


# ── README discovery + context extraction ──────────────────────────────────────

_MARKER_START = "<!-- KB:AUTO-INDEX:START -->"
_MARKER_END   = "<!-- KB:AUTO-INDEX:END -->"


def _find_readme(folder: Path) -> Path | None:
    """
    Locate the README for a knowledge folder (priority cascade):
      1. Any .md whose name contains 'readme'
      2. <FolderName>.md
      3. First .md with a Markdown heading
      4. First .md file found
    """
    try:
        md_files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".md"]
    except Exception as exc:
        logger.debug("Failed to list markdown files in %s (%s); no README available", folder, exc)
        return None
    if not md_files:
        return None
    for f in md_files:
        if "readme" in f.name.lower():
            return f
    folder_md = folder.name + ".md"
    for f in md_files:
        if f.name == folder_md:
            return f
    for f in md_files:
        try:
            head = f.read_text(encoding="utf-8", errors="ignore")[:500]
            if re.search(r"^#{1,3}\s+\S", head, re.MULTILINE):
                return f
        except Exception as exc:
            logger.debug("Could not read candidate README %s (%s); skipping", f, exc)
            continue
    return md_files[0]


# ── Per-domain README cache ───────────────────────────────────────────────────
# README files change only when kb-agent-generate is re-run. Cache the
# (path, text) pair per folder_name so repeated queries in the same process
# don't re-discover and re-read the same file from disk.
# TTL: 5 minutes — stale on server restart anyway.
_README_CACHE: dict[str, tuple["Path | None", str, float]] = {}
_README_CACHE_TTL = 300.0  # seconds


def _get_readme_cached(folder_name: str) -> tuple["Path | None", str]:
    """Return (readme_path, text) for folder_name, using a short-lived cache."""
    now = _time.time()
    if folder_name in _README_CACHE:
        cached_path, cached_text, cached_at = _README_CACHE[folder_name]
        if now - cached_at < _README_CACHE_TTL:
            return cached_path, cached_text

    folder = cfg.kb_root_path / folder_name
    readme = _find_readme(folder)
    if readme is None:
        _README_CACHE[folder_name] = (None, "", now)
        return None, ""
    try:
        text = readme.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        logger.debug("Failed to read README %s (%s); skipping README-first strategy", readme, exc)
        _README_CACHE[folder_name] = (None, "", now)
        return None, ""
    _README_CACHE[folder_name] = (readme, text, now)
    return readme, text


def _extract_auto_index(text: str) -> str | None:
    if _MARKER_START not in text or _MARKER_END not in text:
        return None
    start = text.index(_MARKER_START) + len(_MARKER_START)
    end   = text.index(_MARKER_END)
    return text[start:end].strip()


def _non_index_chars(text: str) -> int:
    """Count chars in the README body outside the AUTO-INDEX block."""
    if _MARKER_START in text and _MARKER_END in text:
        s = text.index(_MARKER_START)
        e = text.index(_MARKER_END) + len(_MARKER_END)
        outside = text[:s] + text[e:]
    else:
        outside = text
    return len(outside.strip())


def _get_readme_context(folder_name: str, question: str) -> tuple[str | None, str]:
    """
    Return (context_text, source_label).
    Returns (None, "") when README is absent/thin or the question is a data query.
    """
    if is_data_question(question):
        return None, ""

    readme, text = _get_readme_cached(folder_name)
    if readme is None or not text:
        return None, ""

    if _non_index_chars(text) < _cb_get("min_readme"):
        return None, ""

    if is_complex_question(question):
        context = _cb_trim(text, "full_readme")
        label   = f"Full README ({readme.name})"
    else:
        auto_index = _extract_auto_index(text)
        if auto_index:
            pre_index = text[: text.index(_MARKER_START)].strip()
            context   = _cb_build_context(pre_index, auto_index)
            label     = f"README index ({readme.name})"
        else:
            context = _cb_trim(text, "full_readme")
            label   = f"Full README ({readme.name})"

    return context, label


# ── LLM call (provider-agnostic, async) ────────────────────────────────────────

# Registry maps provider name → sync callable.
# To add a new provider: register it here — call_llm never needs to change.
_LLM_REGISTRY: dict[str, Any] = {}

def _register_provider(*names: str):
    """Decorator that registers a sync LLM callable under one or more provider names."""
    def decorator(fn):
        for name in names:
            _LLM_REGISTRY[name] = fn
        return fn
    return decorator


async def call_llm(messages: list[dict], temperature: float = 0.2) -> str:
    """Send messages to the configured LLM and return the response text."""
    provider = cfg.KB_LLM_PROVIDER.lower()
    handler = _LLM_REGISTRY.get(provider)
    if handler is None:
        # Default fallback: treat unknown providers as Ollama-compatible.
        handler = _LLM_REGISTRY["ollama"]
    return await asyncio.to_thread(handler, messages, temperature)


@_register_provider("ollama")
def _call_ollama_sync(messages: list[dict], temperature: float) -> str:
    try:
        r = _get_http_client().post(
            f"{cfg.KB_LLM_BASE_URL}/api/chat",
            json={
                "model":    cfg.KB_MODEL,
                "messages": messages,
                "stream":   False,
                "options":  {"temperature": temperature, "num_ctx": cfg.KB_NUM_CTX},
                "think":    False,
            },
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception as e:
        raise RuntimeError(
            f"Ollama call failed: {e}\n"
            f"  URL: {cfg.KB_LLM_BASE_URL}/api/chat\n"
            f"  Model: {cfg.KB_MODEL}\n"
            f"  Check: is Ollama running? (`ollama serve`)\n"
            f"         is the model pulled? (`ollama pull {cfg.KB_MODEL}`)"
        ) from e


@_register_provider("openai", "custom")
def _call_openai_compat_sync(messages: list[dict], temperature: float) -> str:
    base = cfg.KB_LLM_BASE_URL.rstrip("/")
    if "11434" in base and not base.endswith("/v1"):
        base = f"{base}/v1"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.KB_API_KEY:
        headers["Authorization"] = f"Bearer {cfg.KB_API_KEY}"
    try:
        r = _get_http_client().post(
            f"{base}/chat/completions",
            headers=headers,
            json={"model": cfg.KB_MODEL, "messages": messages, "temperature": temperature},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        hint = (
            f"OpenAI-compatible call failed: {e}\n"
            f"  URL: {base}/chat/completions\n"
            f"  Model: {cfg.KB_MODEL}\n"
        )
        if not cfg.KB_API_KEY and cfg.KB_LLM_PROVIDER in ("openai", "custom"):
            hint += "  Check: KB_API_KEY is not set in your .env\n"
        raise RuntimeError(hint) from e


@_register_provider("anthropic")
def _call_anthropic_sync(messages: list[dict], temperature: float) -> str:
    system = ""
    chat_messages = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            chat_messages.append(m)
    headers = {
        "x-api-key":         cfg.KB_API_KEY,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "Content-Type":      "application/json",
    }
    payload: dict = {
        "model":       cfg.KB_MODEL,
        "max_tokens":  4096,
        "temperature": temperature,
        "messages":    chat_messages,
    }
    if system:
        payload["system"] = system
    try:
        r = _get_http_client().post(
            f"{cfg.KB_LLM_BASE_URL}/v1/messages",
            headers=headers,
            json=payload,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        raise RuntimeError(
            f"Anthropic call failed: {e}\n"
            f"  URL: {cfg.KB_LLM_BASE_URL}/v1/messages\n"
            f"  Model: {cfg.KB_MODEL}\n"
            f"  Check: KB_API_KEY correct? Does it have access to {cfg.KB_MODEL}?"
        ) from e


# ── Confidence footer ──────────────────────────────────────────────────────────

def format_confidence_footer(sources: list[dict]) -> str:
    """Build a markdown confidence footer from a sources list."""
    if not sources:
        return ""
    top   = sources[0]
    score = top.get("score", 0.0)
    name  = top.get("name", "unknown")
    if score >= 1.0:
        return f"\n\n---\n📄 **Source:** `{name}`"
    label = "High" if score >= 0.80 else ("Medium" if score >= 0.60 else "Low")
    extra = sources[1:3]
    extra_str = (" · " + " · ".join(f"`{s['name']}`" for s in extra)) if extra else ""
    return (
        f"\n\n---\n🎯 **Confidence:** {label} ({score:.2f})"
        f" — **Source:** `{name}`{extra_str}"
    )


# ── Core ask function ──────────────────────────────────────────────────────────

async def ask(
    question: str,
    folder_name: str,
    agent_name: str,
    system_prompt: str,
    conversation_history: list[dict] | None = None,
    top_n: int = 4,
    max_chars: int | None = None,
    pre_ranked_results: list[dict] | None = None,
    session_id: str = "default",
) -> AgentResult:
    """README-first async RAG pipeline for a single domain folder."""
    if max_chars is None:
        max_chars = _cb_get("rag_file")

    # ── Strategy 1: README-first ──────────────────────────────────────────────
    readme_context, source_label = await asyncio.to_thread(
        _get_readme_context, folder_name, question
    )

    if readme_context:
        if await is_passthrough():
            block = _build_passthrough_block(
                question=question,
                context=readme_context,
                system_prompt=system_prompt,
                agent_name=agent_name,
                source_label=source_label,
            )
            return AgentResult(
                agent=agent_name,
                answer=block,
                sources=[{"name": source_label, "path": f"{folder_name}/README", "score": 1.0}],
                found=True,
                passthrough=True,
                passthrough_block=block,
            )

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            messages.extend(conversation_history[-_cb_get("history"):])
        messages.append({
            "role": "user",
            "content": (
                f"Use the following knowledge base content to answer the question.\n\n"
                f"--- {source_label} ---\n{readme_context}\n---\n\n"
                f"Question: {question}"
            ),
        })

        answer = await call_llm(messages)
        readme_sources = [{"name": source_label, "path": f"{folder_name}/README", "score": 1.0}]
        return AgentResult(
            agent=agent_name,
            answer=answer,
            sources=readme_sources,
            confidence_footer=format_confidence_footer(readme_sources),
            found=True,
            passthrough=False,
        )

    # ── Strategy 2: Raw-file RAG fallback ────────────────────────────────────
    if pre_ranked_results is not None:
        results = pre_ranked_results
    else:
        from kb_agent_mcp.vector_store import search as _vs_search
        results = await _vs_search(folder_name, question, top_n=top_n)

    if not results:
        return AgentResult(
            agent=agent_name,
            answer=f"I could not find any relevant documents in '{folder_name}' to answer this question.",
            sources=[],
            found=False,
            passthrough=False,
        )

    # ── Security gate — classify each result file ─────────────────────────────
    # Files flagged as confidential are either redacted (gate not acknowledged)
    # or included with a 🔒 marker on the source label (gate acknowledged).
    gate_acknowledged = True
    if cfg.KB_SECURITY_GATE_ENABLED:
        from kb_agent_mcp.security_gate import is_gate_acknowledged
        gate_acknowledged = is_gate_acknowledged(session_id)

    def _is_confidential_file(file_path: Path) -> bool:
        if not cfg.KB_SECURITY_GATE_ENABLED:
            return False
        from kb_agent_mcp.security_gate import classify_confidential
        is_conf, _ = classify_confidential(file_path)
        return is_conf

    # Extract text from each result file concurrently
    context_blocks: list[str] = []
    sources: list[dict] = []
    extract_tasks = []
    valid_results = []
    redacted_names: list[str] = []

    for r in results:
        file_path = cfg.kb_root_path / r["path"]
        if not file_path.exists():
            continue
        is_conf = _is_confidential_file(file_path)
        if is_conf and not gate_acknowledged:
            # Gate not yet acknowledged — exclude this file entirely
            redacted_names.append(r["name"])
            continue
        extract_tasks.append(_extract_file(file_path, max_chars=max_chars))
        r_annotated = dict(r)
        if is_conf:
            r_annotated["confidential"] = True   # signals 🔒 prefix in footer
        valid_results.append(r_annotated)

    if not extract_tasks and not redacted_names:
        return AgentResult(
            agent=agent_name,
            answer=f"Found index entries for '{folder_name}' but source files are missing.",
            sources=[],
            found=False,
            passthrough=False,
        )

    if not extract_tasks and redacted_names:
        names = ", ".join(f"`{n}`" for n in redacted_names)
        return AgentResult(
            agent=agent_name,
            answer=(
                f"The most relevant file(s) for this question ({names}) are flagged as "
                "confidential and have been excluded.\n\n"
                "Call `check_confidential()` then `acknowledge_gate()` to include them."
            ),
            sources=[],
            found=True,
            passthrough=False,
        )

    texts = await asyncio.gather(*extract_tasks)
    context_was_truncated = False
    for r, text in zip(valid_results, texts):
        label = r["name"]
        if r.get("confidential"):
            label = f"🔒 {label}"
        context_blocks.append(
            f"--- Source: {label} (relevance: {r.get('score', 0):.2f}) ---\n{text}"
        )
        sources.append({
            "name":         label,
            "path":         r["path"],
            "score":        r.get("score", 0.0),
            "confidential": r.get("confidential", False),
        })
        if text.endswith("…"):
            context_was_truncated = True

    # Append a note when some files were redacted
    if redacted_names:
        redacted_note = (
            "\n\n> ⚠ Note: "
            + ", ".join(f"`{n}`" for n in redacted_names)
            + " were excluded (confidential — call `acknowledge_gate()` to include)."
        )
    else:
        redacted_note = ""

    context = "\n\n".join(context_blocks)

    if await is_passthrough():
        block = _build_passthrough_block(
            question=question,
            context=context,
            system_prompt=system_prompt,
            agent_name=agent_name,
            source_label=", ".join(s["name"] for s in sources[:3]),
        )
        return AgentResult(
            agent=agent_name,
            answer=block,
            sources=sources,
            found=True,
            passthrough=True,
            passthrough_block=block,
        )

    messages = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        messages.extend(conversation_history[-_cb_get("history"):])
    messages.append({
        "role": "user",
        "content": (
            f"Use the following documents to answer the question.\n\n"
            f"{context}\n\n"
            f"Question: {question}"
        ),
    })

    answer = await call_llm(messages)
    return AgentResult(
        agent=agent_name,
        answer=answer + redacted_note,
        sources=sources,
        confidence_footer=format_confidence_footer(sources),
        found=True,
        passthrough=False,
        truncated=context_was_truncated,
    )


# ── Passthrough block builder ──────────────────────────────────────────────────

_PASSTHROUGH_MARKER = "<<<KB_PASSTHROUGH>>>"
_PASSTHROUGH_END    = "<<<KB_PASSTHROUGH_END>>>"


def _build_passthrough_block(
    question: str,
    context: str,
    system_prompt: str,
    agent_name: str,
    source_label: str,
) -> str:
    """
    Build a structured passthrough block containing all retrieved context.

    The block is delimited by _PASSTHROUGH_MARKER / _PASSTHROUGH_END so the
    orchestrator can detect and unwrap it.  The SYSTEM_PROMPT and QUESTION
    fields are included so the unwrapper can emit explicit instructions to
    whatever host AI (Claude, GPT, Bob) receives the MCP response.
    """
    return (
        f"\n{_PASSTHROUGH_MARKER}\n"
        f"AGENT: {agent_name}\n"
        f"QUESTION: {question}\n"
        f"SOURCE: {source_label}\n"
        f"INSTRUCTION: Answer the QUESTION above using ONLY the CONTEXT below. "
        f"Cite the source file name. If the context does not contain the answer, "
        f"say so clearly — do not guess.\n"
        f"SYSTEM_PROMPT:\n{system_prompt}\n"
        f"---CONTEXT---\n{context}\n"
        f"{_PASSTHROUGH_END}\n"
    )
