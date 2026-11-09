# Private-beta evidence audit

Audit date is November 9, 2026. The private-beta objective is incomplete. The evidence below distinguishes implemented behavior, fixture proof, real public-source checks and required external acceptance. Automated results do not grant legal or currentness approval.

The active branch is `feat/mvp-ship-sprint`. PR #25's published head is `ec0f34e3499e66c39491145d9fbe0ac6c0f8c14c`; its existing CI run passed. Subsequent local commits require publication and CI. Automatic approval review rejected the push because it did not accept the pasted authorization for the GitHub destination.

| Criterion | Current evidence | Work required |
|---|---|---|
| 1. Authorized CourtListener v4 acceptance | Bounded probes in `scripts/accept_courtlistener.py`; offline transport tests. No token is present and authenticated calls remain zero. | Configure an authorized token and run all probe phases, retaining quota and latency reports. |
| 2. Real model end-to-end acceptance | Model adapters, bounded query proposals, stage tracing and conversational runner exist. Query proposals are connected to the normal corpus research path with server validation. No server model credential is present; live calls remain zero. | Configure an authorized model and evaluate interpretation, planning, synthesis, verification, rendering and follow-ups. |
| 3. Meaningful real corpus | The inspected SQLite proof corpus has two fixture clusters. Public official PDFs have supplied real compiler collections across three additional topics. | Build a meaningful real case corpus with provenance, exact text and useful subject coverage. |
| 4. Reproducible corpus build/refresh | REST checkpoints, bulk staging and refresh have offline regression coverage. Official compilation commands reproduced public-source collections. | Exercise REST or bulk ingestion and refresh against real CourtListener data. |
| 5. Discover, hydrate, store, search and cite cases | The complete path is covered with API-shaped fixture transports. | Run the same path with authorized real records. |
| 6. Reject fabricated/mismatched citation identities | Offline tests reject unknown, ambiguous and mismatched identities and unsupported pin cites. | Retain real lookup acceptance evidence and adversarial results. |
| 7. Preserve opinion roles | Individual roles survive normalization, storage, synthesis and compilation. Added official compiler inputs retain unknown roles pending review. | Validate authentic role segmentation with real provider records and review unclassified official inputs. |
| 8. Keep RECAP filings outside precedent | Archive inspection uses a separate channel and preserves filing/allegation limitations. Fixture tests cover membership and injection. | Verify real existing archive access and representative classifications. |
| 9. Independently verified multi-authority synthesis | Separate proposal/verifier calls and deterministic validation operate over bounded evidence. Proof uses fixed or mocked models. | Measure live entailment, exceptions, conflicts and false acceptance against reviewed labels. |
| 10. Unsupported propositions fail closed | Attack tests cover unsupported statements, source bindings, jurisdiction, role, quotes and citation mismatches. | Extend evidence through real-model adversarial acceptance. |
| 11. Useful retrieval across Virginia subjects | Known-target benchmark labels cover contracts, contributory negligence and landlord repairs. The fixture SQLite corpus contains none of these real targets. | Ingest labeled cases and broaden reviewed relevance labels before measuring precision and recall. |
| 12. Compile real corpus evidence | Real official-source runs compiled contract, contributory-negligence and landlord-repair collections into proposed artifacts. | Compile a meaningful real CourtListener corpus and review knowledge candidates and source roles. |
| 13. Broader legal capability coverage | Four canonical proposed capabilities remain. Additional generated review bundles are outside canonical data. | Establish evidence and reviewed boundaries across additional subjects. Generated bundle counts do not prove coverage. |
| 14. Workflows remain optional | General research assembles without a workflow ID; specialized procedural intake remains available. | Preserve this behavior as subjects and providers expand. |
| 15. Mixed case/statute/rule research | One actual local run combined a live LIS statute excerpt with fixture case evidence. Providers can be configured together. | Verify a real mixed-authority answer and add relevant official rule coverage. |
| 16. Honest treatment/currentness uncertainty | Bounded local screening retains citing context and roles, flags truncation and leaves currentness unresolved. | Review real later-citing examples and measure screening limitations. |
| 17. Product conversations and documents | Local tests exercise questions, procedural conversations, uploads, heading cues and labeled document excerpts. | Evaluate live conversations and substantive document questions. Heading inspection alone does not establish document intelligence acceptance. |
| 18. Adversarial assurance | Offline suites cover citation, jurisdiction, evidence and prompt-injection boundaries. | Add reviewed live-model results. |
| 19. Existing regressions stay green | Standard unit, evaluation, schema and frontend checks are run after implementation cycles. | Keep exact-commit local and CI results current. |
| 20. CI passes | Published PR head passed CI. Local changes have local validation only. | Publish the branch, wait for CI and repair any legitimate failures. |
| 21. Controlled-beta operations | Shared signing, fixed conversation expiry, read-only readiness probing, corpus outage handling and online backups exist. Production research remains gated. | Establish host access controls, abuse limits, privacy handling and deployment verification before beta exposure. |
| 22. Accurate documentation | Provider, compiler, privacy, readiness, backup and acceptance runbooks disclose limits. This audit records outstanding criteria. | Update evidence as real acceptance runs complete. |
| 23. Keep secrets, databases and private legal text out of Git | Corpus files and local reports are ignored. The current changes use public source metadata and synthetic tests. | Repeat staged-file review before publication and retain corpus data outside Git. |
| 24. Public release stays gated | Production research, citation and proposed workflow execution are blocked by server policy and regression tests. | Keep release review and separate deployment authorization explicit. |
| 25. PR #25 stays unmerged | PR remains open at the published head. | Maintain the merge boundary until explicit user instruction. |

## Immediate external dependencies

An authorized `COURTLISTENER_API_TOKEN` is required for provider acceptance and targeted ingestion. An authorized OpenAI or Anthropic server credential and explicit model configuration are required for live semantic acceptance. Keep credentials in server secret configuration.

Publishing needs direct confirmation following the automatic review rejection. Legal validity, currentness and release readiness require authorized human review of the evidence. None of these dependencies is satisfied by fixture tests or by a successful compiler run.

## Evidence locations

The operational commands and distinctions are documented in [CourtListener](courtlistener.md), [model generation and live acceptance](model-generation.md), [capability compilation](capability-compiler.md), [development setup](development-setup.md) and [privacy](privacy-principles.md). Downloaded material, generated bundles, corpus snapshots and acceptance reports belong in local storage outside Git.
