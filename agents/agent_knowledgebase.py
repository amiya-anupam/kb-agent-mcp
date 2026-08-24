#!/usr/bin/env python3
"""
agent_knowledgebase.py — KnowledgeBase Agent (Orchestrator)
-------------------------------------------------------------
Supervisor agent: routes questions to the correct domain handler,
runs domain handlers in parallel, and merges results.

Domain handlers are data-driven — config lives in domain_meta.json.
No per-domain .py files are needed. Adding a new knowledge folder
only requires running generate.py; no new code is generated.

Usage (interactive chat):
  python3 agents/agent_knowledgebase.py

Usage (interactive chat with a named session / workspace):
  python3 agents/agent_knowledgebase.py --session ace-renewal-review

Usage (single question — called by Bob skill or any AI agent):
  python3 agents/agent_knowledgebase.py "your question"

Usage (single question in a named session):
  python3 agents/agent_knowledgebase.py "your question" --session ace-renewal-review

Usage (single question with explicit format):
  python3 agents/agent_knowledgebase.py "your question" --format table
  python3 agents/agent_knowledgebase.py "your question" --format bullets
  python3 agents/agent_knowledgebase.py "your question" --format oneline
  python3 agents/agent_knowledgebase.py "your question" --format paragraph

  Natural-language intent phrases are also detected automatically:
    "give me a table", "as bullet points", "in one sentence", etc.

Usage (clear session memory):
  python3 agents/agent_knowledgebase.py --clear
  python3 agents/agent_knowledgebase.py --clear --session ace-renewal-review

Usage (list all named sessions):
  python3 agents/agent_knowledgebase.py --sessions
"""

import sys
import json
import re
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from memory import get_history, add_turn, clear, summary, set_session, list_sessions
from agent_base import call_llm, _load_env, _PASSTHROUGH, _apply_format_instruction

_load_env()

# ── Config ─────────────────────────────────────────────────────────────────────

AGENT_NAME   = "KnowledgeBase Agent"
META_PATH    = pathlib.Path(__file__).parent / "vector_store" / "domain_meta.json"
AUDIT_PATH   = pathlib.Path(__file__).parent.parent / ".kb_index" / "audit.jsonl"


# ── Startup drift check ───────────────────────────────────────────────────────

def _warn_if_drift() -> None:
    """
    Compare live file mtimes against the last audit.jsonl entry.
    Prints a one-line warning (stderr) when files were modified after the
    last index run. Silent when the index appears current or audit is absent.
    Non-fatal — never blocks the agent from answering.
    """
    try:
        import datetime as _dt

        if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size == 0:
            return  # no audit yet — generate.py hasn't been run, agent will warn separately

        lines = [l for l in AUDIT_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return
        last = json.loads(lines[-1])
        indexed_ts = last.get("ts", "")
        if not indexed_ts:
            return

        audit_dt = _dt.datetime.fromisoformat(indexed_ts)
        audit_ts = audit_dt.timestamp()

        _BLOCKLIST = {
            "agents", ".git", "__pycache__", ".ds_store", "node_modules",
            ".venv", "venv", "env", ".bob", ".idea", ".vscode", "dist", "build",
            ".kb_index", "kb_agent_mcp", "kb_agent_mcp.egg-info", "scripts", "tests",
        }
        _EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt",
                 ".csv", ".boxnote", ".ppt", ".doc", ".png", ".jpg", ".jpeg"}
        _SKIP = {"readme", ".ds_store", "~$"}

        kb_root   = AUDIT_PATH.parent.parent
        recent: list[str] = []
        for folder in sorted(kb_root.iterdir()):
            if not folder.is_dir() or folder.name.lower() in _BLOCKLIST:
                continue
            for f in folder.rglob("*"):
                if not f.is_file() or f.suffix.lower() not in _EXTS:
                    continue
                if any(p in f.name.lower() for p in _SKIP):
                    continue
                try:
                    if f.stat().st_mtime > audit_ts:
                        recent.append(f.name)
                except OSError:
                    continue

        if recent:
            n = len(recent)
            shown = ", ".join(recent[:3])
            ellipsis = f" + {n - 3} more" if n > 3 else ""
            print(
                f"[{AGENT_NAME}] ⚠  {n} file(s) modified since last index "
                f"({shown}{ellipsis}). "
                f"Run `python3 scripts/generate.py` or check drift with "
                f"`python3 scripts/ask.py --check-drift`.",
                file=sys.stderr,
                flush=True,
            )
    except Exception:
        pass  # drift check is best-effort — never crash the agent

