# Development generation and evaluation

The generation layer consumes the deterministic assembly contract and returns an accepted or rejected **development draft**. Acceptance means the checks described here passed; it is not approval, legal sufficiency, semantic verification, or public release. Generation always returns `public_execution.allowed: false`, while exposing the independent assembly eligibility result. All Virginia records/reviews remain proposed and all currentness remains uncertified.

## Provider boundary and configuration

`app/models/base.py` defines generic `ModelProvider`, `ModelRequest`, and `ModelResponse` contracts. Requests separate versioned instructions, a structured grounded package, response schema, limits, and safe identifier metadata. Responses contain generic provider/model identity, success/output/error state, usage, and adapter-private metadata. No vendor SDK or request semantics enter domain services. No dependencies were added.

`ProviderRegistry` resolves an explicitly selected, server-configured provider and model with no fallback or legal-content routing. Development includes the labeled offline extractive test adapter; isolated OpenAI Responses and Anthropic Messages adapters are registered only with server-held credentials and configured model identifiers. Production excludes testing. Browser clients cannot provide keys or arbitrary model configuration. No SDK or dependency was added.

The real adapters use fixed official HTTPS endpoints, bounded transport/output, no redirects, a timeout, and one call without retries. Provider-specific wire-schema simplification is isolated in the adapter support module; canonical local validation remains mandatory. Raw provider metadata, exception messages, and unrecognized usage fields are never returned or logged. No persistent history, database, model tools, or agents exist. See the root README for environment configuration and current official API references. Live output quality must be verified separately with configured credentials.

## Generation input and scope

`GenerationService.generate(assembly, config)` requires available development context, development grounding, an available response plan, and package integrity. These reuse the existing gates and do not require public grounding. There is at most one adapter call; unavailable packages and invalid configuration cause zero calls. The service snapshots its authority package and gives the adapter a detached copy, so adapter mutation cannot change validation policy.

`app/generation_contract.py` constructs a whitelist projection, not a repository dump. It supplies sanitized user facts with `user_provided` provenance, missing fields, allowed claims, only those claims' passage excerpts/citations, titles/locators, section controls, disclosures, support gaps, limitations, prohibited conclusions/actions, routing, privacy, workflow scope, relevant rule controls, and response-pattern constraints. Unrelated records, unselected evidence, reviewer identities, fixture links/expectations, and scoring assertions are omitted. Raw HTTP answers are never re-read. Facts hidden by intake remain hidden; privacy filtering still operates on category keys and cannot detect sensitive information placed inside an otherwise admitted free-text field.

`ResponseAssemblyRequest.matter` supplies strict structured country/state/audience/matter/court/document/role details. `MatterRoutingService` matches explicit workflow selectors and required fields, then checks sanitized intake bindings for contradictions. Only `confirmed_for_workflow` with complete required intake permits substantive topics. This confirms specification fit, never legal jurisdiction, venue, merits, service validity, standing, or representation requirements. Missing matter/scope inputs narrow legacy generation to exact controls; the product endpoint stops for clarification. `generation.scope` is compatibility metadata and cannot enable topics. Explicit outside scope can still veto generation. Claims whose linked rule disallows user-facing use are excluded, and quotation restrictions remain enforced.

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
  "matter": {"country": "US", "state": "Virginia", "user_type": "self_represented_individual", "matter_type": "small_claims_debt", "court": "General District Court", "form_number": "DC-402", "role": "defendant"},
  "answers": {
    "state": "Virginia",
    "court_name_or_locality": "Augusta County",
    "document_title_or_form_number": "DC-402",
    "return_date_and_time_if_shown": "2026-11-10 09:00",
    "user_goal": "What does the printed return date mean?"
  },
  "risk_ids": [],
  "retrieval": {"query": "return date", "limit": 5},
  "generation": {"provider": "testing", "model": "deterministic-test-model"}
}
```

The result separates `generation` (status, provider/model, version, attempt count, allowed claim IDs, safe usage), accepted `draft` or null, `validation`, an assembly summary (plan IDs, missing fields, routes, gap codes), and blocked `public_execution`. It omits the full source package and private provider metadata. An accepted testing response is an extractive inspection artifact, not a live model answer.

Unknown workflows return 404. Malformed input returns 422 with input values removed from validation diagnostics; unrelated retrieval filters retain 422. Intake/corpus/assembly integrity conflicts retain 409. Safe generation failures return 200 with explicit `not_attempted`, `provider_error`, or `rejected` status and stable errors. Configuration and adversarial-scenario fields cannot be silently ignored.

## Evaluation harness

`app/evaluation.py` maps fixture ID/version to its own workflow, structured inputs/matter, source filters, expected checks, and optional adversarial mode. All 24 required real-workflow fixtures execute (12 DC-402, six SCC, six Maryland). Four older examples remain explicitly unmapped. Missing/stale required mappings and workflow mismatches fail rather than silently reinterpreting narrative text. No fixture expectation or scoring assertion reaches a provider.

Each mapped fixture assembles its workflow package, invokes the offline provider, validates output, and scores declared evidence/citation boundaries, scope, missing facts/provenance, user control, deadline uncertainty, disclosures, routing, privacy, and safe failure. Nine mappings add configured bad-provider cases. Unit tests exercise complete-intake generation across all three workflows, the ten critical Virginia attacks, provider adapters with mocked transport, rendering rejection, and cross-workflow isolation.

The original DC-402 fixtures lack complete court/date inputs and preserve missing information rather than inventing it; new SCC/Maryland ordinary fixtures explicitly supply their structured navigation context. Narrative usefulness, legal accuracy, and clarification criteria remain in `manual_checks_pending`. Automated `passed` never means legal approval; `manual_review_required` and `release_passed: false` remain explicit. Offline evaluation uses the fixed date 2026-10-30; HTTP release evaluation retains its server-owned clock.

```text
python -B scripts/run_evaluations.py
python -B scripts/run_evaluations.py --json
python -B scripts/run_evaluations.py --fixture va-small-claims-ordinary-user-fixture
```

The CLI supports all/workflow/fixture selection and JSON reports, with nonzero exit on required failure. CI needs no credentials or live model. `scripts/benchmark_models.py` reuses one assembled fixture package across configured adapters, reports absent providers, and exposes latency, usage, exact draft hashes, and ten non-authoritative manual semantic dimensions. Optional manual scores must match workflow/fixture/provider/model/hash and cannot override deterministic rejection or grant release approval.