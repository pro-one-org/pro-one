"""Run small, separately budgeted CourtListener v4 acceptance probes."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.citation_research import CitationResearchRequest, resolve_citation
from app.corpus_store import SQLiteCorpusStore
from app.courtlistener_client import CourtListenerClient, CourtListenerError, RequestBudget


CLUSTER = 1058333
CITATION = "278 Va. 84"
COURTS = ("va", "vactapp")


def discovery(client):
    with closing(client.search_pages("constructive notice", COURTS)) as pages:
        first, cursor = next(pages, ([], None))
        if not first or not cursor:
            raise CourtListenerError("keyword_pagination_not_demonstrated")
        second, _ = next(pages, ([], None))
    if not {hit["cluster"] for hit in second} - {hit["cluster"] for hit in first}:
        raise CourtListenerError("keyword_continuation_no_new_clusters")
    with closing(client.search_pages("When does a store have constructive notice of a dangerous condition?",
                                     COURTS, mode="semantic")) as pages:
        semantic, _ = next(pages, ([], None))
    if not semantic:
        raise CourtListenerError("semantic_no_scoped_results")
    return {"keyword_page_hits": [len(first), len(second)], "semantic_hits": len(semantic)}


def hydration(client, store, refresh):
    if refresh and store.case(CLUSTER) is None:
        raise CourtListenerError("hydrate_before_refresh")
    bundle = client.hydrate(CLUSTER, refresh=refresh)
    if bundle.court.id != "va" or CITATION not in bundle.cluster.citations or not any(o.text for o in bundle.opinions):
        raise CourtListenerError("expected_virginia_case_not_hydrated")
    result = store.ingest(bundle)
    stored = store.case(CLUSTER)
    stored.validate_relationships()
    if stored.model_copy(update={"opinions": sorted(stored.opinions, key=lambda o: o.id)}) != bundle.model_copy(
            update={"opinions": sorted(bundle.opinions, key=lambda o: o.id)}):
        raise CourtListenerError("corpus_round_trip_mismatch")
    repeated = store.ingest(bundle)
    if repeated["new"] or repeated["changed"]:
        raise CourtListenerError("corpus_idempotency_failed")
    if not any(hit["cluster"] == CLUSTER for hit in store.search("notice", state="Virginia", courts=("va",))):
        raise CourtListenerError("corpus_case_not_retrieved")
    return {"cluster": CLUSTER, "origin": bundle.origin, "ingestion": result,
            "opinions": [{"id": op.id, "role": op.role, "format": op.text_format,
                          "characters": len(op.text), "sha256": op.content_hash} for op in stored.opinions]}


def relationships(client, store):
    bundle = store.case(CLUSTER)
    if not bundle or bundle.origin != "courtlistener_v4":
        raise CourtListenerError("live_hydration_required")
    value = client.lookup(CITATION)
    if value["cluster"] != CLUSTER:
        raise CourtListenerError("unexpected_citation_cluster")
    store.save_verification(value)
    identity = resolve_citation(CitationResearchRequest(citation=CITATION, state="Virginia"), store)
    if identity["status"] != "identity_verified":
        raise CourtListenerError("stored_citation_identity_not_verified")
    opinion = next((op for op in bundle.opinions if op.cited), bundle.opinions[0])
    with closing(client.citation_edges(opinion.id)) as edges:
        edge = next(edges, None)
    if not edge or edge["citing"] != opinion.id:
        raise CourtListenerError("outgoing_citation_edge_not_demonstrated")
    store.add_edges([edge])
    if edge["cited"] not in store.graph(opinion.id)["cited"]:
        raise CourtListenerError("citation_edge_not_stored")
    try:
        client.resource("courts", "prooneacceptancemissing", refresh=True)
    except CourtListenerError as error:
        if error.code != "not_found":
            raise
    else:
        raise CourtListenerError("expected_not_found")
    return {"citation": CITATION, "cluster": CLUSTER, "sample_outgoing_edge": edge, "safe_error": "not_found"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("discover", "hydrate", "refresh", "relationships"))
    parser.add_argument("--database", type=Path, default=Path(".local/courtlistener-acceptance.sqlite3"))
    args = parser.parse_args(argv)
    token = os.environ.get("COURTLISTENER_API_TOKEN")
    report = {"phase": args.phase, "status": "unavailable"}
    if not token:
        print(json.dumps({**report, "reason": "courtlistener_unconfigured", "requests": 0}))
        return 2
    budget = RequestBudget(max_requests=7, max_pages=3, max_documents=5, max_seconds=60)
    try:
        with SQLiteCorpusStore(args.database) as store:
            client = CourtListenerClient(token, budget=budget, store=store)
            report["usage_before"] = usage = client.usage()
            limits = usage["limits"]
            remaining = min(row["remaining"] for row in limits if row["scope"] == "user")
            citation_blocked = any(row["blocked"] or not row["remaining"]
                                   for row in limits if row["scope"] == "citations")
            if not usage["available"] or (args.phase == "relationships" and citation_blocked):
                raise CourtListenerError("insufficient_reported_quota")
            budget.max_requests = budget.requests + min(5, remaining)
            if args.phase == "discover":
                result = discovery(client)
            elif args.phase == "relationships":
                result = relationships(client, store)
            else:
                result = hydration(client, store, refresh=args.phase == "refresh")
            report["checks"] = result
            budget.max_requests += 1  # A separate API usage scope funds the final snapshot.
            report["usage_after"] = client.usage()
            report["status"] = "passed"
    except CourtListenerError as error:
        report.update(reason=error.code, retry_after_seconds=error.retry_after)
    except (OSError, ValueError, sqlite3.Error):
        report.update(reason="invalid_acceptance_input_or_storage")
    report["metrics"] = budget.metrics()
    if "usage_before" in report:
        report["timings"] = client.timings
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
