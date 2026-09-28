# Roadmap

This roadmap distinguishes completed repository/specification work from current workflow-definition work and future application implementation. A checked foundation item does not mean a production legal AI capability exists.

## Phase 0: Repository foundation — completed

Goal: establish the project direction and contribution standards.

- [x] Define project architecture
- [x] Define proposed MVP scope
- [x] Define the initial roadmap
- [x] Add contribution guidelines
- [x] Add issue templates
- [x] Add development setup documentation
- [x] Document mission, governance, review, safety, privacy, ethics, source, workflow-selection, and evaluation principles

## Phase 0.5: Schema and specification foundation — completed

Goal: create a coherent, enforceable record model before application work begins.

- [x] Define nine interoperable JSON Schema domains
- [x] Add shared common definitions and canonical vocabulary
- [x] Add fictional sample records for every domain
- [x] Add record versioning, review provenance, source freshness, and source provenance fields
- [x] Add supported-state conditional constraints
- [x] Add cross-record reference and state-invariant validation
- [x] Run validation in GitHub Actions on pull requests and pushes to `main`

These milestones describe repository infrastructure only. No sample record is currently approved or supported, and no production application exists.

## Phase 1: First workflow specification — current

Goal: fully specify the proposed first workflow before implementation.

The proposed workflow is narrowly scoped to a defendant who received Virginia General District Court Small Claims Division Form DC-402, Warrant in Debt. It provides information and organization, not a generic civil-answer workflow.

- [x] Select Virginia General District Court Small Claims Division and the DC-402 Warrant in Debt
- [x] Map initial official source propositions and record unresolved questions
- [x] Define the user journey for form/court identification, user-directed question organization, and date-risk routing
- [x] Preserve user control; do not select pleadings, defenses, removal, settlement, or appearance decisions
- [x] Identify minimum required and prohibited inputs
- [x] Identify scope-confirmation questions and timing signals
- [ ] Complete jurisdiction-specific review of the legal-information/legal-advice boundary and other applicable requirements
- [x] Define proposed stop, warning, safe-continuation, and human-help behavior
- [x] Create twelve proposed evaluation fixtures and acceptance criteria
- [ ] Complete jurisdiction-specific legal review, including return-date/appearance wording and written-response requirements
- [ ] Review evaluation fixtures and approve public-support acceptance criteria

## Phase 2: Corpus selection and ingestion — future application foundation

- [x] Identify initial official sources for the proposed Virginia workflow
- [ ] Review and approve authoritative sources for supported use
- [ ] Select court rules, forms, instructions, statutes, regulations, cases, and explanatory sources by proposition
- [ ] Record source versions, effective periods, verification dates, and reuse constraints
- [ ] Create a repeatable ingestion and update process
- [ ] Preserve citations and content provenance

## Phase 3: Retrieval — future implementation

- [ ] Implement a minimal retrieval baseline
- [ ] Add jurisdiction, authority, effective-date, and review-state filtering
- [ ] Compare retrieval approaches against reviewed fixtures
- [ ] Reject stale, superseded, deprecated, rejected, or mismatched authority for supported use

## Phase 4: Grounded workflow and response generation — future implementation

- [ ] Build context assembly from approved records and retrieved passages
- [ ] Generate source-backed explanations and workflow steps
- [ ] Populate draft structure only from explicit user decisions and confirmed facts
- [ ] Add citations, limitations, refusal of unsafe parts, and safe continuation
- [ ] Preserve fact and source provenance through the response pipeline

## Phase 5: Evaluation and release gates — future implementation

- [ ] Execute the reviewed evaluation-fixture suite
- [ ] Measure retrieval, citation, jurisdiction, privacy, boundary, deadline, and refusal behavior
- [ ] Require human review for defined high-consequence cases
- [ ] Document release criteria for the first publicly supported workflow

## Phase 6: Minimal interface — future implementation

- [ ] Build a narrow interface for the selected workflow
- [ ] Display jurisdiction, sources, citations, limitations, and record maturity
- [ ] Add privacy notices and user-confirmation controls
- [ ] Make clear that draft generation does not establish legal sufficiency

## Later phases

Only after the first workflow meets its release gates should the project consider litigation tracking, additional jurisdictions, small-business dispute workflows, or broader document support.

## Guiding rule

Pro-One should not expand coverage faster than it can preserve grounding, citations, jurisdiction accuracy, privacy, user control, fact integrity, safe continuation, and explicit evaluation.
