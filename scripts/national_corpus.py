"""Build and inspect proposed legal authority in ignored operator storage."""

import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
from time import monotonic
from typing import get_args
from uuid import uuid4

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.corpus_store import utcnow
from app.national_corpus import AuthorityType, CorpusError, CorpusQuery, OpinionRole
from app.national_corpus_providers import PROVIDERS
from app.national_corpus_store import SQLiteNormalizedCorpus


def build(store, provider, selector, directory):
    start = monotonic()
    build_id = uuid4().hex
    source = provider.source
    report = {
        "build_id": build_id, "started_at": utcnow(), "provider": source.name,
        "parser_revision": source.parser_revision,
        "jurisdictions": source.jurisdictions, "authority_types": [source.authority_type],
        "request_budget": source.max_requests, "status": "failed",
    }
    try:
        provider.source_url(selector)
        report["selector"] = selector
        fetched = provider.fetch(selector)
        report["requests_attempted"] = fetched.requests
        report["artifact_bytes"] = len(fetched.raw)
        result = store.ingest(provider, selector, fetched.raw)
        report.update(result, status="committed", totals=store.stats())
    except CorpusError as exc:
        report["error"] = str(exc)
    except ValidationError:
        report["error"] = "source_record_validation_failed"
    except sqlite3.Error:
        report["error"] = "corpus_storage_failure"
    report["runtime_seconds"] = round(monotonic() - start, 3)
    report["database_bytes"] = (directory / "corpus.sqlite3").stat().st_size
    with (directory / f"{build_id}.json").open("x", encoding="utf-8") as manifest:
        json.dump(report, manifest, indent=2)
        manifest.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sources")
    commands.add_parser("stats")
    replay = commands.add_parser("replay", help="Replay a stored source snapshot without network access")
    replay.add_argument("snapshot")
    compare = commands.add_parser("identity")
    compare.add_argument("left_version")
    compare.add_argument("right_version")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("provider", choices=PROVIDERS)
    ingest.add_argument("selector")
    search = commands.add_parser("search")
    search.add_argument("jurisdiction")
    search.add_argument("authority_type", choices=get_args(AuthorityType))
    search.add_argument("--citation", default="")
    search.add_argument("--text", default="")
    search.add_argument("--edition", default="")
    search.add_argument("--provider", choices=PROVIDERS, default="")
    search.add_argument("--opinion-role", action="append", choices=get_args(OpinionRole), default=[])
    search.add_argument("--currentness", choices=("unresolved", "current", "historical", "repealed", "superseded", "proposed"),
                        default="unresolved")
    search.add_argument("--as-of", type=date.fromisoformat)
    search.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    if args.command == "sources":
        print(json.dumps([asdict(adapter.source) for adapter in PROVIDERS.values()], indent=2))
        return 0

    directory = Path(__file__).resolve().parents[1] / ".local" / "national-corpus"
    directory.mkdir(parents=True, exist_ok=True)
    with SQLiteNormalizedCorpus(directory / "corpus.sqlite3") as store:
        if args.command == "ingest":
            report = build(store, PROVIDERS[args.provider], args.selector, directory)
            print(json.dumps(report, indent=2))
            return int(report["status"] != "committed")
        if args.command == "stats":
            print(json.dumps(store.stats(), indent=2))
        elif args.command == "replay":
            provider, selector, raw = store.replay_artifact(args.snapshot)
            adapter = PROVIDERS.get(provider)
            if adapter is None:
                raise CorpusError("snapshot_provider_unavailable")
            print(json.dumps(store.ingest(adapter, selector, raw), indent=2))
        elif args.command == "identity":
            print(json.dumps(store.check_identity(args.left_version, args.right_version), indent=2))
        else:
            query = CorpusQuery(args.jurisdiction, args.authority_type, citation=args.citation, text=args.text,
                                edition=args.edition, provider=args.provider, currentness=args.currentness,
                                as_of=args.as_of, opinion_roles=tuple(args.opinion_role), limit=args.limit)
            matches = store.search(query)
            for match in matches:
                match["provenance"] = store.provenance(match["version_id"])
                match["relationships"] = store.relationships(match["version_id"])
            print(json.dumps(matches, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CorpusError, OSError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, CorpusError) else "corpus_io_failure"
        sys.exit(message)
