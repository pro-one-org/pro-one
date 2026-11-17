# Matter Intelligence v1

Matter Intelligence is an opt-in development ledger for the facts and evidence in a single matter. It reuses the document extractor, provider registry, Research Core, and Procedural Intelligence. The built-in evaluation scenario is a Virginia restaurant fall. Other matters can use the typed statement and evidence contracts, subject to the field vocabulary and independent research and procedural coverage.

## Setup

Install the repository development requirements and run the server on loopback. Use synthetic or redacted inputs and keep the database and its journal in a directory available only to the operator.

```sh
export PRO_ONE_MODE=development
export PRO_ONE_MATTER_DB=.local/matters.sqlite3
export PRO_ONE_MATTER_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

On PowerShell, set the same names through `$env:PRO_ONE_MODE`, `$env:PRO_ONE_MATTER_DB`, and `$env:PRO_ONE_MATTER_TOKEN`. The creation token authorizes `POST /matters`. The response includes a distinct bearer token for the new matter. Keep it with the matter ID. The creation token is the server's root secret for deriving matter tokens. Replacing it revokes previously issued tokens. The application disables all matter routes in production, even with development settings configured.

## Commands

Send `Authorization: Bearer <token>` and `Content-Type: application/json` for JSON requests. Use the matter token under `/matters/{id}`. All changes require the current revision to prevent competing writes and accidental replay. On a revision conflict, reread the latest snapshot before resubmitting the intended change.

| Request | Purpose |
| --- | --- |
| `POST /matters` | Create with `{"text":"I slipped in a Wendy's bathroom and broke my wrist. I want them to pay."}`. |
| `GET /matters/{id}?revision=0` | Inspect an earlier snapshot. Omit the revision to read current state. |
| `POST /matters/{id}/statements` | Add `{"revision":0,"text":"Virginia. The fall happened October 3."}`. Optional scope includes a party or event ID. |
| `POST /matters/{id}/documents?revision=1&kind=incident_report` | Send the raw bytes of a supported document. A TXT example body is `Incident date: October 4`. Use its MIME type as the content type. |
| `POST /matters/{id}/statements` | Correct with `{"revision":2,"text":"Actually it was October 4, not October 3.","corrects":["<October 3 assertion ID>"]}`. Use `disputes` with an assertion ID to record a disagreement without supplying a replacement. |
| `POST /matters/{id}/statements` | Change the goal with a dedicated line such as `Goal: pursue settlement`. The earlier goal remains in history. |
| `POST /matters/{id}/evidence` | Record supplied evidence metadata with `revision`, `kind`, and an optional `label` or `custody`. |
| `POST /matters/{id}/external-records` | Import a reviewed record by registered `provider` and `record_id`, with the scoped `party` ID and latest `revision`. |
| `GET /matters/{id}/procedural-facts` | Read known, unknown, conflicting, or unsupported facts with provenance and assertion IDs. |
| `POST /matters/{id}/procedure` | Send the current `revision` and a bounded procedural inquiry in `message`. To choose an offered path, repeat the request with its `selected_path` and `choice_token`. The response records a successful explicit selection and its procedural status. Choices are scoped to the matter, revision, inquiry, and existing procedural catalog constraints. |
| `POST /matters/{id}/research` | Send `area`, `topics`, and optionally `context_fields`. The request uses the matter's resolved jurisdiction. The bounded selected fact context accompanies the authority response. |

Use a new `event_kind` to declare an event, optionally with matter-local `participants` or `related_evidence`. Put the event observations in `text` as separate lines such as `Date: 2026-10-07` and `Location: Clinic`. Use the resulting `event` UUID for later observations. The default for unscoped incident date or location observations is the primary incident. An optional `new_party_role` creates a distinct party from a statement containing a name or brand. Use `party` to scope later legal name, registry ID, alias, owner, or operator observations.

## Records and sources

`Matter.model_json_schema()` exports the versioned Pydantic contract for the ledger. The HTTP schemas are in the development server's OpenAPI document. The normalized record includes timestamped messages, evidence, parties, identity candidates, events, assertions, gaps, corrections, disputes, and path choices. UUID references are checked when reading and writing revisions. Canonical snapshots are deterministic for each stored revision. The response includes assertion IDs, preferred values, status, conflicts, supersession, questions, and source counts. Document text is retained internally to revalidate locators. Snapshot readers see the evidence metadata and excerpts attached to assertions.

| Source | Stored provenance | Treatment |
| --- | --- | --- |
| User statement | Matter-local message ID, original statement, supporting text, received time | Asserted. An authorized user can confirm a replacement or record a dispute. |
| Uploaded text | Evidence ID, raw-file SHA-256, excerpt, extracted-text offset, and PDF page where available | Documented observations. Extraction and classification limitations apply. |
| Court filing | Same document locators and a pleading source classification | Allegations. A recognized pleading is classified as such even if uploaded under a generic label. |
| External registry record | Operator-configured provider, record ID, locator, retrieval time, currentness when known, and a hash of the imported entry | Verified observation from the configured record. A party link additionally needs an operator-reviewed evidence hash, the recorded subject label, and a matching namespaced registration identifier. |
| Model inference | Matter-local message, provider and model, and inference classification | Inferred. Only bounded issue classifications are eligible. |
| Legal authority | Research Core and normalized authority evidence; user-held copies can be inventoried as `legal_authority` | Research support. Authority uploads of this kind create no matter assertions. |

Evidence inventory covers photos, video, messages, witnesses, medical records, receipts, pleadings, and other document and non-document material. Only the existing UTF-8 TXT, text-readable PDF and DOCX parsers extract content. The parser retains its 2 MB, 16,000-character, PDF page and DOCX complexity limits. PDF offsets are measured against extracted text. A heading or known document label can support a bounded candidate. Review the extracted evidence against the original where the text or layout matters.

Conflicts are computed per field and subject. Different observations can coexist across distinct events, while aliases can coexist for the same party. Date intervals can refine an existing observation when they overlap. Disjoint intervals or contradictory single-valued observations create a conflict with both source IDs. A controlled correction appends the replacement and links it to the superseded assertion. A subsequent source can expose a new conflict. Missing and unresolved values remain queryable, with questions linked to the target field.

Dates retain their original expression. Supported normalized inputs include ISO dates, explicit month-day-year dates, ISO datetimes with offsets, and bounded `between YYYY-MM-DD and YYYY-MM-DD` or `approximately YYYY-MM-DD and YYYY-MM-DD` intervals. An optional IANA timezone on an ISO datetime must agree with its offset. Yearless and relative expressions remain unresolved. The schema reserves reference and derivation fields for future explicit normalization. Procedural date fields only consume resolved exact calendar dates.

A brand or alias alone leaves the legal identity unresolved. The operator can configure `PRO_ONE_MATTER_RECORDS` to point to a private reviewed JSON array. An entry consists of `source` with `provider`, `record_id`, `retrieved_at`, optional `current_as_of`, and `locator`; an `excerpt` with supported labels; and `kind` of `corporate_record` or `government_record`. For a party link, the operator also records `source.link_evidence_hash` (the exact reviewed document SHA-256) and `source.subject_label` (the corresponding party label). For example, a party-specific document with `Registry id: state_registry/EX-413` can corroborate the same configured identifier when both the hash and party label match on a record excerpt containing `Legal name: Example Restaurants LLC`. Conflicting registration identifiers disable the link. A legal name can flow to the procedural defendant-identity field only when a single party is explicitly designated as a potential defendant and has corroborated identity. Liability and strategy stay outside this process. Import uses the server file and performs no network lookup.

## Model, privacy, and release boundaries

Model assistance defaults off. When a request opts in, the existing registry sends only the current statement or bounded extracted document to the configured provider. Schema validation rejects unexpected output. Exact quotes from that source may appear as review suggestions. Only deterministic grounding rules and explicit commands create factual assertions. Provider failure leaves deterministic extraction available. Models cannot mutate sources, choose procedural paths, change trust, or resolve conflicts. The current grammar recognizes the bounded restaurant example and typed field labels. Free-form observations outside that coverage are retained as messages and may produce model review suggestions.

Authorization is local and per matter. The app omits matter content from its own logs and uses sanitized errors and no-store HTTP responses. Disable HTTP access logging in the local server, avoid shared deployments and proxies, and give protected treatment to statements, excerpts, SQLite files and journals, backups, and bearer tokens. Provider opt-in can transmit sensitive case text. Use only redacted or synthetic material during development. The ledger retains every recorded revision and bounds an individual matter to 200 revisions and 512 KiB per revision. To discard a local dataset, shut down the server and remove its protected database and any sidecars or backups under the operator's retention policy. Multi-user authentication, encryption at rest, per-matter erasure and production retention infrastructure remain release work.

Research Core receives the selected topic and resolved jurisdiction. The returned matter context contains selected statuses, values and attribution IDs under a fixed limit. Procedural Intelligence receives its typed fact projection and owns procedural requirements. A path choice records what the user selected, with its catalog scope and result at the time. Later ledger changes flag that procedural state for review. No endpoint performs external legal acts.

Private beta requires independent legal and jurisdiction-specific UPL review, privacy and model-provider data handling review, a retention policy, production access controls, abuse controls, operational monitoring, deployment review, broader adversarial testing, and explicit release approval. Future milestones cover claim and element analysis, pre-filing readiness, forms, deadlines, matter management, filing and service, broader jurisdiction and matter coverage, and richer identity and evidence connectors.

## Evaluation and benchmark

```sh
python -B -m unittest discover -s tests -p test_matter_intelligence.py -v
python -B -m unittest discover -s tests -v
python -B scripts/run_evaluations.py
python -B scripts/evaluate_national_corpus.py
python -B scripts/procedural_intelligence.py validate
python -B scripts/validate_repository.py
python -B scripts/benchmark_matter_intelligence.py --iterations 30
```

The matter suite uses synthetic data and tests source scope, corrections and replay, mixed evidence, model hallucination and instruction attacks, registry ambiguity, API isolation, path authorization, and the production gate. The benchmark measures durable creation and updates, isolated TXT parsing plus document commit, in-memory conflict detection and snapshot assembly, and typed retrieval including a SQLite read and graph validation. It uses 30 small independent synthetic matters in a temporary database. Reported p50 and p95 times are wall-clock milliseconds and do not include a model call or HTTP transport. GitHub Actions runs the regression suite, benchmarks, and production container build and smoke.
