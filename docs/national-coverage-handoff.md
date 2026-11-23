# National Coverage Expansion v1 handoff

## Verified starting point

- Branch `codex/national-coverage-expansion-v1`, draft PR #31. Local HEAD, the tracking ref and the latest confirmed pushed checkpoint at recovery were `563bfd6f0aa7e78b4d57dae13ca9edc73ac91498`. The PR was open and mergeable. Exact-head CI run `44983147614` passed, including production build and smoke. Local regression passed 653 tests.
- Recovery found zero staged, unstaged or untracked non-ignored files. The prior report of 16 pending modifications could not be reconciled to files in this checkout. The publisher captures and preparation scripts for the next batch remained available under the ignored `.local` directory.

## Current batch

- Reused publisher captures for 17 scoped passages. Premises evidence reaches 8 of 51 jurisdictions, habitability 15, tenancy notice 13, and possession 11. The premises batch adds six historical records. The housing batch adds 11 records with unresolved currentness.
- The validated corpus has 1,390 authority versions, including 155 verified as of a publisher date, 506 historical and 729 currentness-unresolved. Of 3,764 coverage cells, 1,481 are unsupported, 1,621 partial and 662 reference-only at the coverage-depth tier. Execution is disabled.
- Added a regression distinguishing the Michigan and Ohio open-and-obvious opinions and the [64-criterion acceptance tracker](national-coverage-acceptance.md).
- Local preparation and validation logs are under `.local/sub211-*.log`. The batch includes eight jurisdiction manifests, the focused regression and these two documents. Publisher captures and temporary scripts remain ignored.

## Validation

- Passed 92 focused national tests, repository and coverage validation, verification of 15 publisher capture hashes, and the gap, stale and source-health reports.
- Passed all 37 mapped fixtures and both national research evaluations. Four fixtures remain unmapped. The adversarial retrieval evaluation ran 24 positive and 18 negative checks with zero negative leaks. Retained-data and synthetic national benchmarks passed.
- The paused full regression log ends before the test summary. A clean rerun is recorded under `.local/sub211-resume-full.log`. The exact-head production build and smoke evidence above is for `563bfd6`. Verify the batch commit and its checks on the draft PR before relying on the new checkpoint.

## Acceptance gap checkpoint

