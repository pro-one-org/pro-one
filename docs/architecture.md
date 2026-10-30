# Architecture

Pro-One is currently an architecture and specification foundation for a future workflow-first legal AI system rather than a general-purpose legal chatbot. No production pipeline or publicly supported workflow exists today.

The system should help self-represented users and small businesses understand legal processes, organize their facts, and complete common legal tasks using structured workflows, retrieval from approved legal sources, and AI-generated explanations that cite their supporting material.

## Design goals

Pro-One should be:

- **Source-grounded:** Answers should be based on retrieved legal material.
- **Jurisdiction-aware:** The system should identify the relevant jurisdiction before answering.
- **Workflow-first:** Features should be tied to concrete legal tasks such as responding to a complaint, understanding court steps, or organizing a contract dispute.
- **Transparent:** Users should see sources, limitations, and confidence signals.
- **Cautious:** When the system cannot find adequate support, it should say so.
- **Accessible:** Legal information should be written in clear language.
- **Free and open:** Core access should remain free, and the software should be open for inspection, contribution, and reuse.

## Specification foundation

The repository defines ten interoperable record domains: sources, workflows, process steps, legal documents, intakes, legal rules, risks, response patterns, evaluation fixtures, and curated source passages. `schemas/common.schema.json` centralizes record identifiers, version metadata, known jurisdiction structures, maturity and review states, review provenance, harm severity, urgency, support modes, routing behavior, human-help framing, and deadline handling where the concepts are semantically shared.

Country values use uppercase ISO 3166-1 alpha-2 codes across every domain—for example, `US` rather than a display name. User interfaces may localize those codes for display without changing stored records.

All domain records include `schema_version`, `record_version`, and `last_modified`. Review objects distinguish reviewer identity or handle, reviewer role, review scope, review date, and the exact record version reviewed. A reviewer role is a project capacity and does not assert professional credentials.

The records include fictional examples and proposed Virginia research. Schema validity establishes structural conformance only; it does not make a record accurate, reviewed, approved, supported, or legally appropriate.

## Current deterministic local runtime

```text
structured answers + explicit risk IDs
  -> RecordRepository.resolve_workflow()
  -> single applicable intake definition (fail on none/multiple)
  -> required/optional completeness + key-based privacy filtering
  -> explicit linked-risk resolution + canonical routing
  -> WorkflowReadinessService.evaluate()
  -> package integrity checks + development context assembly
  -> separate public eligibility result (no execution or answer generation)
```

`app/intake.py` uses workflow input identifiers and intake privacy metadata without interpreting answer text or inferring facts. `app/execution.py` consumes that assessment and the existing readiness result. It verifies required package references without importing additional records, then returns detached, deterministic metadata from the existing resolver. Partial facts may appear in inspection contexts; excluded, restricted, and unrecognized values do not. User facts retain their exact value and explicit user-provided provenance. Repository jurisdiction metadata never confirms the user's jurisdiction.

