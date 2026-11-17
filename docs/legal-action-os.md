# Legal Action OS v1

Legal Action OS is a local development capability for preparing a user-selected action for review. It reads Matter Intelligence for facts and evidence, Claim & Element Engine for analyzed theories and evidence links, Research Core for authoritative evidence, and Procedural Intelligence for the chosen path, court and procedural requirements. It preserves their currentness and coverage limitations.

## Preparation and provenance

The [action catalog](../data/legal-action-os.json) is versioned and validated against both upstream catalogs. An action binds a jurisdiction, forum, path, stage, permitted party roles, claim theories, requirements, deadline policies and a template. A scoped procedural choice is recorded using the existing signed-offer exchange. Each result binds to that choice and to the current ledger revision. A party or incident selection is explicit when ambiguity would change the action.

The readiness report includes per-dimension statuses, blockers, other gaps, next steps and source references. Each requirement declares the source of the requirement and how an unresolved result affects preparation. For the Richmond complaint, the selected party's linked legal name and operator record must agree, an attributed report must place the incident in the City of Richmond, and the claim report must match the current revision, incident and party. The engine preserves adverse and conflicting accounts, retains their sources, and leaves the affected requirement unresolved. A registry record is evidence of a linked identity. Deciding which party to name remains the user's choice.

The complaint contract distinguishes preparation inputs from legal review. A complete set of required preparation inputs permits an unsigned development reference draft. Claim currentness, court requirements, accrual, remedies and execution authorization have separate statuses. The current claim catalog supports bounded reference analysis. An unresolved law or remedy review remains visible on a reviewable draft. Pro-One does not determine whether a person should litigate, which legal strategy to pursue, or whether a pleading meets the user's legal obligations.

## Deadline calculation

The response policy uses the existing pinned procedural evidence for ordinary service of a summons and complaint and the statutory counting convention. It requires the exact bounded court, a matching recorded procedural choice, and a single scoped service event. Add an exact date, document type and service method from the same supplied proof-of-service document. Explicitly record the case order/extension status and applicable local-rule check on that event. Competing accounts, waiver, extensions and dates outside the reviewed authority date return unresolved results. The calculation's authority includes the original edition, locator, source digest and date of review. [Virginia Code § 1-210](https://law.lis.virginia.gov/vacode/title1/chapter2.1/section1-210/)

Set `PRO_ONE_ACTION_CALENDARS` to an operator-reviewed local JSON array of court calendars when applicable. Each calendar gives its ID, version, forum, jurisdiction, reviewer and a `days` map keyed by ISO date. Each day gives a state and source locator. Supported states cover an open day, a federal or jurisdiction holiday, a court closure and a weekend. An unknown required weekday stops the calculation. The counting core supports calendar days, business days, explicit trigger inclusion, and forward or backward adjustment. The shipped rule uses calendar days, excludes the trigger and rolls forward. It retains each consulted day and its source, the nominal date, the adjustment and the assumptions. The only dated Virginia response rule edition in the catalog is reviewed as of November 16, 2026. The repository includes no operative court calendar. The offline replay uses a synthetic closure with an explicitly scoped calendar.

The personal-injury policy records the selected incident, the limitations authority and the accrual and exceptions gap. It yields an unresolved result without a due date. A verified date identifies the deterministic result under the recorded evidence, authority date, and reviewed calendar. It does not certify the authenticity of a user-supplied document or undisclosed case orders. A date correction or dependency change stales previous results. Deadline work remains available even when the associated preparation has blockers.

## Document packages and exact review

The canonical format is structured JSON. It includes caption and section fields, paragraph numbering, signature metadata, a plain-text rendering, supporting evidence inventory, filing and variable fee metadata, service conditions and deadline references. It can be consumed by a future renderer that supports DOCX or PDF. The complaint template is a bounded preparation copy. Court-specific layout, signatures, attachments, requested relief and actual payment or service need separate review. Unknown required values are exposed as placeholders, and a draft with required placeholders cannot be marked reviewable.

Each populated factual field points to the exact assertion, source classification, locator and evidence identity or source message. The manifest binds the template version, matter revision, claim analysis, readiness report and procedural fingerprint. A reported condition remains attributed. The compiler does not turn a notice account into a conclusion about actual knowledge. It uses only schema-defined projections from the ledger and has no model-writing path. A model's upstream claim mappings cannot supply new facts or bypass required checks.

The bearer holder can record review of the current package by submitting the exact displayed digest and package ID with `reviewed: true`. That request attests to viewing the identified package. The review scope includes the action, matter revision, document package, destination, fee information, service information and deadline context. It does not certify counsel review, sign a document or grant external execution authority. There are no execution adapters for filing, submission, service, payment, correspondence, e-signature, negotiation or representation.

