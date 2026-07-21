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

Usage (single question — called by Bob skill or any AI agent):
  python3 agents/agent_knowledgebase.py "your question"

Usage (clear session memory):
  python3 agents/agent_knowledgebase.py --clear
"""

import sys
import json
import re
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from memory import get_history, add_turn, clear, summary
from agent_base import call_llm, _load_env, _PASSTHROUGH

_load_env()

# ── Config ─────────────────────────────────────────────────────────────────────

AGENT_NAME   = "KnowledgeBase Agent"
META_PATH    = pathlib.Path(__file__).parent / "vector_store" / "domain_meta.json"

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
            f"  Fix:  python3 generate.py --force",
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
    return list(meta.values())


# ── Fast keyword router ────────────────────────────────────────────────────────

def keyword_route(question: str, domains: list[dict]) -> list[str]:
    q = question.lower()
    return [
        d["folder_name"] for d in domains
        if any(kw.lower() in q for kw in d.get("keywords", []))
    ]


# ── LLM-based intent classifier ───────────────────────────────────────────────

def classify_intent(
    question: str,
    conversation_history: list[dict],
    domains: list[dict],
) -> dict:
    """Classify which domain(s) the question belongs to using the LLM."""
    if not domains:
        return {"domains": [], "needs_clarification": False, "clarification_question": ""}

    domain_descriptions = "\n".join(
        f'- "{d["folder_name"]}": {d.get("description", d["folder_name"])}'
        for d in domains
    )
    valid_domain_names = [d["folder_name"] for d in domains]
    fallback           = valid_domain_names[0] if valid_domain_names else ""

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


def call_sub_agent(domain: str, question: str, history: list[dict]) -> dict:
    """
    Dispatch a question to the handler for a single domain.

    Reads domain config from domain_meta.json and calls agent_base.ask()
    directly — no per-domain .py file required.
    """
    meta = load_domain_meta()
    domain_cfg = meta.get(domain)
    if not domain_cfg:
        return {
            "agent":   domain,
            "answer":  (
                f"Domain '{domain}' not found in domain_meta.json. "
                f"Run `python3 generate.py` to register new domains."
            ),
            "sources": [],
            "found":   False,
        }

    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from agent_base import ask as _base_ask

    return _base_ask(
        question             = question,
        folder_name          = domain_cfg["folder_name"],
        agent_name           = domain_cfg.get("agent_name", domain + " Agent"),
        system_prompt        = domain_cfg.get("system_prompt") or _build_system_prompt(domain_cfg),
        conversation_history = history,
        top_n                = domain_cfg.get("top_n", 4),
        max_chars            = domain_cfg.get("max_chars", 6000),
    )


def run_agents_parallel(
    domain_names: list[str],
    question: str,
    history: list[dict],
) -> list[dict]:
    if len(domain_names) == 1:
        return [call_sub_agent(domain_names[0], question, history)]

    results = []
    with ThreadPoolExecutor(max_workers=len(domain_names)) as executor:
        futures = {
            executor.submit(call_sub_agent, domain, question, history): domain
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
        sources_text = ""
        if r.get("sources"):
            sources_text = "\n\n---\n**Sources:** " + " · ".join(
                f"`{s['name']}`" for s in r["sources"][:3]
            )
        return r["answer"] + sources_text

    merged = []
    for r in found:
        sources_text = ""
        if r.get("sources"):
            sources_text = "\n*Sources: " + ", ".join(
                f"`{s['name']}`" for s in r["sources"][:2]
            ) + "*"
        merged.append(f"### From {r['agent']}\n\n{r['answer']}{sources_text}")
    return "\n\n---\n\n".join(merged)


# ── Main orchestrator ──────────────────────────────────────────────────────────

def ask_knowledgebase(question: str) -> str:
    """Full pipeline: classify → route → run sub-agents → merge → return answer."""
    domains  = get_domains()
    history  = get_history()

    if not domains:
        if META_PATH.exists():
            return (
                f"No knowledge domains found in domain_meta.json.\n"
                f"  Path: {META_PATH}\n"
                f"  The file may be empty or corrupt. Run:\n"
                f"    python3 generate.py --force"
            )
        return (
            f"domain_meta.json not found. Run `python3 generate.py` first to "
            f"discover folders and build the knowledge index.\n"
            f"  Expected at: {META_PATH}"
        )

    # Fast keyword pre-filter
    kw_domains = keyword_route(question, domains)

    # LLM classification
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

    results = run_agents_parallel(domain_names, question, history)
    for r in results:
        status = "✓ found" if r.get("found") else "✗ not found"
        print(f"[{r['agent']}] {status}")

    final_answer = merge_answers(results, domains)
    add_turn(question, final_answer)
    return final_answer


# ── Entry points ───────────────────────────────────────────────────────────────

def run_interactive():
    domains = get_domains()
    print(f"\n{'='*60}")
    print(f"  {AGENT_NAME}")
    if domains:
        print(f"  Domains: {', '.join(d['folder_name'] for d in domains)}")
    else:
        print(f"  ⚠ No domains found — run python3 generate.py first")
    print(f"  Type 'exit' · 'clear' to reset memory · 'memory' to show history")
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

        answer = ask_knowledgebase(question)
        print(f"\nKnowledgeBase Agent:\n{answer}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = " ".join(sys.argv[1:])
        if arg.strip() == "--clear":
            clear()
            sys.exit(0)
        if arg.strip() == "--memory":
            print(summary())
            sys.exit(0)
        print(ask_knowledgebase(arg))
    else:
        run_interactive()
