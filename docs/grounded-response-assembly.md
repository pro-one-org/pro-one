# Grounded response assembly

This assembly layer creates an inspection contract for constrained generation. It makes no model call and produces no legal prose. The separate [development generation layer](model-generation.md) now consumes it through a provider-neutral interface and mandatory validation, using an offline adapter only. All Virginia records, passages, and reviews remain proposed; no production workflow exists.

## Separate gates

`WorkflowReadinessService` retains its existing workflow, required-source, process-step, and fixture rules. Optional passages are not added as workflow-level prerequisites. `GroundingEligibilityService` evaluates only the selected passages plus their linked sources/rules/steps, all applicable response patterns, and explicit active risks. Callers cannot bypass implicit evidence links by passing empty rule/step lists.

Development grounding requires nonempty, workflow-linked, structurally valid evidence with citation metadata. Rejected/deprecated records or reviews, superseded sources, invalid hashes, broken links, mismatched jurisdiction, and unsupported record relationships fail closed. Proposed and freshness-uncertain records remain available for inspection with limitations. Corpus relationships reuse `app/corpus.py`; workflow discovery reuses the repository resolver.

Public grounding additionally requires supported maturity, approved reviews, complete existing domain review scopes, exact record-version review provenance, and domain-schema conformance for selected passages, sources, rules, steps, patterns, and active risks. Scopes are shared unchanged between repository validation and the gate through `app/review_policy.py`; domain checks reuse the repository's cached schema validator. Sources must satisfy response-pattern authority/review constraints and have usable reuse metadata; unknown, link-only, or unresolved permission states do not authorize quotation in public grounding. Legal rules must permit user-facing use and have their required source support represented. Existing quotation and output restrictions remain constraints even when a topic is inspectable.

Every rule/step relied upon must have an explicit selected passage link; lexical similarity does not supply support. A topic reference supports only its curated proposition, not every statement or action in the linked rule or step. Full linked records retain their limits for future evaluation.

The final assembly eligibility is input eligibility AND existing workflow readiness AND grounding eligibility AND package integrity, with substantive supported topics required. A positive result is eligibility metadata, not execution, approval fabrication, or generated output. Actual Virginia public eligibility remains false. Hypothetical passing cases exist only as fictional in-memory test fixtures.

## Freshness policy

Sources and passages may optionally carry `public_currentness` using a shared schema definition. Absence or `status: unresolved` blocks public grounding. No current record receives a certification in this milestone. `status: certified` requires exact `record_version`, observed `source_content_version`, `verified_on`, `valid_through`, and an empty `unresolved_issues` list.

The gate requires the certification's record/content version to match canonical metadata, its verification date to match the source's `dates.last_verified` or passage's `verification.verified_on`, and its interval to contain the evaluation date. Review must cover the exact record version, include the existing `source_freshness` scope, and occur no earlier than verification and no later than evaluation. Expired, future, mismatched, or incomplete certification fails closed. There is no automatic certification from an old/new date, URL availability, lexical score, or approval of another record.

Statutes, regulations, court rules, and agency rules additionally require an established `effective_from`; future starts or expired effective periods block release. An absent end date can represent an ongoing period only alongside the explicit bounded certification. No effective date or currentness assertion is invented for existing sources.

The evaluation date is owned by the service (UTC calendar date by default), returned as `evaluation_date`, and injectable only through the internal service constructor for deterministic evaluation/tests. The HTTP request cannot backdate it. Results are deterministic for the same repository, request, and evaluation date. Certification expiry is a release-control interval, not a user legal deadline. The gate does not parse limitation prose for legal currentness. Reviewers must make accurate explicit metadata and resolve contradictory limitations before certification.

The September 2008 instruction uncertainty is preserved as both missing certification and an explicit workflow support gap. No currentness is certified. The legacy retrieval endpoint remains development-only; its inspection freshness flag is not a substitute for this canonical-record release evaluation.

## Claims, support gaps, and citations

