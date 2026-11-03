# Capability compiler

`app/capability_compiler.py` converts authoritative collections into proposed review artifacts, without certifying legal truth. One capability covers many questions and factual scenarios. Workflows remain optional procedural modules.

## Command and inputs

```text
python -B scripts/build_capability.py --jurisdiction Virginia --legal-area torts --topic premises_liability --output review/va-premises
python -B scripts/build_capability.py --jurisdiction Virginia --legal-area torts --topic premises_liability --provider virginia_official --output review/va-premises-fresh
python -B scripts/build_capability.py --jurisdiction Virginia --legal-area torts --topic premises_liability --previous review/va-premises/bundle.json --output review/va-premises-refresh
```

Default provider: `repository`, using actual curated authoritative excerpts offline. The official provider uses its fixed bounded catalog. `--collection collection.json` accepts a UTF-8 JSON array, at most 4 MB/twelve documents. Each document contains `source` (a complete source-schema record), `text` (actual normalized source text), and optional `passages` (complete source-passage records). Collection URLs are metadata and are never fetched. Developers must establish authentic primary-source provenance; assigning an official URL does not authenticate arbitrary local text.

## Pipeline

1. Collect source documents and preserve dates, metadata and actual text.
2. Reset every input record to proposed/null review; reject invalid jurisdiction/metadata.
3. Validate supplied passages against collected text, or propose bounded sentence excerpts and record a context-review gap.
4. Check authority, jurisdiction, locator, citation, version/provenance, hash and exact source-text inclusion.
5. Construct candidate propositions and existing-schema legal rules. An unsupported or nonexact candidate paraphrase is excluded and becomes a support gap. No model key is required.
6. Preserve conflict notices. Do not decide exceptions or treat a dissent as a binding holding.
7. Generate a capability and proposed evaluation fixtures, then validate schemas and typed graph relationships.
8. Write `bundle.json` and `REVIEW.md` to a new directory outside canonical data. Never promote records, rewrite Git or commit.

All records remain proposed, all review identities/dates/versions remain null, and currentness is unresolved. Exact text linkage establishes occurrence in collected evidence, not legal applicability or holding status. Generated rule `user_facing_allowed` stays false. Future LLM extraction must remain candidate data and satisfy this boundary or introduce a stronger reviewed entailment mechanism.

## Review and refresh

Review source sets, capability boundaries, key propositions, exceptions, majority/dissent roles, posture, conflicts, dates/treatment and risk policy. Curated plain-language variants require legal review against linked evidence. Register generated fixture versions and executable checks before scoring them; generated narratives cannot approve themselves.

`--previous` compares source IDs, normalized-text hashes, provenance and dates, reporting new/removed/changed sources and resetting review. Changed/missing excerpts remain gaps. Automatic legal amendment analysis, citator treatment and scheduled refresh are not implemented. Promotion is a separate versioned repository change under existing review/currentness policy. Public research remains blocked independently of compiler success.

## Virginia proof package

- [Fultz v. Delhaize America, Inc., 278 Va. 84 (2009)](https://www.vacourts.gov/static/opinions/opnscvwp/1080782.pdf): invitee/storeowner care, warning/open-and-obvious qualifications and contributory-negligence context.
- [Austin v. Shoney's, Inc., 254 Va. 134 (1997)](https://www.vacourts.gov/static/opinions/opnscvwp/1961236.pdf): conditional created-condition/notice and causation inferences on a motion to strike; dissent preserved.
- [Va. Code section 8.01-243(A)](https://law.lis.virginia.gov/vacode/title8.01/section8.01-243/): general personal-injury limitations language; no deadline calculation or resolution of accrual/tolling/exceptions.

This set does not establish factual notice, proper defendant, premises control, causation, medical evidence, damages, venue, defenses or outcome. A complete negligence-elements/damages framework and ordinary third-party constructive-notice doctrine remain gaps. Case treatment is unknown and legal/currentness review is pending. Thirteen registered canonical fixtures cover grounded answering, missing/wrong jurisdiction, workflow independence, general research, conflicts, currentness, invented cases/statutes, injection, unsupported propositions and outcome/deadline/damages claims.
