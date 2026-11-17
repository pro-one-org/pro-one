"""Validate the action catalog or benchmark its deterministic local operations."""
import argparse
from datetime import date
import json
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.action_catalog import ActionCatalog
from app.action_documents import assemble
from app.action_models import EvaluateAction
from app.action_readiness import evaluate_readiness
from app.action_service import ActionService
from app.action_workspace import tasks_for
from app.claim_catalog import ClaimCatalog
from app.claim_models import AnalyzeClaim
from app.deadline_counting import CountingMethod, count_days
from app.matter_service import MatterService
from app.matter_state import projection
from app.matter_store import MatterStore
from app.procedural_authority import load_catalog
from app.repository import RecordRepository


def benchmark(repository, catalog, iterations):
    samples = {}

    def measure(label, callback, *args):
        start = perf_counter_ns()
        value = callback(*args)
        samples.setdefault(label, []).append((perf_counter_ns() - start) / 1_000_000)
        return value

    on = date(2026, 11, 16)
    action = catalog.actions["va_richmond_complaint"]
    rule = catalog.deadlines[action.deadline_rules[0]]
    with TemporaryDirectory() as folder:
        ledger = MatterService(MatterStore(Path(folder) / "synthetic.sqlite3"))
        system = ActionService(ledger.store, repository, catalog=catalog)
        for _ in range(iterations):
            matter, _ = ledger.create("Virginia. I slipped in a Wendy's bathroom and broke my wrist. I want them to pay.")
            matter, _ = ledger.statement(matter, "Date: 2026-11-16\nHazard: water near the sink")
            fields = projection(matter)
            claim = system.claims.analyze(matter, AnalyzeClaim(revision=matter.revision))
            claim = system.claim_store.save(matter, claim)
            request = EvaluateAction(revision=matter.revision, action_id=action.id,
                                     claim_analysis_id=claim["analysis_id"], party_id=matter.parties[0].id)
            deadline = measure("deadline_derivation", system.derive_deadline, matter, rule, None, fields)
            dates = measure("calendar_counting", count_days, CountingMethod(21, "calendar_days", False, "next_open"),
                            on, {date(2026, 12, 7): False, date(2026, 12, 8): True})
            if not dates or dates.due != date(2026, 12, 8):
                raise RuntimeError("deadline_counting_fixture_invariant")
            readiness = measure("readiness_evaluation", evaluate_readiness, catalog, matter, action, request,
                                claim, {rule.id: deadline}, fields)
            report = system.store.prepare(matter, "readiness", system.dependencies, readiness)
            package = measure("document_assembly", assemble, catalog, matter, report, [deadline])
            artifact = system.store.prepare(matter, "document", system.dependencies, package)
            measure("artifact_persistence", system.store.save, matter, deadline, report, artifact)
            measure("staleness_check", system.artifact, matter.id, "document", artifact["artifact_id"])
            measure("task_generation", tasks_for, matter, [report], [artifact], [deadline], [], [action], on)
            workspace = measure("workspace_projection", system.workspace, matter.id, on)
            if not workspace["blockers"] or package["status"] != "incomplete":
                raise RuntimeError("benchmark_fixture_invariant")
    return {
        "iterations": iterations,
        "scope": "Synthetic local SQLite and retained authority. Deadline timing covers a substantiated trigger with unresolved applicability.",
        "model_latency": "No model calls. HTTP and external network latency are excluded.",
        "operations_ms": {
            label: {"p50": round(median(values), 3), "p95": round(sorted(values)[(95 * len(values) + 99) // 100 - 1], 3)}
            for label, values in samples.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    bench = commands.add_parser("benchmark")
    bench.add_argument("--iterations", type=int, default=30, choices=range(1, 201), metavar="1..200")
    args = parser.parse_args()
    repository = RecordRepository()
    claims = ClaimCatalog(repository)
    catalog = ActionCatalog(load_catalog(), claims)
    if args.command == "validate":
        claims.validate()
        result = {"actions": len(catalog.actions), "requirements": sum(len(row.requirements) for row in catalog.actions.values()),
                  "templates": len(catalog.templates), "deadline_policies": len(catalog.deadlines)}
    else:
        result = benchmark(repository, catalog, args.iterations)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