# ── Domain meta loader ────────────────────────────────────────────────────────

def load_domain_meta() -> dict[str, dict]:
    """Load domain_meta.json. Returns empty dict if not yet generated."""
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(
            f"[KnowledgeBase Agent] ✗ domain_meta.json is corrupt (invalid JSON): {e}\n"
            f"  Path: {META_PATH}\n"
            f"  Fix:  python3 scripts/generate.py --force",
            flush=True,
        )
        return {}
    except Exception as e:
        print(
            f"[KnowledgeBase Agent] ✗ Could not read domain_meta.json: {e}\n"
            f"  Path: {META_PATH}",
            flush=True,
        )
        return {}


def get_domains() -> list[dict]:
    """Return list of domain dicts from domain_meta.json."""
    meta = load_domain_meta()
    domains = list(meta.values())
    if domains:
        _warn_if_drift()
    return domains


# ── Format intent detection ───────────────────────────────────────────────────

# Map each canonical format name to the instruction injected into the system prompt.
_FORMAT_INSTRUCTIONS: dict[str, str] = {
    "table":     "Format your entire answer as a Markdown table with clear column headers. "
                 "Do not use prose paragraphs — the response must be a table.",
    "bullets":   "Format your entire answer as a concise Markdown bullet list. "
                 "Use short, scannable bullet points. Do not use prose paragraphs.",
    "oneline":   "Answer in exactly ONE sentence. Be direct and specific. "
                 "Do not add any explanation, preamble, or follow-up.",
    "paragraph": "Write your answer as clear prose paragraphs. "
                 "Do not use bullet points or tables.",
    "numbered":  "Format your entire answer as a numbered Markdown list. "
                 "Each item should be a concise, self-contained point.",
    "json":      "Return your answer as valid JSON only. No markdown fences, no prose. "
                 "Choose a sensible structure (array of objects or flat object) for the content.",
}

# Natural-language phrases that map to a format name.
# Checked in order — first match wins.
_FORMAT_PHRASE_MAP: list[tuple[re.Pattern, str]] = [
    # table
    (re.compile(r"\b(as a table|in (a )?table (format|form)?|give me a table|show (it|that|results?) as a table)\b", re.IGNORECASE), "table"),
    # bullets
    (re.compile(r"\b(as bullet[- ]?points?|in bullet[- ]?points?|bullet[- ]?point (format|form|list)?|as a (bullet )?list)\b", re.IGNORECASE), "bullets"),
    # one line / one sentence
    (re.compile(r"\b(in one sentence|as one sentence|one[- ]liner|one[- ]line (answer|summary)?|in a single sentence|briefly in one sentence|give me (a )?(quick |short )?one[- ]?liner)\b", re.IGNORECASE), "oneline"),
    # numbered list
    (re.compile(r"\b(as a numbered list|in a numbered list|number (the |each )?(items?|points?|steps?))\b", re.IGNORECASE), "numbered"),
    # json
    (re.compile(r"\b(as (valid )?json|in json( format)?|return (as )?json)\b", re.IGNORECASE), "json"),
    # paragraph (explicit request — paragraphs are the default but allow explicit override)
    (re.compile(r"\b(as (prose )?paragraphs?|in paragraph (format|form)?)\b", re.IGNORECASE), "paragraph"),
]

# --format flag alias normalisation (accepts shorthands like "bullet", "1line", etc.)
_FORMAT_ALIASES: dict[str, str] = {
    "bullet":    "bullets",
    "bullet-points": "bullets",
    "list":      "bullets",
    "1line":     "oneline",
    "one-line":  "oneline",
    "one-liner": "oneline",
    "1liner":    "oneline",
    "prose":     "paragraph",
    "paragraphs": "paragraph",
    "num":       "numbered",
    "numbered-list": "numbered",
}


