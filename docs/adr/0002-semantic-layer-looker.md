# 0002: Semantic layer now in Python, Looker in production

**Status:** Accepted

## Context
Without agreed definitions, an AI can compute "on-time rate" differently from the dashboards (for example, include
in-transit shipments). Different numbers for the same metric destroy trust. Looker's LookML solves this, but Looker is
a licensed product that takes days to provision, which isn't possible for a prototype.

## Decision
- **Now:** `semantic.py` holds view descriptions, column meanings, one formula per metric and a glossary. It is put
  into the agent's instructions; Gemini writes SQL that follows it. The same content is shown on the Data catalog page.
- **Production:** point the agent at the Looker model. Gemini chooses measures, dimensions and filters; Looker
  generates the SQL (joins, GROUP BY, formulas) from LookML and runs it, applying Looker's user permissions.

## Alternatives considered
| Option | Why not (for now) |
|---|---|
| No semantic layer (schema only) | Model guesses formulas; numbers drift from dashboards |
| dbt metrics / other semantic layers | Valid, but Looker is the Google Cloud-native choice and matches the target environment |
| Looker from day one | Licensing and provisioning time; the design doesn't depend on it to be proven |

## Consequences
- Today the definitions are **guidance the model follows**, not enforcement. Mitigations: SQL is visible to users,
  and the scorecard checks that metric definitions were applied (e.g. on-time rate over delivered shipments only).
- With Looker the formula **can't drift**, and dashboards and AI always match. The tradeoff: the AI can only ask
  questions the LookML model supports, so governed SQL against authorized views stays as a fallback for
  investigations outside the model.
