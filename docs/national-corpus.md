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

## Source coverage

| Registry source | Normalized unit | Edition check | Currentness |
| --- | --- | --- | --- |
| `olrc` | U.S. Code section with title and available chapter hierarchy | USLM title number, title identifier and embedded public-law release point | Unresolved |
| `govinfo_cfr` | CFR section with title and part hierarchy | Annual volume title and embedded revision year | Historical |
| `courtlistener` | Federal opinion with separate role and provider citation edges | v4 citation lookup agrees with the hydrated case identity and requested court | Unresolved |
| `virginia_code` | Virginia Code section with title and chapter hierarchy | Official section heading agrees with the requested citation | Unresolved |

The official-publisher flag describes who supplied the artifact. The
GovInfo XML is a rendition of the annual edition. Text is extracted from
supported section elements. The exact snapshot retains editorial material,
source credits, reserved sections and unsupported structures for audit.
Effective periods and independent currentness verification remain pending.
If the requested catalog year conflicts with the embedded date, ingestion
rejects the volume. The real GovInfo 2024 Title 1 Volume 1 XML returned
embedded revision year 2023 during acceptance.

CourtListener is a derivative opinion source. Its adapter uses the Research
Core client and scope checks, stores exact public response bytes in a replay
envelope, and retains provider-scoped opinion IDs, roles, citations and
relationships. The envelope carries response bodies and resource paths.
It excludes request credentials. Reported citation lookup establishes
provider identity. Independent official-text comparison and later treatment
remain unresolved. The accepted Brown opinion was supplied as combined text.

Virginia's adapter reads the official section page and extracts the scoped
statutory body. The exact HTML retains editorial history. Pages containing
multiple bodies, including the sampled § 55.1-1244, require an edition-aware
parser before ingestion.

Attribute U.S. Code material to the Office of the Law Revision Counsel and
CFR material to the Government Publishing Office and Office of the Federal
Register. The import targets federal statutory and regulatory text. Retained
publisher files may contain seals, images and other ancillary material.
Redistribution review of those materials is pending.

- [OLRC release-point archive](https://uscode.house.gov/download/releasepoints/us/pl/119/88/usc-rp@119-88.htm)
- [GovInfo CFR coverage and revision cycle](https://www.govinfo.gov/help/cfr)
- [GovInfo CFR bulk data and XML resources](https://www.govinfo.gov/bulkdata/CFR)
- [CourtListener v4 API usage](https://wiki.free.law/c/courtlistener/help/api/rest/v4/api-usage)
- [Virginia Code and publisher coverage notes](https://law.lis.virginia.gov/vacode/)

## Operations

Run from the repository root in the development Python environment.

```powershell
python -B scripts/national_corpus.py sources
python -B scripts/national_corpus.py ingest olrc 119-88/1
python -B scripts/national_corpus.py ingest govinfo_cfr 2023/1/1
python -B scripts/national_corpus.py ingest courtlistener "scotus/347 U.S. 483"
python -B scripts/national_corpus.py ingest virginia_code 55.1/12/55.1-1220
python -B scripts/national_corpus.py ingest virginia_code 1/2/1-200
python -B scripts/national_corpus.py stats
python -B scripts/national_corpus.py search US statute --citation "1 USC 1"
python -B scripts/national_corpus.py search US regulation --citation "1 CFR 1.1" --currentness historical
python -B scripts/evaluate_national_corpus.py
python -B scripts/benchmark_national_corpus.py --scale 10000
```

Public publisher imports make one HTTPS request per build. The CourtListener
import uses the server-side `COURTLISTENER_API_TOKEN` and budgets at most
12 requests, eight opinions and 5.5 MB of response bytes. All adapters refuse
redirects. The maximum artifact size is 8 MiB, with a 1 MiB limit for Virginia
pages. The single decompressed OLRC XML member has an 8 MiB limit.
Operators can repeat a failed request after the source becomes available.
SQLite commits a whole snapshot or rolls it back. A committed snapshot is
the restart boundary. A refresh of matching bytes and parser revision
updates the last retrieval timestamp. A changed representation keeps its
prior observation. Different representations under one edition are flagged
for review. There is no automatic edition or version promotion.

The SQLite database and JSON build manifests live in `.local/national-corpus/`.
Each manifest identifies the build, provider, selector, parser revision,
source hash and counts for committed records and new versions. Query output
includes snapshot and source-native locators. Preserve the database when
reproducibility requires the original artifact bytes.

Search requires a jurisdiction and an authority family. It applies edition,
currentness, provider, citation and opinion-role predicates before ranking.
Text search uses SQLite FTS5 and deterministic tie-breaking. The current-law
filter returns zero results until an evidence-backed currentness mechanism
exists.

## Verified foundation results

| Measure | Observed result |
| --- | --- |
| OLRC Title 1, release 119-88 | 39 authorities and versions |
| GovInfo CFR 2023 Title 1, Volume 1 | 250 authorities and versions |
| CourtListener, `347 U.S. 483` | 1 combined opinion, 21 source relationship edges, 5 requests |
| Virginia Code, §§ 1-200 and 55.1-1220 | 2 authorities and versions, 2 requests |
| Live corpus total | 292 authorities, 292 versions, 5 snapshots, 292 observations |
| Federal publisher refresh | 2 requests and zero new versions |
| Live database size | 3,268,608 bytes |
| Labeled live retrieval | 5 targets at rank one and zero results on 7 negatives |
| Offline synthetic benchmark | 10,000 regulations, 101 correct rank-one hits and zero results on 3 scope negatives |
| Local benchmark measurement | 1.738 seconds to ingest and index, 0.808 ms p95 positive query latency, 22,953,984-byte database |
| Model/API usage for the synthetic benchmark | Zero requests, calls, tokens and estimated model cost |

The synthetic benchmark uses generated section identities and short, unique
text anchors. It measures this parsing and retrieval path with labeled
positives and scope negatives. It provides no estimate of nationwide recall.
Fixture tests cover raw-byte provenance, changed text, competing same-edition
versions, cross-source observations, citation and jurisdiction isolation,
historical exclusion, opinion roles, relationship provenance, rollback and
malformed inputs. CourtListener could not resolve either sampled reporter
citation for Loper Bright during live acceptance. The operator received an
explicit error and the database retained its prior state.

## Outstanding Corpus v1 acceptance

Coverage is bounded to one U.S. Code title release, one annual CFR volume,
one federal case and two Virginia statutes. Federal Register, official federal
judiciary sources, additional representative states, a verified Research Core
bridge, legal relationship and currentness evidence, live cross-provider
identity checks, broader source rights review and a labeled mixed-source
research evaluation remain pending. The benchmark covers the corpus path.
Mixed-source research and live model costs remain unmeasured.
