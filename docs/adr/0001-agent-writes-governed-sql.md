# 0001: An agent writes SQL; code governs and runs it

**Status:** Accepted

## Context
Operations managers ask questions that dashboards don't answer, especially "why" questions that need several
queries (compare terminals, then delay reasons, then customers). Today these go to an analyst and take days.

## Decision
A Gemini agent with two tools, `run_sql` and `present_answer`, runs a loop of up to 8 steps: it writes a query,
reads the result, and decides whether to drill down or answer. **The model never connects to BigQuery.** It proposes
SQL; the backend checks it, runs it with its own credentials and limits, logs it, and returns the rows.

## Alternatives considered
| Option | Why not |
|---|---|
| More dashboards | Answer *what* but not *why*; every new question is a new dashboard |
| Single text-to-SQL call | Can't drill down or recover from an error; "why" questions need several queries |
| Give the model a database connection or MCP tool with direct access | No central place to enforce read-only, size limits and audit |
| Fixed query templates the model picks from | Safe but brittle: covers only anticipated questions |

## Consequences
- Answers in 15-60 seconds instead of days; every step and SQL is visible to the user.
- Blocked or failed queries go back to the model as tool results, so it corrects itself.
- Latency and cost scale with steps, so the step limit and a byte cap per query are required.
- Correctness depends on the model following definitions (see 0002) and is measured by the scorecard (0007).
