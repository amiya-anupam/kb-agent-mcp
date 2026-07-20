#!/usr/bin/env python3
"""
agent_base.py — Shared base logic for all KnowledgeBase sub-agents
-------------------------------------------------------------------
Generated agents (agent_<folder>.py) are thin wrappers that set their
folder-specific config and delegate everything here.

Provides:
  - extract_full_text(file_path)  — multi-format text extractor
  - call_llm(messages)            — provider-agnostic LLM call
  - ask(question, folder, ...)    — README-first RAG pipeline

README-first pipeline:
  1. Find the folder's README (must contain <!-- KB:AUTO-INDEX:START --> block)
  2. For normal questions  → pass AUTO-INDEX block only (~500-2000 tokens)
  3. For complex questions → pass full README up to MAX_README_CHARS
  4. Fallback              → raw-file RAG if README is absent or too thin

LLM provider is driven entirely by env vars:
  KB_LLM_PROVIDER  ollama | openai | anthropic | custom | passthrough
  KB_LLM_BASE_URL  base endpoint
  KB_MODEL         model name
  KB_API_KEY       API key (openai / anthropic / custom)

Passthrough mode (KB_LLM_PROVIDER=passthrough, or auto-detected when no
LLM is reachable and KB_PASSTHROUGH_FALLBACK != "false"):
  Instead of calling a local LLM, the agent emits a structured
  <<<KB_PASSTHROUGH>>> block to stdout. Bob's Claude reads that block and
  answers directly — no local LLM required.
"""

import os
import re
import json
import pathlib
import sys

# ── Environment loader ────────────────────────────────────────────────────────

def _load_env():
    for candidate in [
        pathlib.Path(os.environ.get("KB_ROOT", "")) / ".env",
        pathlib.Path(__file__).parent.parent / ".env",
    ]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
            break

_load_env()

# ── Config (all from env) ─────────────────────────────────────────────────────

def _kb_root() -> pathlib.Path:
    raw = os.environ.get("KB_ROOT", "")
    if raw:
        return pathlib.Path(raw)
    return pathlib.Path(__file__).parent.parent

KB_ROOT      = _kb_root()
LLM_PROVIDER = os.environ.get("KB_LLM_PROVIDER", "ollama").lower()
LLM_BASE_URL = os.environ.get("KB_LLM_BASE_URL", "http://localhost:11434")
MODEL        = os.environ.get("KB_MODEL", "qwen3:14b")
API_KEY      = os.environ.get("KB_API_KEY", "")

# ── Passthrough helpers ───────────────────────────────────────────────────────

_PASSTHROUGH_MARKER = "<<<KB_PASSTHROUGH>>>"
_PASSTHROUGH_END    = "<<<KB_PASSTHROUGH_END>>>"

def _is_passthrough_mode() -> bool:
    """
    Return True when the agent should emit a passthrough block instead of
    calling a local LLM.

    Conditions (any of):
      1. KB_LLM_PROVIDER is explicitly set to "passthrough"
      2. KB_LLM_PROVIDER is "ollama" (default), no KB_API_KEY is set,
         and the Ollama endpoint is not reachable
         (auto-detection; can be disabled with KB_PASSTHROUGH_FALLBACK=false)
    """
    if LLM_PROVIDER == "passthrough":
        return True

    # Only auto-detect for the default Ollama provider when no API key is set
    if LLM_PROVIDER not in ("ollama",) or API_KEY:
        return False

    if os.environ.get("KB_PASSTHROUGH_FALLBACK", "true").lower() == "false":
        return False

    try:
        import httpx
        r = httpx.get(f"{LLM_BASE_URL}/api/tags", timeout=3.0)
        return r.status_code >= 400
    except Exception:
        return True  # unreachable → passthrough


# Evaluated once at import so sub-agents share the same decision
_PASSTHROUGH = _is_passthrough_mode()


def emit_passthrough(question: str, context: str, system_prompt: str,
                     agent_name: str, source_label: str) -> dict:
    """
    Print a structured passthrough block to stdout and return a sentinel dict.

    Bob's skill handler reads everything the script prints.  The block is
    human-readable so Bob's Claude can parse it without any special tooling:

        <<<KB_PASSTHROUGH>>>
        AGENT: <name>
        QUESTION: <question>
        SOURCE: <label>
        SYSTEM_PROMPT:
        <system prompt>
        ---CONTEXT---
        <retrieved context>
        <<<KB_PASSTHROUGH_END>>>

    Bob's Claude sees this output and answers the question using the context
    provided, then returns the answer to the user.
    """
    block = (
        f"\n{_PASSTHROUGH_MARKER}\n"
        f"AGENT: {agent_name}\n"
        f"QUESTION: {question}\n"
        f"SOURCE: {source_label}\n"
        f"SYSTEM_PROMPT:\n{system_prompt}\n"
        f"---CONTEXT---\n{context}\n"
        f"{_PASSTHROUGH_END}\n"
    )
    print(block, flush=True)
    return {
        "agent":   agent_name,
        "answer":  block,   # orchestrator treats this as the answer text
        "sources": [{"name": source_label, "path": source_label, "score": 1.0}],
        "found":   True,
        "passthrough": True,
    }

