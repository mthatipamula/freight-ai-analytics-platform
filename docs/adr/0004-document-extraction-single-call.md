# 0004: Bills of lading: one structured-output call, not an agent

**Status:** Accepted

## Context
Bills of lading arrive as scans and phone photos. Errors (missing freight class, wrong weights, missing hazmat
emergency contact) cause re-rating, billing disputes and compliance risk.

## Decision
One Gemini 2.5 Flash call per document with a strict JSON schema (shipper, consignee, line items, class, weights,
hazmat, signature, legibility notes), temperature 0, then **deterministic Python rules** validate the result. Any
issue marks the document `NEEDS_REVIEW` for a person; clean documents are `READY`.

## Alternatives considered
| Option | Why not |
|---|---|
| An agent | The task has one input and one output; a loop adds cost, latency and variability without benefit |
| Let the model validate (e.g. "is the class valid?") | Rules that must be exact belong in code, where they are testable and auditable |
| Document AI only | Strong for OCR, classification and splitting multi-page scans, but freight-specific fields still need custom extraction; a good complement at higher volume |
| Traditional OCR + templates | Breaks on new layouts, handwriting and phone photos |

## Consequences
- About 8-10 seconds and under $0.01 per document.
- The model is told to return null rather than guess, and legibility notes become review items.
- A person approves anything doubtful: AI accelerates the work, it doesn't make the final call.
