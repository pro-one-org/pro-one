# National acceptance closure audit

Criteria 14–18 and 39 remain open. The numbered gates below correspond to §161 of the original milestone. Sections 30 and 32 define substantive and fault coverage, §§39–40 define limitations and deadline safeguards, and §§56–57, 102, and 109–110 define form metadata, preference, and fallback.

## Closure conditions

| Criterion | Required evidence and verification |
| --- | --- |
| 14. Negligence | For each of the 51 jurisdictions, review and bind the ordinary duty, breach, causation and injury or damages propositions to retained primary text. Record the premises relationship and materially different entrant, control, notice or hazard rules where applicable. Review controlling scope and subsequent treatment. Test ordinary and premises propositions separately, including wrong-state and wrong-premises cases. A single general-elements passage can support several propositions only after each is reviewed. |
| 15. Fault allocation | For all 51 binding records, verify the actual threshold or bar against the governing version and distinguish any material class exception, attribution rule, separate allocation of liability and transition. Preserve prior text, effective dates and event or filing triggers. Test both sides of any threshold and transition with the jurisdiction and claim class fixed. |
| 16. Personal-injury limitations | For all 51 jurisdictions, verify the primary period and the covered claim, separately identify accrual, discovery, tolling and material exceptions, such as disability and special defendants or injury classes. Record the basis where an item does not apply. Review dates and versions. A period alone yields no calculated deadline. |
| 17. Contract | For all 51 jurisdictions, verify ordinary agreement and obligation, breach, and ordinary remedies or damages, with material scope and exceptions. Review alternate treatment such as no signed writing, sale of goods, or a special contract class against separate authority where applicable. Test ordinary claims against goods-only and other limited authority. |
| 18. Contract limitations | For all 51 jurisdictions, bind the ordinary limitations authority separately for material written, oral and special claim classes. Review accrual, discovery or tolling where governing, and exceptions such as payment, signed acknowledgment or statutory displacement where material. Record version applicability and test that duration alone produces no computed deadline. |
| 39. Official mandatory forms | Inventory the supported action paths by jurisdiction, tribunal, case subtype, party role, stage and filing channel. For every mandatory or substantially-similar form, preserve the publisher artifact and revision evidence, exact digest, governing requirement, scope and filing prerequisites. Test that the correct artifact is preferred only in the supported path. Where an official form is optional or custom pleading is allowed, record the publisher evidence, and otherwise keep unresolved local requirements explicit. Test mandatory, optional or custom, and unresolved fallback paths without enabling completion or execution. |

## Reading the jurisdiction inventory

- **D** means dated publisher verification for at least one retained passage or the bound fault regime. **U** means currentness unresolved. **H** means historical. A dash means no separately indexed passage or binding in that column. These are evidence states. Scope, effective interval, precedential weight, exceptions and applicability require separate review.
- For criterion 14, every elements entry still needs a proposition-by-proposition review. The 31 jurisdictions with no premises passage need a primary premises source or a documented, source-backed applicability finding.
- For criteria 16 and 18, the period column counts any retained source in the named category, including narrowly scoped sources. Unindexed accrual and tolling are review gaps. A general tolling record also needs claim-class applicability review. Washington's indexed accrual concerns property damage from construction negligence.
- For criterion 17, **sales** identifies jurisdictions whose formation category currently has only sale-of-goods text. **Candidate** marks possible non-sale coverage, including limited opinions or instructions that still require scope and currentness review. Colorado's new ordinary formation instruction does not certify its currentness. General damages excludes sales-only and special remedies.
- For criterion 39, the last column lists exact artifact identifiers with a scoped requirement binding. Unlisted paths still need an affirmative applicability or fallback review. NYC's CIV-SC-50 binding covers the eligible paper mail route in the NYC Civil Court Small Claims Part. Maryland DC-CV-115 is an identified residential nonpayment prefiling notice under §8-401(c). The court lists revision 10/2024 and exposes the rendered PDF, but direct and legacy PDF downloads returned HTTP 403 here, and the maintenance hostname failed TLS hostname validation. Its exact PDF bytes still need a reproducible acquisition before binding. [New York court form record](https://www.nycourts.gov/forms/statement-claim-small-claims) · [NYC filing instructions](https://www.nycourts.gov/new-york-city-small-claims-court/starting-case-nyc-small-claims-court) · [Maryland court form](https://www.mdcourts.gov/sites/default/files/court-forms/dccv115.pdf).
- Reproduce the table with `python -B scripts/audit_national_acceptance.py`. It uses validated manifests and does not assign acceptance status.