## Workspace and persistence

The workspace joins authorized matter state and current artifact projections. It shows goal, path, stage, parties, evidence, claims and defenses, blockers, questions, tasks, upcoming verified deadlines, drafts and review events. The timeline distinguishes recorded events, corrections, choices, analyses, deadline calculations, document generation and reviews. Filing and service events are historical reports from the ledger. The workspace can report generated packages and planned preparation tasks. It cannot mark an external act completed.

Tasks and next actions derive from current requirements and artifact state. Stable task IDs depend on the matter revision and source. Upcoming verified deadlines receive priority alongside blockers. A recorded exact review clears the matching draft review task. A stored workspace snapshot preserves tasks, dependencies and state at the time of projection.

The action tables share the private Matter Intelligence SQLite database. Artifacts are content-addressed, immutable and scoped by matter and revision. SQLite verifies the current matter using the existing optimistic revision boundary and inserts related artifacts atomically. Reads report freshness without changing historical bytes. Policy, procedure, claim, calendar and template dependencies participate in freshness checks. Identical inputs reuse the same artifact and original creation timestamp. Review and workspace records can be retrieved historically by ID.

## Development API

Use the [Matter Intelligence local configuration and per-matter bearer](matter-intelligence.md). The existing `POST /matters/{id}/documents` remains the evidence upload endpoint. Use `/action-documents` for preparation packages. Every action endpoint uses the matter release gate, sanitized errors and `Cache-Control: no-store`. Use synthetic or redacted data, a private operator-only database directory, and a local server with access logging disabled.

All paths below are relative to `/matters/{id}`.

| Method and route | Purpose |
| --- | --- |
| `GET /actions` | List bounded action definitions and deadline policies in the matter jurisdiction |
| `POST /readiness` | Evaluate with `revision`, `action_id`, and relevant `claim_analysis_id`, `event_id`, `party_id` and `user_party_id` |
| `GET /readiness/{id}` | Read a readiness report and its freshness |
| `POST /deadlines/evaluate` | Evaluate with `revision`, `rule_id` and optional `event_id` |
| `GET /deadlines`, `GET /deadlines/{id}` | Read revision deadlines or a specific historical result |
| `POST /action-documents` | Assemble from a current `readiness_id` and `revision` |
| `GET /action-documents/{id}` | Read exact package, manifest and freshness |
| `GET /workspace`, `POST /workspace`, `GET /workspace/{id}` | Project, save with `revision`, or retrieve a workspace snapshot. Projection accepts an optional `as_of` date for how deadlines are displayed. |
| `GET /tasks`, `GET /tasks/{id}` | Read current derived tasks |
| `POST /reviews`, `GET /reviews/{id}` | Record or retrieve exact review. The POST body requires `revision`, `package_id`, `displayed_digest` and `reviewed: true`. |

For a Richmond complaint replay, use matter statements for jurisdiction, the recorded forum `va_richmond`, the user caption name (`Self name` on a party declared with `new_party_role: user`), amount sought and scoped incident observations. Upload medical documentation and the venue record to their incident. Link party identity via operator-reviewed registry records. Obtain and confirm the litigation offer from `POST /procedure`, then create an analysis against the resulting revision. Repeat explicit choice and analysis after a matter change before evaluating the new readiness. Historical artifacts retain their revision even after later updates.

## Validation and release

```sh
python -B scripts/validate_repository.py
python -B scripts/legal_action_os.py validate
python -B -m unittest discover -s tests -p test_legal_action_os.py -v
python -B -m unittest discover -s tests -v
python -B scripts/run_evaluations.py
python -B scripts/legal_action_os.py benchmark --iterations 30
```

The action suite covers the Richmond fall through exact review, a scoped service deadline with reproducible calendar logic, stale and immutable artifacts, cross-matter access, fabricated inputs and injection, and a synthetic contract-demand template using the existing Virginia contract analysis. Synthetic portability is evidence about the architecture. The development API exposes a Richmond complaint preparation reference and the two documented deadline policies.

The benchmark reports operation p50 and p95 for local readiness, deadline derivation, document assembly, workspace projection, task generation, staleness and artifact persistence. It uses synthetic SQLite data and retained evidence. Model, provider, HTTP and external network timing are excluded. CI checks these stages, the repository regression suite, mapped evaluation fixtures, the production image and production release gates.

Per-matter authorization is a development bearer, and local retention is the operator's responsibility. Action OS makes no new provider calls with matter facts and adds no sensitive prompt or evidence logging. Before private beta or release, require independent legal and jurisdiction-specific legal-services/UPL review, substantive and procedural currentness review, template and deadline review, privacy and provider data-handling review, retention policy and access-control approval, abuse controls, monitoring, deployment review, broader adversarial testing and explicit release approval.
