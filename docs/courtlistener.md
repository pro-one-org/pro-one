# CourtListener corpus and research milestone

CourtListener / Free Law Project is an optional case-law and existing federal-document provider. Official legislatures, courts and agencies remain the providers for statutes, rules, forms and guidance. External ingestion never approves a capability or promotes material into the canonical legal graph.

CourtListener supplies legal data; Pro-One owns research planning, authority comparison, evidence-linked claims, independent verification, deterministic validation, capability compilation and release policy.

## Access and verified contracts

The implementation uses `https://www.courtlistener.com/api/rest/v4/` with a server-only `Authorization: Token …` header. Official documentation and model definitions were checked November 3–4, 2026: [REST v4](https://wiki.free.law/c/courtlistener/help/api/rest/v4/rest-api-v47), [search](https://wiki.free.law/c/courtlistener/help/api/rest/v4/search), [case law](https://wiki.free.law/c/courtlistener/help/api/rest/v4/case-law), [citation lookup](https://wiki.free.law/c/courtlistener/help/api/rest/v4/citation-lookup), [usage](https://wiki.free.law/c/courtlistener/help/api/rest/v4/api-usage), [citation graph](https://wiki.free.law/c/courtlistener/help/api/rest/v4/citations), [PACER data model](https://wiki.free.law/c/courtlistener/help/api/rest/v4/pacer-data), [bulk data](https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data), and [replication](https://wiki.free.law/c/courtlistener/help/api/replication/database-replication-for-organizations-and-researchers).

| Surface | Implementation |
|---|---|
| Keyword / semantic search | GET `search`, `type=o`, server-selected court filters, `order_by=score desc`; `semantic=true` for semantic discovery |
| Case hydration | GET individual `courts`, `dockets`, `clusters`, `opinions`; validate every relationship |
| Citation identity | POST form-encoded `text` to `citation-lookup`; exactly one resolved cluster and matching normalized base citation |
| Usage | GET `api-usage`; use current server-reported user quota; omit membership/account data |
| Relationships | GET bounded `opinions-cited`, or opinion cited IDs / bulk edges; incoming/outgoing indexes and depth |
| Existing archive | GET `docket-entries` and `recap-documents`; verify document membership in entry first |
| Bulk | Stream local UTF-8 CSV / CSV.bz2 by table with PostgreSQL escaping into indexed staging; join into normalized bundles |
| Future replication | Normalized `CaseBundle` / ingestion-source boundary; no replication connection or access provisioned |

No CourtListener token or live model key was available for this milestone. **Authenticated downloads: zero. Authenticated API calls: zero. Live semantic-model calls: zero.** Public documentation and public cluster metadata were checked; the authenticated wire behavior is tested with offline transports. Access still needs live acceptance testing with an authorized account.

Access is subject to Free Law Project's current terms, membership limits, quotas and commercial arrangements. Do not assume today's access terms persist. No sign-up, payment, account rotation, quota evasion, PACER credentials or purchase/fetch APIs are implemented. The fixed endpoint allowlist cannot call `recap-fetch`.

### Authorized live acceptance

Set `COURTLISTENER_API_TOKEN` in the server environment. Run each phase with the same fresh acceptance database under `.local/`. Use the quota snapshots to leave room between phases when the active window is nearly exhausted. The command consults the [v4 usage endpoint](https://wiki.free.law/c/courtlistener/help/api/rest/v4/api-usage) and makes at most five ordinary requests per invocation, plus up to two usage requests against the separate usage quota.

```text
python -B scripts/accept_courtlistener.py discover
python -B scripts/accept_courtlistener.py hydrate
python -B scripts/accept_courtlistener.py refresh
python -B scripts/accept_courtlistener.py relationships
```

- **Discover** checks two scoped keyword pages for distinct results and one scoped semantic page for results. This measures API compatibility and latency. Relevance requires separately labeled queries.
- **Hydrate** downloads the known Virginia cluster for `278 Va. 84`, checks its court, docket and opinion joins, and verifies a corpus round trip, scoped retrieval and repeat ingestion. The report records each opinion's role, text format, length and hash.
- **Refresh** bypasses the resource cache and checks the same invariants again. Compare opinion hashes and the ingestion result across the two reports. If the provider returns unchanged content, a real change transition remains unobserved. The offline suite exercises that transition with a changed fixture.
- **Relationships** resolves the live base citation, checks the persisted identity, reads and stores one outgoing edge, and exercises safe normalization of a real 404.

Retain the JSON reports locally. On a passing phase, compare matching quota windows before and after the run and record request counts separately. Concurrent requests and rolling resets can affect the observed delta. Check the reported text formats against the provider response if the case uses a fallback. A phase that stops for quota or an API error emits a safe reason and attempted-request metrics and exits with code 2. Re-run it when the provider permits. Run hydration initially on a fresh database so cached resources from another run cannot serve as evidence of new downloads. This acceptance procedure has offline transport coverage. Authenticated acceptance remains pending.

Malformed search hits, citation identities and pagination URLs yield safe error codes. A citation edge must match the requested opinion on the filtered side before the client hands it to the corpus.

## Configuration and operation

Set `PRO_ONE_AUTHORITY_NETWORK=courtlistener`, `COURTLISTENER_API_TOKEN` and optionally `PRO_ONE_CORPUS_PATH` in the server environment. Tokens cannot be supplied by the browser or model. The default corpus location, when network access is explicitly selected, is `.local/courtlistener.sqlite3`. Without a token, an existing corpus can still be used; an empty collection yields an explicit support gap. Set only `PRO_ONE_CORPUS_PATH` to use a local/bulk corpus without network access. With neither setting, research performs no corpus file I/O.

Set `PRO_ONE_AUTHORITY_NETWORK=courtlistener,virginia_official` to enable both network providers for one research request. The official adapter can recheck sources already linked to an exact capability. A successful fetch with changed text drops excerpts that no longer match. A failed fetch leaves the proposed repository evidence available with a provider limitation and unresolved currentness. CourtListener supplies separate case records and citation identities. Mixed-provider orchestration has offline transport coverage. A local acceptance run also assembled one package with a live excerpt from the [Virginia LIS test section](https://law.lis.virginia.gov/vacode/title8.01/section8.01-243/) and fixture case excerpts. Authenticated mixed-provider acceptance remains pending.

```text
python -B scripts/courtlistener_corpus.py --database .local/courtlistener.sqlite3 stats
python -B scripts/courtlistener_corpus.py --database .local/courtlistener.sqlite3 ingest --state Virginia --topic premises_liability --mode semantic --max-results 6 --max-pages 2 --max-requests 30 --max-seconds 30 --resume
python -B scripts/courtlistener_corpus.py --database .local/courtlistener.sqlite3 search notice --state Virginia
python -B scripts/courtlistener_corpus.py --database .local/courtlistener.sqlite3 show 1058333
python -B scripts/courtlistener_corpus.py --database .local/courtlistener.sqlite3 lookup "278 Va. 84"
python -B scripts/courtlistener_corpus.py --database .local/courtlistener.sqlite3 refresh 1058333
python -B scripts/courtlistener_corpus.py --database .local/courtlistener.sqlite3 graph 123 --refresh
python -B scripts/courtlistener_corpus.py --database .local/courtlistener.sqlite3 read-recap 123 --entry 456
```

Identifiers in the last two commands are placeholders for authorized existing archive records. The CLI reports safe errors and Retry-After seconds; it never sleeps through a throttle. Re-run an ingestion with the same legal scope and `--resume`. Checkpoints retain completed clusters and the validated cursor, including partial-page progress. A different scope gets a different checkpoint. Request, page, document, byte and runtime caps apply across an operation. HTTPS uses a fixed host, no redirects/proxies, bounded socket deadlines and bounded streaming reads. Only same-endpoint, unchanged-scope continuation URLs can yield cursor tokens. 401/403, 404, HTTP/per-citation 429 and malformed data fail safely without raw error bodies.

```text
python -B scripts/courtlistener_corpus.py --database .local/bulk.sqlite3 bulk --courts courts.csv.bz2 --dockets dockets.csv.bz2 --clusters clusters.csv.bz2 --opinions opinions.csv.bz2 --citations citations.csv.bz2 --opinions-cited opinions-cited.csv.bz2 --max-rows 10000 --max-clusters 1000
python -B scripts/build_capability.py --jurisdiction Virginia --legal-area torts --topic premises_liability --provider courtlistener_corpus --corpus-path .local/bulk.sqlite3 --output .local/proposed-review
```

Bulk ingestion is a bounded streaming proof, not a nationwide mirror manager. Every table load reports its staged count. Raise explicit caps or partition large snapshots externally; partial/inconsistent snapshots retain unresolved joins in staging. Nothing evaluates SQL from a dump. Future replication can emit the same normalized bundles without changing the legal compiler.

## Corpus and provenance

SQLite tables store courts, dockets, clusters, individual opinions, exact text versions, metadata versions, citations, edges, candidate treatment signals, API resource cache, citation verifications, checkpoints, entries and archive documents. WAL and indexed joins support incremental ingestion. FTS5 retrieves within exact state/sovereign/court/date boundaries; a parameterized keyword fallback works without FTS5. Court hierarchy, publication and opinion role precede text score in ranking. The initial reviewed court map covers Virginia and Maryland state appellate courts plus selected federal courts for archive/metadata inspection. **General legal answers remain state-scoped; nationwide and federal substantive research are not enabled.** Unknown courts are never silently assigned a state or hierarchy.

Text and metadata versions survive refresh. Changed content is marked `changed_review_required`, and reimporting identical content cannot reset that state. Removed/unavailable opinions are withheld from retrieval. Records retain first seen, last fetched, last checked, decision date, provider identifiers and SHA-256 content hashes. A 30-day metadata/identity cache reduces requests; cache age does not establish legal currentness. No corpus database or downloaded snapshot is committed. Conversation state and user documents are never written to the corpus.

## Case structure and evidence

Court → docket → cluster → opinion remains intact. Cluster metadata and citations are shared; opinion text, type, hash and cited edges remain individual. `html_with_citations` is preferred; a non-executing parser removes active content and preserves paragraph anchors. Plain text is the fallback. Exact excerpts retain normalized-text start/end offsets, paragraph/anchor locator, context window, opinion/cluster identity, role, candidate classification and hash. A locator is not a verified reporter pin cite.

The provider's `010combined` role remains **mixed**. Lead, unanimous, plurality, concurrence, concurrence in part, dissent, addendum and other document roles remain distinct. Only majority/lead/unanimous passages may support synthesized general rules; contrary roles may qualify or conflict. Combined text is withheld from majority-rule synthesis until separately classified. The compiler retains non-majority evidence and conflicts but excludes it from proposed general rules. Publication is preserved independently from role; neither “Published” nor a court rank establishes binding force.

## Citation and treatment assurance

Base-citation lookup verifies identity only: unique cluster, canonical citation, case name and requested jurisdiction. A bulk snapshot can establish identity only through a unique exact citation join. Offline fixtures are marked `fixture_verified`, never live verified. The `/research/citation` development endpoint accepts an optional expected case name and rejects mismatch. Quotation, pin cite, proposition, precedential force and currentness require their own checks. Unknown citations, ambiguous results, unseen passage IDs, invented quotes and legal text outside the allowed claim statement fail closed.

Edges preserve outgoing/incoming relationships and depth. One optional bounded incoming-edge expansion follows discovery when page budget remains. The graph screens up to 20 of the most recent available, later-dated citing opinions in the local corpus. It checks for a known exact citation near treatment language in the same paragraph and returns one candidate per citing opinion. Each candidate retains the matched citation, language, passage and locator, court, decision date, opinion role, and fetch timestamp. The graph reports when it has more eligible citing opinions than the screening limit.

Screening uses the current graph and text when requested. An opinion or edge added later can contribute as soon as both opinions are available, and unavailable opinions are excluded. A signal requires human review. Controlling force and currentness remain unresolved, including when the screen finds no candidates.

Opinion refresh replaces the references carried by the opinion payload while retaining separately collected graph edges and their depth. The corpus migrates older databases in place. Legacy depth-one edges that match the stored opinion's reference list are classified as opinion references because the original table did not record their origin. Other legacy edges are retained as graph data. A fresh graph fetch can reestablish graph provenance for overlapping legacy edges.

## Research and synthesis

The legal planner emits only server-approved issue concepts, court/date scope and budgets. Names, employer/retailer identity, narrative, uploaded documents and user goals are excluded from authority queries. Model suggestions must pass a legal-vocabulary allowlist; they cannot select hosts, courts, cursors or policy.

Compiled collections may be augmented with a configured external provider; general research needs no workflow ID. Official statutes and CourtListener cases keep separate source types and authority metadata. Hydrated text and citation identity are checked before evidence assembly. Live-model research can use three stages:

1. A strict proposal call receives bounded evidence and proposes claims with supporting, qualifying and conflicting passage IDs.
2. A **separate verifier call per candidate** receives only that candidate, its cited evidence and relevant jurisdiction/qualification metadata. It receives no conversation, private facts or proposer rationale. Partial support, omitted conflicts, unsupported fragments and jurisdiction mismatch prevent acceptance.
3. Deterministic checks enforce allowed IDs, exact source bindings/hashes, role, citation identity, jurisdiction, qualifications, all required citations and exact accepted rendering text. Rendering independently repeats validation.

The ledger records proposition, issue, source-role relationships, supporting/qualifying/conflicting cases, jurisdiction, research date, treatment/currentness uncertainty, evidence bindings, verifier version and development verification state. A verifier is not a citator, court, outcome predictor or release approver. If either model stage fails, the original exact-text evidence plan remains. The live provider implementations share the same model-neutral request interface. Live semantic quality is unmeasured until credentials and reviewed adversarial labels are available.

## RECAP document boundary

Only existing metadata and available extracted text/OCR are read. The document detail serializer does not carry the parent entry, so entry membership is checked before detail fetch. Description-based “complaint/motion/order” is merely a candidate classification; every result remains an unclassified filing, `is_precedent=false`. Allegations are not established facts; briefs are not law. Archive text uses a separate deterministic document-inspection channel and cannot support research propositions. Embedded instructions remain quoted untrusted document content. OCR and missing-text uncertainty are displayed. No PACER request is possible.

## Proof, scale and limits

Choose **Try CourtListener research example** in the product. The fixture reconstructs two excerpt-only API-shaped cases from previously checked official sources: [Fultz](https://www.courtlistener.com/opinion/1058333/fultz-v-delhaize-america-inc/) and [Austin](https://www.courtlistener.com/opinion/1060050/austin-v-shoneys-inc/). Public cluster identities are real; the demo's docket/opinion IDs and API records are synthetic. The demo separates majority excerpts for contract testing; it makes no claim about authentic CourtListener role segmentation. The in-memory fixture database is discarded after the response. Its fixed proposer and separately invoked fixed verifier demonstrate orchestration, **not semantic model accuracy**.

The demo explains ordinary care, warning/open-obvious qualifications, the conditional owner-created-condition theory and unresolved facts/currentness in two synthesized paragraphs. It does not declare negligence or predict recovery. Named follow-ups display the same known evidence. An exact named citation example resolves fixture metadata; arbitrary quoted/case/pin-cite claims are explicitly unverified. Other arbitrary offline questions still require configured AI.

Run `python -B scripts/benchmark_research.py --scale 1000`. The committed [measurement](research-benchmark.json) covers twelve scope/retrieval scenarios, separate stage timings, a two-case multi-authority contract, and 1,000 synthetic duplicate cases for storage/FTS scaling. Synthetic counts are not downloads or legal coverage. The unit suite separately exercises authenticated wire shapes, safe errors, compressed bulk joins, history, resume, dissent, prompt injection, citation mismatch, mixed official/external evidence, compiler and RECAP. Existing workflow/capability suites and production release gates remain required. CI additionally builds and smoke-tests the production container.

Remaining work before release: authorized live API/model acceptance tests; broader reviewed court/issue policies; representative real-corpus relevance/entailment benchmarks; large-snapshot orchestration/replication; legal/source/treatment review; operational authentication, rate limits and monitoring. Public execution remains closed.

The first Virginia retrieval labels cover contract breach, contributory negligence and landlord repairs. They point to court-published opinions and their corresponding CourtListener clusters. Run the following against a locally ingested corpus.

```text
python -B scripts/benchmark_virginia_corpus.py --database .local/courtlistener.sqlite3 --limit 12
```

The benchmark supplies fixed area and issue labels to the same deterministic planner used by local research. It measures local FTS or keyword retrieval separately from model interpretation and answer quality. It records whether each labeled case is present, its distinct-case rank among the returned real-origin opinions, scope violations and latency. A missing target counts as a coverage gap. Fixture rows cannot count as target hits. The labels cover one known case per question, so unlabeled results need judgment before calculating precision. These are retrieval targets for engineering evaluation. Legal relevance beyond the selected target, opinion-role accuracy and currentness require separate review.

Contract breach and landlord repairs now have area-scoped research tags and query vocabulary. The extractor sees these tags as candidate classifications. The planner selects the query and court scope, and opinion excerpts are matched against the selected area's issue vocabulary. These routes require matching, citation-verified corpus evidence before they can produce an answer.
