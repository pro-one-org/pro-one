# National Normalized Legal Corpus v1

## Baseline and architecture decision

Protected `main` was synchronized at `ec1be937c0b5e77f9f113bbc83c13b4cf748a3ae`.
Before implementation, 457 unit tests, repository validation and 37 mapped
offline evaluations passed. Four unmapped evaluations remain subject to manual review.

The normalized corpus uses a separate SQLite file and a provider-neutral write
and retrieval interface. The existing CourtListener database and Research Core
provider contract keep their existing schemas. A later bridge must project
eligible, identity-checked evidence through that contract and all existing
verification gates. The first increment exposes an offline corpus operator
interface. Its records are proposed and carry explicit currentness uncertainty.

An authority is a legal identity. A version is a normalized representation
with an edition and content fingerprint. A snapshot is the exact byte sequence
received from a provider, and an observation links a version to its snapshot
and source-native locator. Identical bytes are stored once. Repeating a source
request with unchanged material is idempotent. Distinct versions and conflicting
representations remain available for review.

Source adapters own document selectors, URL construction, identity validation
and extraction. The source registry is code-owned. The corpus keeps original
publisher artifacts outside the curated graph.

## Implemented source coverage

| Publisher | Authority and bounded live sample | Update and provenance |
| --- | --- | --- |
| OLRC | 426 federal statutory identities across Titles 1 and 44, including 38 repeal markers | Two USLM release points. Title, chapter, release point, section identifiers and original ZIP. |
| GovInfo annual CFR | 250 historical sections from 2023 Title 1, Volume 1 | Annual volume. Embedded revision year, part hierarchy, XML and part authority citations. |
| GPO eCFR bulk | Three sections from Titles 1 and 8 | Unofficial editorial rendition. Exact XML and embedded title amendment metadata. Section currency unresolved. |
| GovInfo Federal Register | 112 preambles from January 30, 2026. Nine proposed rules, three recognized final rules, 96 notices and four other items. | Explicit issue date and document number. Full issue retained, with 14 explicit CFR part references and three section amendments in the latest parser revision. |
| CourtListener | Four Supreme Court opinion records across two cases and 41 source relationships | Citation lookup plus case hydration. Exact public JSON responses retained in a replay envelope. Derivative provenance. |
| U.S. Reports via GovInfo | One official Supreme Court reporter granule | Pinned PDF, reporter citation and case date. The granule combines judicial and editorial material. |
| Virginia General Assembly | Two statutory sections | Section HTML and title/chapter scope. |
| Maryland General Assembly | Three Real Property sections and two Declaration of Rights articles | Scoped HTML and January rendition selector. Publisher does not expose a reliable edition year in the sampled body. |
| Florida Legislature | Three Chapter 83 sections and 28 Article I constitutional sections | Online Sunshine markup, statutory edition heading and constitutional section anchors. |
| New York State Senate | Two Real Property sections and one constitutional section | Public HTML and embedded revision date. Some CLI fetches returned 403. Two exact public captures were independently fetched and parsed locally. |
| California Legislative Counsel | Two Civil Code sections | Three bounded ranges from the reviewed PUBINFO archive. Archive ETag, exact compressed members, CRCs, SHA-256 and operative text identifiers. |
| California Department of Industrial Relations | One Title 8 regulation | Publisher HTML with the title, section and operative body checked. Section currentness remains unresolved. |
| Judicial Branch of California | Two retained Title 8 court rules | Rule and edition headings, operative paragraphs and rule-history dates. Automated refresh is disabled under the publisher's site terms. |

No external publisher fetch runs in CI. Exact artifacts, manifests and SQLite files are ignored. The official-publisher flag describes the source channel. Both Brown records remain separately queryable. The pinned official granule and CourtListener opinion were linked as a derivative representation based on court, date, reporter citation, native IDs and pinned source evidence. Their text representations differ. Unchecked matches remain probable, conflicting or unresolved.

The California statute adapter uses the active-code flag and the pinned archive publication date of November 9, 2026. Currentness queries require the exact supported as-of date. Civil Code § 1941.1 includes an explicit January 1, 2026 effective date. OLRC repeal markers are stored separately from operative text. Federal Register classifications come from the issue's publication section and explicit action wording. A final-rule date is retained only when its wording is unambiguous. The underlying CFR effect of proposed, corrected or delayed material remains unresolved.

