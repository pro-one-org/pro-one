# Claim & Element Engine v1

Claim & Element Engine is a development-only Matter Intelligence feature. It reads an immutable matter revision, resolves bounded legal theories through Research Core, and links scoped evidence to source-backed conditions. The results describe evidence posture and gaps for human review. Strategy, valuation, defendant selection, filing readiness, operative drafting, and external action are outside this service's output contract.

## Architecture and authority

The claim catalog lives in [claim-theories.json](../data/claim-theories.json). Research Core resolves its jurisdiction, area, and topics and returns its existing verified evidence package. Claim analysis binds each element to a selected passage ID, source ID, source edition, exact excerpt hash, and allowed authority type. The bound output includes the canonical citation, official link, locator, quote, currentness metadata, and qualifications. Any missing binding removes the affected structured proposition and retains the exact Research Core evidence when available.

The catalog uses retained repository authority for its shipped definitions. Research Core validates the supplemental [claim authority passages](../data/claim-authority.json) against the existing source and passage schemas when assembling claim evidence. Where configured, Research Core can also replay authoritative snapshots from the normalized corpus, including a dated query. An exact match to a catalog source edition and passage remains necessary for structured output. A newly found edition or changed passage requires a new catalog version before it can support a structured theory. A dated request without an exact applicable binding returns an authority gap and the available reference evidence. Retrieval dates and case decision dates cannot certify current law. Current-as-of metadata requires the normalized corpus's date and basis, plus consistency with available effective dates. The shipped versions have unresolved currentness, including subsequent case treatment. Their status is `reference_analysis`.

Primary authority is required for operative support. For case propositions, a reported lead, majority, or unanimous opinion can supply support. Combined, concurring, dissenting, and nonprecedential material is available only in context or as separately attributed exact evidence when returned by Research Core. Context and conflicting sources have explicit relationships. An element with a cataloged legal conflict stays unresolved. The engine preserves the opinion's court, role, disposition context, and later-treatment limitations.

## Theories and elements

A theory identity has a jurisdiction, area, and category. Older versions remain in the catalog when a definition changes. The last record for an identity is selected for new analysis. Each version has review metadata, elements, source bindings, and limitations. Categories include claim, defense, remedy, entitlement, and bar. A theory can link to another theory and carry a procedure reference. An element can record source-backed burdens or standards and a parent element. The validator checks references, arity, jurisdiction, and hierarchy.

The rule tree supports `all`, `any`, `if`, and `unless`. For `if`, the first operand is the trigger. For `unless`, the second operand is the exception. The tree preserves the source's structure for downstream use. Analysis emits independent evidence posture for each condition and leaves application to legal judgment.

The Virginia restaurant-fall scenario uses the following bounded sources.

