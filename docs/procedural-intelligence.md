# Procedural Intelligence v1

The development endpoint takes a short lay description and returns supported
paths for the bounded subject and jurisdiction. The user selects a path. The next
response explains the selected stage using official evidence, identifies missing
facts and lists transitions whose prerequisites the user has supplied.

## Architecture and records

```text
Inquiry and stated outcome
  -> bounded subject and jurisdiction discovery
  -> Research Core substantive evidence
  -> cited options and signed choice receipt
  -> explicit path and stage request
  -> jurisdiction, forum, authority type and prerequisite checks
  -> normalized authority projection and Research Core assembly
  -> optional independent semantic verification
  -> deterministic validation, publication excerpts and canonical citations
```

The [versioned catalog](../data/procedural-intelligence.json) uses the same
`AuthorityVersion`, source observations and content identities as the
national corpus. Typed records describe jurisdictions, forum identifiers and
hierarchy, available paths, stages, completion conditions and transitions.
Requirements bind the proceeding, stage, forum and trigger to exact authority
references. Filing, fee, service and deadline payloads retain their distinct
fields. A local requirement must name a forum and have forum-specific evidence.
The repository validator checks the graph, including stage cycles, reachability,
registered filing systems and cross-reference scope.

Procedure uses the existing Research Core assembly, independent verifier,
generation contract and revalidating renderer. In development with a configured
model, a proposer can select a supplied proposition with exact evidence IDs.
The verifier receives only the selection and its citations, including
jurisdiction, proceeding, forum, stage, authority type, currentness, conditions
and limitations. Deterministic checks reject any text or binding outside the
catalog's eligible propositions. The deterministic renderer retains validated
source quotations when a model is absent, unavailable or rejected. The bounded
offline checks exercise this contract with a fixture proposer and verifier.

## Coverage and currentness

| Scope | Bounded implementation |
| --- | --- |
| Virginia | Premises-liability research and conditional insurance, demand, negotiated settlement and civil litigation options. Civil court and venue considerations, circuit court commencement, paper formatting, signatures, fee information, initial service and proof. Circuit civil response rules, Richmond scheduling material and later-stage appeal and judgment references. |
| Federal | Federal district court initial civil service under Rule 4(c)(1)–(2) in the December 1, 2025 edition. The December 1, 2024 edition is retained as historical. |
| Florida | Initial civil process under § 48.031(1)(a) as an official reference sample with unresolved currentness. |

The jurisdiction and forum registry describes court classes and one local court.
Venue and case-specific subject-matter jurisdiction remain open questions.
Filing and service payloads apply only to their stated scope and triggers.
The official fee and e-filing pages supply reference material. The court,
eligible channel, applicable amount and local exceptions require review.
The source date, effective date where established, review date, edition,
publisher locator and content fingerprints travel with the evidence.

The November 16, 2026 date is the sole reviewed as-of date for selected
development samples. The Virginia Code sample uses the operative section
rendition and 2026 Code update index. The Virginia rules sample uses the
operative compilation and the judiciary's amendment-order index. The federal
sample uses the pinned rules edition and the judiciary's current-rules page.
Each dated record identifies its basis and carries the hash of the verification
publication. For another requested date, or for unresolved, historical,
superseded or proposed evidence, the endpoint serves a reference excerpt
without actionable requirement details or an available transition. A retrieval
timestamp alone cannot promote a record.
[Virginia Code updates](https://law.lis.virginia.gov/vacodeupdates/),
[Virginia rule amendments](https://www.vacourts.gov/courts/scv/amend),
[Federal civil rules](https://www.uscourts.gov/forms-rules/current-rules-practice-procedure/federal-rules-civil-procedure).

The bounded deadline rule links the triggering event and period to separate
counting authority, service-method effects, extensions and clerk closures.
The offline preview evaluates one reviewed combination with an explicit
trigger date, confirmed assumptions and an explicitly supplied open/closed
calendar. It fails closed when any necessary calendar entry is absent.
The HTTP response gives the rule and missing facts. User-specific deadline
calculation remains a later milestone.
[Virginia response rule](https://www.vacourts.gov/static/courts/scv/rulesofcourt.pdf),
[Virginia time computation](https://law.lis.virginia.gov/vacode/title1/chapter2.1/section1-210/).

## Choice and legal-services controls

The option receipt is signed by the server, expires after one hour and binds
the inquiry, jurisdiction, review date, catalog version and offered paths.
The user's subsequent request names the option and, where needed, confirms a
forum and facts. The original inquiry and supplied facts stay out of model
requests in this endpoint. The response distinguishes inferred subject or
objective, user-supplied facts, missing facts and publisher evidence.

Output classifications include objective procedural facts, conditional
requirements, available options, strategy or legal judgment and reserved
legal acts. The last two classifications cannot be returned as eligible
procedural instructions. The model receives neither a choice-signing key
nor an execution interface. Production blocks the route before any
procedural research, model call or external act. Independent legal review
and jurisdiction-specific legal-services approval remain release gates.

The first round accepts this JSON at `POST /research/procedure` in development.

```json
{
  "message": "I slipped and fell at a restaurant in Virginia, I was injured, and I want them to pay me."
}
```

Send the same message together with the returned `choice_token` and the user's
`selected_path`. Selecting `va_litigation` returns court and venue
considerations. A later `stage` request requires the preceding completion
facts and a supported forum. `jurisdiction` accepts the confirmed scope
when the message leaves it open. `as_of` can request an explicit reference
date and defaults to the catalog's dated development sample. Inspect the
schema in development at `/docs`.

## Operators and evaluation

```text
python -B scripts/procedural_intelligence.py validate
python -B scripts/procedural_intelligence.py benchmark --iterations 30
python -B -m unittest discover -s tests -p test_procedural_intelligence.py -v
python -B scripts/procedural_intelligence.py capture federal .local/procedure-snapshots
python -B scripts/procedural_intelligence.py replay .local/procedure-snapshots .local/procedure.sqlite3
```

Each capture selects one code-owned publisher URL. The existing corpus transport
bounds requests, bytes and time and rejects redirects. The replay command
expects the catalog's pinned publisher and status files, named by selector.
Changed publisher bytes are saved under their hash for review. Replay checks
every hash, verifies exact normalized excerpts at the selected publication
locators and ingests idempotently into the existing SQLite corpus. Archived
raw bytes and local databases go in the ignored `.local/` directory.
The repository contains the normalized excerpts and metadata needed for
deterministic offline CI. Replay of the exact capture requires the retained
local publisher copies, including the status files.

The offline evaluation covers the lay compensation round trip, explicit
choice, document response, venue uncertainty, filing fees and formatting,
entity/service proofs, the deadline trigger and calendar, scope and publication
type isolation, historical and unresolved authorities, local overlays,
unsupported model proposals and the production gate. The benchmark measures
one two-request offline Virginia round trip, including Research Core assembly
and rendering. It measures neither nationwide retrieval nor live model latency.

Matter Intelligence, the Claim & Element Engine, Action Readiness, Forms &
Document Assembly, the Deadline & Event Engine, Matter Management, Filing &
Service Integrations and broader jurisdiction coverage are later milestones.
