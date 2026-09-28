# MVP

The first Pro-One legal workflow remains a proposal, not an implemented product. An early local runtime can load and resolve repository records and evaluate a workflow's readiness gate, but it does not execute or publicly support a legal workflow. The MVP should remain intentionally narrow: one jurisdiction, one civil-procedure task, one reviewed source corpus, and explicit release gates.

## Direction

The proposed MVP would help a self-represented civil litigant understand and prepare a basic answer to a civil complaint. Its purpose is to explain sourced concepts, organize information, and structure a user-reviewed draft—not to make litigation decisions.

## Intended behavior

A future implementation should:

1. identify the document, jurisdiction, and reviewed workflow
2. retrieve approved, current sources for the propositions being explained
3. explain what admissions, denials, lack-of-knowledge responses, and defenses generally mean when the sources support those explanations
4. collect and organize user-confirmed facts
5. record the user's explicit decisions for each allegation or section
6. populate a draft structure from those explicit decisions only where a reviewed workflow permits it
7. show citations, limitations, unanswered questions, and required review points
8. evaluate the output against reviewed fixtures before public support

The system must not:

- decide what the user should admit, deny, or state based on lack of knowledge
- invent facts, defenses, objections, or legal authority
- select litigation strategy or predict an outcome
- turn silence, ambiguity, or model inference into a factual choice
- calculate a final deadline without adequate reviewed authority and required facts
- represent that a pleading is complete or legally sufficient merely because it was generated
- file, serve, sign, or submit a document for the user

## Initial scope

- one user type: self-represented civil litigants
- one jurisdiction selected through documented review
- one task: understanding and preparing a basic answer to a civil complaint
- one inspectable, approved legal corpus
- source-backed procedural explanations and citations
- structured intake and user-confirmation controls
- warnings, refusal of unsafe parts, and safe continuation
- privacy and data-minimization controls
- reviewed evaluation fixtures

Payments, accounts, attorney matching, multi-jurisdiction coverage, broad legal advice, automated submissions, complex strategy, production deployment, mobile apps, and advanced interface work remain out of scope.

## Source and review requirements

The corpus should be selected by proposition, not by a single universal source ranking. Statutes, regulations, cases, and rules may support substantive propositions; court rules, forms, and instructions may support filing and procedural requirements; official self-help and legal-aid materials may support plain-language explanation and navigation.

Before the workflow is publicly supported, the project should complete jurisdiction-specific review of the legal-information/legal-advice boundary and other applicable requirements. A `legal_information_only` label is a design constraint, not a legal conclusion. The project does not currently claim attorney review.

The runtime readiness gate is an enforcement point for these release conditions, not evidence that they have been satisfied. The current sample workflows remain proposed and fail the gate because required reviews, supported dependencies, and evaluation fixtures have not been completed.

## Example interaction boundary

```text
User: I was served with a civil complaint. What does an answer do?

Permitted future behavior:
- identify or ask for jurisdiction and the document title
- explain sourced response categories and procedural structure
- ask the user to confirm facts and choose their own response for each allegation
- place those explicit choices into a clearly labeled draft structure
- show sources, unresolved questions, deadlines requiring verification, and limitations

Prohibited behavior:
- choose "admit" or "deny" for the user
- invent a defense or factual explanation
- select a litigation strategy
- state that the draft is ready or legally sufficient solely because it was generated
```

## Success criteria

The MVP should not be called publicly supported until it passes source-grounding, citation, jurisdiction, fact-integrity, user-decision, privacy, deadline, safe-continuation, and legal-boundary evaluations. Correctness, transparency, and narrow scope matter more than broad coverage.
