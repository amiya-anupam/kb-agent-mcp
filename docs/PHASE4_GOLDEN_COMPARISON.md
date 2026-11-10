# Phase 4 — tiered retrieval: golden-set comparison

Task 4.4 of `IMPLEMENTATION_PLAN.html`. Compares the old path (`KB_CONTEXT_STORE=0`:
README-first, then Chroma/BM25) with the tiered path (`KB_CONTEXT_STORE=1`).

## Method

- Questions: `tests/golden_questions.json` — 13 questions (BizOps 7, ACE Docs 4,
  CP4I Docs 2), each with `expected_facts` taken from the KB content.
- Runner: `python3 scripts/golden_eval.py [--json out.json]`. By default it runs
  `DomainAgent.run()` in passthrough mode (no LLM), so the result is the context the model
  would receive. Flags: `--gate {off,blocked,ack}` (security gate disabled / enabled and
  unacknowledged / enabled and acknowledged), `--routing` (report routing accuracy),
  `--llm` (call the real model and score recall on the answer; chars are what was sent).
- **Recall** = fraction of `expected_facts` present in the returned context.
  **Chars** = size of that context.
- Decision rule: the new path must match or beat the old one on recall while using fewer
  context characters. Otherwise the default stays off.

## Result

| Metric | Flag off | Flag on |
|---|---|---|
| Recall (mean) | 0.231 | **1.000** |
| Avg context chars | 11,267 | **8,831** (−22%) |

| Question | Recall off | Recall on | Chars off | Chars on |
|---|---|---|---|---|
| `bz-part-vpc-perpetual` | 1.00 | 1.00 | 17,033 | 3,269 |
| `bz-part-linux-z` | 0.00 | 1.00 | 17,133 | 10,338 |
| `bz-part-monthly-nonprod` | 0.00 | 1.00 | 17,288 | 11,617 |
| `bz-renewal-rate-total` | 0.00 | 1.00 | 12,812 | 6,370 |
| `bz-renewal-rate-japan` | 0.00 | 1.00 | 15,012 | 11,274 |
| `bz-renewal-rate-product` | 0.00 | 1.00 | 17,237 | 17,160 |
| `bz-top-expiring-customer` | 1.00 | 1.00 | 12,856 | 17,627 |
| `ace-migration-waiver` | 0.50 | 1.00 | 6,718 | 1,806 |
| `ace-iib-support-end` | 0.00 | 1.00 | 6,727 | 6,552 |
| `ace-warm-standby` | 0.50 | 1.00 | 6,736 | 2,733 |
| `ace-program-number` | 0.00 | 1.00 | 6,737 | 11,539 |
| `cp4i-unified-mgmt-release` | 0.00 | 1.00 | 5,115 | 4,305 |
| `cp4i-agent` | 0.00 | 1.00 | 5,073 | 10,211 |

Recall is equal or better on every question. Context is smaller on average but **larger on
some questions** (`bz-top-expiring-customer`, `ace-program-number`, `cp4i-agent`), where the
matching digests are bigger than the chunks the old path returned.

## Decision

The tiered path matches or beats the old path on correctness and uses fewer characters on
average, so `KB_CONTEXT_STORE` now defaults to **on**. It is a no-op until a store exists
(`kb-agent context build`); set `KB_CONTEXT_STORE=0` to disable.

## Security gate

Same run, passthrough, recall / average chars (off → on):

| Gate | Recall | Avg chars |
|---|---|---|
| off (above) | 0.231 → 1.000 | 11,267 → 8,831 |
| enabled, not acknowledged (`blocked`) | 0.231 → **0.923** | 10,635 → 7,845 |
| enabled, acknowledged (`ack`) | 0.231 → **1.000** | 11,268 → 8,832 |

With the gate blocking, the only loss is `ace-program-number` (recall 0.00): the program-number
document is classified confidential and is redacted on the tiered path, as intended. After
`acknowledge_gate()` it is 1.000 again.

## Real-LLM run (`--llm --gate ack`, `qwen3:14b`)

Recall is scored on the model's answer. Avg chars is what `call_llm` received.

| Metric | Flag off | Flag on |
|---|---|---|
| Answer recall (mean) | 0.115 | **0.769** |
| Avg chars sent | 2,588 | 8,141 |

- ACE Docs and CP4I Docs (6 questions): recall 1.00 on for all but none missed; off was 0.00
  on 5 of 6.
- BizOps (7 questions): on is 1.00 on 4, and 0.00 on 3 (`bz-part-vpc-perpetual`,
  `bz-part-linux-z`, `bz-top-expiring-customer`).
- **Do not read the chars column as a cost comparison.** For 7 BizOps questions the old path
  sent 0 chars through `call_llm` (answered by another path or not at all), so its average is
  lower for that reason. The comparison that is valid is the passthrough one above.
- `bz-top-expiring-customer` regressed (1.00 → 0.00): the old path answered it without a
  tapped LLM call, the tiered path sent 16,936 chars and the model missed the fact. Not
  investigated further.
- `bz-part-vpc-perpetual` and `bz-part-linux-z` have the right context in passthrough
  (recall 1.00) but the model's answer misses it, so those are model-side, not retrieval.

## Routing (task 4.3)

Two changes. (1) Manifest keywords are used only when no configured keyword matched.
(2) `orchestrator.content_route()` ranks domains by their best-matching digest and wins over
the keyword router when that router is unsure, or is confident but shares no domain with the
content result (a greedy keyword like "CP4I"). See ARCHITECTURE.md.

| Metric (passthrough) | Flag off | Flag on |
|---|---|---|
| Top-1 correct | 7/13 | **12/13** |
| Right domain in matched set | 10/13 | **13/13** |
| Confident-correct | 1/13 | 2/13 |

Under the real LLM classifier: top-1 9/13 → 12/13, in set 9/13 → 13/13. Remaining miss:
`ace-program-number` routes to `[BizOps, ACE Docs]`, the right domain second.

## Caveats

- The original run disabled the security gate and used passthrough. Both are now covered
  above; the LLM run is only for `--gate ack`.
- 13 questions is a small sample, and the LLM run is one pass with one local model. Add
  questions to `tests/golden_questions.json` as real failures turn up.

---

<!-- KB:AUTO-INDEX:START -->

| File | Summary |
|---|---|
| `PHASE4_GOLDEN_COMPARISON.md` | The document evaluates tiered retrieval (KB_CONTEXT_STORE=1) against the old method (KB_CONTEXT_STORE=0) using 13 golden questions, showing higher recall and shorter context length when the security flag is enabled. |

<!-- KB:AUTO-INDEX:END -->
