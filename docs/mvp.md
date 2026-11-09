# MVP operation and release limits

Pro-One is a local development system for source-grounded legal research and structured procedural help. Users can ask a question, describe facts or add a redacted document. The server identifies candidate matter information, selects a bounded source collection, assembles evidence and validates a proposed answer. Specialized workflows provide structured intake when appropriate. Private-beta acceptance remains pending.

## Current coverage

- Virginia DC-402 small-claims defendant information: proposed; appearance wording, universal written-answer support, local practice, and old instruction currentness remain unresolved.
- Virginia SCC business records/status navigation: proposed official-resource navigation only. No actual entity lookup, compliance/status conclusion, filing, registration deadline, fee, or reinstatement advice.
- Maryland District Court civil-summons orientation: proposed ordinary civil money-claim document navigation. No high-consequence matters, calculated deadline, service/venue conclusion, or response strategy.

All real records and reviews remain proposed. Research checks on official pages are not legal review or currentness certification. The five older fictional workflows are excluded from product coverage.

## Modes and configuration

Development mode permits proposed research and workflow inspection through the clearly labeled offline test adapter or configured OpenAI/Anthropic adapters. The server owns provider/model allowlists and credentials. The consumer UI presents the question-and-document flow. Offline examples identify their fixture origin.

Production mode omits the testing provider, suppresses development inspection endpoints, and refuses unapproved workflow generation before calling any model. Health, coverage, safe model status, routing, scope, and OpenAPI remain available. All current workflows fail the public gates. A functioning production container is not public beta approval.

## Safety and privacy

Exact structured routing confirms specification fit only, never legal jurisdiction or merits. Missing distinguishing data narrows or stops the flow; contradictory intake cannot override scope. Caller generation.scope is compatibility metadata, not authority. Unsupported matters receive no generic LLM response.

Only sanitized facts and selected evidence/constraints reach providers. Structured drafts must pass strict local validation; rendering revalidates and uses canonical citation metadata. Rejected text and private provider errors are never displayed. Controls include exact fact repetition, required rendered disclosures/limitations/notices, relationship checks, and supplementary prose guards. The guards do not establish arbitrary prose-level factual/legal correctness or perfect injection resistance.

The browser holds signed conversation state in memory with one-hour expiry. A separate SQLite corpus stores public legal material and provenance. Configured CourtListener and fixed official-source adapters can retrieve legal material. Host-level access controls and provider privacy review remain required. Privacy filtering has limited coverage for sensitive data in free text.

Uploaded documents with recognizable headings have a separate development inspection path. It identifies a possible document type, states the uncertainty and displays a labeled excerpt of up to 600 characters. Allegations, advocacy, proposed orders and apparent orders retain their distinct caveats. The excerpt is user-provided text and receives no authority citation. Existing DC-402 and other recognized procedural intake remains available. This feature identifies cues and quotes text. It does not determine a document's legal effect.

## Evaluation and operation

The evaluation runner currently executes 37 mapped workflow and research fixtures, with four fictional fixtures unmapped. It supports all/workflow/fixture modes. Required unmapped or stale fixtures fail. Declared automated checks remain separate from manual narrative expectations and release approval.

Cross-model benchmarking reuses the same assembled package across configured providers and reports status, deterministic validation, latency, usage, draft hashes, and pending/manual semantic dimensions. Manual scores are bound to exact drafts and cannot override deterministic rejection. No model judge grants approval. Standard CI uses no live credentials.

The container uses Python 3.12, runtime dependencies only, a non-root user, PORT-aware Uvicorn startup, and a health check. Deployment is provider-neutral OCI hosting with environment injection and host TLS. No paid resource is provisioned. See the root README for setup and commands.

Before public beta, complete legal/source/rights/currentness and fixture approvals, real-model semantic/privacy evaluation, production configuration verification, and host-level abuse controls/monitoring. Optional saved history, additional jurisdictions, and further polish remain product choices rather than blockers to local use.
