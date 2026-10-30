# Pro-One

**An open-source foundation for free, source-grounded legal AI for people and small businesses handling legal matters on their own.**

Pro-One is building the technical and governance foundation for narrow, jurisdiction-aware legal-information workflows. The project emphasizes authoritative sources, citations, user control, privacy, fact integrity, safe continuation, and explicit evaluation.

## Project status

Pro-One is currently in the **architecture, specification, and early local-runtime stage**. The stateless local API loads and validates records, evaluates intake/readiness, routes explicit risks, retrieves local evidence, and assembles grounded response plans. A provider-neutral generation layer now validates structured development drafts and runs mapped evaluation fixtures using an offline test provider. There is no production legal AI application, hosted service, or publicly supported legal workflow today.

The repository already contains a substantial, machine-validatable schema and governance foundation. Some older records under [`data/`](data/) are fictional examples used to demonstrate structure and relationships; newer records include proposed research for a real jurisdiction, such as the Virginia DC-402 candidate. Neither fictional examples nor jurisdiction-specific proposed research records are automatically approved or supported, and none should be treated as legal guidance or evidence that a workflow is available to the public.

## Current technical foundation

Ten interoperable JSON Schema domains define the project's core records:

1. [source metadata](schemas/source.schema.json)
2. [workflow definitions](schemas/workflow.schema.json)
3. [process steps](schemas/process-step.schema.json)
4. [legal documents](schemas/legal-document.schema.json)
5. [intake definitions](schemas/intake.schema.json)
6. [legal rules](schemas/legal-rule.schema.json)
7. [risk definitions](schemas/risk.schema.json)
8. [response patterns](schemas/response.schema.json)
9. [evaluation fixtures](schemas/evaluation-fixture.schema.json)
10. [curated source passages](schemas/source-passage.schema.json)

Shared definitions in [`schemas/common.schema.json`](schemas/common.schema.json) keep identifiers, versions, review provenance, jurisdiction structures, maturity states, risk levels, routing behavior, and other cross-domain vocabulary consistent. A lightweight validator checks JSON syntax, Draft 2020-12 schema validity, sample-record conformance, cross-record references, key state invariants, and Markdown integrity.

The early local runtime exposes workflow records, resolved workflow packages, and `GET /workflows/{workflow_id}/readiness`. The readiness endpoint fails closed unless the workflow and each required source, process step, and evaluation fixture meet the supported and approved gates. It does not make any sample workflow publicly available. Development generation uses an offline extractive test adapter; there is no live LLM adapter, runtime web fetching, frontend, database, or persistent user session.

### Structured intake and development context

`POST /workflows/{workflow_id}/intake/evaluate` accepts an `answers` object with string, boolean, number, or null values and an optional `risk_ids` list (default `[]`). Nested answer objects/arrays, wrong types, and extra top-level fields receive FastAPI validation errors (`422`). For example:

```json
{
  "answers": {
    "state": "Virginia",
    "court_name_or_locality": "Augusta County",
    "document_title_or_form_number": "DC-402",
    "return_date_and_time_if_shown": "2026-11-10 09:00",
    "user_goal": "Understand what this document is"
  },
  "risk_ids": ["va-small-claims-return-date-risk"]
}
```

The result separates `intake`, `risks`, `privacy`, `routing`, `execution`, and `public_execution`. Required/optional field names come from the workflow record; intake questions remain explanatory metadata. Null and whitespace-only answers are missing; zero and false remain explicit values. Completeness means presence only, never confirmation of jurisdiction, form identity, dates, or legal facts.

Excluded fields and intake/risk privacy categories are matched by key (case folding and space/underscore equivalence only). Excluded, restricted, and unrecognized values are withheld from context and block input eligibility. There is no inspection of prose for sensitive information or risks: callers must use the configured field names and supply explicit risk IDs. Values admitted to `user_facts` are preserved unchanged with `provenance: "user_provided"`; absent facts are never inferred.

Risk IDs are checked against the selected workflow package. Unknown and unrelated IDs are reported separately and block input eligibility. All recognized risk records and their configured routes are preserved in stable order, including distinct urgent-date and response-choice routes. Routing uses the existing canonical vocabulary; incomplete input adds `pause_for_missing_information`, and privacy filtering adds `narrow_then_continue`.

