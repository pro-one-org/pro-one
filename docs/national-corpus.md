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

## Federal foundation

| Registry source | Normalized unit | Edition check | Currentness |
| --- | --- | --- | --- |
| `olrc` | U.S. Code section with title and available chapter hierarchy | USLM title number, title identifier and embedded public-law release point | Unresolved |
| `govinfo_cfr` | CFR section with title and part hierarchy | Annual volume title and embedded revision year | Historical |

The official-publisher flag describes who supplied the artifact. The
GovInfo XML is a rendition of the annual edition. Text is extracted from
supported section elements. The exact snapshot retains editorial material,
source credits, reserved sections and unsupported structures for audit.
Effective periods and independent currentness verification remain pending.
If the requested catalog year conflicts with the embedded date, ingestion
rejects the volume. The real GovInfo 2024 Title 1 Volume 1 XML returned
embedded revision year 2023 during acceptance.

Attribute U.S. Code material to the Office of the Law Revision Counsel and
CFR material to the Government Publishing Office and Office of the Federal
Register. The import targets federal statutory and regulatory text. Retained
publisher files may contain seals, images and other ancillary material.
Redistribution review of those materials is pending.

- [OLRC release-point archive](https://uscode.house.gov/download/releasepoints/us/pl/119/88/usc-rp@119-88.htm)
- [GovInfo CFR coverage and revision cycle](https://www.govinfo.gov/help/cfr)
- [GovInfo CFR bulk data and XML resources](https://www.govinfo.gov/bulkdata/CFR)

## Operations

Run from the repository root in the development Python environment.

```powershell
python -B scripts/national_corpus.py sources
python -B scripts/national_corpus.py ingest olrc 119-88/1
python -B scripts/national_corpus.py ingest govinfo_cfr 2023/1/1
python -B scripts/national_corpus.py stats
python -B scripts/national_corpus.py search US statute --citation "1 USC 1"
python -B scripts/national_corpus.py search US regulation --citation "1 CFR 1.1" --currentness historical
python -B scripts/benchmark_national_corpus.py --scale 10000
```

The CLI makes one HTTPS request per build and refuses redirects. The
download and single decompressed XML member each have an 8 MiB limit.
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
| First ingestion and one repeat per source | 4 requests, 2 snapshots, 289 observations, zero new versions on repeats |
| Live database size | 2,879,488 bytes |
| Offline synthetic benchmark | 10,000 regulations, 101 correct rank-one hits and zero results on 3 scope negatives |
| Local benchmark measurement | 1.525 seconds to ingest and index, 0.744 ms p95 positive query latency, 22,945,792-byte database |
| Model/API usage for the synthetic benchmark | Zero requests, calls, tokens and estimated model cost |

The synthetic benchmark uses generated section identities and short, unique
text anchors. It measures this parsing and retrieval path with labeled
positives and scope negatives. It provides no estimate of nationwide recall.
Fixture tests cover raw-byte provenance, changed text, competing same-edition
versions, cross-source observations, citation and jurisdiction isolation,
historical exclusion, rollback and malformed inputs.

## Outstanding Corpus v1 acceptance

The federal foundation covers one U.S. Code title release and one annual
CFR volume. Federal case ingestion into this layer, Federal Register,
federal judiciary sources, representative state sources, a verified Research
Core bridge, legal relationship and currentness evidence, live cross-provider
identity checks, broader source rights review and a labeled mixed-source
evaluation remain pending. The first benchmark covers the corpus path and
excludes mixed-source research and live model costs.
