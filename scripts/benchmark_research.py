"""Offline research benchmark. Synthetic scale and fixture calls are not live quality evidence."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.capabilities import ResearchMatter
from app.corpus_store import SQLiteCorpusStore
from app.courtlistener_authority import LocalCorpusAuthorityProvider
from app.legal_research import GeneralLegalResearchService
from app.repository import RecordRepository
from app.research_demo import demo_bundles, run_research_demo
from app.research_planning import LegalResearchPlanner


CASES = [
    ("wet floor", "Virginia", "premises_liability", True),
    ("actual constructive notice", "Virginia", "notice", True),
    ("owner-created condition", "Virginia", "negligence", True),
    ("open obvious", "Virginia", "contributory_negligence", True),
    ("cleaning and causation", "Virginia", "premises_liability", True),
    ("same topic wrong state", "Maryland", "premises_liability", False),
    ("unconfigured jurisdiction", "California", "premises_liability", False),
    ("unconfigured issue", "Virginia", "tax", False),
    ("missing jurisdiction", None, "premises_liability", False),
    ("unconfigured family issue", "Virginia", "custody", False),
    ("ordinary care", "Virginia", "negligence", True),
    ("conflicting notice inferences", "Virginia", "notice", True),
]


def benchmark(scale=1000):
    repository = RecordRepository()
    started = time.perf_counter()
    result = {"mode": "offline_reconstructed_fixtures", "authenticated_downloads": 0, "live_model_calls": 0,
              "scale_kind": "synthetic_duplicates_for_storage_search_only", "queries": []}
    result["external_stages"] = {"search_ms": None, "hydration_ms": None, "citation_verification_ms": None,
                                  "status": "not_measured_without_authorized_credentials"}
    with SQLiteCorpusStore() as store:
        for bundle in demo_bundles(repository):
            store.ingest(bundle)
            store.save_verification({"citation": bundle.cluster.citations[0], "cluster": bundle.cluster.id, "name": bundle.cluster.name, "origin": "fixture"})
        for label, state, topic, expected in CASES:
            matter = ResearchMatter(country="US", state=state, legal_area="torts", topics=[topic])
            plan_start = time.perf_counter()
            try:
                plan = LegalResearchPlanner().plan(matter)
                courts = plan.courts
            except ValueError:
                courts = ()
            planning_ms = 1000 * (time.perf_counter() - plan_start)
            provider = LocalCorpusAuthorityProvider(store)
            retrieval_start = time.perf_counter()
            prepared = GeneralLegalResearchService(repository, providers=[provider]).assemble(matter, force_general=True)
            package = prepared["package"]
            sources = package["grounding"]["sources"] if package else []
            passed = bool(sources) == expected and all(s["jurisdiction"]["state"] == state for s in sources)
            result["queries"].append({"scenario": label, "status": prepared["status"], "expected_evidence": expected,
                "passed": passed, "courts": courts, "sources": len(sources), "jurisdiction_contamination": 0 if passed else None,
                "planning_ms": round(planning_ms, 3), "assembly_ms": round(1000 * (time.perf_counter() - retrieval_start), 3),
                **provider.metrics})
        result["fixture_corpus"] = store.stats()
        result["fixture_corpus"].pop("last_sync", None)
    demo_start = time.perf_counter()
    demo = run_research_demo(repository)
    result["synthesis"] = {"status": demo["synthesis"]["status"], "metrics": demo["synthesis"]["metrics"],
        "fixture_stage_calls": demo["fixture_calls"], "claims": len(demo["synthesis"]["ledger"]),
        "final_validation": demo["validation"], **demo["timings"], "end_to_end_ms": round(1000 * (time.perf_counter() - demo_start), 3),
        "semantic_accuracy": "not_measured_without_live_models_and_reviewed_labels"}
    with SQLiteCorpusStore() as store:
        seed = next(demo_bundles(repository))
        load_start = time.perf_counter()
        for index in range(scale):
            bundle = deepcopy(seed)
            docket, cluster, opinion = 8000000 + index, 9000000 + index, 7000000 + index
            bundle.docket.id, bundle.cluster.id, bundle.cluster.docket, bundle.cluster.opinions = docket, cluster, docket, [opinion]
            bundle.opinions[0].id, bundle.opinions[0].cluster = opinion, cluster
            store.ingest(bundle)
        load_ms = 1000 * (time.perf_counter() - load_start)
        search_start = time.perf_counter()
        hits = store.search("actual constructive notice dangerous condition", state="Virginia", courts=["va"], limit=12)
        search_ms = 1000 * (time.perf_counter() - search_start)
        result["synthetic_scale"] = {"clusters": store.stats()["clusters"], "opinions": store.stats()["opinions"],
            "bytes": store.stats()["bytes"], "ingest_ms": round(load_ms, 2), "search_ms": round(search_ms, 2), "returned": len(hits)}
    result["passed"] = all(row["passed"] for row in result["queries"]) and demo["validation"]["valid"]
    result["elapsed_ms"] = round(1000 * (time.perf_counter() - started), 2)
    result["limitations"] = ["Two excerpt-only reconstructed cases, not a representative national corpus.",
        "No authenticated search, hydration or usage latency measured; v4 wire contracts are exercised by offline transport tests.",
        "Retrieval scenario success does not measure legal relevance or semantic entailment accuracy."]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.scale <= 10000:
        parser.error("scale must be 1..10000")
    result = benchmark(args.scale)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
