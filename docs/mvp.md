# MVP

The first Pro-One legal workflow remains a proposal, not an implemented product. An early local runtime can load and resolve repository records and evaluate a workflow's readiness gate, but it does not execute or publicly support a legal workflow. The MVP should remain intentionally narrow: one jurisdiction, one civil-procedure task, one reviewed source corpus, and explicit release gates.

## Direction

The proposed first workflow is a self-represented defendant information workflow for a Virginia General District Court Small Claims Division Warrant in Debt (Form DC-402). It identifies the official form and court, organizes user-confirmed information, explains only verified procedural propositions, and routes date uncertainty to official resources. It does not prepare a responsive pleading or make a litigation decision. See the [workflow specification](virginia-small-claims-warrant-in-debt-workflow.md).

## Intended behavior

A future implementation of this specific workflow should:

1. identify the document, jurisdiction, and reviewed workflow
2. retrieve approved, current sources for the propositions being explained
3. identify the court, division, form, and return date shown on the warrant
4. organize user-confirmed facts and questions while leaving all response choices to the user
5. explain verified small-claims procedure with links to official sources
6. avoid creating or approving any answer, grounds of defense, counterclaim, or filing
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

- one user type: self-represented defendants who received Form DC-402
- one jurisdiction: Virginia General District Court Small Claims Division
- one task: identify a served Warrant in Debt and organize user-directed questions and official resources
- one inspectable source corpus, reviewed and approved before any supported use
- source-backed procedural explanations and citations
- structured intake and user-confirmation controls
- warnings, refusal of unsafe parts, and safe continuation
- privacy and data-minimization controls
- reviewed evaluation fixtures

Payments, accounts, attorney matching, multi-jurisdiction coverage, broad legal advice, automated submissions, complex strategy, production deployment, mobile apps, and advanced interface work remain out of scope.

## Source and review requirements

The corpus should be selected by proposition, not by a single universal source ranking. Statutes, regulations, cases, and rules may support substantive propositions; court rules, forms, and instructions may support filing and procedural requirements; official self-help and legal-aid materials may support plain-language explanation and navigation.

Before the workflow is publicly supported, the project should complete jurisdiction-specific review of the legal-information/legal-advice boundary and other applicable requirements. A `legal_information_only` label is a design constraint, not a legal conclusion. The project does not currently claim attorney review.

The runtime readiness gate is an enforcement point for these release conditions, not evidence that they have been satisfied. All sample workflows, including the Virginia DC-402 candidate, remain proposed and fail the gate because reviews and required dependencies have not been approved or supported. The Virginia candidate's twelve evaluation fixtures are proposed and unreviewed.

## Example interaction boundary

```text
User: I received a Virginia DC-402. What does the return date mean?

Permitted future behavior:
- identify or ask for jurisdiction and the document title
- identify the document and listed court and date
- summarize only verified procedure with official sources
- help the user organize questions without recommending a response
- show sources, unresolved questions, deadlines requiring verification, and limitations

Prohibited behavior:
- choose whether the user should respond, appear, remove, contest, settle, or assert a defense
- invent facts, a defense, or a legal position
- select litigation strategy or predict an outcome
- say an outline or document is legally sufficient or ready to file
```

## Success criteria

The MVP should not be called publicly supported until it passes source-grounding, citation, jurisdiction, fact-integrity, user-decision, privacy, deadline, safe-continuation, and legal-boundary evaluations. Correctness, transparency, and narrow scope matter more than broad coverage.
