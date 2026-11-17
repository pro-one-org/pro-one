"""Validate or benchmark the claim catalog on synthetic, offline matters."""
import argparse
import json
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.claim_catalog import ClaimCatalog
from app.claim_mapping import validate_mappings
from app.claim_models import AnalyzeClaim
from app.claim_service import ClaimService
from app.claim_store import ClaimStore
from app.matter_service import MatterService
from app.matter_store import MatterStore
from app.repository import RecordRepository


def benchmark(repository, iterations):
    engine = ClaimService(repository)
    samples = {}

    def time(label, callback, *args):
        start = perf_counter_ns()
        value = callback(*args)
        samples.setdefault(label, []).append((perf_counter_ns() - start) / 1_000_000)
        return value

    with TemporaryDirectory() as directory:
        ledger = MatterService(MatterStore(Path(directory) / "synthetic.sqlite3"))
        claims = ClaimStore(ledger.store)
        for _ in range(iterations):
            initial, _ = ledger.create("I slipped in a Wendy's bathroom and broke my wrist. I want them to pay.")
            initial, _ = ledger.statement(initial, "Virginia. There was water near the sink.")
            matter = time("load_matter_revision", ledger.store.get, initial.id, initial.revision)
            request = AnalyzeClaim(revision=matter.revision)
            time("discover_and_bind_theories", engine.discover, matter, request)
            analysis = time("build_snapshot_mappings_questions", engine.analyze, matter, request)
            rows = tuple(evidence["mapping"] for theory in analysis["theories"]
                         for element in theory["elements"] for evidence in element["evidence"])
            time("validate_mapping_tuples", validate_mappings, rows, rows)
            saved = time("persist_snapshot", claims.save, matter, analysis)
            updated, _ = ledger.statement(matter, "The manager told me they knew the sink had been leaking since that morning.")
            read = time("read_history_and_check_staleness", claims.get, matter.id, saved["analysis_id"], engine)
            if read["freshness"] != "stale":
                raise RuntimeError("expected_stale_analysis")
            time("reanalyze_after_revision", engine.analyze, updated, AnalyzeClaim(revision=updated.revision))
    return {
        "iterations": iterations,
        "scope": "Synthetic local SQLite and retained authority. Model calls, HTTP and network are excluded.",
        "operations_ms": {label: {"p50": round(median(values), 3),
                                  "p95": round(sorted(values)[(95 * len(values) + 99) // 100 - 1], 3)}
                          for label, values in samples.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    bench = commands.add_parser("benchmark")
    bench.add_argument("--iterations", type=int, default=30, choices=range(1, 201), metavar="1..200")
    args = parser.parse_args()
    repository = RecordRepository()
    if args.command == "validate":
        catalog = ClaimCatalog(repository)
        catalog.validate()
        result = {"versions": len(catalog.versions), "elements": sum(len(row.elements) for row in catalog.versions)}
    else:
        result = benchmark(repository, args.iterations)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