# README-first config
MARKER_START     = "<!-- KB:AUTO-INDEX:START -->"
MARKER_END       = "<!-- KB:AUTO-INDEX:END -->"
MAX_README_CHARS = int(os.environ.get("KB_MAX_README_CHARS", "40000"))
MIN_README_CHARS = 200   # README must have at least this many non-index chars to be used

# Keywords that indicate the user wants a detailed/full answer
_COMPLEX_QUESTION_PATTERNS = re.compile(
    r"\b(explain|detail|elaborate|compare|contrast|difference|how does|"
    r"walk me through|deep dive|in depth|comprehensive|full|everything about|"
    r"tell me about|describe|outline|overview of|breakdown|analysis of)\b",
    re.IGNORECASE,
)


# ── README helpers ────────────────────────────────────────────────────────────

def _find_readme(folder: pathlib.Path) -> pathlib.Path | None:
    """
    Locate the README for a knowledge folder using a priority cascade:
      1. Any .md whose name contains 'readme' (case-insensitive)
      2. <FolderName>.md  (standard name used by generate.py)
      3. Any .md file whose first 500 chars contain a Markdown heading (# …)
      4. The first .md file found (last resort)

    This makes README discovery fully dynamic — it works regardless of what
    the user named the file (e.g. 'ACE readme file.md', 'ACE Docs.md',
    'Jon Doe Analytics Overview.md', etc.).
    """
    try:
        md_files = [f for f in folder.iterdir()
                    if f.is_file() and f.suffix.lower() == ".md"]
    except Exception:
        return None

    if not md_files:
        return None

    # Priority 1: name contains "readme"
    for f in md_files:
        if "readme" in f.name.lower():
            return f

    # Priority 2: matches the folder name exactly (e.g. "ACE Docs.md")
    folder_name_md = folder.name + ".md"
    for f in md_files:
        if f.name == folder_name_md:
            return f

    # Priority 3: first .md whose content starts with a Markdown heading
    for f in md_files:
        try:
            head = f.read_text(encoding="utf-8", errors="ignore")[:500]
            if re.search(r"^#{1,3}\s+\S", head, re.MULTILINE):
                return f
        except Exception:
            continue

    # Priority 4: first .md file
    return md_files[0]


def _extract_auto_index_block(readme_text: str) -> str | None:
    """Extract text between AUTO-INDEX markers. Returns None if markers absent."""
    if MARKER_START not in readme_text or MARKER_END not in readme_text:
        return None
    start = readme_text.index(MARKER_START) + len(MARKER_START)
    end   = readme_text.index(MARKER_END)
    return readme_text[start:end].strip()


def _non_index_chars(readme_text: str) -> int:
    """Count characters in the README outside the AUTO-INDEX block."""
    if MARKER_START in readme_text and MARKER_END in readme_text:
        start = readme_text.index(MARKER_START)
        end   = readme_text.index(MARKER_END) + len(MARKER_END)
        outside = readme_text[:start] + readme_text[end:]
    else:
        outside = readme_text
    return len(outside.strip())


def _is_complex_question(question: str) -> bool:
    return bool(_COMPLEX_QUESTION_PATTERNS.search(question))


def _get_readme_context(folder_name: str, question: str) -> tuple[str | None, str]:
    """
    Return (context_text, source_label) for the README-first strategy.

    Returns (None, "") if README is absent or too thin — caller should
    fall back to raw-file RAG.
    """
    folder = KB_ROOT / folder_name
    readme = _find_readme(folder)

    if readme is None:
        return None, ""

    try:
        readme_text = readme.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None, ""

    # README must have meaningful hand-written content (not just the auto-index)
    if _non_index_chars(readme_text) < MIN_README_CHARS:
        return None, ""

    is_complex = _is_complex_question(question)

    if is_complex:
        # Pass the full README up to MAX_README_CHARS
        context = readme_text[:MAX_README_CHARS]
        label   = f"Full README ({readme.name})"
    else:
        # Try to use just the AUTO-INDEX block for efficiency
        auto_index = _extract_auto_index_block(readme_text)
        if auto_index:
            # For index-only context, prepend the non-index hand-written part
            # (limited to first 3000 chars) so the LLM has domain context too
            pre_index = readme_text[:readme_text.index(MARKER_START)].strip()
            context   = (pre_index[:3000] + "\n\n" + auto_index) if pre_index else auto_index
            label     = f"README index ({readme.name})"
        else:
            # README has no auto-index block yet — use full README
            context = readme_text[:MAX_README_CHARS]
            label   = f"Full README ({readme.name})"

    return context, label


