# Local source corpus

The first corpus is for `va-small-claims-warrant-in-debt-information` only: nine short excerpts, four existing official sources, and ten local proposition tags. All passages, sources, related legal records, and reviews remain proposed. This is development inspection material, not a legal answer or approved public corpus.

## Passage model and integrity

`data/source-passages.json` is a required repository domain validated by `schemas/source-passage.schema.json` at startup. Each entry has a stable ID, versions, source/workflow relationships, jurisdiction snapshot, precise locator, narrow proposition tags, exact short text, manual retrieval/verification dates, observed version, SHA-256 of the UTF-8 excerpt, review metadata, limitations, and optional legal-rule/process-step links. Whitespace in excerpts may be flattened; text is not generated at runtime.

The source relationship resolves the official URL, title, authority, preferred citation, dates, rights, and source review. These are not copied into passage records. Proposition tags are local labels rather than a new foreign-key domain; they do not certify a legal proposition.

The existing loader indexes and schema-validates passages. `app/corpus.py` supplies shared checks for runtime and repository validation: source/workflow/rule/step existence, source workflow fit, exact jurisdiction dimensions, source support for linked rules/steps, excerpt hash, and verification chronology. Structural validity cannot prove legal support; that remains a review obligation. The new singular `source_id` reference participates in typed cross-record validation. Supporting a passage publicly would require an approved passage review with the documented scopes and a supported/approved source. No such approval occurred.

## Official-source research, checked 2026-10-30

| Existing source ID and official URL | Passage suffixes and locators | Observed version and limitations |
| --- | --- | --- |
| `va-small-claims-procedure-code`: [Article 5](https://law.lis.virginia.gov/vacodefull/title16.1/chapter6/article5/) | `division` — [§ 16.1-122.1](https://law.lis.virginia.gov/vacode/title16.1/chapter6/section16.1-122.1/); `first-return-date` and `pleading-categories` — [§ 16.1-122.3(E), (F)](https://law.lis.virginia.gov/vacode/title16.1/chapter6/section16.1-122.3/); `removal` — [§ 16.1-122.4(B)](https://law.lis.virginia.gov/vacode/title16.1/chapter6/section16.1-122.4/); `informal-trial` — [§ 16.1-122.5](https://law.lis.virginia.gov/vacode/title16.1/chapter6/section16.1-122.5/) | Currently hosted Code text was opened at the article and section URLs. This does not certify the effective law for a matter, service, eligibility, exceptions, or local practice. Trial timing is subject to the remainder of subsection E. The pleading list is not evidence of a universal written-answer duty or deadline. Removal concerns small claims to General District Court, not locality transfer. |
| `va-dc402-warrant-in-debt-small-claims-form`: [DC-402](https://vacourts.gov/static/forms/district/dc402.pdf) | `dc402-identity` — page 1 heading and form-number footer; `form-appearance-warning` — page 1 defendant warning | Front marked 10/07, reverse 07/01. The currently hosted PDF was inspected. The nonappearance warning must remain conditional; appearance wording is not reconciled with self-help material. |
| `va-dc402-warrant-in-debt-instructions`: [DC-402 instructions](https://www.vacourts.gov/static/forms/district/dc402inst.pdf) | `grounds-of-defense-order` — PDF page 3, Data Element 31, judge-completed fields | Marked September 2008. The field describes dates for judge-ordered grounds of defense. Currentness and local implementation remain unresolved; hosting the old PDF does not resolve them. |
| `va-small-claims-self-help`: [Small Claims](https://selfhelp.vacourts.gov/page/11/small-claims) | `self-help-appearance` — Trial or Return Date, first sentence | Page displays updated February 07, 2026. Retained as official explanatory wording to expose the appearance tension, not to displace primary authority. Its default discussion separately conditions nonappearance consequences on proper service. |

Passage IDs use the prefix `va-small-claims-passage-`. No forms-directory passage was needed: the already linked official form directly identifies the document. No new source record or outside material was added.

## Support gaps and reuse

The set does not establish a universal written-answer requirement or deadline. This is a gap in curated support, not proof that a case-specific duty cannot arise. No passage asserts a negative legal rule. The pleading and instruction passages retain this limitation; it is also exposed at retrieval-package level.

The form's appearance warning and self-help's appearance wording remain separate excerpts with an explicit unresolved limitation. There is no recommendation about appearance, response, removal, strategy, service validity, or consequences for an individual case.

Only the pleading-category excerpt links to the existing legal rule. Its `source_quotes_allowed: false` and `user_facing_allowed: false` remain unchanged; an inspection link does not authorize user-facing quotation. The instruction excerpt has no rule/step support link because those records do not currently list the instruction source. No links or legal propositions were fabricated to close that gap. Organization choices and safety controls in steps are not all legal propositions and are not all established by these short excerpts.

Reuse status remains unknown. Only targeted fragments are retained, not full statutes, forms, sheets, or pages. No open license is claimed. Rights review, source freshness, locality-specific practice, legal review, and approved evaluations remain public-release blockers.

## Retrieval and handoff

`POST /workflows/{workflow_id}/retrieval` accepts optional `query`, `source_ids`, `legal_rule_ids`, `process_step_ids`, `proposition_ids`, and integer `limit` (1–20, default 5). All defaults select the bounded package; an omitted query performs relationship retrieval. Filters use OR within a type and AND across types. Unknown/unrelated IDs fail with `422` and sorted invalid IDs; they are never ignored.

The service calls `RecordRepository.resolve_workflow()` before ranking, validates corpus links, and restricts passages to that package, matching jurisdiction, official source authority, and eligible maturity. Deprecated/rejected passages or sources, rejected source reviews, and explicitly superseded sources are excluded. Proposed passages and uncertain freshness remain inspectable with their limitations. Source effective dates are exposed; no public effective-date or staleness policy is asserted.

Lexical scoring tokenizes case-folded text with `[a-z0-9]+`. Unique query-token overlap with the title has weight 2; overlap with excerpt, locator, and proposition tags combined has weight 1. Limitations are not ranking evidence. There is no stemming, semantic interpretation, or legal-confidence score. Positive matches sort by decreasing score, then passage ID. Relationship-only results have score zero and sort by ID. Blank queries return `empty_query`; no eligible or matching passages return explicit empty packages, without fallback.

The response includes source citation/provenance, passage/source maturity and reviews, excerpt verification, source freshness/rights, corpus limitations, and candidate/match/return counts. Package limitations preserve corpus support gaps even when a narrow query does not return the conflicting passage. Source-record verification dates remain distinct from excerpt checks; dates and hashes do not certify currentness or approval.

The existing readiness service is called unchanged. This development-only endpoint always sets `public_execution.allowed: false`, even for a hypothetically ready workflow. Retrieval does not perform intake or grant execution. A future layer can join an execution context and retrieval package by workflow ID while preserving both sets of limits; no generation layer exists here.

## Updates and runtime boundary

To change a passage, reopen the official source, confirm the locator and exact text, record observed version/dates, update the excerpt hash and record version, preserve uncertainty, validate relationships, run tests and repository validation, and obtain review before merge. Research checks do not create review approval. Existing source metadata remains historical unless separately and accurately updated.

Runtime loads local files at startup and retrieves from memory. It makes no network/model calls, writes no user data, logs no queries, and retains no request state. No ingestion daemon, OCR, model SDK, embeddings, vector database, or deployment infrastructure was added.
