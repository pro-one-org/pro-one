"""Inspect jurisdiction coverage, replay pinned evidence, and benchmark offline lookups."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.coverage_audit import build, gaps, health, retained_observations, review_queue, source_distribution, state_baseline
from app.coverage_health import check
from app.jurisdictions import jurisdiction_id, registry
from app.national_coverage import action_shells, coverage, manifest, summary
from app.national_corpus import CorpusQuery
from app.national_corpus_store import SQLiteNormalizedCorpus


def benchmark():
    results = {}
    with TemporaryDirectory() as directory:
        path = Path(directory) / "corpus.sqlite3"
        start = perf_counter_ns()
        stats = build(path)
        elapsed = (perf_counter_ns() - start) / 1e9
        with SQLiteNormalizedCorpus(path, read_only=True) as db:
            queries = []
            for provider, selector, raw, _ in retained_observations():
                observation, = provider.normalize(selector, raw)
                v = observation.version
                queries.append(CorpusQuery(v.jurisdiction, v.authority_type, citation=v.citation,
                                           currentness=v.currentness, as_of=v.current_as_of))
            scopes = tuple(registry())
            def lookup(i):
                return db.search(queries[i % len(queries)])
            def current(i):
                q = queries[i % len(queries)]
                return db.search(CorpusQuery(q.jurisdiction, q.authority_type, citation=q.citation, currentness="current_as_of"))
            for name, operation in {
                "jurisdiction": lambda i: jurisdiction_id(scopes[i % len(scopes)]),
                "coverage": lambda i: coverage(scopes[i % len(scopes)]),
                "court_directory": lambda i: manifest(scopes[i % len(scopes)])["court_directory"],
                "procedure": lambda i: coverage(scopes[i % len(scopes)])["cells"]["procedure.service"],
                "action_routing": lambda i: action_shells(scopes[i % len(scopes)]),
                "authority": lookup, "currentness": current,
            }.items():
                samples = []
                for i in range(max(len(scopes), len(queries)) * 3):
                    start = perf_counter_ns()
                    result = operation(i)
                    samples.append((perf_counter_ns() - start) / 1e6)
                    if (name == "authority" and not result) or (name == "currentness" and result):
                        raise ValueError("national_benchmark_evidence_mismatch")
                samples.sort()
                results[name] = {"p50_ms": round(median(samples), 4),
                                 "p95_ms": round(samples[(95 * len(samples) - 1) // 100], 4), "queries": len(samples)}
        return {"records": stats, "jurisdictions": len(scopes), "ingest_seconds": round(elapsed, 4),
                "database_bytes": path.stat().st_size, "lookups": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for cmd in ("status", "validate", "distribution", "benchmark", "baseline"):
        commands.add_parser(cmd)
    commands.add_parser("jurisdiction").add_argument("scope")
    commands.add_parser("domain").add_argument("domain")
    commands.add_parser("build").add_argument("database", type=Path)
    refresh = commands.add_parser("check-publisher")
    refresh.add_argument("scope")
    refresh.add_argument("selector")
    refresh.add_argument("history", type=Path)
    for cmd in ("gaps", "stale", "source-health"):
        commands.add_parser(cmd).add_argument("--jurisdiction")
    args = parser.parse_args()
    if args.command == "status":
        result = summary()
    elif args.command == "distribution":
        result = source_distribution()
    elif args.command == "baseline":
        result = state_baseline()
    elif args.command == "build":
        result = build(args.database)
    elif args.command == "check-publisher":
        result = check(jurisdiction_id(args.scope), args.selector, args.history)
    elif args.command == "benchmark":
        result = benchmark()
    elif args.command == "validate":
        with TemporaryDirectory() as directory:
            result = {"coverage": summary(), "retained_corpus": build(Path(directory) / "verify.sqlite3")}
    elif args.command == "jurisdiction":
        scope = jurisdiction_id(args.scope)
        if not scope:
            parser.error("unknown jurisdiction")
        result = coverage(scope)
    elif args.command == "domain":
        result = {scope: {key: cell for key, cell in coverage(scope)["cells"].items()
                          if args.domain in (key, *key.split("."))} for scope in registry()}
        if not any(result.values()):
            parser.error("unknown coverage capability")
    else:
        scopes = list(registry())
        if args.jurisdiction:
            scope = jurisdiction_id(args.jurisdiction)
            if not scope:
                parser.error("unknown jurisdiction")
            scopes = [scope]
        fn = {"gaps": gaps, "stale": review_queue, "source-health": health}[args.command]
        items = [item for scope in scopes for item in fn(scope)]
        result = {"counts": dict(Counter(item.get("status", item.get("currentness")) for item in items)), "items": items}
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
