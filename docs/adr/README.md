# Architecture decision records

Short records of the main design decisions: the context, what was decided, the alternatives, and the tradeoffs.

| # | Decision | Status |
|---|---|---|
| [0001](0001-agent-writes-governed-sql.md) | An agent writes SQL; code governs and runs it | Accepted |
| [0002](0002-semantic-layer-looker.md) | Semantic layer now in Python, Looker in production | Accepted |
| [0003](0003-defense-in-depth-governance.md) | Governance in code and in the platform | Accepted |
| [0004](0004-document-extraction-single-call.md) | Bills of lading: one structured-output call, not an agent | Accepted |
| [0005](0005-telematics-in-bigquery.md) | Trailer telematics in BigQuery, Bigtable only if needed | Accepted |
| [0006](0006-model-selection.md) | Gemini 2.5 Pro for the agent, Flash for documents | Accepted |
| [0007](0007-evaluation-scorecard.md) | Evaluation scorecard with expected answers computed at run time | Accepted |