- Invitee care, warning, and the open-and-obvious qualification. [Fultz v. Delhaize America, Inc.](https://www.vacourts.gov/static/opinions/opnscvwp/1080782.pdf)
- An owner-created condition, the consequent constructive-knowledge analysis, and the role of fall-mechanism testimony at the motion-to-strike stage. The retained excerpts were checked against the official opinion and are attributed to its lead opinion. [Austin v. Shoney's, Inc.](https://www.vacourts.gov/static/opinions/opnscvwp/1961236.pdf)
- Contributory negligence as a possible defense, including the excerpt's objective standard of reasonable care. [Fultz v. Delhaize America, Inc.](https://www.vacourts.gov/static/opinions/opnscvwp/1080782.pdf)
- General personal-injury limitations text with statutory exceptions preserved. Any determination of accrual or applicable exceptions requires further work. [Va. Code § 8.01-243(A)](https://law.lis.virginia.gov/vacode/title8.01/section8.01-243/)
- Virginia contract elements as the second-domain proof. The official passage supplies enforceable obligation, breach, and resulting injury or damage. [Filak v. George](https://www.vacourts.gov/static/opinions/opnscvwp/1031407.pdf)

The catalog covers selected premises propositions and the contract-elements passage. It leaves the broader negligence test, alternative notice doctrines, historical applicability, and specific remedy availability open. There are currently no remedy records. Future sourced remedies can add prerequisites and link to the relevant claim, with their own authority and limitations.

## Facts, source quality, and questions

Each mapping binds the matter ID and revision, theory identity and version, element, fact target, assertion ID, and evidence ID when available. The record retains the original assertion status, source and locator, evidence classification and content identity, and any external record identity. Document and allegation statuses come from Matter Intelligence. A medical record can describe injury. Connecting that injury or fall to an unsafe condition requires distinct evidence. A reported brand does not establish control or legal identity.

The same element can expose context, asserted support, documentary support, independently linked external evidence, allegations, conflicts, or adverse evidence. Open fields remain explicit. A disputed fact keeps its competing assertions and document or statement attribution. Multiple copies do not count as additional independent support. The ledger tracks evidence identity and content hashes.

The report asks neutral factual questions tied to a field, gap, theory, element and authority passage. Shared field questions are deduplicated and retain each dependency. Submit answers through `POST /matters/{id}/statements` with the latest revision and an event or party ID where needed. A scoped report uses the selected incident and its participants. Legacy unscoped incident facts can be used where there is a single incident and no competing scope. Existing procedural choices appear only when recorded by the user for the current revision. The engine can compare covered theories without choosing an objective, ranking claims, or estimating outcomes.

## Optional models and deterministic validation

The default engine uses catalog-defined evidence relevance. Its output remains a source-linked description of the material available for assessment. With `model_assistance=true`, the proposer can select only eligible mapping tuples, and a separate verifier call evaluates the selected tuples against the specific assertion and authority. Each provider and model resolves through the existing server-owned registry. Set `PRO_ONE_CLAIM_VERIFIER_PROVIDER` and `PRO_ONE_CLAIM_VERIFIER_MODEL` to a registered pair. A distinct configured model or provider can perform verification. Either call can fail closed.

The deterministic layer checks exact tuple membership before and after verification. A model cannot add legal prose, change relationships or source posture, fabricate a citation or evidence ID, resolve a conflict, change event scope, or select a party. If either call fails, outputs invalid data, or suppresses protected adverse or conflicting evidence, the report retains the legal evidence and returns the relevant matter records separately. No model is used to write canonical legal theories. Catalog changes go through source comparison and repository validation.

## Development API and storage

Use the same local configuration and per-matter bearer as [Matter Intelligence](matter-intelligence.md). Responses use `Cache-Control: no-store`. The API exposes:

| Operation | Scope |
| --- | --- |
| `GET /matters/{id}/legal-theories?revision=3` | List reference analysis and canonical sources in the current matter scope |
| `POST /matters/{id}/claim-analysis` | Analyze the current revision and persist an immutable report |
| `GET /matters/{id}/claim-analysis/{analysis_id}` | Read a matter-scoped report and its freshness |
| `GET /matters/{id}/claim-analysis/{analysis_id}/questions` | Read factual questions with the report's revision and freshness |

An analysis request requires `revision`. Optional keys are `theory_ids`, `event_id`, `party_id`, `law_as_of`, `model_assistance` and `requested_output`. For example:

```json
{
  "revision": 3,
  "theory_ids": ["va_premises_warning"],
  "requested_output": "evidence"
}
```

Unsupported output modes receive a bounded information response and an explicit scope status. Unrecognized fields are rejected. A stale write returns 409. A missing report within an authorized matter returns 404. The routes return a release-gate denial in production.

Reports live in the same local SQLite database as matter revisions. Their IDs are derived from a deterministic snapshot with matter ID, matter revision, source bindings, model stage result, and theory version fingerprints. Creation is transactional against the analyzed revision. Repeating the same analysis reuses its snapshot and creation timestamp. Later revisions or a changed active theory or authority binding mark earlier reports stale on read. Historical bytes remain available with their original provenance. The response distinguishes the stored report's revision from the live matter revision.

The local database contains sensitive information. Keep it in a private directory with access restricted to the development operator. The feature sends only bounded scoped evidence to models when explicitly requested. The model package excludes full documents, raw history, unrelated evidence and unrelated parties. Errors omit source text and provider diagnostics. Use the repository's no-access-log service settings for local model and API testing.

## Offline validation and replay

Run these commands from the repository root with the development dependencies installed.

```sh
python -B scripts/validate_repository.py
python -B scripts/claim_engine.py validate
python -B -m unittest discover -s tests -p test_claim_engine.py -v
python -B -m unittest discover -s tests -v
python -B scripts/run_evaluations.py
python -B scripts/procedural_intelligence.py validate
python -B scripts/claim_engine.py benchmark --iterations 30
```

The claim suite replays retained authoritative excerpts, synthetic matter updates, and fixture model outputs. It covers the restaurant-fall scenario, external identity attribution, stale and concurrent writes, cross-matter and incident isolation, contract portability, authority boundaries, and adversarial model output. The benchmark reports p50 and p95 for local revision loads, authority binding, mapping and question construction, validation, SQLite persistence and stale reads. Its synthetic timings exclude model, network and HTTP latency.

## Release gates

Production exposure requires independent legal review of source coverage and mappings, jurisdiction-specific legal-services and UPL review, privacy and provider data-handling approval, a retention policy, access-control and abuse review, operational monitoring, broader adversarial testing, deployment review, and explicit release approval. The development [Legal Action OS](legal-action-os.md) uses these reports for bounded preparation, deadlines, draft assembly and matter workspace projections.