- The prior checkpoint `0454ecf` passed 654 local regression tests and [exact-head CI](https://github.com/pro-one-org/pro-one/actions/runs/45200027326), including production build and smoke. The branch and worktree were clean at recovery.
- Criterion 22 now has a signed, enacted Mississippi wage-law source. The retained Equal Pay for Equal Work Act covers the stated equal-pay claim and retains the July 1, 2022 effective date. Ordinary payday-frequency research still requires the enacted 1991 amendment and subsequent history. The State Archives lists 1991 Regular Session chapters 376–450 in Series 2585, container 28677.
- Criterion 36 now has independent nationwide shell verification and restored court-rule references for D.C., Michigan, New Mexico and Ohio. The shell test requires local selection, in-jurisdiction commencement and service evidence, and disabled execution.
- California's revised SC-100 links directly to the matched official PDF in the small-claims shell. Identification of remaining mandatory forms and applicability is open. The Maryland Judiciary identifies DC-CV-115 and the statutory trigger. The public PDF and form index downloads returned access errors, so this batch retains the existing statute without a verified PDF binding.
- The corpus now has 1,393 authority versions, including 155 dated publisher verifications, 506 historical records and 732 with unresolved currentness. There are 1,477 unsupported, 1,622 partial and 665 reference-only coverage cells. Focused tests, source validation, all 37 mapped evaluations and both national research evaluations passed. Consolidated logs are under `.local/sub215-*.log`.

## Contract and premises checkpoint

- Prior exact-head checkpoint `9a29315` passed 657 local regression tests and [CI run 45207730947](https://github.com/pro-one-org/pro-one/actions/runs/45207730947), including production build and smoke.
- Ten new passages bind California and Massachusetts official civil jury instructions and a certified Nebraska Supreme Court decision. General contract breach evidence increased from 18 to 20 jurisdictions, damages from 22 to 24, and premises from eight to ten. Model instructions retain their court and edition scope with unresolved currentness. The Nebraska opinion is historical.
- This batch has 1,403 retained versions, with 155 dated publisher verifications, 507 historical and 741 currentness-unresolved. Of 3,764 coverage cells, 1,469 are unsupported, 1,630 partial and 665 reference-only. The acceptance tracker now gives individual status and measurements for criteria 14 through 18. Local checks are under `.local/sub217-*.log`.
- Checkpoint `df5f85a` exposed a regression fixture that assumed California premises authority was absent. The next batch gives that negative test an explicitly empty provider set and checks that the service returns no evidence package.

## Limitations exceptions checkpoint

- Added nine passages across Arizona, D.C., Illinois, Kentucky, Michigan and Texas. The D.C. publisher version verifies two provisions as of April 29, 2026. The XML replay preserves the operative clause that follows the list of disabilities. Illinois retains two differing historical appellate readings of the survival-action rules under their respective case scopes.
- Nationwide accrual passage coverage rose from six to seven jurisdictions and tolling from 13 to 18. The corpus now has 1,412 authority versions with 157 dated publisher verifications, 509 historical and 746 currentness-unresolved. Coverage depths are 1,463 unsupported, 1,636 partial and 665 reference-only.
- The corrected negative test and new D.C. and Illinois regressions passed. Consolidated checks are logged under `.local/sub220-check-*.log`.
- The full suite at `61d799d` found a test that expected exactly one Michigan tolling authority. The form batch checks both retained statutes and verifies that neither satisfies the ordinary limitations query.

## Official form applicability checkpoint

- Added four official form references. California SC-120 is scoped to a defendant's small claim, Idaho CAO SC 1-2 to plaintiff commencement, and Utah 2001SC and 1025XX to the two distinct justice-court paths. Utah requires a substantially similar form. The shell exposes the court's applicability source and exact requirement level with completion disabled.
- Ten form artifacts are indexed and five have verified form and requirement bindings. Direct court downloads for Maryland DC-CV-115 and NYC CIV-SC-50 were inaccessible. The full corpus has 1,415 versions, including 157 dated publisher verifications, 509 historical and 749 currentness-unresolved. There are 1,461 unsupported, 1,638 partial and 665 reference-only coverage cells.

## State fault and premises checkpoint

- Prior exact-head checkpoint `dc6d1d9` passed 660 local regression tests and [CI run 45212480209](https://github.com/pro-one-org/pro-one/actions/runs/45212480209), including production build and smoke.
- Alaska official model instructions distinguish improved and unimproved property and provide general contract formation, breach and expectation damages. Arizona's Supreme Court opinion addresses actual control. Kansas's published Supreme Court opinion adds ordinary contract-breach elements. The model instructions retain unresolved currentness and the opinions remain historical.
- D.C.'s pinned April 29, 2026 publisher version retains the collision scope, vulnerable-user definition and preserved doctrines. New York's signed chapter law and agency guidance confirm the May 26, 2026 action-commencement transition. Both statutory text versions remain available.
- The corpus has 1,427 versions, including 160 dated publisher verifications, 512 historical and 755 currentness-unresolved. There are 1,455 unsupported, 1,644 partial and 665 reference-only coverage cells. Checks are under `.local/sub226-check-*.log`.

## Accrual and civil cover sheet checkpoint

- Prior exact-head checkpoint `1c1f8f1` passed 662 local regression tests and [CI run 45215365701](https://github.com/pro-one-org/pro-one/actions/runs/45215365701), including production build and smoke.
- Added the North Carolina bodily-harm or physical-damage discovery provision, New York's latent-exposure rules with exclusions, and Wisconsin's 2015 survival and wrongful-death opinion. Retained accrual evidence now spans ten jurisdictions. The Wisconsin opinion is historical and the statutes remain currentness-unresolved.
- Added initiating civil cover-sheet bindings for Colorado JDF 601, Massachusetts SC0001 and Florida 1.997. Florida's court copy has no displayed revision, so the reference preserves that uncertainty with the capture date and digest. Thirteen forms are indexed and eight have retained form and requirement evidence.
- The corpus has 1,433 versions, including 160 dated publisher verifications, 513 historical and 760 currentness-unresolved. There are 1,449 unsupported, 1,650 partial and 665 reference-only coverage cells. Checks are under `.local/sub230-check-*.log`.

## Certified Washington law and contract remedies checkpoint

- Prior exact-head checkpoint `3635d52` passed 663 local regression tests and [CI run 45217119331](https://github.com/pro-one-org/pro-one/actions/runs/45217119331), including production build and smoke.
- The original checkout was unavailable at recovery. The pending Washington and contract-remedy edits were reconstructed against the same pushed commit in a separate checkout. All four Washington publisher files match their previously recorded SHA-256 digests.
- Washington's publisher-certified July 12, 2024 PDFs preserve the ordinary injury and written-contract periods, comparative fault, and the distinct joint-liability statute. The certificate replay preserves the publisher's bracketed correction in RCW 4.22.070.
- Florida, Ohio and Texas published opinions add scoped historical contract-remedy evidence. Texas distinguishes direct and consequential damages, including separate foreseeability and reasonable-certainty requirements.
- The corpus has 1,441 authority versions, with 164 dated publisher verifications, 517 historical and 760 currentness-unresolved. There are 1,447 unsupported, 1,652 partial and 665 reference-only coverage cells. Contract damages passages span 26 jurisdictions. Recovery checks are under `.local/recovery-*.log`.

## Maryland and New York court forms

- Checkpoint `bad044f` contains the recovered Washington and contract-remedy batch. The original checkout and its local live-corpus snapshots were unavailable. The recovered diff has 253 additions and six deletions across the eight tracked files and four certified archives. The earlier report of 296 additions and 19 deletions could not be independently reconciled.
- All 664 local regression tests passed at `bad044f` along with coverage and repository validation, 37 mapped evaluations, and both national coverage benchmarks. [Exact-head CI](https://github.com/pro-one-org/pro-one/actions/runs/45262010022) passed, including the production container build and smoke tests. PR #31 was open, draft and mergeable at that head. The live-corpus adversarial and national research evaluations could not be rerun because their ignored SQLite inputs were in the missing checkout.
- Maryland identifies DC-CV-115, revised October 2024, as the required notice before a residential nonpayment summary-ejectment complaint. The retained Maryland statute supplies the notice trigger and methods. The notice form is separate from the complaint form. [Maryland Judiciary housing instructions](https://www.mdcourts.gov/legalhelp/housing) and [official DC-CV-115](https://www.mdcourts.gov/sites/default/files/court-forms/dccv115.pdf).
- New York identifies NYC Civil Court CIV-SC-50, revised April 22, 2022, as the small-claims statement of claim. The court publishes clerk-office and limited mail procedures. The captured July 7, 2023 statutory rendition supports NYC small-claims commencement and preserves the employee fee exception. The statute does not identify the form by number, and its currentness remains unresolved. [New York State Senate § 1803](https://www.nysenate.gov/legislation/laws/CCA/1803) and [NYC small-claims filing instructions](https://www.nycourts.gov/new-york-city-small-claims-court/starting-case-nyc-small-claims-court).
- Direct publisher downloads of the two PDF artifacts returned HTTP 403. The published text can be inspected, but the download failure prevents reproduction of a raw artifact hash. Both forms remain outside the verified binding count.

## Colorado and Illinois premises and Washington accrual

- Colorado's enacted 2022 session law preserves the limited treatment of the Wagner decisions and the pending-action applicability clause. Two published appellate opinions separately support the licensee rule on dangers created by the landowner and the invitee rule for unit owners' guests in association-owned and controlled common elements.
- Illinois's published Bruns opinion preserves the actual-distraction requirement and distinguishes looking elsewhere. Washington's published Nichols opinion adds a scoped discovery and reasonable-diligence passage for water intrusion and construction negligence. It does not fill Washington's personal-injury discovery gap.
- The corpus has 1,447 authority versions, including 164 dated publisher verifications, 521 historical and 762 currentness-unresolved. Of 3,764 cells, 1,444 are unsupported, 1,655 partial and 665 reference-only. Premises passage coverage spans 13 jurisdictions. The full validation logs are under `.local/premises-final-*.log`.
- The full suite and [CI for `31964db`](https://github.com/pro-one-org/pro-one/actions/runs/45262668355) found a NYC procedural test that assumed one reference. The regression now requires both NYC statutes and checks that each remains local and currentness-unresolved. The response still denies external action.

## Colorado ordinary contract and Connecticut summons checkpoint

- Checkpoint `e641eed` passed 666 local regression tests and [exact-head CI](https://github.com/pro-one-org/pro-one/actions/runs/45264092999), including the production container build and smoke tests.

- Five February 2026 judiciary pattern instructions distinguish ordinary breach, materiality, the effects of nominal damages, and the proof required for general and special damages. Later currentness and case-specific instruction selection remain unresolved. The historical Colorado Supreme Court accrual opinion distinguishes discovery of breach from awareness of damages.
- Twenty-three jurisdictions have retained breach evidence and 26 have damages evidence across all categories, including 16 with general contract damages. The corpus has 1,453 authority versions, including 164 dated publisher verifications, 522 historical and 767 currentness-unresolved. Of 3,764 cells, 1,442 are unsupported, 1,656 partial and 666 reference-only. Checks are recorded under `.local/contract-summons-final-*.log`.

- The Connecticut Judicial Branch now distributes JD-CV-1, revision August 2026. The direct PDF is linked to the verified 2026 Practice Book § 8-1(a) capture and applies to ordinary Superior Court civil writs substantially in compliance with the form. Its instructions distinguish the clerk-signed pro se route, exclusions, and filing after service. Fourteen official form artifacts are indexed and nine have a verified form and requirement binding. [Official JD-CV-1](https://www.jud.ct.gov/webforms/forms/cv001.pdf) and [2026 Connecticut Practice Book](https://www.jud.ct.gov/publications/PracticeBook/PB.pdf).

## Florida and Wisconsin premises and Louisiana transitions

- Checkpoint `444d255` passed 668 local regression tests and [exact-head CI](https://github.com/pro-one-org/pro-one/actions/runs/45265469918), including production container build and smoke.

- Florida adds the 2026 Online Sunshine text on notice for transitory foreign substances in business establishments and the separate trespasser immunity, duty and exceptions provision. The source edition is recorded and subsequent currentness remains unresolved.
- Wisconsin adds the published Rosario decision on actual or constructive notice for an unsafe condition associated with the structure of a public building. The passage remains historical and scoped to that test.
- Louisiana preserves the January 1, 2026 comparative fault amendment with the prior proportional-reduction clause, the separate solidary liability provision, and the July 1, 2024 prescription act's prospective applicability. The date evidence does not resolve a particular action's governing version.
- Fifteen jurisdictions have premises evidence. The corpus has 1,460 authority versions, including 164 dated publisher verifications, 524 historical and 772 currentness-unresolved. Of 3,764 coverage cells, 1,438 are unsupported, 1,660 partial and 666 reference-only. Checks are logged under `.local/transitions-verified-*.log`.

## Rhode Island and Vermont premises checkpoint

- Vermont's Demag opinion preserves the standard for lawful entrants and its distinct trespasser scope. Rhode Island's Kurczy and Berard opinions distinguish the duty to expected invitees from the commercial lessor's duties concerning the leased premises, including the repair-covenant and latent-defect exceptions.
- Seventeen jurisdictions now have premises evidence. The corpus has 1,463 authority versions, including 164 dated publisher verifications, 527 historical and 772 currentness-unresolved. Of 3,764 coverage cells, 1,434 are unsupported, 1,664 partial and 666 reference-only.
- The full suite and [CI for `3f6e932`](https://github.com/pro-one-org/pro-one/actions/runs/45267131062) found a Wisconsin isolation test that assumed there was no local premises evidence. The regression now checks that the original authority cannot cross into Wisconsin and that every Wisconsin result belongs to Wisconsin. Checks are recorded under `.local/ri-vt-final-*.log`.

## Next priorities

- Close substantive baseline gaps first. Continue personal-injury accrual and tolling, exceptions to fault regimes, ordinary contract breach and damages, and premises coverage as measured in the tracker.
- Continue verified form applicability after restoring access to the official Maryland and New York artifacts. The prior checkout's ignored live-research snapshots are unavailable. Exact-head CI uses retained evidence and offline fixtures. The historical live evaluation needs its separate pinned corpus inputs.

Keep PR #31 in draft. External execution and public release remain disabled.
