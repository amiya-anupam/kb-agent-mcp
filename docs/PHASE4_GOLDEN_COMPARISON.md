# Phase 4 — tiered retrieval: golden-set comparison

Task 4.4 of `IMPLEMENTATION_PLAN.html`. Compares the old path (`KB_CONTEXT_STORE=0`:
README-first, then Chroma/BM25) with the tiered path (`KB_CONTEXT_STORE=1`).

## Method

- Questions: `tests/golden_questions.json` — 13 questions (BizOps 7, ACE Docs 4,
  CP4I Docs 2), each with `expected_facts` taken from the KB content.
- Runner: `python3 scripts/golden_eval.py [--json out.json]`. It runs `DomainAgent.run()` in
  passthrough mode (no LLM), so the result is the context the model would receive.
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

## Routing (task 4.3)

Manifest keywords are used only when no configured keyword matches. On the golden set,
routing is identical with the flag on and off: top-1 correct 6/13, confident-correct 1/13,
right domain within the matched set 10/13. The three misses are BizOps questions where only
`CP4I Docs` matched on "CP4I" or "Cloud Pak". The golden questions never reach the manifest
fallback because the configured keywords always match something. The weakness is in the
existing keyword router and is outside Phase 4; a follow-up should tighten it.

## Caveats

- The eval disables the security gate (`KB_SECURITY_GATE_ENABLED=false`). Several of the
  source files are classified confidential; with the gate on and unacknowledged they are
  redacted on both paths.
- Passthrough mode measures retrieval only, not LLM answer quality.
- 13 questions is a small sample. Add questions to `tests/golden_questions.json` as real
  failures turn up.