The stateless `POST /workflows/{workflow_id}/intake/evaluate` endpoint returns completeness, privacy handling, all explicit risk routes, context availability, and public eligibility separately. Public eligibility requires complete and acceptable input, resolved required package references, and the readiness gate. An available context alone is not permission to generate or publicly execute anything. Source records contain metadata only; evaluation scenarios are omitted from context. Intake makes no model call and persists/logs no values. See the [request and response contract](../README.md#structured-intake-and-development-context).

The separate `POST /workflows/{workflow_id}/retrieval` service resolves that same workflow package and its local `source_passages`, validates filters, selects eligible sources/jurisdiction, and optionally ranks candidates by deterministic lexical overlap. `app/corpus.py` shares passage relationship/hash checks between repository startup and repository validation. Source metadata stays in source records; short excerpts, locators, topic tags, verification provenance, and limits live in `data/source-passages.json`.

Retrieval returns an inspection package joined to an execution context by `workflow_id`. It calls the existing readiness service and never grants public execution. Intake/execution logic is unchanged; proposed excerpts are not automatically copied into its fact context. Retrieval performs no runtime network/model calls or generation. See [Source corpus](source-corpus.md) for selection, ranking, maturity, and freshness behavior.

`app/grounding.py` now evaluates the actual selected evidence and its linked sources, legal rules, process steps, response patterns, and active risks. It calls workflow readiness independently rather than adding optional passages to the workflow readiness gate. Existing review scopes are shared with repository validation through `app/review_policy.py`. Public grounding additionally requires explicit version-bound currentness certification; absence, expiry, unresolved issues, unsupported/rejected material, invalid links, and applicable unresolved propositions block release.

`app/response_assembly.py` composes execution, retrieval, and grounding in `POST /workflows/{workflow_id}/response/assemble`. It builds citation-backed proposition references and response constraints, not prose. Repository-configured support gaps can withhold topic claims without interpreting source language. Its public conjunction is input eligibility AND workflow readiness AND grounding eligibility AND package integrity; development availability is separate. See [Grounded response assembly](grounded-response-assembly.md) for the release date policy and claim boundaries.

`app/generation.py` consumes this assembly through a provider-neutral contract in `app/models/base.py`. `generation_contract.py` projects only sanitized facts, allowed topics and selected evidence, citations, and enforcement constraints; source/fact data are separate from versioned instructions. A registry resolves explicit provider/model configuration with no fallback. Only an offline extractive testing adapter is registered. A caller's unconfirmed scope or missing required inputs narrows output to supplied controls; explicit outside scope prevents a call. Model requests have no tools, source access, or workflow/review mutation capability.

`app/output_validation.py` treats structured output as untrusted and validates every successful adapter result before acceptance. Strict Pydantic draft models, contextual IDs, canonical relationships, exact control/fact channels, disclosure/limitation rendering, and supplementary prose guards produce stable errors. The service makes one bounded attempt and returns no rejected draft text. Semantic legal/factual verification is not claimed, and public generation is disabled even for a structurally accepted draft. `app/evaluation.py` runs version-bound mappings of existing fixtures with explicit automated checks and pending manual criteria; CI uses no credentials or live model. See [Model generation and evaluation](model-generation.md) for the contracts and limitations.

## Intended pipeline

```text
user need
  -> intake
  -> jurisdiction and workflow identification
  -> approved sources
  -> source-backed legal rules and process steps
  -> risk controls
  -> response pattern
  -> citations and limitations
  -> evaluation
```

This diagram is an intended architecture. It is not running in production.

## First MVP direction

The first MVP should focus on one narrow legal workflow rather than broad legal coverage.

A strong first workflow is helping a self-represented civil litigant understand and prepare a basic answer to a civil complaint in one jurisdiction.

This keeps the project focused on a real procedural need while allowing a future implementation to demonstrate intake, jurisdiction awareness, retrieval, citations, plain-language explanations, user-confirmed draft structure, and safe refusal behavior. The system may explain sourced response categories and organize explicit user decisions, but it must not choose admissions, denials, defenses, objections, facts, or litigation strategy.

## Long-term direction

Over time, Pro-One may expand into additional legal workflows for self-represented users and small businesses, including:

- understanding court papers
- preparing basic responses
- tracking litigation steps
- organizing deadlines
- understanding contract disputes
- preparing demand letters
- reviewing common contract terms
- organizing facts, documents, and correspondence

Each expansion should preserve the same standard: narrow scope, reliable sources, citations, clear limitations, and user control.

## Components

### 1. Intake

The intake layer receives the user's question, document, or task description.

Future intake should capture:

- the user's jurisdiction, if known
- the legal topic
- the task the user is trying to complete
- whether the user is asking for general information, document help, or procedural guidance

### 2. Jurisdiction detection

Legal answers depend heavily on jurisdiction.

The system should avoid answering legal questions until it has enough information to identify the relevant jurisdiction or clearly state that the answer is general and may not apply to the user's location.

### 3. Legal topic classification

The system should classify the user's question into a specific legal topic, such as:

- responding to a civil complaint
- landlord-tenant
- small claims
- employment
- contracts
- consumer issues
- administrative matters

The first MVP should support only one narrow topic and jurisdiction.

### 4. Source selection

The system should use approved sources for the selected topic and jurisdiction.

Possible source types include:

- statutes
- regulations
- court rules
- official forms
- court self-help materials
- primary legal authorities
- carefully selected secondary explainers

Primary and official sources should be preferred where available.

### 5. Retrieval

The retrieval layer should search the approved corpus for passages relevant to the user's question or workflow step.

Future retrieval may combine:

- keyword search
- vector search
- metadata filters
- jurisdiction filters
- topic filters
- reranking

The first version should be simple and measurable.

### 6. Context builder

The context builder prepares the retrieved material for answer or workflow generation.

It should preserve:

- source title
- citation or authority reference
- jurisdiction
- document type
- retrieved passage text
- source URL, if available

### 7. Answer and workflow generation

The answer generator should respond using the retrieved context.

For workflow tasks, the system should guide the user through steps rather than only answering a question.

It should not invent legal authority. If the retrieved context does not support an answer, the system should say that it could not find enough reliable information.

### 8. Citations

Answers should show the sources used.

Citations should help users understand:

- what authority supports the answer
- whether the source is primary law, an official source, or secondary material
- where the user can read more

### 9. Confidence and limitations

The system should communicate when an answer is limited.

Examples:

- the jurisdiction is unclear
- the retrieved sources are incomplete
- the answer is based only on secondary material
- the question is too fact-specific
- the issue may involve a deadline or court filing

## Non-goals for the first MVP

The first MVP should not attempt to:

- cover every area of law
- answer questions for every jurisdiction
- replace a lawyer
- file court documents automatically
- provide case-specific legal advice
- rely on unsupported model output
- optimize for a polished user interface before the retrieval and grounding pipeline works

## Application evaluation

Before any workflow is publicly supported, a future application should evaluate:

- retrieval recall
- citation accuracy
- groundedness
- unsupported claims
- jurisdiction accuracy
- refusal behavior
- latency
- cost

Evaluation should be treated as part of the product, not an afterthought.