`ResponseAssemblyService` reuses `ExecutionContextService`, `PassageRetrievalService`, and the new gate. It never interprets answer prose or derives legal conclusions from excerpt text. Canonical repository records supply evidence; returned retrieval text is not treated as an independent approval or editable source of truth.

Claims are `legal_information_topic` references built from explicit passage proposition tags. Each has a stable claim ID, workflow ID, passage/source/citation links, preserved rule/step relationships, limitations, and an eligibility status. No claim has a generated legal statement. `user_fact_ids` remains empty because no fact-to-legal-conclusion inference occurs. User facts are separately preserved unchanged with existing `user_provided` provenance; missing facts stay missing.

Each citation preserves the stored preferred citation, official title/URL, locator, passage ID, source ID, excerpt verification/hash, source dates/version, maturity/reviews, rights, and explicit or unresolved currentness metadata. Technical citation IDs are references, not invented formal legal citations. Citations can also document withheld topics and gaps.

Optional workflow `response_constraints.support_gaps` records explicit gap codes/descriptions, affected proposition tags, claim-withholding controls, public-grounding blocks, and prohibited conclusions. Empty proposition lists make an enabled withholding/blocking control package-wide; a gap with both controls false is informational. The Virginia workflow now records its already-known universal written-answer requirement/deadline gaps, appearance conflict, instruction freshness, and local-practice uncertainty. This metadata change remains proposed and does not resolve or approve a legal proposition.

The unresolved appearance topic is withheld as a substantive claim; the two source wordings remain inspectable as evidence of the gap. The Grounds of Defense topic retains the conditional judge-order limitation and instruction-age warning. Universal written-answer duty/deadline gaps never become negative legal rules. Selecting a topic marked as blocking public grounding keeps the package in development until actual review changes that metadata; certifying an unrelated source cannot clear it.

Response sections derive from existing response-pattern section metadata, with existing privacy/risk-notice categories required when configured. Multiple patterns must have compatible required sections. Workflow/intake output constraints, rule user-facing/quotation limits, pattern citation/safety rules, active-risk prohibited actions, required disclosures, and workflow exclusions remain explicit. Preserving these controls is not authorization to choose strategy, appearance, removal, admissions/denials, defenses, service validity, deadlines, filing readiness, or outcomes. No automated enforcement of future generated prose is claimed; there is no generated prose here.

## API and availability

`POST /workflows/{workflow_id}/response/assemble` extends the existing typed intake request (`answers`, optional `risk_ids`) with optional nested `retrieval: RetrievalRequest`. No duplicate answer/retrieval model or caller-supplied certification is introduced.

The result separates `development_package`, `user_context`, intake, risks, privacy, routing, selected `grounding` records/eligibility, `response_plan`, and `public_execution`. The plan contains section controls, supported claim references, citation metadata, support gaps, limitations, prohibited conclusions/actions, and required static disclosures. It exposes enough state for later fixture checks without implementing a fixture runner.

Unknown workflows return 404; malformed requests and unrelated retrieval filters return 422; intake-resolution and corpus-integrity conflicts retain 409. Composed workflow identities must match. No eligible evidence returns an explicit grounding-unavailable gap, an unavailable substantive plan, and no substantive claims. Partial intake may still yield an inspection package, but cannot override input eligibility. Inspection package availability, grounding availability, plan availability, and public eligibility are distinct fields.

Only the already configured workflow and selected material appear. Retrieval's bounded lexical behavior is unchanged: weak token matches may select additional topics, and every selected item must pass the package gate. Use explicit relationship/proposition filters to narrow selection. No silent evidence replacement, global fallback, response generation, or model knowledge is used.

## Review and next handoff

The schema, UTC certification policy, proposition-level support boundaries, pattern composition, and support-gap controls remain review concerns. Rights/currentness/legal review and approved fixtures remain release blockers; no workflow has passed them. The separate development generation layer preserves this contract's gates, citations, scope, user decisions, and prohibited content, with structural validation and supplementary prose guards. Semantic validation, live-model evaluation, and public release remain future work.
