# Pro-One

**Pro-One is a source-grounded legal AI operating system for individuals and small businesses.**

Free legal AI for everyone. Ask a question, describe a situation, or add a redacted document. Pro-One identifies candidate issues, checks authoritative evidence, and presents sourced information. Structured workflows help when a particular legal process benefits from them.

## High-Assurance Legal Operating System

```text
Legal Graph -> Capabilities -> General Research -> Optional Workflows

matter understanding -> jurisdiction -> legal issues
  -> compiled capability OR bounded authoritative research
  -> evidence -> grounded claims -> shared model generation
  -> deterministic validation -> sourced answer
  -> specialized workflow when useful
```

Capabilities define what Pro-One can research and explain. Workflows define structured processes. **No authoritative support means no confident legal claim.** A general question does not require a workflow ID. Versioned schemas, provenance, grounding, model abstraction, evaluations and the conversational product remain. See [Architecture](docs/architecture.md).

## Current coverage

| Capability | Authoritative collection | Specialized module |
|---|---|---|
| Virginia premises liability | Two Supreme Court opinions and Va. Code section 8.01-243(A) | None required |
| Virginia civil procedure | Existing court forms, instructions and Code excerpts | DC-402 defendant orientation |
| Virginia business entity records | Existing SCC official guidance | SCC record/status navigation |
| Maryland civil procedure | Existing District Court official guidance | Civil summons orientation |

These are bounded proposed collections, not nationwide coverage. **All new capabilities, sources, passages, rules, evaluations and reviews remain proposed; currentness is unresolved.** Development availability is not legal approval or public release. Five fictional workflow examples remain outside the product catalog.

Research uses exact evidence excerpts or curated source-linked variants, with optional multi-authority synthesis through a separate proposal call, independent verifier calls and deterministic evidence/citation checks. Failed synthesis retains exact-text fallback. Legal and currentness review remain required; public execution stays closed.

The [CourtListener milestone](docs/courtlistener.md) adds optional REST v4 keyword/semantic discovery, typed opinion hydration, citation identity checks, a persistent SQLite/FTS corpus, bounded bulk ingestion, citation relationships, existing RECAP document inspection and corpus-to-capability compilation. No credentials were available: authenticated downloads and live model calls are zero. The product's **Try CourtListener research example** is an explicitly reconstructed two-case fixture; [benchmark results](docs/research-benchmark.json) distinguish it from 1,000 synthetic storage/search cases.

## Run locally

Use Python 3.12 or later. Create and activate a virtual environment, then install dependencies and start:

