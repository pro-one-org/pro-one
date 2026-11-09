"""Bounded CourtListener ingestion and external-corpus inspection (never PACER purchase)."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.corpus_store import CORPUS_STORAGE_ERRORS, SQLiteCorpusStore
from app.corpus_ingestion import CourtListenerCorpusBuilder, CourtListenerBulkImporter
from app.courtlistener_client import CourtListenerClient, CourtListenerError, RequestBudget
from app.research_planning import LegalResearchPlanner
from app.capabilities import ResearchMatter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(".local/courtlistener.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats")
    backup = sub.add_parser("backup")
    backup.add_argument("destination", type=Path, help="New backup file in an existing directory")
    backup.add_argument("--max-seconds", type=int, default=30)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--state", required=True)
    search.add_argument("--limit", type=int, default=12)
    show = sub.add_parser("show")
    show.add_argument("cluster", type=int)
    graph = sub.add_parser("graph")
    graph.add_argument("opinion", type=int)
    graph.add_argument("--refresh", action="store_true", help="Read bounded existing citation edges; requires token")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--state", required=True)
    ingest.add_argument("--legal-area", default="torts")
    ingest.add_argument("--topic", default="premises_liability")
    ingest.add_argument("--mode", choices=["keyword", "semantic"], default="keyword")
    ingest.add_argument("--date-from")
    ingest.add_argument("--date-to")
    ingest.add_argument("--max-results", type=int, default=6)
    ingest.add_argument("--max-pages", type=int, default=2)
    ingest.add_argument("--max-requests", type=int, default=30)
    ingest.add_argument("--max-seconds", type=int, default=30)
    ingest.add_argument("--resume", action="store_true")
    refresh = sub.add_parser("refresh")
    refresh.add_argument("cluster", type=int)
    lookup = sub.add_parser("lookup")
    lookup.add_argument("citation", help="Base citation only; no pin cites")
    bulk = sub.add_parser("bulk")
    for table in sorted(CourtListenerBulkImporter.TABLES):
        bulk.add_argument("--" + table.replace("_", "-"), type=Path)
    bulk.add_argument("--max-rows", type=int, default=10000)
    bulk.add_argument("--max-clusters", type=int, default=1000)
    recap = sub.add_parser("read-recap")
    recap.add_argument("document", type=int)
    recap.add_argument("--entry", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "backup" and not args.database.is_file():
            raise ValueError("existing_corpus_required")
        if args.command in {"ingest", "refresh", "lookup", "read-recap"} and not os.environ.get("COURTLISTENER_API_TOKEN"):
            print(json.dumps({"status": "unavailable", "reason": "courtlistener_unconfigured", "requests": 0}))
            return 2
        with SQLiteCorpusStore(args.database) as store:
            client = CourtListenerClient(os.environ.get("COURTLISTENER_API_TOKEN"), store=store,
                budget=RequestBudget(max_pages=getattr(args, "max_pages", 2), max_requests=getattr(args, "max_requests", 30),
                                     max_seconds=getattr(args, "max_seconds", 30), max_documents=100))
            if args.command == "stats":
                result = store.stats()
            elif args.command == "backup":
                result = store.backup(args.destination, max_seconds=args.max_seconds)
            elif args.command == "search":
                result = store.search(args.query, state=args.state, sovereign="state", limit=args.limit)
            elif args.command == "show":
                case = store.case(args.cluster)
                result = case.model_dump() if case else {"status": "not_found"}
            elif args.command == "graph":
                if args.refresh:
                    store.add_edges(list(client.citation_edges(args.opinion)))
                    if client.budget.pages < client.budget.max_pages:
                        store.add_edges(list(client.citation_edges(args.opinion, incoming=True)))
                result = store.graph(args.opinion)
            elif args.command == "lookup":
                result = client.lookup(args.citation)
                store.save_verification(result)
            elif args.command == "refresh":
                result = store.ingest(client.hydrate(args.cluster, refresh=True))
            elif args.command == "read-recap":
                from app.recap import RecapArchiveProvider, render_archive_document
                result = render_archive_document(RecapArchiveProvider(client, store).read_document(args.document, args.entry))
            elif args.command == "bulk":
                importer = CourtListenerBulkImporter(store)
                staged = [importer.load(table, getattr(args, table), max_rows=args.max_rows)
                          for table in sorted(importer.TABLES) if getattr(args, table)]
                result = {"loads": staged, "result": importer.materialize(args.max_clusters)}
            else:
                plan = LegalResearchPlanner().plan(ResearchMatter(country="US", state=args.state, legal_area=args.legal_area, topics=[args.topic]))
                result = CourtListenerCorpusBuilder(client, store).ingest(plan.queries[0], plan.courts, jurisdiction=args.state,
                    mode=args.mode, date_from=args.date_from, date_to=args.date_to, max_results=args.max_results, resume=args.resume)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except CourtListenerError as error:
        print(json.dumps({"status": "unavailable", "reason": error.code, "retry_after_seconds": error.retry_after}))
        return 2
    except (ValueError, *CORPUS_STORAGE_ERRORS):
        print(json.dumps({"status": "unavailable", "reason": "invalid_corpus_input_or_storage"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
