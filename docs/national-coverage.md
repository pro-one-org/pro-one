# National coverage catalog

The development catalog registers the federal jurisdiction, 50 states, the District of Columbia and five inhabited territories. The named tribal directories identify separate sovereigns for further inquiry. Residence, court location and the address of an employer can point to different jurisdictions. The matter ledger can preserve those facts separately.

## Inspect a jurisdiction

```sh
python scripts/national_coverage.py status
python scripts/national_coverage.py jurisdiction US-DC
python scripts/national_coverage.py domain fault_allocation
python scripts/national_coverage.py gaps --jurisdiction LA
python scripts/national_coverage.py stale --jurisdiction NH
python scripts/national_coverage.py source-health --jurisdiction PR
python scripts/national_coverage.py distribution
python scripts/national_coverage.py baseline
```

The same public catalog is readable at `GET /api/coverage`, `GET /api/coverage/{jurisdiction}` and `GET /api/coverage/{jurisdiction}/{domain}`. These routes accept no matter content. The existing product page is at `/coverage`.

Each matrix cell lists the source IDs, citation leads and retained passage selectors for its particular capability. A source directory supports discovery. A missing entry leaves a visible gap. A source's last retrieval date records when the application observed a representation. Determining the applicable law on a date requires a legal version and temporal evidence. The currentness queue identifies retained excerpts that require that work.

Court directories may include historic court structures. The `edition` and `currentness` fields on those entries qualify their use. A state court and a federal district court located in that state have different jurisdiction IDs. Puerto Rico's publisher-supplied English rules identify the Spanish original-language directory. Louisiana's Civil Code references retain the publisher's terminology.

## Reproduce the evidence

The status report counts retained authority separately from matrix cells. Offline validation checks SHA-256 digests of retained publisher files and matches the excerpt to the cited subsection. Wisconsin's retained statutory edition is certified as of November 4, 2026. Michigan's retained Chapter 2 civil rules and Chapter 4 small-claims rules carry dates of November 18, 2026 and September 1, 2024, respectively. The Michigan rental statutes match the enrolled acts and the compiled publications dated October 25 and November 16, 2026. Indiana's published trial and small-claims indexes identify August 1, 2026 and January 1, 2025, respectively. Indiana validation checks the index link, the individual rule's effective date and its text. Delaware's Court of Common Pleas rules index dates the retained edition to January 10, 2023. Research can use each dated passage for its stated date and scope. The broader capability still requires its own legal, procedural and local review.

```sh
python scripts/national_coverage.py validate
python scripts/national_coverage.py build .local/coverage.sqlite3
python scripts/national_coverage.py benchmark
python scripts/benchmark_national_coverage.py
```

The build replays retained official text through the normalized corpus into a local SQLite database. Federal granules include the exact GovInfo HTML and pin the historical U.S. Code edition. For subnational excerpts, the selector binds the scope, citation, exact retained text and digest of the publisher capture. Each excerpt also has a separate text digest. The build can reproduce the excerpt snapshot offline. Independently checking its extraction requires the identified publisher representation. A changed page needs a new review and selector. A failed retrieval yields no normalized authority.

Jurisdiction-specific claims require every bound passage, proposition, edition and hash in their definitions. The development research provider exposes matching text for the requested jurisdiction, authority type and subject. A limitations reference alone cannot determine accrual, tolling, service, a calendar or a deadline. Each national Action OS reference definition describes dependencies and requires local review. All 204 reference definitions block execution.

## Review and release

To check a publisher, run `python scripts/national_coverage.py check-publisher US 28-1331-2024 .local/publisher-health.sqlite3`. This operator command requests only the public URL for a catalogued selector. The local history stores its timestamp, status and hashes. Changed bytes or an inaccessible endpoint require review. Existing legal records keep their prior versions and status.

California PUBINFO excerpts identify the archive ETag, section-table identity and XML member. The publisher hash covers the uncompressed XML member. A whole-archive health check reports `archive_member_replay_required`. New Jersey excerpts identify the legislative update through P.L.2026, c.70 and J.R.2 and retain separate hashes for the ZIP and its statutory text member. Both sets preserve unresolved currentness. A California effective date applies only to the version that carries it.

