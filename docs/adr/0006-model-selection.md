# 0006: Gemini 2.5 Pro for the agent, Flash for documents

**Status:** Accepted

## Context
The agent needs multi-step reasoning: choosing queries, reading results and deciding what to check next.
Document extraction is a narrower task that runs many times a day.

## Decision
- **Gemini 2.5 Pro** for the analytics agent (temperature 0.1).
- **Gemini 2.5 Flash** for bill of lading extraction (temperature 0, strict schema).
- Models are set by configuration (`AGENT_MODEL`, `FAST_MODEL`), pinned to GA versions, and any change must pass the
  scorecard (0007) before release.

## Alternatives considered
| Option | Tradeoff |
|---|---|
| Flash for the agent | Cheaper and faster; worth testing against the scorecard, but "why" questions benefit from stronger reasoning |
| Preview models (e.g. Gemini 3) | Newer capabilities, but preview terms and changing behavior; evaluate with the scorecard before adopting |
| Third-party models | Possible through Vertex AI Model Garden; Gemini keeps everything inside Google Cloud with one set of controls |

## Consequences
- About $0.03 per question and under $0.01 per document at list prices.
- Quota errors (429) are handled with retry and backoff; steady production load would use provisioned throughput.
