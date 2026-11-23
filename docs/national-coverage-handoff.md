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

## Next priorities

- Close substantive baseline gaps first. Reuse the cached Kentucky disability-tolling statute and confirm the Texas Chapter 16 legislative text. Continue personal-injury accrual and tolling, exceptions to fault regimes, ordinary contract breach and damages, and premises coverage as measured in the tracker.
- Reuse the captured filing-fee and transition evidence under `.local/sub209-*` when needed for court-specific procedure. Iowa Acts 2026 ch. 1192, §§ 24 and 28 distinguish fees paid before and on or after July 1, 2026. Maine's March 9, 2026 fee schedule distinguishes ordinary filings from covered debt-buyer filings.

Keep PR #31 in draft. External execution and public release remain disabled.
