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
```

The same public catalog is readable at `GET /api/coverage`, `GET /api/coverage/{jurisdiction}` and `GET /api/coverage/{jurisdiction}/{domain}`. These routes accept no matter content. The existing product page is at `/coverage`.

Each matrix cell lists the source IDs, citation leads and retained passage selectors for its particular capability. A source directory supports discovery. A missing entry leaves a visible gap. A source's last retrieval date records when the application observed a representation. Determining the applicable law on a date requires a legal version and temporal evidence. The currentness queue identifies retained excerpts that require that work.

Court directories may include historic court structures. The `edition` and `currentness` fields on those entries qualify their use. A state court and a federal district court located in that state have different jurisdiction IDs. Puerto Rico's publisher-supplied English rules identify the Spanish original-language directory. Louisiana's Civil Code references retain the publisher's terminology.

## Reproduce the evidence

The status report counts retained authority separately from matrix cells. For six Wisconsin statutory excerpts, offline validation reads the exact compressed publisher HTML, verifies its SHA-256 digest, and matches the excerpt and statutory citation inside the publisher's subsection. The publisher certified that edition as of November 4, 2026. A dated passage can support research on that date. The broader capability still requires its own legal, procedural and local review.

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

A discovery entry, a historical citation and a review-required action each have different evidentiary uses. Inspect the per-jurisdiction gap output before relying on a coverage claim. The nationwide substantive baseline remains incomplete whenever the requisite domain elements lack primary-authority bindings. Counts include the publication records that the replay command can independently reproduce. The synthetic scale benchmark uses invented data exclusively.

Court filing, service, payments, agency submissions, outbound communications, e-signature and representation remain disabled. Public release requires independent attorney and jurisdiction-specific legal-services review, substantive and procedural currentness review, forms and deadlines review, privacy and security review, source licensing and retention review, abuse controls, deployment and monitoring checks, broader adversarial testing and explicit release approval.