def detect_format_intent(question: str, explicit_flag: str | None = None) -> tuple[str, str]:
    """
    Detect the desired answer format from an explicit --format flag or
    natural-language phrases embedded in the question text.

    Returns:
        (clean_question, format_instruction)

    clean_question       — question with any intent phrases left intact
                           (they are part of the user's phrasing, not noise)
    format_instruction   — instruction string to append to the system prompt,
                           or "" when no format preference is detected.
    """
    # 1. Explicit --format flag takes highest priority
    if explicit_flag:
        key = explicit_flag.strip().lower()
        key = _FORMAT_ALIASES.get(key, key)
        instruction = _FORMAT_INSTRUCTIONS.get(key, "")
        if instruction:
            print(f"[KnowledgeBase Agent] Format: {key} (--format flag)")
        return question, instruction

    # 2. Scan question for natural-language intent phrases
    for pattern, fmt_key in _FORMAT_PHRASE_MAP:
        if pattern.search(question):
            instruction = _FORMAT_INSTRUCTIONS[fmt_key]
            print(f"[KnowledgeBase Agent] Format: {fmt_key} (detected from question)")
            return question, instruction

    return question, ""


# ── Fast keyword router ────────────────────────────────────────────────────────

def keyword_route(question: str, domains: list[dict]) -> list[str]:
    q = question.lower()
    return [
        d["folder_name"] for d in domains
        if any(kw.lower() in q for kw in d.get("keywords", []))
    ]


def _keyword_confidence(question: str, domains: list[dict]) -> tuple[list[str], bool]:
    """
    Return (matched_domain_names, is_confident).

    is_confident is True when keyword matching alone is sufficient to route:
      - exactly 1 domain matched AND it has ≥2 keyword hits, OR
      - one domain has ≥3× more keyword hits than any other matched domain
        (dominant match — e.g. BizOps:5 vs ACE Docs:1 for a multi-product
         revenue question where both product names appear in the query)

    When not confident, the LLM classifier is invoked to disambiguate.
    """
    q = question.lower()
    hit_counts: dict[str, int] = {}
    for d in domains:
        hits = sum(1 for kw in d.get("keywords", []) if kw.lower() in q)
        if hits > 0:
            hit_counts[d["folder_name"]] = hits

    matched = list(hit_counts.keys())

    if not matched:
        return matched, False

    # Confident: single domain with ≥2 hits
    if len(matched) == 1 and hit_counts[matched[0]] >= 2:
        return matched, True

    # Confident: one domain has ≥3× the hits of every other matched domain
    top_name  = max(hit_counts, key=hit_counts.__getitem__)
    top_hits  = hit_counts[top_name]
    others    = [v for k, v in hit_counts.items() if k != top_name]
    if top_hits >= 2 and others and top_hits >= 3 * max(others):
        return [top_name], True

    return matched, False


# ── LLM-based intent classifier ───────────────────────────────────────────────