```text
python -m venv .venv
python -m pip install -r requirements-dev.txt
python -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open [the local product](http://127.0.0.1:8000). No frontend build or database is needed. Default development mode says **Live AI is not configured. The offline demo can exercise known example matters only.** Use the named premises-liability example or existing DC-402, SCC and Maryland examples. Arbitrary questions do not enter a fake AI clarification loop.

## Live model configuration

Set process environment variables; `.env` files are not loaded automatically:

```text
PRO_ONE_MODE=development
PRO_ONE_MODEL_PROVIDER=openai
PRO_ONE_MODEL=<an explicitly selected structured-output model>
OPENAI_API_KEY=<server-only credential>
```

For Anthropic, use `PRO_ONE_MODEL_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`. Optional `PRO_ONE_OPENAI_MODEL` and `PRO_ONE_ANTHROPIC_MODEL` register server-owned models. Clients cannot choose arbitrary models or supply credentials, tools or policy. Both providers share candidate extraction and grounded generation contracts.

With a real provider, try **I'd like to sue Wendy's. I fell and hurt myself in their bathroom.** Missing jurisdiction prompts **What state did this happen in?** After **Virginia**, deterministic resolution selects premises-liability evidence without DC-402 or a business-specific workflow. Also try **What is premises liability in Virginia?**, **I received Virginia form DC-402. What does this mean?**, and **My Virginia LLC shows a status in SCC I don't understand.** These are candidate classifications, never findings of negligence or likely success.

Configured providers receive necessary message/document context for extraction and selected evidence for generation. Pro-One stores/logs no prompt history. Provider data policies still apply. Uploaded text cannot change source policy, approve records or establish research jurisdiction. Models never control sources, credentials, validation or release.

## Authority providers and compiler

Authority retrieval is independent of the model vendor. The default repository adapter discovers actual curated passages by jurisdiction and legal concepts, without a workflow. Optional official Virginia retrieval is enabled by:

```text
PRO_ONE_AUTHORITY_NETWORK=virginia_official
```

It fetches fixed official court/Code resources with no key/payment, arbitrary URLs, redirects, proxies or web-search fallback. Body/text/page limits, socket timeouts and an isolated worker deadline bound requests and parsing. Changed excerpts are withheld. Runtime results stay ephemeral and never rewrite the legal graph. See [provider scope and rationale](docs/architecture.md#authority-providers).

Build proposed capability artifacts:

```text
python -B scripts/build_capability.py --jurisdiction Virginia --legal-area torts --topic premises_liability --output review/va-premises
```

Options include `--provider virginia_official`, `--collection <source-collection.json>`, and `--previous <prior-bundle.json>`. Output must be a new review directory outside canonical data. It contains proposed records, candidate evaluations and a review report. No record is automatically approved, certified, committed or promoted. See [Capability compiler](docs/capability-compiler.md).

## Validation

```text
python -B -m unittest discover --start-directory tests --verbose
python scripts/validate_repository.py
python -B scripts/run_evaluations.py
python -B scripts/run_evaluations.py --capability va-premises-liability
python -B scripts/run_evaluations.py --mode general_research
python -B scripts/run_evaluations.py --workflow va-scc-business-record-navigation
python -B scripts/run_evaluations.py --fixture va-premises-invented_case-evaluation --json
node --check app/web/app.js
git diff --check
```

The harness runs 24 mapped workflow fixtures and 13 registered capability/general-research fixtures. Four older fictional fixtures remain explicitly unmapped. Compiler fixtures require explicit execution registration before being scored. Automated checks cover links, evidence/citation fidelity, scope, jurisdiction, currentness honesty, conflicts and unsupported-output rejection. They do not approve law. Tests/CI need no live credentials or network retrieval.

`scripts/benchmark_models.py` retains workflow provider comparisons and version/hash-bound manual semantic scoring. Live provider calls can incur charges. No score overrides deterministic rejection or legal/source/currentness release review.

## API and product

- `GET /health`, `/model/status`, `/assistant/status`, `/workflows`, `/capabilities`
- `POST /assistant/message`: conversation with server-owned configuration
- `POST /documents/extract`: raw PDF/DOCX/TXT; no filesystem path or filename
- `POST /capabilities/resolve`: deterministic subject matching
- `POST /research/evidence`: development evidence inspection without a workflow
- Existing workflow routing, scope, readiness, intake, retrieval, assembly and response APIs remain.
- `/openapi.json` documents strict requests; `/docs` is development-only.

The UI retains one question/document composer, context, follow-ups and canonical source links. Case cards add court/date/treatment; statutes add section/effective-date uncertainty. Internal evidence-mode names stay out of normal UI text.

Uploads stay in memory: 2 MB, 16,000 characters, 20 PDF pages; no OCR, encrypted PDFs, macros or saved uploads. Parsers run in child processes. Signed conversation state is bounded to 30 turns, process-local and held in browser memory; restart expires it. Use one worker until shared key/expiry management exists. Remove unnecessary personal identifiers. Pro-One does not establish representation or choose legal positions.

## Docker and release

```text
docker build -t pro-one:mvp .
docker run --rm -p 127.0.0.1:8000:8000 -e PRO_ONE_MODE=development pro-one:mvp
```

The Python 3.12 container runs as a non-root user with health checks. Production defaults block proposed research/workflow execution and exclude testing. CI builds and smoke-tests production mode. No cloud resources are provisioned. Public exposure requires legal/source/currentness approvals, live-model semantic/privacy evaluation, and operational rate limiting/monitoring.

Read the [architecture](docs/architecture.md), [source standards](docs/source-standards.md), [privacy principles](docs/privacy-principles.md), [legal safety](docs/legal-safety.md), [review standards](docs/review-standards.md), and [development setup](docs/development-setup.md).