The baseline report counts partial coverage from bound passages separately from publication currentness and reference-only entries. The Wisconsin replay requires effective-date review when the publisher attaches a version note to the selected text. The publisher page can display future text beside the certified edition. Action OS reference actions expose the court scope, passage citation and supported date where available, with readiness blocked pending verification of all required dependencies. The `review_evidence` field exposes related passages, such as proof of service and response after a motion, for review. Required dependency checks use `procedure_evidence`.

A discovery entry, a historical citation and a review-required action each have different evidentiary uses. Inspect the per-jurisdiction gap output before relying on a coverage claim. The nationwide substantive baseline remains incomplete whenever the requisite domain elements lack primary-authority bindings. Counts include the publication records that the replay command can independently reproduce. The synthetic scale benchmark uses invented data exclusively.

### Publisher access gaps

The catalog binds passages from archived copies of the original court PDFs for two Tennessee contract opinions, the Maryland *Coleman* majority opinion and the New Jersey Supreme Court's May 2022 small-claims amendment. The archive URLs identify the original publishers and the retained digests identify the retrieved bytes. The opinions have historical status with subsequent treatment unverified. The dated New Jersey amendment establishes the adopted text in that order. Later currentness remains unresolved.

New Hampshire's archived Superior Court rules preserve distinct answer, appearance and motion triggers. Maryland's November 2003 order supports the January 2004 Circuit Court exceptions and District Court notice of intention to defend. The order omits the Circuit Court's general answer rule. The New Mexico Compilation Commission publishes the retained District Court text. The signed service amendment establishes an effective date of December 31, 2025, and the rule limits that edition to cases filed on or after that date. The compilation's upload timestamp leaves later currentness unresolved. [New Mexico order](https://supremecourt.nmcourts.gov/wp-content/uploads/sites/2/2025/10/Order-No.-S-1-RCR-2023-00009.pdf) · [Approved rule text](https://supremecourt.nmcourts.gov/wp-content/uploads/sites/2/2025/10/Rule-1-004-NMRA.pdf)

The ordinary-negligence topic has a retained judicial passage for each state and the District of Columbia. The passages support their stated rules and case contexts. Currentness review, specialized duties, defenses, exceptions and damages coverage remain separate. Several original court PDFs were available through public repositories. Oregon's *Stone* passage was checked against the State Law Library edition. [Oregon Reports](https://ojd.contentdm.oclc.org/digital/api/collection/p17027coll3/id/16317/download)

Arkansas Act 559 establishes the 2009 changes to security-deposit refunds and the cross-reference to the deposit statute. Act 531 of 1979 remains unavailable through the archives reviewed. The Kentucky Court Rules archive supplies Rule 12.01 as published with amendments received through May 1, 2022. Alabama's signed local wage-preemption act addresses local regulatory authority. The Bureau of Labor Statistics' 1926 compilation reproduces Mississippi's earlier wage-payment frequency statute. The 1991 Mississippi amendment is held in box 28677 at the state archives, and the applicable current text still needs verification. For Maine, the catalog retains bounded statutory text with currentness unresolved. Redistribution of the complete publisher archives carrying a rights notice was rejected in approval review. [Arkansas Act 559](https://www.arkleg.state.ar.us/Home/FTPDocument?path=%2FACTS%2F2009%2FPublic%2FACT559.pdf) · [Mississippi enrolled-bill inventory](https://finding.mdah.ms.gov/index.php/government-records/258-1)

Retained procedure passages cover venue and personal service in Alaska, service methods in California and Connecticut, and summons requirements in Connecticut and Colorado. Illinois's April 2023 rules distinguish the time for service, proof of service and summons in cases governed by the residual response rule. Kentucky's March 2024 rules edition requires both filing and issuance in good faith. Kentucky's limitations statute addresses the date of commencement and has a separate research topic. The catalog preserves the publication dates and keeps present applicability unresolved. [Alaska civil rules](https://courts.alaska.gov/rules/docs/civ.pdf) · [Colorado Rule Change 2024(08)](https://www.coloradojudicial.gov/sites/default/files/2024-05/Rule%20Change%202024%2808%29.pdf) · [Illinois Rule 102](https://www.illinoiscourts.gov/resources/d890ef39-a2b2-4b43-8014-500f5c3826f3/file)

Court filing, service, payments, agency submissions, outbound communications, e-signature and representation remain disabled. Public release requires independent attorney and jurisdiction-specific legal-services review, substantive and procedural currentness review, forms and deadlines review, privacy and security review, source licensing and retention review, abuse controls, deployment and monitoring checks, broader adversarial testing and explicit release approval.
