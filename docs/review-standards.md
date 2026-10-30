# Review Standards

Pro-One should review contributions carefully because the project deals with legal information, privacy, source grounding, and AI safety.

This document explains what reviewers should check before approving or merging changes.

## Core review standard

A change should be:

- accurate about the project's current status
- aligned with Pro-One's mission
- narrow enough to review
- clear about limitations
- careful with legal information
- respectful of privacy and security
- grounded in reliable sources when legal claims are involved

A contribution should not make Pro-One appear more capable, complete, or legally authoritative than it is.

## General review checklist

Before merging, reviewers should check:

- Does the change do what the pull request says it does?
- Is the scope focused?
- Are unrelated changes avoided?
- Is the wording clear?
- Are planned features described as planned rather than already available?
- Does the change preserve the free and open legal-access mission?
- Does the change avoid unsupported legal claims?
- Does the change avoid exposing sensitive information?
- Does the change introduce any safety concerns?
- Do schemas, records, documentation, and validation remain synchronized?
- Does `python scripts/validate_repository.py` pass?

## Documentation review

Documentation should be clear, accurate, and current.

Reviewers should check whether documentation:

- matches the current state of the repository
- avoids overstating features
- avoids implying Pro-One provides legal advice
- distinguishes legal information from legal advice
- explains limitations clearly
- uses plain language where possible
- stays consistent with existing mission, safety, privacy, source, and evaluation documents

Documentation-only changes should still be reviewed carefully because they define the project's public commitments and boundaries.

## Legal-information review

Changes involving legal information require extra care.

Reviewers should check whether the change:

- identifies the relevant jurisdiction
- cites or references reliable sources
- preserves source metadata
- avoids guessing deadlines
- avoids unsupported legal conclusions
- distinguishes official, primary, and secondary sources
- warns when information is incomplete or uncertain
- stays within the supported workflow
- preserves user control over factual positions, admissions, denials, defenses, objections, and strategy
- avoids claiming that a generated draft is legally sufficient solely because it was generated
- documents jurisdiction-specific review expectations before public support

If a legal claim is not supported, it should be removed, limited, or rewritten.

A `legal_information_only` label is a design constraint, not a legal conclusion. Before public support, reviewers should consider the workflow's jurisdiction-specific legal-information/legal-advice boundary and other applicable requirements. Do not claim attorney review unless it actually occurred.

## Source-grounding review

For source or corpus changes, reviewers should check:

- Is the source reliable?
- Is it official, primary, or clearly labeled as secondary?
- What jurisdiction does it apply to?
- Is it current?
- Can users verify it?
- Can the project reuse it?
- Is citation metadata preserved?
- Does the source support the workflow being built?
- Are any limitations or safety concerns documented?
- Does the source actually support the specific proposition for which it will be used?
- Are effective dates, source/content version, supersession, and last verification recorded where available?

Sources should not be added only because they are convenient.

Official self-help and legal-aid materials may be strong explanatory and navigation sources, but they do not categorically outrank primary authority for substantive propositions. Court forms and instructions may be authoritative for local filing requirements even when they are not substantive law.

## Schema, version, and review-provenance review

For schema or record changes, reviewers should check:

- whether the shared common definition is genuinely semantically identical across domains
- whether enum changes were synchronized across schemas, samples, docs, issue templates, and validation
- whether `schema_version`, `record_version`, and `last_modified` are accurate
- whether reviewed or approved records identify reviewer handle, role, scope, date, and reviewed record version
- whether professional credentials are stated only when explicitly verified and recorded
- whether all cross-record IDs resolve and supported-state conditions remain enforceable

### Public-support review gates

An `approved` review is necessary but not sufficient for a record to become `supported`. Repository validation requires the following minimum `review_scope` values by record domain:

