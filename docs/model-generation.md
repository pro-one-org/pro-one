# Development generation and evaluation

The generation layer consumes the deterministic assembly contract and returns an accepted or rejected **development draft**. Acceptance means the checks described here passed; it is not approval, legal sufficiency, semantic verification, or public release. Generation always returns `public_execution.allowed: false`, while exposing the independent assembly eligibility result. All Virginia records/reviews remain proposed and all currentness remains uncertified.

## Provider boundary and configuration

`app/models/base.py` defines generic `ModelProvider`, `ModelRequest`, and `ModelResponse` contracts. Requests separate versioned instructions, a structured grounded package, response schema, limits, and safe identifier metadata. Responses contain generic provider/model identity, success/output/error state, usage, and adapter-private metadata. No vendor SDK or request semantics enter domain services. No dependencies were added.

`ProviderRegistry` resolves an explicitly selected provider and configured model. It has no fallback, model routing, or source/content-based selection. The local development application registers only `testing` / `deterministic-test-model`. That offline adapter constructs an extractive structured draft; it is not a live LLM and demonstrates no paraphrasing quality. Named bad-output scenarios are constructor-injected for tests/evaluation, never HTTP options. No credentials or network are needed by the app, tests, CLI, or CI.

There is no real provider adapter or production provider configuration in this milestone. A future adapter must be explicitly registered with permitted models, obtain secrets through server environment/configuration, implement transport/output limits, and keep vendor types inside its module. Clients cannot supply API keys. Raw provider metadata, exception messages, error details, and unrecognized usage fields are never returned or logged. The result includes only bounded integer token counters from an allowlist. No persistent prompt history, database, sessions, model tools, agents, or automatic retries exist.

## Generation input and scope

`GenerationService.generate(assembly, config)` requires available development context, development grounding, an available response plan, and package integrity. These reuse the existing gates and do not require public grounding. There is at most one adapter call; unavailable packages and invalid configuration cause zero calls. The service snapshots its authority package and gives the adapter a detached copy, so adapter mutation cannot change validation policy.

`app/generation_contract.py` constructs a whitelist projection, not a repository dump. It supplies sanitized user facts with `user_provided` provenance, missing fields, allowed claims, only those claims' passage excerpts/citations, titles/locators, section controls, disclosures, support gaps, limitations, prohibited conclusions/actions, routing, privacy, workflow scope, relevant rule controls, and response-pattern constraints. Unrelated records, unselected evidence, reviewer identities, fixture links/expectations, and scoring assertions are omitted. Raw HTTP answers are never re-read. Facts hidden by intake remain hidden; privacy filtering still operates on category keys and cannot detect sensitive information placed inside an otherwise admitted free-text field.

`generation.scope` is an explicit caller assertion: `unconfirmed` (default), `within_workflow`, or `outside_workflow`. It is never a legal finding or a model decision. Unconfirmed scope or any missing required intake field narrows output to supplied control notices; it does not present workflow procedures as applicable to the case. Explicit outside scope makes no provider call. A within-workflow assertion with complete intake enables supported topic references but cannot override review/readiness. Claims whose linked rule disallows user-facing use are excluded from generation. Rule quotation restrictions remain explicit and exact excerpt quotation/double-quote use is rejected when disallowed. This is a conservative boundary, not automatic jurisdiction or document classification.

The stable instruction version is `grounded_legal_information_v1`. Instructions forbid outside knowledge, invented facts/citations, gap resolution, strategy/appearance/removal decisions, unsupported deadline calculations, currentness certification, and legal-sufficiency claims. They require supplied disclosures/uncertainty and plain language. Facts and excerpts are separate untrusted data fields, not instruction text. No chain-of-thought is requested, retained, or exposed. Source/user instruction-like text cannot change policy/schema or expand retrieval; injection resistance of future real models will require separate evaluation.

## Strict output and mandatory validation

`app/generated_draft.py` defines strict Pydantic models with extra fields forbidden, bounded text/list sizes, and no diagnostic reasoning channel. The provider also receives a contextual JSON Schema restricting workflow, section, claim, citation, and fact IDs. Every section has `section_id`, `kind`, `text`, `claim_ids`, `citation_ids`, `user_fact_ids`, `actions`, and `conclusions`. Drafts include `workflow_id`, `sections`, `citations_used`, `disclosures_included`, and `limitations_included`. Allowed kinds are:

- `legal_information`: supplied claim IDs and their linked citations are mandatory; prose is constrained by the supplied topics/limitations and supplementary guards.
- `control`: every paragraph must exactly match supplied control text; arbitrary legal prose cannot hide in this channel.
- `user_fact`: exactly one known fact ID, exact supplied value, and original provenance; the renderer must label this as user-provided, unverified text, not adopt it as a legal conclusion.

`OutputValidationService` runs on every successful provider output. It rejects malformed/oversized/nonfinite/duplicate-key JSON, structural violations, wrong workflow, unknown/missing/duplicate sections, unknown/duplicate IDs, unsupported claim/passage/source relationships, unrelated or missing citations, inconsistent citation manifests, changed/unknown fact references, structured actions/conclusions, and missing disclosures/limitations/risk notices. Required disclosures and limitations must actually appear as control paragraphs; a manifest checkbox is insufficient. URLs must be rendered from canonical citation metadata, not generated prose. Model-created source/passage/fact records and tool requests fail the strict schema. No output is executed and no URL is followed.