- [OLRC release archive](https://uscode.house.gov/download/releasepoints/us/pl/119/88/usc-rp@119-88.htm)
- [GovInfo CFR coverage](https://www.govinfo.gov/help/cfr)
- [Federal Register XML resources](https://www.govinfo.gov/bulkdata/xml/FR/resources)
- [United States Reports granule](https://www.govinfo.gov/app/details/USREPORTS-347/USREPORTS-347-483/context)
- [CourtListener v4 API usage](https://wiki.free.law/c/courtlistener/help/api/rest/v4/api-usage)
- [California PUBINFO format and code table evidence](https://github.com/cagov/caldata-legislation-tracker/blob/main/docs/ca-leginfo-bulk-download.md)
- [California legislative data downloads](https://downloads.leginfo.legislature.ca.gov/)
- [California official legislative information and reuse notice](https://www.leginfo.ca.gov/)
- [California court rules](https://courts.ca.gov/cms/rules/index/eight)
- [California Judicial Branch site terms](https://courts.ca.gov/about/terms-use)
- [California DIR conditions of use](https://www.dir.ca.gov/od_pub/conditions.html)
- [GovInfo policies and copyright notice](https://www.govinfo.gov/about/policies)
- [CourtListener terms](https://wiki.free.law/c/terms/courtlistener/courtlistenercom-terms-of-service-and-policies)

## Operations

Run in the development Python environment. CourtListener uses the existing server-side token.

```powershell
python -B scripts/national_corpus.py sources
python -B scripts/national_corpus.py ingest olrc 119-88/44
python -B scripts/national_corpus.py ingest olrc 119-138/1
python -B scripts/national_corpus.py ingest olrc 119-138/44
python -B scripts/national_corpus.py ingest govinfo_cfr 2023/1/1
python -B scripts/national_corpus.py ingest govinfo_ecfr 1
python -B scripts/national_corpus.py ingest govinfo_ecfr 8
python -B scripts/national_corpus.py ingest govinfo_register 2026-01-30
python -B scripts/national_corpus.py ingest courtlistener "scotus/347 U.S. 483"
python -B scripts/national_corpus.py ingest courtlistener "scotus/332 U.S. 380"
python -B scripts/national_corpus.py ingest us_reports 347-483
python -B scripts/national_corpus.py ingest virginia_code 55.1/12/55.1-1220
python -B scripts/national_corpus.py ingest maryland_code grp/8-211
python -B scripts/national_corpus.py ingest maryland_constitution c0/24
python -B scripts/national_corpus.py ingest florida_code 83.51
python -B scripts/national_corpus.py ingest florida_constitution article-I
python -B scripts/national_corpus.py ingest new_york_code RPP/226-B
python -B scripts/national_corpus.py ingest new_york_constitution CNS/A1S6
python -B scripts/national_corpus.py ingest california_code 2025/civil-habitability
python -B scripts/national_corpus.py ingest california_regulations 3203
python -B scripts/national_corpus.py stats
python -B scripts/national_corpus.py replay SNAPSHOT_ID
python -B scripts/national_corpus.py search US-CA statute --currentness current --as-of 2026-11-09
python -B scripts/national_corpus.py search US opinion --citation "347 U.S. 483"
python -B scripts/national_corpus.py identity LEFT_VERSION RIGHT_VERSION
python -B scripts/evaluate_national_corpus.py
python -B scripts/benchmark_national_corpus.py --scale 10000
python -B scripts/benchmark_mixed_corpus.py
python -B scripts/accept_national_research.py --courtlistener .local/courtlistener-acceptance-nov12.sqlite3
```

The live evaluation also uses OLRC Title 1, Virginia § 1-200, the bounded
New York § 235-b capture and the source editions in the table. The mixed
benchmark requires the six ingested authority families. Local output is
stored under `.local/national-corpus/`. The importer validates a bounded
artifact and commits it atomically. A repeat with identical bytes and parser
revision updates retrieval metadata. A corrected rendition remains traceable
to its earlier version. Offline replay preserves the original retrieval
timestamp. Currentness and opinion role are deterministic filters.

Development mode enables corpus evidence when
`PRO_ONE_NORMALIZED_CORPUS_PATH` names the existing local database. The
bridge opens it read-only, enforces the planned matter scope, verifies the
raw artifact hash, reruns the matching registered parser and checks the
version and source-native locator before generating exact excerpts. Corpus
opinions remain searchable for review. The bridge replays CourtListener
citation resolution and projects separately attributed opinions together
through the existing role and citation controls. Official reporter granules
remain corpus evidence for identity review. Register material
is retained as publication context and is ineligible as operative law
in semantic synthesis. The existing proposal, independent verifier and
deterministic response validation remain in the response path.

## Verified increment

The working corpus has 840 authority identities, 1,270 versions, 34
snapshots, 1,783 observations, 1,463 source relationship rows and three
cross-provider identity checks. The annual CFR and eCFR renditions of
1 CFR 1.1 and 1 CFR 2.2 share authority identity and retain distinct versions.
OLRC releases 119-88 and 119-138 coexist for all 426 sampled identities.
Their normalized text hashes matched across both releases. The corpus
preserves the edition change without treating it as an amendment.
California's two earlier observations
and their current-as-of versions coexist. The counts include preserved
parser-revision observations for OLRC Title 1, GovInfo CFR and Federal Register.

The labeled retrieval sample spans all six jurisdictions. All 22 targets
ranked first, with precision at 1 of 1.00 and precision at 3 of 0.33
under a one-target-per-query label. All 14 negative controls returned
zero rows. Two labeled cross-provider identity checks matched.
The 30,000-record benchmark replicates real normalized shapes across six
families. It processed 30,000 edges in 26.53 seconds including indexing,
with 1,131 records per second, 0.782 ms p95 retrieval latency, 100.23 ms
total for unchanged refresh and a 221,163,520-byte database. Python
allocations peaked at 916,625 traced bytes. That measurement excludes
SQLite native allocations and OS cache.

Five state-scoped packages rendered through the offline Research Core,
including a Virginia statute plus CourtListener case and the bounded
California as-of request. Separate federal statute and historical
regulation evidence checks passed. A live Sol Virginia mixed-source run
answered with verified synthesis after four calls, including independent
semantic verification. Reported usage was 18,249 input and 2,023 output
tokens. All responses remained development-only.
The federal statute-and-case run paired Title 44 with the separately
attributed Merrill lead and dissent. Live Sol completed five calls and
verified two claims using 31,420 input and 3,906 output tokens.
Virginia and Florida passed a development comparison through
`/research/compare`, which renders two separately verified state answers
side by side. Federal statute/regulation and Register/regulation live Sol
checks also answered and independently verified four and two claims,
respectively. Register material was publication context. The two runs used
31,942 input and 5,159 output tokens across 12 calls.
The four live scenarios used 81,611 input and 11,088 output tokens across
21 calls. The uncached standard-rate estimate is $0.27. [Model pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol)

## Outstanding Corpus v1 acceptance

Expanded amendment and supersession relationships and broader
operative currentness remain open. The eCFR title API exposed publisher
coverage metadata, but the matching point-in-time XML returned HTTP 406
for the attempted title, part and section routes. GPO bulk XML supplied
the text for the three bounded sections with unresolved currentness.
The Federal Register adapter indexes preambles and preserves
full issue bytes. The bounded sample provides no nationwide recall estimate.

### State source investigation

These publisher entry points are candidates for additional state adapters.
Each requires its own section identity, edition and operative-text checks.

| State | Publisher format and integration question |
| --- | --- |
| Maryland | The General Assembly's HTML and PDF portal distinguishes January and October snapshots. The adapter must preserve the selected edition and distinguish law text from session enactment data. [Maryland statutes portal](https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes) |
| Florida | The legislature's Online Sunshine site exposes year-specific statutes and a download option. The adapter must preserve the displayed edition and distinguish statutes, the constitution and session laws. [Florida statutes and constitution](https://www.leg.state.fl.us/Statutes/) |
| New York | The Senate JSON API exposes law IDs, section locations and weekly publication updates. It requires a key, and the site lists CC BY-NC-ND 3.0 for its content. Review applicability to the planned normalized redistribution before choosing this route. [NYS Laws API](https://legislation.nysenate.gov/static/docs/html/laws.html), [Open Legislation terms](https://legislation.nysenate.gov/) |
| California | The Legislature exposes a legislative downloads directory. The interactive codes endpoint returned HTTP 403 during source discovery. Evaluate the bulk artifacts and documentation for code-table coverage and update semantics. [California legislative downloads](https://downloads.leginfo.legislature.ca.gov/) |

### Optional derivative dataset

Vaquill publishes Open US Law snapshot `v2026.09.1` under CC BY-NC 4.0
for the compilation and metadata. The publisher lists Apache-2.0 for its
scrapers and treats underlying statutory, regulatory and constitutional
text separately from its normalization. Sharing or adapting the compilation
under that license is limited to noncommercial use and requires appropriate
credit, a license link and disclosure of changes. [Publisher data license](https://github.com/Vaquill-AI/open-us-law/blob/main/data/LICENSE.md), [Creative Commons license](https://creativecommons.org/licenses/by-nc/4.0/)

The dataset is a candidate for derivative discovery. It reports government
source URLs and snapshot metadata. A future import would need to pin the
snapshot and hashes, retain the original attribution and distinguish
provider-derived status fields from official identity and currentness evidence.
This foundation uses publisher feeds and CourtListener. It includes zero
Open US Law records. [Dataset card](https://huggingface.co/datasets/vaquill/open-us-law)