Inspection contexts may contain partial facts and proposed metadata. They contain only resolver-linked process steps, sources, legal rules, risks, legal documents, and response patterns, alongside workflow/intake definitions, output constraints, safety/privacy limitations, routing, and readiness. Evaluation scenarios and unrelated records are excluded; sources remain metadata, with no external content fetches. Missing required package references make context unavailable and are listed explicitly.

`execution.context_available` is independent of `intake.complete` and `public_execution.allowed`. Public eligibility requires input eligibility, package integrity, and the unchanged readiness service. For the Virginia candidate, complete intake produces a development context while public execution remains **false**. Unknown workflows return `404`; missing or ambiguous intake definitions return `409` with stable codes.

The application does not persist intake values, write them to disk or a database, retain them in sessions, or log answer values. Values are held transiently to evaluate the request and return admitted facts; this is not a retention or privacy guarantee about a caller, proxy, or hosting environment. No production service exists.

### Local source-passage retrieval

`POST /workflows/{workflow_id}/retrieval` accepts an optional `query`, `source_ids`, `legal_rule_ids`, `process_step_ids`, `proposition_ids`, and `limit` (default 5, range 1–20). Empty filter lists impose no extra constraint. Omit `query` for relationship-only retrieval; blank or unmatched queries return explicit empty results.

The first corpus has nine short excerpts from four existing official Virginia sources, checked on 2026-10-30. All passages, sources, and reviews remain proposed. Repository startup validates the new passage schema, excerpt hashes, source/workflow relationships, jurisdiction, and optional rule/step links. Missing or invalid corpus data fails startup.

Retrieval selects the workflow package and eligible source passages before applying filters or lexical ranking. Filter types intersect; values within one type union. Unrelated/unknown IDs return `422` rather than broaden scope. Token overlap uses title weight 2 and excerpt/locator/topic weight 1, with passage ID breaking ties. This score is not legal confidence or a decision about applicability.

Results expose exact excerpts, locators, existing preferred citations, official URLs, source and passage review states, verification dates, excerpt hashes, source freshness, rights, and limitations. No eligible or matching passage means no fallback. The endpoint is development inspection only and always returns `public_execution.allowed: false`, alongside the unchanged readiness result. Unknown workflows return `404`; detected runtime corpus corruption returns `409`.

The appearance-wording conflict, lack of support for a universal written-answer deadline, and September 2008 instruction-sheet currentness remain unresolved. No legal answer is generated. Retrieval is local, stateless, and adds no model, embedding, vector database, or network dependency. See [Source corpus](docs/source-corpus.md) for passage provenance, support gaps, and the update process.

### Grounding gate and response-plan assembly

`POST /workflows/{workflow_id}/response/assemble` reuses the intake contract and accepts an optional nested `retrieval` request. It combines the existing execution context and local retrieval with the selected-evidence grounding gate. For example:

```json
{
  "answers": {"state": "Virginia", "user_goal": "Understand the listed date"},
  "risk_ids": [],
  "retrieval": {"query": "return date", "limit": 5}
}
```

The inspectable response separates user facts/provenance and missing input, explicit routing/privacy controls, selected evidence, grounding eligibility, and a response plan. Claims are topic references built only from passage proposition tags, with passage/source/rule/step links, citations, and limitations. They contain no generated legal statement. Response-pattern constraints and prohibited actions are preserved, not treated as approval. Unresolved appearance wording is a support gap, not a resolved claim; missing universal written-answer support is never turned into a negative legal rule.

Public eligibility requires input eligibility, existing workflow readiness, selected grounding eligibility, and package integrity. The new gate requires supported/approved evidence and linked records, the existing review scopes and exact-version review provenance, valid relationships, usable citation/rights metadata, and explicit currentness certification for each selected passage and source. Missing certification fails closed; verification dates alone do not certify currentness. No current record was certified or promoted.

Complete Virginia intake can produce a development package while public grounding and execution remain **false**. No-match retrieval returns an explicit grounding-unavailable gap with no substantive claims. Unknown workflows return `404`, malformed/unrelated filters return `422`, and intake/corpus integrity conflicts retain `409`. Assembly itself makes no model call and produces no generated legal answer. See [Grounded response assembly](docs/grounded-response-assembly.md) for the policy and claim/citation contract.