# ── Full text extractor ───────────────────────────────────────────────────────

def extract_full_text(file_path: pathlib.Path, max_chars: int = 6000) -> str:
    """Extract as much useful text as possible from a file."""
    ext = file_path.suffix.lower()
    try:
        if ext in {".txt", ".md", ".csv"}:
            return file_path.read_text(encoding="utf-8", errors="ignore")[:max_chars]

        elif ext == ".docx":
            import zipfile, re as _re
            with zipfile.ZipFile(file_path) as z:
                with z.open("word/document.xml") as f:
                    xml = f.read().decode("utf-8", errors="ignore")
            text = _re.sub(r"<[^>]+>", " ", xml)
            return " ".join(text.split())[:max_chars]

        elif ext == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                text = ""
                for page in reader.pages:
                    text += (page.extract_text() or "") + "\n"
                    if len(text) >= max_chars:
                        break
                return text[:max_chars]
            except Exception as e:
                return f"[PDF read error: {e}]"

        elif ext in {".pptx", ".ppt"}:
            try:
                from pptx import Presentation
                prs = Presentation(str(file_path))
                text = ""
                for slide in prs.slides:
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            text += shape.text.strip() + "\n"
                    if len(text) >= max_chars:
                        break
                return text[:max_chars]
            except Exception as e:
                return f"[PPTX read error: {e}]"

        elif ext in {".xlsx", ".xls"}:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
                text = ""
                for sheet in wb.worksheets:
                    text += f"[Sheet: {sheet.title}]\n"
                    for row in sheet.iter_rows(max_row=200, values_only=True):
                        row_text = " | ".join(str(c) for c in row if c is not None)
                        if row_text.strip():
                            text += row_text + "\n"
                    if len(text) >= max_chars:
                        break
                return text[:max_chars]
            except Exception as e:
                return f"[XLSX read error: {e}]"

        elif ext == ".boxnote":
            try:
                data = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
                def walk(node):
                    if isinstance(node, dict):
                        if node.get("type") == "text":
                            yield node.get("text", "")
                        for v in node.values():
                            yield from walk(v)
                    elif isinstance(node, list):
                        for item in node:
                            yield from walk(item)
                return " ".join(walk(data))[:max_chars]
            except Exception as e:
                return f"[BoxNote read error: {e}]"

    except Exception as e:
        return f"[Read error: {e}]"

    return f"[Unsupported: {file_path.name}]"


# ── LLM call (provider-agnostic) ──────────────────────────────────────────────

def call_llm(messages: list[dict], temperature: float = 0.2) -> str:
    """
    Send messages to the configured LLM and return the response text.
    Supports: ollama | openai | anthropic | custom
    """
    if LLM_PROVIDER == "anthropic":
        return _call_anthropic(messages, temperature)

    if LLM_PROVIDER in ("openai", "custom"):
        return _call_openai_compat(messages, temperature)

    # Default: Ollama
    return _call_ollama(messages, temperature)


