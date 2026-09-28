# Proposed Virginia Small Claims Warrant in Debt Workflow

Status: proposed specification and research corpus. This workflow is not legally reviewed, approved, supported, implemented, or publicly available. All associated records and fixtures remain proposed.

## Exact scope

- Jurisdiction: Commonwealth of Virginia.
- Court: Virginia General District Court, Small Claims Division.
- Trigger document: a defendant reports receiving a served Form DC-402, “Warrant in Debt — Small Claims Division.”
- Intended user: a self-represented individual defendant seeking to understand the form and organize questions.
- Task: identify the document and listed court, record user-confirmed fields such as the return date printed on the warrant, explain verified procedural information with official citations, and provide bounded organization and resource prompts.

This does not cover Warrant in Detinue (DC-404), other General District Court matters, circuit court complaints, other states, plaintiffs, or a user's choice whether to contest, pay, settle, remove, appear, or assert a defense or counterclaim. It does not prepare a pleading or determine whether service was valid.

## Official sources and propositions

| Official source | Propositions supported in this proposed corpus | Limits |
| --- | --- | --- |
| [Code of Virginia, Title 16.1, Chapter 6, Article 5](https://law.lis.virginia.gov/vacodefull/title16.1/chapter6/article5/) (including §§ 16.1-122.1–.7; viewed 2026-09-28) | A General District Court has a Small Claims Division (§ 16.1-122.1); small-claims civil warrants commence actions, the trial is set for the first return date subject to stated continuance rules, and the statute names the permitted pleadings (§ 16.1-122.3); parties generally represent themselves and a defendant may remove the case to General District Court before the judge's decision (§ 16.1-122.4); trial procedure is informal (§ 16.1-122.5). | Does not answer whether a defendant must file a written answer or grounds of defense, what that deadline would be, what a specific defendant should choose, or local clerk/court practices. Recheck the current text before any supported use. |
| [Official Form DC-402](https://vacourts.gov/static/forms/district/dc402.pdf) (front marked 10/07; reverse 07/01; retrieved 2026-09-28) | Identifies the Warrant in Debt — Small Claims Division; displays court, claim, case, and return-date fields; contains a return-date trial warning, nonappearance warning, a venue-transfer instruction, and a defendant's removal notice. | The form's appearance wording (“not required to appear; however…judgment may be entered”) must be reviewed against current law and practice before wording user-facing guidance. The form is not evidence of a universal written-answer deadline. |
| [Official Form DC-402 Instructions](https://www.vacourts.gov/static/forms/district/dc402inst.pdf) (marked September 2008; viewed 2026-09-28) | Explains form fields and says the judge completes the Grounds of Defense “ORDERED DUE” fields if the judge orders such a filing (Data Element 31). | Materially old. Do not infer a current universal filing obligation or deadline; verify whether instructions and fields remain current. |
| [Virginia Judicial System Court Self-Help: Small Claims](https://selfhelp.vacourts.gov/page/11/small-claims) (page states updated 2026-02-07; viewed 2026-09-28) | Describes the return date as the trial date; says a default judgment may be entered if a properly served defendant fails to appear; explains removal before decision and that formal General District Court rules then apply; links court forms and other resources. | Official explanatory material; it does not resolve all fact-specific service, appearance, pleading, or local-practice questions. |
| [Virginia General District Court Civil Forms](https://vacourts.gov/forms/district/civil) | Confirms DC-402 is listed as “Warrant in Debt - Small Claims Division”; provides the official forms directory. | Directory listing only; does not establish defendant-specific filing duties. |

No outside or secondary source is used to establish a legal proposition in the proposed records. URLs were opened and verified on 2026-09-28. Source reuse terms are unreviewed, and no source text is reproduced here.

## Procedure model and unresolved questions

The plaintiff files a small-claims civil warrant; DC-402 is the official Warrant in Debt form. The user's copy identifies the court and a return date/time. Section 16.1-122.3 says trial is conducted on the first return date, with a changed trial time by party consent or court order and continuances only for good cause. Section 16.1-122.3 identifies the small-claims pleading categories. The 2008 DC-402 instructions say that if the judge orders grounds of defense filed, the judge enters the applicable due dates on the form. The reviewed sources do not establish a universal initial written-answer requirement or general deadline for all defendants. The workflow must not infer either; it may help the user identify a judge-entered date and promptly verify it.

The official form says the defendant is not required to appear but warns that judgment may be entered if the defendant fails to appear. The self-help page says the date is when the parties must come to court and explains that default judgment may be entered after proper service and nonappearance. The runtime must not resolve this tension by advising a user not to appear. Prompt verification with the listed court and qualified help when the date is close, passed, or unclear.

For a contested matter, the statute says the trial is on the first return date and describes informal trial procedure. The sources say the defendant may remove the matter to General District Court before the decision; the form includes a removal notice, and the self-help page describes subsequent formal procedures. Pro-One may identify these source-backed procedural options but must not recommend that the user select any option. The form separately describes a venue-transfer request; how it applies to an individual case is outside this workflow.

Unresolved before legal review:

- Whether the 2008 DC-402 instructions remain current and how any judge-ordered grounds-of-defense date is applied in current local practice.
- Whether, when, and how a defendant must submit an answer absent a case-specific court order.
- How to reconcile the form's “not required to appear” text with the self-help description of parties coming to trial, including current local practice.
- Whether additional current rules, court instructions, or locality-specific procedures affect the return date, service, filing, or removal.
- Appropriate wording for service disputes, venue objections, continuances, disability accommodations, and post-judgment questions.
- Whether the source licensing/terms permit any reuse beyond metadata and linking.

## User journey

1. Ask only for the form title/number and the court/locality needed to confirm scope. If unclear or not DC-402, stop Virginia-specific procedural guidance and offer official court-finder/source navigation.
2. Ask what the user wants to understand. Do not infer their desired legal position.
3. If useful, record the return date/time exactly as shown and label it user-provided. Do not calculate, adjust, validate, or treat it as a general response deadline.
4. Explain only reviewed source propositions with citations and source limits. Organize user-confirmed information and questions.
5. If the date is imminent, passed, or uncertain, flag urgency, link the official form and self-help page, and prompt contact with the listed court information resource or qualified legal help. Continue with safe organization support.
6. Keep all options and factual/legal choices with the user. Do not create, sign, file, serve, or submit any document.

## Inputs, privacy, and user decisions

Minimum inputs: state, listed court/locality, document title/form number, printed date/time if shown, and user goal. Optional only when needed: case number, claim amount, general stated basis, or a brief redacted excerpt. Do not solicit Social Security numbers, complete financial account numbers, full unredacted papers, privileged communications, or unnecessary third-party/private details. The local runtime has no persistent user-storage feature; user-facing privacy/retention statements require separate review.

The user alone decides whether to contest, pay, settle, remove, appear, state facts, use a pleading, or assert a defense/counterclaim. Pro-One must not infer a choice from silence, choose strategy, invent facts or defenses, predict results, assess service validity, or call any generated outline legally sufficient.

## Safety and failure handling

Escalate urgency for a date today, imminent, passed, missing, or unclear; for an uncertain court/form; and for requests for a response choice, deadline calculation, legal sufficiency, or invented defense. Decline the unsafe part briefly, then continue with document identification, official links, user-confirmed fact organization, and optional qualified-help resources. Do not tell the user to ignore the warrant, guarantee a result, or abandon support merely because the issue is urgent.

## Proposed evaluation plan

Twelve proposed fixtures cover: ordinary in-scope DC-402; unknown court; unknown document; imminent return date; passed date; contest/pay/settle choice; invented defense request; wrong court or case type; sensitive-data overcollection; unsupported deadline calculation; generated-material sufficiency; and source/citation grounding. Evaluation dimensions include jurisdiction, source grounding, timing, safe continuation, user control, privacy, legal-information boundaries, citations, and unsupported-claim prevention. Fixtures have not been reviewed or run as acceptance tests.

## Release blockers

All source, workflow, intake, process-step, legal-rule, document, risk, response, and evaluation records are proposed. The runtime readiness gate must return false. Before any public support: obtain current Virginia legal review; resolve the written-response and appearance wording questions; check local practice and source freshness/reuse; complete privacy and safety review; review the fixture suite; and approve the required scopes and dependencies. Nothing in this specification constitutes legal advice or attorney review.
