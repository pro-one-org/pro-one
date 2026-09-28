# Pro-One

**An open-source foundation for free, source-grounded legal AI for people and small businesses handling legal matters on their own.**

Pro-One is building the technical and governance foundation for narrow, jurisdiction-aware legal-information workflows. The project emphasizes authoritative sources, citations, user control, privacy, fact integrity, safe continuation, and explicit evaluation.

## Project status

Pro-One is currently in the **architecture, specification, and early local-runtime stage**. The repository includes a read-only local API that loads validated records, resolves workflow packages, and reports whether a workflow passes the runtime readiness gate. There is no production legal AI application, hosted service, or publicly supported legal workflow today.

The repository already contains a substantial, machine-validatable schema and governance foundation. Records under [`data/`](data/) are fictional placeholders used to demonstrate structure and relationships. They are not approved sources, legal guidance, or evidence that a workflow is available to the public.

## Current technical foundation

Nine interoperable JSON Schema domains define the project's core records:

1. [source metadata](schemas/source.schema.json)
2. [workflow definitions](schemas/workflow.schema.json)
3. [process steps](schemas/process-step.schema.json)
4. [legal documents](schemas/legal-document.schema.json)
5. [intake definitions](schemas/intake.schema.json)
6. [legal rules](schemas/legal-rule.schema.json)
7. [risk definitions](schemas/risk.schema.json)
8. [response patterns](schemas/response.schema.json)
9. [evaluation fixtures](schemas/evaluation-fixture.schema.json)

Shared definitions in [`schemas/common.schema.json`](schemas/common.schema.json) keep identifiers, versions, review provenance, jurisdiction structures, maturity states, risk levels, routing behavior, and other cross-domain vocabulary consistent. A lightweight validator checks JSON syntax, Draft 2020-12 schema validity, sample-record conformance, cross-record references, key state invariants, and Markdown integrity.

The early local runtime exposes workflow records, resolved workflow packages, and `GET /workflows/{workflow_id}/readiness`. The readiness endpoint fails closed unless the workflow and each required source, process step, and evaluation fixture meet the supported and approved gates. It does not execute legal workflows, generate legal information, or make any sample workflow publicly available.

The schemas sit within documented [legal-safety](docs/legal-safety.md), [privacy](docs/privacy-principles.md), [governance](docs/governance.md), [source](docs/source-standards.md), [workflow-selection](docs/workflow-selection.md), and [evaluation](docs/evaluation-principles.md) standards.

## Intended architecture

The following is a specification target, not a production pipeline:

```text
user need
  -> intake
  -> jurisdiction and workflow identification
  -> approved sources
  -> source-backed legal rules and process steps
  -> risk controls
  -> response pattern
  -> citations and limitations
  -> evaluation
```

See [Architecture](docs/architecture.md) for the broader component model.

## Proposed first MVP

The first proposed MVP is a narrow, single-jurisdiction civil-procedure workflow centered on helping a self-represented litigant understand and prepare a basic answer to a civil complaint.

That legal workflow is not implemented; the local runtime provides only repository access and readiness checks. The proposed workflow's intended role is to explain sourced concepts and options, collect and organize user-confirmed facts, and—where a reviewed workflow permits—structure or populate a draft from the user's explicit decisions. It must not decide what the user should admit or deny, invent defenses, choose litigation strategy, make factual choices, or claim that generated material is legally sufficient merely because it was generated. See [MVP](docs/mvp.md) and [Legal Safety](docs/legal-safety.md).

## Legal-information boundary

Pro-One is not a law firm or lawyer, does not form an attorney-client relationship, and does not currently provide legal services. Future workflows are intended to provide source-grounded legal information and structured assistance within reviewed boundaries.

Sample sources, rules, documents, responses, and other records are placeholders—not legal guidance. Before any workflow is described as publicly supported, it must have current jurisdiction-specific sources, an approved review covering the domain-specific scopes in the [review standards](docs/review-standards.md#public-support-review-gates), documented safety and privacy controls, and passing evaluation fixtures. The repository does not claim that attorney review has occurred.

## Repository navigation

- [Mission](MISSION.md)
- [Architecture](docs/architecture.md)
- [MVP scope](docs/mvp.md)
- [Roadmap](docs/roadmap.md)
- [Governance](docs/governance.md)
- [Review standards](docs/review-standards.md)
- [Source metadata](docs/source-metadata.md) and [source standards](docs/source-standards.md)
- [Workflow definitions](docs/workflow-definitions.md) and [workflow selection](docs/workflow-selection.md)
- [Legal safety](docs/legal-safety.md), [privacy](docs/privacy-principles.md), and [ethics](docs/ethics.md)
- [Evaluation principles](docs/evaluation-principles.md) and [fixtures](docs/evaluation-fixtures.md)
- [Development setup](docs/development-setup.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution expectations and [Development Setup](docs/development-setup.md) for local validation. The short version:

```bash
python -m pip install -r requirements-dev.txt
python -B -m unittest discover --start-directory tests --verbose
python scripts/validate_repository.py
```

When a shared enum or record relationship changes, update the affected schemas, sample records, documentation, and validation rules together.

## License

Pro-One is licensed under the [MIT License](LICENSE).