def _call_ollama(messages: list[dict], temperature: float) -> str:
    import httpx
    response = httpx.post(
        f"{LLM_BASE_URL}/api/chat",
        json={
            "model":    MODEL,
            "messages": messages,
            "stream":   False,
            "options":  {"temperature": temperature, "num_ctx": 32768},
            "think":    False,
        },
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()


def _call_openai_compat(messages: list[dict], temperature: float) -> str:
    import httpx
    base = LLM_BASE_URL.rstrip("/")
    if "11434" in base and not base.endswith("/v1"):
        base = f"{base}/v1"
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    response = httpx.post(
        f"{base}/chat/completions",
        headers=headers,
        json={
            "model":       MODEL,
            "messages":    messages,
            "temperature": temperature,
        },
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _call_anthropic(messages: list[dict], temperature: float) -> str:
    import httpx
    system      = ""
    chat_messages = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            chat_messages.append(m)

    headers = {
        "x-api-key":         API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
    }
    payload = {
        "model":       MODEL,
        "max_tokens":  4096,
        "temperature": temperature,
        "messages":    chat_messages,
    }
    if system:
        payload["system"] = system

    response = httpx.post(
        f"{LLM_BASE_URL}/v1/messages",
        headers=headers,
        json=payload,
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"].strip()


# ── Core ask function ─────────────────────────────────────────────────────────

def ask(
    question: str,
    folder_name: str,
    agent_name: str,
    system_prompt: str,
    conversation_history: list[dict] | None = None,
    top_n: int = 4,
    max_chars: int = 6000,
) -> dict:
    """
    README-first RAG pipeline for a single folder domain.

    Strategy:
      1. Try README-first: use the folder README as primary context
         - Normal questions  → AUTO-INDEX block + brief intro section
         - Complex questions → full README (up to MAX_README_CHARS chars)
      2. Fallback to raw-file RAG if README is absent or too thin (<200 chars
         of hand-written content outside the AUTO-INDEX block)

    Args:
        question:             The user's question
        folder_name:          KB folder to search (e.g. "ACE Docs")
        agent_name:           Display name for this agent
        system_prompt:        Domain-specific system prompt
        conversation_history: Optional prior messages for multi-turn context
        top_n:                Number of files to retrieve (fallback RAG only)
        max_chars:            Max chars to extract per file (fallback RAG only)

    Returns:
        { "agent", "answer", "sources", "found" }
    """
    # ── Strategy 1: README-first ──────────────────────────────────────────────
    readme_context, source_label = _get_readme_context(folder_name, question)

    if readme_context:
        is_complex = _is_complex_question(question)
        print(
            f"  [{agent_name}] README-first "
            f"({'full' if is_complex else 'index'} mode, "
            f"{len(readme_context):,} chars)"
        )

        # ── Passthrough: emit context for Bob's Claude to answer ──────────────
        if _PASSTHROUGH:
            print(f"  [{agent_name}] Passthrough mode — emitting context for Bob")
            return emit_passthrough(
                question     = question,
                context      = readme_context,
                system_prompt= system_prompt,
                agent_name   = agent_name,
                source_label = source_label,
            )

        messages = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            messages.extend(conversation_history[-6:])

        messages.append({
            "role": "user",
            "content": (
                f"Use the following knowledge base content to answer the question.\n\n"
                f"--- {source_label} ---\n{readme_context}\n---\n\n"
                f"Question: {question}"
            ),
        })

        answer = call_llm(messages)

        return {
            "agent":   agent_name,
            "answer":  answer,
            "sources": [{"name": source_label, "path": f"{folder_name}/README", "score": 1.0}],
            "found":   True,
        }

    # ── Strategy 2: Raw-file RAG fallback ────────────────────────────────────
    print(f"  [{agent_name}] Falling back to raw-file RAG (no usable README)")

    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from embeddings import search

    results = search(question, folder_name, top_n=top_n)

    if not results:
        return {
            "agent":   agent_name,
            "answer":  f"I could not find any relevant documents in {folder_name} to answer this question.",
            "sources": [],
            "found":   False,
        }

    context_blocks = []
    sources        = []
    for r in results:
        file_path = KB_ROOT / r["path"]
        if not file_path.exists():
            continue
        text = extract_full_text(file_path, max_chars=max_chars)
        context_blocks.append(
            f"--- Source: {r['name']} (relevance: {r['score']:.2f}) ---\n{text}"
        )
        sources.append({"name": r["name"], "path": r["path"], "score": r["score"]})

    if not sources:
        return {
            "agent":   agent_name,
            "answer":  f"Found index entries for {folder_name} but source files are missing.",
            "sources": [],
            "found":   False,
        }

    context = "\n\n".join(context_blocks)

    # ── Passthrough: emit context for Bob's Claude to answer ──────────────────
    if _PASSTHROUGH:
        print(f"  [{agent_name}] Passthrough mode — emitting context for Bob")
        return emit_passthrough(
            question      = question,
            context       = context,
            system_prompt = system_prompt,
            agent_name    = agent_name,
            source_label  = ", ".join(s["name"] for s in sources),
        )

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        messages.extend(conversation_history[-6:])

    messages.append({
        "role": "user",
        "content": (
            f"Use the following documents to answer the question.\n\n"
            f"{context}\n\n---\nQuestion: {question}"
        ),
    })

    answer = call_llm(messages)

    return {
        "agent":   agent_name,
        "answer":  answer,
        "sources": sources,
        "found":   True,
    }