def classify_intent(
    question: str,
    conversation_history: list[dict],
    domains: list[dict],
) -> dict:
    """Classify which domain(s) the question belongs to using the LLM."""
    if not domains:
        return {"domains": [], "needs_clarification": False, "clarification_question": ""}

    valid_domain_names = [d["folder_name"] for d in domains]
    fallback           = valid_domain_names[0] if valid_domain_names else ""

    # Build domain descriptions: include per-file summaries when available so
    # the router can match question content against actual file contents rather
    # than just folder-level keywords.
    domain_sections = []
    for d in domains:
        section = f'- "{d["folder_name"]}": {d.get("description", d["folder_name"])}'
        file_summaries = d.get("file_summaries", {})
        if file_summaries:
            # Include up to 10 file summaries, one per line, indented
            sample = list(file_summaries.items())[:10]
            summary_lines = "\n".join(
                f'    • {pathlib.Path(k).name}: {v[:120]}'
                for k, v in sample
            )
            section += f"\n  Files in this domain:\n{summary_lines}"
        domain_sections.append(section)

    domain_descriptions = "\n".join(domain_sections)

    system_prompt = (
        "You are a routing agent for a KnowledgeBase system with these domains:\n"
        f"{domain_descriptions}\n\n"
        "Respond ONLY with valid JSON:\n"
        '{\n  "domains": ["Domain Name"],\n'
        '  "needs_clarification": false,\n'
        '  "clarification_question": ""\n}\n\n'
        "Rules:\n"
        f"- domains must be one or more of: {', '.join(valid_domain_names)}\n"
        "- Set needs_clarification true only if the question is completely ambiguous\n"
        "- Return ONLY the JSON object"
    )

    messages = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        messages.extend(conversation_history[-4:])
    messages.append({"role": "user", "content": question})

    # In passthrough mode the LLM is unavailable — skip to keyword fallback
    if _PASSTHROUGH:
        kw = keyword_route(question, domains)
        return {
            "domains":                kw or ([fallback] if fallback else []),
            "needs_clarification":    False,
            "clarification_question": "",
        }

    try:
        raw   = call_llm(messages, temperature=0.0)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        result = json.loads(match.group()) if match else {}

        valid_set     = set(valid_domain_names)
        domains_found = [d for d in result.get("domains", []) if d in valid_set]
        return {
            "domains":                domains_found or [fallback],
            "needs_clarification":    result.get("needs_clarification", False),
            "clarification_question": result.get("clarification_question", ""),
        }
    except Exception:
        kw = keyword_route(question, domains)
        return {
            "domains":                kw or ([fallback] if fallback else []),
            "needs_clarification":    False,
            "clarification_question": "",
        }


# ── Sub-agent dispatcher ───────────────────────────────────────────────────────
# Domain config lives in domain_meta.json — no per-domain .py files needed.
# call_sub_agent() reads the domain's config and calls agent_base.ask() directly.

def _build_system_prompt(domain_meta: dict) -> str:
    """Build the system prompt for a domain from its domain_meta.json entry."""
    name  = domain_meta.get("agent_name",  domain_meta["folder_name"] + " Agent")
    fname = domain_meta["folder_name"]
    desc  = domain_meta.get("description", f"Knowledge domain: {fname}")
    return (
        f"You are the {name}, a specialist in the {fname} knowledge domain.\n"
        f"Domain description: {desc}\n"
        f"You answer questions strictly based on the provided document context.\n"
        f"Be concise, accurate, and cite which document your answer came from.\n"
        f"If the answer is not in the provided context, say so clearly — do not guess.\n"
        f"Format your answer in clean markdown."
    )


def call_sub_agent(
    domain: str,
    question: str,
    history: list[dict],
    format_instruction: str = "",
) -> dict:
    """
    Dispatch a question to the handler for a single domain.

    Reads domain config from domain_meta.json and calls agent_base.ask()
    directly — no per-domain .py file required.

    Args:
        domain:             Domain folder name to query.
        question:           The user's question.
        history:            Conversation history for multi-turn context.
        format_instruction: Optional format directive injected into the
                            system prompt (from detect_format_intent).
    """
    meta = load_domain_meta()
    domain_cfg = meta.get(domain)
    if not domain_cfg:
        return {
            "agent":   domain,
            "answer":  (
                f"Domain '{domain}' not found in domain_meta.json. "
                f"Run `python3 scripts/generate.py` to register new domains."
            ),
            "sources": [],
            "found":   False,
        }

    agents_dir = pathlib.Path(__file__).parent
    sys.path.insert(0, str(agents_dir))

    safe       = domain_cfg.get("safe_name") or re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")
    agent_file = agents_dir / f"agent_{safe}.py"

    # ── Prefer the per-domain agent file when it exists ───────────────────────
    # Each agents/agent_<safe>.py is generated by scripts/generate.py and
    # carries domain-specific retrieval logic (e.g. BizOps pins Revenue files).
    # Fall back to the shared agent_base.ask() for domains without a file.
    if agent_file.exists():
        import importlib.util as _ilu
        spec   = _ilu.spec_from_file_location(f"agent_{safe}", agent_file)
        module = _ilu.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.domain_ask(
            question          = question,
            history           = history,
            format_instruction= format_instruction,
        )

    # Fallback: no per-domain file — use shared base ask()
    from agent_base import ask as _base_ask

    base_prompt  = domain_cfg.get("system_prompt") or _build_system_prompt(domain_cfg)
    final_prompt = _apply_format_instruction(base_prompt, format_instruction)

    return _base_ask(
        question             = question,
        folder_name          = domain_cfg["folder_name"],
        agent_name           = domain_cfg.get("agent_name", domain + " Agent"),
        system_prompt        = final_prompt,
        conversation_history = history,
        top_n                = domain_cfg.get("top_n", 4),
        max_chars            = domain_cfg.get("max_chars", 6000),
    )


