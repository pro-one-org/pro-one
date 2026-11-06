# High-Assurance Legal Operating System

Capabilities define what Pro-One can research and explain. Workflows define structured legal processes. The control rule is **no authoritative support means no confident legal claim**, rather than requiring a workflow for every question.

```text
Legal Graph -> Capabilities -> General Research -> Optional Workflows

question / facts / document
  -> candidate matter understanding
  -> jurisdiction + sovereign + area + legal topics
  -> deterministic capability resolution
  -> compiled capability OR bounded authoritative discovery
  -> source text + provenance + passages + uncertainty
  -> grounded claims
  -> shared generation -> deterministic validation
  -> revalidated rendering + canonical citations
```

## Three layers

1. General research discovers evidence without a workflow or compiled capability. Coverage depends on configured authoritative collections, not model memory.
2. Capabilities organize reusable jurisdiction/subject packages. One premises-liability package supports many stores/restaurants/fact patterns without prescribing conversations or deciding user-specific issues.
3. Workflows retain strict procedural scope, intake, risk and readiness checks. Virginia DC-402, Virginia SCC records and Maryland civil summons remain available as specialized modules, associated with broader capabilities.

## Graph and migration

The repository remains versioned JSON with Draft 2020-12 schemas, not a graph database. Existing source, passage, rule, process-step, document, intake, risk, response, evaluation and workflow domains remain. `legal_capabilities` and `research_evaluations` are additional first-class domains.

Capability records reference sources, passages, rules, process steps, risks, optional workflows and research evaluations. They own subject boundaries, topic tags, support gaps, conflicts and currentness. Source metadata stays in sources; quotes/locators stay in passages; curated explanations stay in legal rules. Startup and runtime validation check typed graph links, source/rule evidence and jurisdiction. Workflow references are associations, not capability release prerequisites.

Passages may now have empty workflow lists. Workflow retrieval still requires explicit membership and institution-level jurisdiction isolation. Capability/general research uses exact country/state isolation, retaining court/agency as authority context. Matching establishes subject relevance, never court jurisdiction, venue, standing, duty, negligence, causation, damages or likely success.

`PassageRetrievalService.retrieve_capability()` checks filters against the selected capability. `GeneralLegalResearchService` builds compiled/dynamic evidence packages. Workflow assembly remains in `ResponseAssemblyService`. All modes converge on `GenerationService`, `build_model_request`, `GeneratedDraft`, `OutputValidationService` and `ResponseRenderingService`. Research has a null workflow ID and an internal evidence mode, never a fabricated workflow.

## Matter interpretation

Both configured model providers can suggest jurisdiction, sovereign, court/agency, area/topics, user/opponent posture, procedural/document context, dates, goal and fact categories. Strict schemas reject capability IDs, approvals and policy changes. Explicit provenance requires an exact evidence quote; inference/document text cannot establish research jurisdiction. Virginia/Maryland state facts supply US country context; other incomplete jurisdictions require clarification.

The Wendy's example is a candidate plaintiff-side tort/premises-liability issue. With state missing, the assistant asks **What state did this happen in?** An explicit Virginia answer enables deterministic resolution and sourced explanation. Existing procedural conversations still confirm inferred court/document context before workflow execution. Missing workflows no longer make a legal topic unsupported; missing authoritative evidence does.

Conversation state is signed and bounded to 30 turns. It includes structured context, never assistant statements or legal authority. Browser-memory state and the process-local key expire on restart. A single worker is required until shared signing/expiry management exists.

## Authority providers

`LegalAuthorityProvider.search(ResearchMatter)` returns source identifiers; `fetch(source_id)` returns metadata, actual text and passages. This interface is independent of `ModelProvider`. Models have no tools and cannot invoke either method. Authority searches receive legal concepts, not names, user goals, facts or documents.

| Provider | Sources and access | Bounds and limitations |
|---|---|---|
| `repository` | Actual curated official primary/secondary passages; offline, no account | Exact jurisdiction/topic discovery; bounded collection, not comprehensive research |
| `virginia_official` | Fixed catalog: two Virginia Supreme Court opinions and one official Code section; optional, free, no key | 2 MB body, 200,000-character text, 20 PDF pages, eight-second socket timeout and twelve-second worker deadline; changed excerpts withheld |
| `courtlistener` / local corpus | REST v4 discovery and separate Court/Docket/Cluster/Opinion hydration, citation lookup; SQLite/FTS cache and bulk import | Server token; fixed endpoints, operation budgets, exact jurisdiction, preserved opinion roles; external records remain unreviewed |

`PRO_ONE_AUTHORITY_NETWORK=virginia_official` explicitly enables the official adapter. Use `courtlistener,virginia_official` to enable both network providers. The official adapter uses fixed URLs, credential-free requests and a bounded child process for network access and parsing. Linux additionally limits worker memory and CPU. The worker uses a wall deadline on Windows.

