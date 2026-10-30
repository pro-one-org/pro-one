# Pro-One

**Free legal AI for everyone.**

Pro-One helps individuals representing themselves and small businesses handling matters themselves understand documents, find official information, and organize questions. It is a free, model-agnostic legal-information platform. It does not choose legal positions, establish a lawyer-client relationship, or replace qualified help.

## Product status

The local beta has a usable web interface, structured matter routing, deterministic scope checks, official-source retrieval, provider-neutral generation, independent output validation, and readable citations. It is stateless: no accounts, saved conversations, database, payments, or user profiling.

**All real workflows, sources, passages, and reviews remain proposed. No workflow is approved for unrestricted public use.** Development mode can exercise them. Production mode refuses unapproved workflow generation and disables the testing provider and internal inspection endpoints. No currentness or attorney review has been fabricated.

## Development coverage

| Audience | Workflow | Official authority | Important limits |
|---|---|---|---|
| Individuals | Virginia Small Claims DC-402 defendant information | Virginia Judicial System, Supreme Court form/instructions, Code of Virginia | Appearance wording, universal written-answer duties/deadlines, and older instruction currentness remain unresolved. |
| Small businesses | Virginia SCC business records and status navigation | [SCC CIS help](https://www.scc.virginia.gov/businesses/business-faqs/cis-faq/), [Clerk's Office](https://www.scc.virginia.gov/businesses/about-the-clerks-office/) | Navigate records and questions; no live entity lookup, active-status/compliance opinion, filing, fees, or reinstatement decision. |
| Individuals | Maryland District Court civil summons orientation | [Maryland Courts defendant help](https://www.mdcourts.gov/courthelp/suedindistrictcourt) | Ordinary civil money-claim document orientation; no deadline calculation, strategy, service/venue decision, or high-consequence matter. |

These are three bounded workflows in two states, not nationwide coverage. Five older fictional examples remain repository demonstrations and are excluded from the product catalog. Open `/coverage` or `GET /workflows` to inspect actual development coverage.

## Run locally

Use Python 3.12 or later. From the repository root:

```text
python -m venv .venv
```

Activate `.venv` using your platform's normal command, then:

```text
python -m pip install -r requirements-dev.txt
python -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open [Pro-One locally](http://127.0.0.1:8000). Choose Individual or Small Business, confirm the structured matter, complete the minimum intake, and submit a question. The default development adapter is explicitly labeled **Offline test provider**: it returns selected source excerpts, not a live AI answer. No frontend build or provider credential is needed for this path.

## Real-provider setup

OpenAI and Anthropic adapters implement the same generic `ModelProvider` interface. Core routing, legal scope, evidence, validation, and rendering do not depend on either vendor. There is no fallback or content-based provider switching.

Copy `.env.example` only if useful for your deployment, fill in the required values, and keep the resulting `.env` private. The app reads process environment variables; it does not automatically load a `.env` file. Set them in your shell, process manager, or container environment:

```text
PRO_ONE_MODE=development
PRO_ONE_MODEL_PROVIDER=openai
PRO_ONE_MODEL=<a model enabled for your account that supports structured outputs>
OPENAI_API_KEY=<server-only credential>
```

For Anthropic, select `anthropic` and set `ANTHROPIC_API_KEY`. To make both providers selectable, also set `PRO_ONE_OPENAI_MODEL` and `PRO_ONE_ANTHROPIC_MODEL` with their respective keys. The default `PRO_ONE_MODEL` registers that model for the default provider; the provider-specific variables configure the other allowlisted model. Choose models explicitly; Pro-One supplies no potentially stale real-model default. `GET /model/status` reports only safe configuration identifiers and availability. Browser clients cannot provide keys or select unconfigured models.

Real providers receive sanitized necessary facts and selected evidence when you submit. Their own data-handling terms apply; Pro-One maintains no prompt history. Requests use fixed official HTTPS endpoints, no redirects, no tools, bounded responses, a timeout, and no retries. OpenAI requests disable response storage. Refusals, incomplete responses, and errors fail safely. Integration follows the official [OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) and [Anthropic structured-output documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs). Local validation remains authoritative even where an adapter simplifies unsupported wire-schema keywords.

## Architecture

```text
Web UI / strict API
  -> workflow catalog + exact structured matter routing
  -> deterministic workflow-specification scope + sanitized intake
  -> execution context + local curated passage retrieval
  -> workflow readiness + selected-evidence grounding gate
  -> deterministic response plan
  -> explicitly configured provider adapter
  -> strict draft + independent output validation
  -> revalidated rendering + canonical citations, or a safe failure
```

Scope matching confirms only that structured details fit a workflow specification. It does not establish jurisdiction, venue, standing, service validity, merits, or representation requirements. The old caller `generation.scope` flag cannot enable substantive topics. Unknown/contradictory matters do not receive generic model answers. No model controls retrieval, sources, workflow selection, tools, filing, or review state.

The renderer displays only revalidated drafts. Citation titles, issuing authorities, locators, URLs, and source limitations come from canonical records. Invalid model text is never rendered. Structured checks and supplementary prose guards reject the documented attacks; they do not prove arbitrary prose semantically or legally correct. See [Model generation](docs/model-generation.md), [Product architecture](docs/architecture.md), and [MVP operation and release limits](docs/mvp.md).

## API

- `GET /health`, `GET /workflows`, `GET /model/status`
- `POST /routing/evaluate`, `POST /workflows/{id}/scope`
- `POST /workflows/{id}/response`: safe rendered product result
- Existing readiness, intake, retrieval, assembly, and generation APIs remain available for development inspection.
- OpenAPI: `/openapi.json`; development interactive docs: `/docs`.

The product response distinguishes accepted development response, missing information, unsupported/out-of-workflow matter, provider unavailable, insufficient evidence, and rejected draft. Request bodies are bounded to 64 KB and validation errors omit raw input values. Frontend text uses text nodes, canonical HTTPS links, and restrictive security headers. Do not submit unnecessary sensitive information, even inside an otherwise allowed question field.

## Evaluation

```text
python -B -m unittest discover --start-directory tests --verbose
python -B scripts/validate_repository.py
python -B scripts/run_evaluations.py
python -B scripts/run_evaluations.py --workflow va-scc-business-record-navigation
python -B scripts/run_evaluations.py --fixture md-district-civil-defendant-orientation-ordinary-fixture --json
```

The harness executes all 24 required real-workflow fixtures: 12 Virginia DC-402, six SCC, and six Maryland. Four older fictional fixtures remain explicitly unmapped. Missing required mappings fail; fixture versions and workflow identities must match. Automated passes cover declared deterministic checks, not narrative legal approval. Manual criteria remain pending.

For cross-provider measurements:

```text
python -B scripts/benchmark_models.py --workflow va-scc-business-record-navigation --fixture va-scc-business-record-navigation-ordinary-fixture
```

This explicitly calls configured providers and may incur API charges. Without real credentials it reports them unavailable and continues the test provider. Reports contain validation, latency, usage, exact draft hashes, and a ten-dimension manual semantic rubric. `--include-drafts` displays fixture drafts for review; `--review-file` accepts strict manual scores bound to the exact workflow/fixture/provider/model/draft hash. Use `--report-file <saved-report.json> --review-file <scores.json>` to apply scores to an existing result without calling a real model again. A manual score cannot override deterministic failure or approve release. No live provider or secret is required by tests or CI.

## Docker and deployment

```text
docker build -t pro-one:mvp .
docker run --rm -p 127.0.0.1:8000:8000 -e PRO_ONE_MODE=development pro-one:mvp
```

The Python 3.12 image installs runtime dependencies only, runs as a non-root user, exposes port 8000, and includes a health check. The image defaults to **production**, which deliberately refuses every currently unapproved workflow. For a production-like start, omit the development override and inject private configuration with your host's environment mechanism or a fully configured `--env-file`. Never bake keys into the image.

Any host supporting an OCI container and HTTPS can run it. Set `PORT` if your host requires another port, point health checks at `/health`, terminate TLS at the host, and run the supplied command. No database or vendor-specific infrastructure is required. CI builds the container and smoke-tests production health, catalog, and mode. No cloud resources are created by this repository change.

Before public exposure, legal/source/currentness and fixture review must complete, real-model semantic/privacy evaluation must be measured, and operational abuse controls and monitoring must be reviewed. External rate limiting is not implemented by this stateless beta. Optional accounts/history, more jurisdictions, and further visual polish are future product work, not requirements for local use.

## Project standards

Read the [roadmap](docs/roadmap.md), [legal-safety standards](docs/legal-safety.md), [privacy principles](docs/privacy-principles.md), [source standards](docs/source-standards.md), [review standards](docs/review-standards.md), and [evaluation principles](docs/evaluation-principles.md). Structural validity and automated test success do not confer legal approval.