def run_agents_parallel(
    domain_names: list[str],
    question: str,
    history: list[dict],
    format_instruction: str = "",
) -> list[dict]:
    if len(domain_names) == 1:
        return [call_sub_agent(domain_names[0], question, history, format_instruction)]

    results = []
    with ThreadPoolExecutor(max_workers=len(domain_names)) as executor:
        futures = {
            executor.submit(call_sub_agent, domain, question, history, format_instruction): domain
            for domain in domain_names
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                domain = futures[future]
                results.append({
                    "agent": domain, "answer": f"Error: {e}",
                    "sources": [], "found": False,
                })
    return results


# ── Answer merger ──────────────────────────────────────────────────────────────

def merge_answers(results: list[dict], domains: list[dict]) -> str:
    found = [r for r in results if r.get("found")]

    if not found:
        domain_hints = "\n".join(
            f"  - {d['folder_name']}: {d.get('description', '')}"
            for d in domains
        )
        return (
            "I couldn't find relevant information to answer your question.\n\n"
            "Try rephrasing, or add more context. Available domains:\n"
            + domain_hints
        )

    # Passthrough results: the <<<KB_PASSTHROUGH>>> blocks are already printed
    # to stdout by each sub-agent. Just concatenate them — Bob's Claude will
    # read the entire stdout and answer using all the context blocks.
    if any(r.get("passthrough") for r in found):
        return "".join(r["answer"] for r in found if r.get("passthrough"))

    if len(found) == 1:
        r = found[0]
        footer = r.get("confidence_footer") or ""
        return r["answer"] + footer

    merged = []
    for r in found:
        footer = r.get("confidence_footer") or ""
        merged.append(f"### From {r['agent']}\n\n{r['answer']}{footer}")
    return "\n\n---\n\n".join(merged)


# ── Main orchestrator ──────────────────────────────────────────────────────────

def ask_knowledgebase(question: str, format_flag: str | None = None) -> str:
    """
    Full pipeline: detect format → classify → route → run sub-agents → merge → return answer.

    Args:
        question:    The user's question (may contain natural-language format phrases).
        format_flag: Explicit format name from --format CLI flag, or None.
                     Supported values: table | bullets | oneline | paragraph | numbered | json
                     (and their aliases).  Natural-language detection always runs in parallel
                     and is used when format_flag is None.
    """
    domains  = get_domains()
    history  = get_history()

    if not domains:
        if META_PATH.exists():
            return (
                f"No knowledge domains found in domain_meta.json.\n"
                f"  Path: {META_PATH}\n"
                f"  The file may be empty or corrupt. Run:\n"
                f"    python3 scripts/generate.py --force"
            )
        return (
            f"domain_meta.json not found. Run `python3 scripts/generate.py` first to "
            f"discover folders and build the knowledge index.\n"
            f"  Expected at: {META_PATH}"
        )

    # Detect format intent (explicit flag takes priority over phrase detection)
    question, format_instruction = detect_format_intent(question, explicit_flag=format_flag)

    # Fast keyword pre-filter — skip the LLM routing call when confident
    kw_domains, kw_confident = _keyword_confidence(question, domains)

    if kw_confident:
        # Single domain, ≥2 keyword hits — no LLM call needed
        domain_names = kw_domains
        print(f"\n[{AGENT_NAME}] Keyword routing (confident, skipping LLM): {domain_names[0]}")
    else:
        # Ambiguous or zero keyword matches — invoke LLM classifier
        classification = classify_intent(question, history, domains)
        domain_names   = classification["domains"] or kw_domains or [domains[0]["folder_name"]]

        # Needs clarification?
        if classification.get("needs_clarification") and classification.get("clarification_question"):
            cq = classification["clarification_question"]
            add_turn(question, cq)
            return cq

    print(f"\n[{AGENT_NAME}] Routing to: {', '.join(domain_names)}")
    if len(domain_names) > 1:
        print(f"[{AGENT_NAME}] Running {len(domain_names)} agents in parallel...")

    results = run_agents_parallel(domain_names, question, history, format_instruction)
    for r in results:
        status = "✓ found" if r.get("found") else "✗ not found"
        print(f"[{r['agent']}] {status}")

    final_answer = merge_answers(results, domains)
    add_turn(question, final_answer)
    return final_answer


# ── Entry points ───────────────────────────────────────────────────────────────

def run_interactive(session_name: str = "default"):
    if session_name and session_name != "default":
        set_session(session_name)
    domains = get_domains()
    print(f"\n{'='*60}")
    print(f"  {AGENT_NAME}")
    if domains:
        print(f"  Domains: {', '.join(d['folder_name'] for d in domains)}")
    else:
        print(f"  ⚠ No domains found — run python3 scripts/generate.py first")
    print(f"  Type 'exit' · 'clear' to reset memory · 'memory' to show history")
    print(f"  Tip: prefix your question with --format <table|bullets|oneline|paragraph|numbered|json>")
    print(f"{'='*60}")
    print(f"  {summary()}\n")

    while True:
        try:
            question = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit", "bye"}:
            print("Goodbye.")
            break
        if question.lower() == "clear":
            clear()
            continue
        if question.lower() == "memory":
            print(summary())
            continue

        # Allow inline --format flag in interactive mode: "What is ACE? --format table"
        fmt_flag = None
        fmt_match = re.search(r"--format\s+(\S+)", question, re.IGNORECASE)
        if fmt_match:
            fmt_flag = fmt_match.group(1)
            question = question[:fmt_match.start()].strip() + question[fmt_match.end():].strip()
            question = question.strip()

        answer = ask_knowledgebase(question, format_flag=fmt_flag)
        print(f"\nKnowledgeBase Agent:\n{answer}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Parse --format, --session, --clear, --memory, --sessions flags from CLI args
        args        = sys.argv[1:]
        fmt_flag    = None
        session_arg = None
        clean_args  = []
        i = 0
        while i < len(args):
            if args[i] == "--format" and i + 1 < len(args):
                fmt_flag = args[i + 1]
                i += 2
            elif args[i].startswith("--format="):
                fmt_flag = args[i].split("=", 1)[1]
                i += 1
            elif args[i] == "--session" and i + 1 < len(args):
                session_arg = args[i + 1]
                i += 2
            elif args[i].startswith("--session="):
                session_arg = args[i].split("=", 1)[1]
                i += 1
            else:
                clean_args.append(args[i])
                i += 1

        # Apply named session before any memory operation
        if session_arg:
            set_session(session_arg)

        arg = " ".join(clean_args)

        if arg.strip() == "--clear":
            clear()
            sys.exit(0)
        if arg.strip() == "--memory":
            print(summary())
            sys.exit(0)
        if arg.strip() == "--sessions":
            rows = list_sessions()
            if not rows:
                print("No sessions found.")
            else:
                print(f"{'Session':<30}  {'Turns':>5}  {'Last active':>12}  Status")
                print("-" * 60)
                for s in rows:
                    la = int((time.time() - s["last_active"]) // 60)
                    la_str = f"{la}m ago" if la < 60 else f"{la // 60}h ago"
                    status = "expired" if s["expired"] else "active"
                    print(f"{s['session_id']:<30}  {s['turns']:>5}  {la_str:>12}  {status}")
            sys.exit(0)
        if not arg.strip():
            # No question provided — enter interactive mode
            run_interactive(session_arg or "default")
        else:
            print(ask_knowledgebase(arg, format_flag=fmt_flag))
    else:
        run_interactive()