### Structured development generation and evaluation

`POST /workflows/{workflow_id}/response/generate` reuses the assembly request and requires `generation: {"provider": "testing", "model": "deterministic-test-model", "scope": "within_workflow"}`. Scope defaults to `unconfirmed`; missing required inputs or unconfirmed scope restrict the draft to supplied control notices. Explicit outside scope prevents a provider call. Scope assertions do not establish legal applicability or override review.

The generic registry has no fallback or model routing. The only adapter is offline and extractive; it adds no SDK, credentials, or network dependency. The model receives only a whitelist projection of sanitized facts, selected evidence/topics, citations, and deterministic constraints. Strict structured output is validated independently for section/claim/citation/fact IDs, support relationships, disclosures, limitations, and prohibited structured content. Supplementary prose guards reject the named Virginia red-team cases; they do not prove semantic legal or factual correctness. Failed drafts return null with stable errors. All generation remains development-only with public execution false.

Run `python -B scripts/run_evaluations.py` for the twelve mapped Virginia fixtures (`--json` gives detailed checks). Required automated failures produce a nonzero exit. Four older example fixtures remain explicitly unmapped. Narrative criteria and manual approval remain pending; automated passes do not approve a workflow. See [Model generation and evaluation](docs/model-generation.md) for the API, instruction version, privacy boundary, validator limitations, and fixture coverage.

The schemas sit within documented [legal-safety](docs/legal-safety.md), [privacy](docs/privacy-principles.md), [governance](docs/governance.md), [source](docs/source-standards.md), [workflow-selection](docs/workflow-selection.md), and [evaluation](docs/evaluation-principles.md) standards.

## Intended architecture

The following is a specification target, not a production pipeline:

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

See [Architecture](docs/architecture.md) for the broader component model.

## Proposed first MVP

The first proposed legal workflow is a narrow Virginia General District Court Small Claims Division information workflow for a defendant who received Form DC-402, Warrant in Debt. Its specification and source metadata are proposed and have not received jurisdiction-specific legal review.

That legal workflow is not publicly supported; the local runtime provides repository access, readiness checks, structured intake assessment, explicit risk routing, and development context assembly. The future grounded workflow would identify the official form and court, organize user-confirmed information, link current official sources, and flag the printed return date for prompt verification without calculating a deadline or choosing a response. See the [Virginia DC-402 workflow specification](docs/virginia-small-claims-warrant-in-debt-workflow.md), [MVP](docs/mvp.md), and [Legal Safety](docs/legal-safety.md).

## Legal-information boundary

Pro-One is not a law firm or lawyer, does not form an attorney-client relationship, and does not currently provide legal services. Future workflows are intended to provide source-grounded legal information and structured assistance within reviewed boundaries.

Sample sources, rules, documents, responses, and other records are placeholders—not legal guidance. Before any workflow is described as publicly supported, it must have current jurisdiction-specific sources, an approved review covering the domain-specific scopes in the [review standards](docs/review-standards.md#public-support-review-gates), documented safety and privacy controls, and passing evaluation fixtures. The repository does not claim that attorney review has occurred.

## Repository navigation

- [Mission](MISSION.md)
- [Architecture](docs/architecture.md)
- [MVP scope](docs/mvp.md)
- [Roadmap](docs/roadmap.md)
- [Governance](docs/governance.md)
- [Review standards](docs/review-standards.md)
- [Source metadata](docs/source-metadata.md) and [source standards](docs/source-standards.md)
- [Workflow definitions](docs/workflow-definitions.md) and [workflow selection](docs/workflow-selection.md)
- [Legal safety](docs/legal-safety.md), [privacy](docs/privacy-principles.md), and [ethics](docs/ethics.md)
- [Evaluation principles](docs/evaluation-principles.md) and [fixtures](docs/evaluation-fixtures.md)
- [Development setup](docs/development-setup.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution expectations and [Development Setup](docs/development-setup.md) for local validation. The short version:

```bash
python -m pip install -r requirements-dev.txt
python -B -m unittest discover --start-directory tests --verbose
python scripts/validate_repository.py
```

When a shared enum or record relationship changes, update the affected schemas, sample records, documentation, and validation rules together.

## License

Pro-One is licensed under the [MIT License](LICENSE).
