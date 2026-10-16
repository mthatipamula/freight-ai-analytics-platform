# 0007: Evaluation scorecard with expected answers computed at run time

**Status:** Accepted

## Context
The first question leaders ask about AI answers is "how do we know it's right?" Manual spot checks don't scale and
don't catch regressions when a prompt, a metric definition or a model version changes.

## Decision
A scorecard of 14 questions in three groups, run with `./scripts/dev.sh eval` and shown on the Governance page:
- **Accuracy:** does the answer name the right terminal, customer, hub or trailer?
- **Metric definitions:** do numbers match, and did the SQL apply the semantic layer's definition (e.g. on-time rate
  over delivered shipments only)?
- **Safety:** a PII request, a write attempt and a prompt-injection attempt must be refused or blocked.

Expected answers are computed with **fixed, hand-written SQL at run time**, so the scorecard stays valid when data
changes. Each result records pass/fail per check, latency, queries, tokens and cost, and is saved to
`ai_eval_results` in BigQuery.

## Alternatives considered
| Option | Why not |
|---|---|
| Hard-coded expected answers | Break whenever data refreshes |
| LLM-as-judge only | Useful for tone and completeness, but facts and numbers are checked more reliably with code |
| No evaluation, rely on users | Errors are found in production, after trust is lost |

## Consequences
- Runs in a few minutes for about $0.40. In CI/CD it gates prompt, model and semantic-layer changes.
- The first run surfaced two real issues: grader checks that were too literal (fixed) and Vertex AI quota errors
  under parallel load (retry with backoff added to the agent).
- The set should grow from real user questions, especially ones that were answered wrong.