| Scope | 14 elements | 14 premises | 15 regime | 16 period | 16 accrual | 16 tolling | 17 formation | 17 breach | 17 ordinary damages | 18 period | 18 accrual | 39 scoped forms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AK | H | U | U | U | — | — | candidate | U | U | U | — | — |
| AL | H | — | H | H | — | — | candidate | H | — | H | — | — |
| AR | H | — | H | H | — | — | candidate | — | — | H | — | — |
| AZ | H | H | U | U | — | U | sales | H | — | U | — | — |
| CA | H | U | H | U | — | — | candidate | U | U | H | — | SC-100, SC-120 |
| CO | H | U/H | H | H | H | — | candidate | U | U | U | U/H | JDF 601 |
| CT | H | — | H | H | — | H | sales | H | — | H | — | JD-CV-1 |
| DC | H | — | D | U | — | D | sales | — | — | D | — | — |
| DE | H | — | U | U | — | — | sales | H | H | U | U | — |
| FL | H | U | U | U | U | — | candidate | H | H | U | — | 1.997 |
| GA | H | H | H | H | — | — | sales | — | — | H | — | — |
| HI | H | — | U | H | — | — | sales | — | — | U | — | — |
| IA | H | H | U | H | — | H | sales | H | — | H | — | 3.1 |
| ID | H | — | U | U | — | — | sales | H | — | U | — | CAO SC 1-2 |
| IL | H | H | H | H | — | H | candidate | H | H | H | — | — |
| IN | H | — | H | H | — | — | candidate | — | — | H | — | — |
| KS | H | — | U | U | — | — | sales | H | — | H | — | — |
| KY | H | H | U | U | — | U | sales | — | — | U | — | — |
| LA | H | — | U | U | — | — | candidate | U | U | U | U | — |
| MA | H | U | U | U | — | U | candidate | U | U | U | — | SC0001 |
| MD | H | — | H | U | — | — | sales | — | — | U | — | — |
| ME | H | — | U | U | U | U | sales | H | — | U | — | SC-001 |
| MI | H | H | U | U | U | U | sales | H | — | U | — | — |
| MN | H | H | U | U | — | U | sales | H | — | U | — | — |
| MO | H | — | U | U | — | — | sales | H | — | U | H | — |
| MS | H | — | H | H | — | — | candidate | — | — | H | — | — |
| MT | H | — | U | U | — | — | sales | — | H | H | — | — |
| NC | H | — | H | U | U | — | sales | — | — | U | — | — |
| ND | H | — | U | U | — | U | sales | — | U | U | — | — |
| NE | H | — | U | U | — | — | sales | — | H | U | — | — |
| NH | H | — | U | U | — | — | sales | — | — | U | — | — |
| NJ | H | — | U | U | — | — | sales | — | — | H | — | — |
| NM | H | — | H | H | — | — | candidate | — | — | H | — | — |
| NV | H | — | U | U | — | — | sales | — | — | U | — | — |
| NY | H | — | U | U | U | U | sales | — | — | U | — | CIV-SC-50 |
| OH | H | H | U | U | U | — | sales | H | H | U/H | — | — |
| OK | H | — | U | U/H | — | — | sales | — | U | U | — | — |
| OR | H | — | U | U | — | H | sales | — | — | U | — | — |
| PA | H | H | H | H | — | — | candidate | — | — | H | — | — |
| RI | H | H | U | U | — | — | sales | — | — | U | — | — |
| SC | H | — | H | U | — | — | sales | — | — | H | — | — |
| SD | H | — | U | U | — | — | sales | — | U | U | — | — |
| TN | H | — | H | H | — | — | candidate | — | — | H | — | — |
| TX | H | H | U | H | U | U | sales | H | H | U | — | — |
| UT | H | — | U | U | — | U | sales | — | — | U | — | 1025XX, 2001SC |
| VA | H | H | H | U | U | U | sales | H | — | U | — | — |
| VT | H | H | U | U | — | U | sales | — | — | U | — | — |
| WA | H | — | D | D/U | H (property) | D/U | sales | H | H | D/U | — | — |
| WI | H | H | D | D | H | — | sales | — | — | D | — | — |
| WV | H | H | U | U | — | — | sales | H | — | H | — | — |
| WY | H | — | U | U | — | — | sales | — | — | U | — | — |