The source schema supports statutes, regulations, court rules, constitutions, opinions, forms and official guidance. Primary law and explanatory guidance remain distinct. Case metadata preserves court, date, publication/precedential status, posture, opinion role and unknown subsequent treatment. Authority hierarchy is metadata and review context; no general algorithm resolves competing holdings. A government guidance page does not become a case holding by virtue of its hostname.

The optional [CourtListener adapter](courtlistener.md) implements documented v4 search, hydration and citation lookup contracts with server-authorized access. No free-access assumption is made. Search snippets never constitute evidence, and unavailable credentials preserve offline collection use.

Research packages are ephemeral; CourtListener snapshots persist only in the separate configured external corpus. Fetched excerpts must occur in normalized actual text; changed/missing wording is excluded. A fresh snapshot replaces old passages for that source. No runtime result rewrites `data/`, changes maturity/review or creates permanent law. Provider failure is an explicit gap.

## Grounded claims and validation

Research claims bind propositions to passage/source/citation IDs, jurisdiction, support state, limitations and conflicts. Compiled mode can select exact source text or its curated source-linked plain-language rule variant. General mode starts with exact source text; independently verified development synthesis can add an accepted statement variant. Compiler-created rules remain extractive candidates.

Deterministic string checks cannot prove arbitrary paraphrase entailment. An independent model verification stage can propose an allowed synthesis variant, subject to exact evidence bindings and role/jurisdiction/qualification checks. Final generation must exactly select accepted variants. New cases, quotations, URLs, deadlines, approval/currentness and outcome assertions remain prohibited. Curated and synthesized variants still require legal review; live semantic accuracy remains unmeasured.

The shared validator enforces strict schema/types, identity, actual evidence links, citation existence, jurisdiction, exact legal text, empty actions/conclusions, disclosure/limitation rendering and citation manifests. Revalidation occurs before rendering. Combined research claims become individually cited paragraphs; canonical records supply names/URLs/metadata. A real citation cannot launder an invented sentence.

## Conflicts, currentness and review

Source dates, retrieval date, content version/hash, effective dates, amendment information, known supersession and uncertainty are distinct. **Retrieved today is not certified current law.** Subsequent case treatment defaults to unknown; no citator is implemented. Austin's majority/dissent distinction and motion-to-strike posture remain mandatory limitations, without deciding their application to new facts.

All new canonical records remain proposed, null-reviewed and unresolved for currentness. Supported-record schemas and repository validation preserve review scopes, reviewed versions and eligible supporting dependencies. Public research is blocked independently of development structural success. Existing workflow release gates remain unchanged.

The [compiler](capability-compiler.md) collects sources, checks exact linkage, proposes rules/capability boundaries/evaluations and writes a separate review report. All generated records remain proposed. Refresh identifies added/removed/changed source content/provenance/dates and resets review. Humans review boundaries, source sets, key propositions, exceptions, conflicts, currentness and risk policy, not every possible user question.

## Product and release

The conversational UI, bounded in-memory document extraction and source panel remain. Case cards add court/date/treatment; statute cards add section/effective-date uncertainty. Internal modes and provider selection stay out of normal UI flows. Arbitrary offline questions get an explicit configuration notice; known named examples remain available as labeled demonstrations.

Production blocks proposed research/workflow execution before model calls, disables testing and inspection paths, and retains privacy/source/release gates. Document parsers are isolated and bounded. No raw legal text or provider diagnostics are logged; documented startup disables access logs. Host-level rate limiting, monitoring, live-model semantic/privacy checks and legal/currentness review precede public exposure.

Reusable process primitives remain jurisdiction/document identification, captured user dates, official-instruction navigation, service/deadline awareness, redaction and escalation. Future workflows can compose these without creating a workflow for each retailer, statute or factual permutation.

## External corpus and independently verified synthesis

The [CourtListener architecture and operational contract](courtlistener.md) extends the authority layer with a separate persistent corpus. It never writes retrieved material into the canonical graph. REST and streaming CSV/CSV.bz2 share normalized bundles; a future replication adapter can use that boundary. Individual opinions retain roles, hashes, paragraph locators and citation edges. Official statutes/rules/forms remain separate authorities. Corpus compilation emits proposed artifacts only.

Live research may propose multi-authority claims, call an independent verifier with only each candidate's cited evidence/metadata, then require deterministic IDs, citation identity, jurisdiction, role, exact evidence bindings, qualifiers and accepted statement text. The claim ledger stays a development artifact. Failure preserves the exact-text plan. Verifier acceptance does not establish controlling force, currentness, an outcome or release approval. The offline product example uses an explicitly fixed fixture verifier; live semantic accuracy has not been measured. RECAP filings use a separate read-only document channel and never supply legal propositions.