Stable codes include `model_output_unparseable`, `generated_schema_invalid`, `workflow_mismatch`, `unknown_section`, `required_section_missing`, `unknown_claim_id`, `unknown_citation_id`, `unsupported_claim`, `citation_not_supporting_claim`, `claim_without_citation`, `unknown_user_fact_id`, `user_fact_changed`, `prohibited_action`, `prohibited_conclusion`, `required_disclosure_missing`, `required_limitation_missing`, `required_control_missing`, and `risk_notice_missing`. Scope, missing-input, privacy/redaction, and development notices must be rendered as applicable. Separate configuration/generation failures include `unknown_provider`, `model_not_configured`, `development_package_unavailable`, `scope_outside_workflow`, and `provider_error`. Provider errors have status `provider_error`; validation failures have status `rejected`; both return `draft: null`. No rejected text or private adapter diagnostics are returned.

Supplementary normalized prose guards return specific codes for the Virginia red-team cases: appearance advice/conflict resolution, removal/strategy recommendations, service validity, invented/universal answer deadlines or duties, certified-current 2008 instructions, and legal sufficiency. These patterns are **not complete natural-language legal reasoning**. A valid claim ID does not prove that arbitrary prose accurately paraphrases its source; prose can still invent facts, source names, or conclusions without using an obvious guard phrase. Exact structured fact controls do not prove prose-level factual correctness. Tests establish the named attacks and boundaries, not universal resistance to paraphrase, negation, obfuscation, or prompt injection. Semantic quality, usefulness, full legal/factual verification, and real-provider adversarial evaluation remain review/release blockers. No accepted development draft should be presented as an approved public answer.

## API

`POST /workflows/{workflow_id}/response/generate` extends `ResponseAssemblyRequest` with required `generation: GenerationConfig`; intake and retrieval models are reused. For example:

```json
{
  "answers": {
    "state": "Virginia",
    "court_name_or_locality": "Augusta County",
    "document_title_or_form_number": "DC-402",
    "return_date_and_time_if_shown": "2026-11-10 09:00",
    "user_goal": "What does the printed return date mean?"
  },
  "risk_ids": [],
  "retrieval": {"query": "return date", "limit": 5},
  "generation": {"provider": "testing", "model": "deterministic-test-model", "scope": "within_workflow"}
}
```

The result separates `generation` (status, provider/model, version, attempt count, allowed claim IDs, safe usage), accepted `draft` or null, `validation`, an assembly summary (plan IDs, missing fields, routes, gap codes), and blocked `public_execution`. It omits the full source package and private provider metadata. An accepted testing response is an extractive inspection artifact, not a live model answer.

Unknown workflows return 404. Malformed input returns 422 with input values removed from validation diagnostics; unrelated retrieval filters retain 422. Intake/corpus/assembly integrity conflicts retain 409. Safe generation failures return 200 with explicit `not_attempted`, `provider_error`, or `rejected` status and stable errors. Configuration and adversarial-scenario fields cannot be silently ignored.

## Evaluation harness

`app/evaluation.py` supplies explicit mappings for the twelve existing Virginia fixture IDs and exact record versions. It maps stated facts to intake fields and reads explicit risk/source IDs; it never interprets narrative expectations into rules or fills unknown court, locality, dates, or case facts. No fixture schema or data change was needed. Version/workflow mismatches fail as `mapping_stale`. The four older example fixtures are explicitly unmapped; asking to execute one fails rather than claiming success. Missing mappings for required Virginia fixtures fail the suite.

Each mapped fixture assembles the real package, invokes the offline provider, validates the draft, and scores named automated checks: evidence/workflow boundaries, citation/claim validation, scope narrowing, missing-fact/provenance preservation, user control, deadline uncertainty, disclosures, routing, privacy, and safe failure. Five mappings add explicit bad-provider cases for response choice, invented defense, unsupported deadline, sufficiency, and citation failure. Unit tests separately exercise complete-intake substantive generation and all ten critical Virginia attacks. A rejected attack is an expected passing evaluation only when the configured error is present and no draft is returned.

The original fixtures lack complete court/date inputs. Their ordinary runs therefore produce control notices or an out-of-scope stop, not invented case facts to enable procedural prose. Narrative expectations such as useful form explanation, exact clarification quality, and legal correctness remain in `manual_checks_pending`. `passed` means only the listed automated checks passed; `manual_review_required` and `release_passed: false` remain explicit. The fixed offline evaluation date is 2026-10-30 and is separate from the HTTP release clock. Results are deterministic for the same repository, mapping, and test scenario.

```text
python -B scripts/run_evaluations.py
python -B scripts/run_evaluations.py --json
python -B scripts/run_evaluations.py --fixture va-small-claims-ordinary-user-fixture
```

The CLI prints concise results and exits nonzero when required automated checks fail or a requested fixture is not executable. CI runs it without secrets or live models. Passing automated checks never approve fixtures, certify sources/currentness, resolve appearance/written-answer gaps, or enable public release. Future real-model evaluation is separate work.
