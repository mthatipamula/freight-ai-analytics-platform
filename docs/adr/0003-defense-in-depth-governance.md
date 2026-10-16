# 0003: Governance in code and in the platform

**Status:** Accepted

## Context
An AI that writes SQL can be wrong, can be manipulated by prompt injection, or can ask for data it shouldn't see.
Prompt instructions alone are not a control.

## Decision
Layers that don't depend on the model behaving:
1. **Data:** the AI can only query curated views; raw tables with customer contact details are not reachable.
   In production these are authorized views plus policy tags and row-level access policies.
2. **Query checks (code):** one read-only SELECT, allowlisted views only (FROM/JOIN lists, comma joins and
   subqueries are parsed), no metadata tables.
3. **Cost:** BigQuery dry run before execution, refused above a byte cap, and the same cap set as
   `maximum_bytes_billed`; at most 500 rows returned to the model; at most 8 agent steps.
4. **Audit:** every attempt (allowed, blocked, error) logged with the question, SQL, bytes and rows.
5. **Identity:** the service account itself has read access only to the AI-facing dataset.

## Alternatives considered
| Option | Why not |
|---|---|
| Rely on the system prompt ("only use these views") | Prompt injection and model mistakes bypass it |
| Use BigQuery dry run's `referenced_tables` for the allowlist | It lists the base tables behind a view, so a valid view query looks like a raw-table query; the SQL must be parsed instead |
| Platform IAM only | Necessary but coarse; no per-query cost cap, row limit or app-level audit with the user's question |

## Consequences
- A model mistake or manipulation fails safely (blocked and logged) and the model is told why, so it can correct itself.
- The SQL parser must be maintained; it has unit tests including alias, EXTRACT and nested-subquery cases.
- The scorecard's safety cases (PII request, write attempt, prompt injection) check the whole chain end to end.