| Record domain | Required review scopes |
| --- | --- |
| Source | `schema`, `source_authority`, `source_freshness`, `jurisdiction` |
| Source passage | `schema`, `source_authority`, `source_freshness`, `jurisdiction`, `legal_information_boundary` |
| Workflow | `schema`, `jurisdiction`, `legal_information_boundary`, `safety`, `evaluation` |
| Process step | `schema`, `jurisdiction`, `legal_information_boundary`, `safety`, `evaluation` |
| Legal document | `schema`, `jurisdiction`, `legal_information_boundary`, `safety`, `privacy`, `evaluation` |
| Intake | `schema`, `jurisdiction`, `legal_information_boundary`, `safety`, `privacy`, `evaluation` |
| Legal rule | `schema`, `source_authority`, `jurisdiction`, `legal_information_boundary`, `safety`, `evaluation` |
| Risk | `schema`, `safety`, `evaluation` |
| Response | `schema`, `jurisdiction`, `legal_information_boundary`, `safety`, `privacy`, `evaluation` |
| Evaluation fixture | `schema`, `evaluation` |

A supported workflow that sets `intake.collects_sensitive_data` to `true` must also include `privacy`. The workflow schema enforces its base scopes and this conditional privacy scope; repository validation enforces the complete domain table consistently across record types.

Supporting dependencies of a supported record must themselves have `status: supported` and `review.status: approved`. Sources retain their source-specific schema and review gates. Negative and test relationships—including prohibited, excluded, superseded, and evaluation-target references—must resolve but are not supporting dependencies and therefore may intentionally point to records that are not eligible for public support.

## Privacy review

Reviewers should check whether a change collects, stores, exposes, logs, or transmits user information.

Extra caution is required for:

- names
- addresses
- court papers
- contracts
- business records
- financial information
- employment facts
- housing facts
- family facts
- immigration facts
- medical information
- deadlines
- user-uploaded documents
- communications with lawyers, courts, agencies, or opposing parties

A change should collect less data where possible.

## Security review

Reviewers should check whether a change could expose the project or users to security risks.

Do not merge changes that include:

- API keys
- credentials
- private user data
- real user legal documents
- sensitive logs
- environment files with secrets
- unnecessary dependencies
- unsafe handling of uploaded documents

Future code changes should also consider prompt injection, dependency risk, access controls, and safe handling of third-party services.

## AI safety review

Changes involving AI prompts, retrieval, generation, evaluation, or model behavior require extra review.

Reviewers should check whether the change:

- prevents unsupported legal answers
- avoids invented citations
- preserves jurisdiction awareness
- supports refusal behavior
- handles uncertainty clearly
- avoids overconfident language
- keeps users in control
- avoids pretending the system is a lawyer
- is testable through evaluation examples or fixtures

AI output should not be treated as reliable unless it is supported by sources and safety checks.

## Deadline and high-risk topic review

Deadline-related and high-risk legal topics require the most caution.

Reviewers should be especially careful with changes involving:

- court deadlines
- defaults
- appeals
- eviction
- foreclosure
- bankruptcy
- criminal matters
- immigration
- family law
- domestic violence
- child custody
- emergency court relief
- loss of housing, liberty, status, custody, or major financial rights

If a change cannot be made safely, it should be delayed or narrowed.

## Pull request review questions

Before approving a pull request, ask:

- Is this change accurate?
- Is it narrow?
- Is it grounded?
- Is it safe?
- Is it clear about limits?
- Does it protect user privacy?
- Does it avoid overstating Pro-One's capabilities?
- Does it move the project toward practical legal access?

## When to request changes

Request changes when a pull request:

- overstates the project
- implies legal advice
- lacks source support for legal claims
- guesses deadlines
- ignores jurisdiction
- exposes sensitive data
- weakens privacy or security standards
- removes important safety limitations
- combines too many unrelated changes
- is difficult to review

## Guiding rule

A careful review protects users and the project.

For Pro-One, accuracy, safety, and trust matter more than speed.
