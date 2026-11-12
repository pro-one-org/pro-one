"""Measure local retrieval of known Virginia cases in a supplied corpus."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.corpus_store import SQLiteCorpusStore
from app.capabilities import ResearchMatter
from app.research_planning import LegalResearchPlanner


LABELS = (
    ("contracts", "contract_breach", "What must I show for breach of contract and resulting damages in Virginia?",
     1059098, "267 Va. 612",
     "https://www.vacourts.gov/static/opinions/opnscvwp/1031407.pdf"),
    ("torts", "contributory_negligence", "When should a jury decide contributory negligence in a Virginia accident?",
     1058226, "279 Va. 370",
     "https://www.vacourts.gov/static/opinions/opnscvwp/1090193.pdf"),
    ("landlord_tenant", "landlord_repairs", "Can a Virginia landlord face a claim over negligent repairs and mold?",
     1058223, "279 Va. 475",
     "https://www.vacourts.gov/static/opinions/opnscvwp/1090143.pdf"),
)
REAL_ORIGINS = {"courtlistener_v4", "courtlistener_bulk"}


def benchmark(store, limit):
    scenarios = []
    for area, topic, question, cluster, citation, opinion_url in LABELS:
        plan = LegalResearchPlanner().plan(ResearchMatter(country="US", state="Virginia", legal_area=area, topics=[topic]))
        query = " ".join(plan.queries)
        target = store.case(cluster)
        available = bool(target and target.origin in REAL_ORIGINS and target.court.id == "va"
                         and citation in target.cluster.citations and any(op.text for op in target.opinions))
        started = time.perf_counter()
        rows = store.search(query, state=plan.state, sovereign=plan.sovereign, courts=plan.courts, limit=limit)
        elapsed = round(1000 * (time.perf_counter() - started), 3)
        cases = {}
        outside_scope = set()
        for row in rows:
            key = row["cluster"]
            if key not in cases:
                cases[key] = store.case(key)
            bundle = cases[key]
            if (not bundle or bundle.court.state != plan.state or bundle.court.sovereign != plan.sovereign
                    or bundle.court.id not in plan.courts):
                outside_scope.add(key)
        ranked = [key for key, bundle in cases.items() if key not in outside_scope and bundle.origin in REAL_ORIGINS]
        rank = ranked.index(cluster) + 1 if available and cluster in ranked else None
        scenarios.append({"topic": topic, "question": question, "query": query, "target_cluster": cluster,
                          "target_citation": citation, "official_opinion": opinion_url, "target_in_corpus": available,
                          "target_case_rank": rank, "real_origin_case_count": len(ranked),
                          "outside_scope_clusters": sorted(outside_scope), "local_search_ms": elapsed})
    covered = sum(case["target_in_corpus"] for case in scenarios)
    hits = sum(case["target_case_rank"] is not None for case in scenarios)
    return {"opinion_limit": limit, "requests": 0, "corpus": store.stats(), "targets_in_corpus": covered,
            "targets_retrieved": hits, "target_recall_given_coverage": hits / covered if covered else None,
            "scenarios": scenarios}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    if not args.database.is_file() or not 1 <= args.limit <= 50:
        parser.error("supply an existing corpus database and an opinion limit from 1 to 50")
    with SQLiteCorpusStore(args.database) as store:
        report = benchmark(store, args.limit)
    print(json.dumps(report, indent=2))
    return 0 if report["targets_in_corpus"] == report["targets_retrieved"] == len(LABELS) and not any(
        case["outside_scope_clusters"] for case in report["scenarios"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
