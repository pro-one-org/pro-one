# National Coverage Expansion v1 acceptance tracker

Numbers follow section 161 of the original 165-section specification. **Satisfied** means the listed evidence verifies the criterion at the recorded checkpoint. **Incomplete** includes pending independent verification. **Blocked** identifies a specific dependency outside the implementation. Recheck exact-head gates after each push.

| Criteria | Status | Evidence or work remaining |
| --- | --- | --- |
| 1 | Satisfied | The branch creation reflog records `origin/main` at `a9ce93b` on November 17, 2026, six seconds after that main ref was fetched. The first feature commit, `a368888`, has `a9ce93b` as its sole parent. |
| 2–8 | Satisfied | Registry and manifest validation cover 52 core jurisdictions and five inhabited territories, including state and D.C. statutory, judiciary, procedural and court hierarchy entries. |
| 9–13 | Satisfied | Small claims, service, response, fees and e-filing have a source or an explicit status in each state and D.C. The baseline report separately identifies which entries have retained passages and which require local research. |
| 14–18 | Incomplete | Retained negligence, fault, personal-injury limitations, contract formation and contract limitations evidence spans all 51 jurisdictions. Premises rules, fault exceptions, accrual, ordinary contract breach and damages, and publisher currentness still have gaps. Sales and electronic transaction authority only supports its stated scope. |
| 19–21 | Satisfied | The baseline identifies jurisdiction-specific consumer, residential rental and collection-law sources. The corresponding substantive remedies and procedural routes still have coverage gaps. |
| 22 | Blocked | Obtain authoritative Mississippi Code § 71-1-35 text and amendment evidence. The Mississippi Archives identifies the enrolled-bill collection, and 2025 H.B. 1307 as introduced is discovery evidence. Wage agency and enforcement coverage also remains incomplete elsewhere. |
| 23–24 | Satisfied | The matrix and capability records include separate jurisdiction entries and disabled action states. |
| 25–30 | Satisfied | Manifest and corpus tests check passage-to-authority binding, jurisdiction isolation, invented and wrong-proposition evidence, dated currentness, and coexistence of earlier and later legal text. |
| 31–35 | Satisfied | Corpus and downstream tests cover version preservation, drift, parser and network failures, and stale authority invalidating downstream artifacts. Reviewed real-world supersession links remain a corpus gap. |
| 36 | Incomplete | All 51 jurisdictions have review shells. The production action catalog has one bounded preview definition. Verify whether each shell meets the definition obligation in sections 139 and 161 and supply the missing jurisdiction-specific procedure bindings. |
| 37–38 | Satisfied | Local dependencies remain explicit, and proposed capability records preserve the complaint and document gates. |
| 39 | Incomplete | Retain and verify mandatory court forms and the triggers for their use where applicable. Seven form records are present. |
| 40–44 | Satisfied | Deadline and action tests preserve the currentness and approval gates, research remains available, and D.C. and the territories retain distinct scope. |
| 45–48 | Satisfied | Louisiana claim evidence preserves civil-law treatment. Puerto Rico supports original-language metadata. Federal and state procedure remain isolated and federal jurisdiction requires grounding. |
| 49–52 | Satisfied | Adversarial tests reject model-created authority, currentness promotion, invented procedural support and coverage bypass. |
| 53–56 | Satisfied | The coverage CLI exposes status, gaps, stale authority, and source health. |
| 57–60 | Satisfied | The checkpoint handoff records the most recent tested commit, national benchmarks, full regression, production build and smoke results. |
| 61–62 | Satisfied | External execution and public release gates are closed. |
| 63–64 | Satisfied at last remote verification | Draft PR #31 CI and mergeability must be checked on the new remote head. See the handoff for the exact verified checkpoint. |

Run `python scripts/national_coverage.py baseline` for jurisdiction-by-jurisdiction passage gaps, `validate` for version and currentness totals, and `gaps`, `stale` and `source-health` for their respective review lists. A retained passage supports its recorded proposition and scope. Review depth and dated verification are independent.
