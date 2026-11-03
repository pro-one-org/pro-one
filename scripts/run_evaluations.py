"""Run offline mapped fixture checks; failure gives a nonzero exit status."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation import EvaluationService
from app.repository import RecordRepository
from app.research_evaluation import ResearchEvaluationService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the full deterministic report")
    parser.add_argument("--fixture", help="Run one existing explicitly mapped fixture")
    parser.add_argument("--workflow", help="Run mapped fixtures for one real workflow")
    parser.add_argument("--capability", help="Run registered fixtures for one capability")
    parser.add_argument("--mode", choices=["workflow", "capability", "general_research"])
    args = parser.parse_args()
    if args.workflow and (args.capability or args.mode in {"capability", "general_research"}):
        parser.error("workflow and research filters are mutually exclusive")
    repository = RecordRepository()
    service = EvaluationService(repository)
    research = ResearchEvaluationService(repository)
    if args.fixture:
        result = research.run_fixture(args.fixture) if args.fixture in repository.records["research_evaluations"] else service.run_fixture(args.fixture)
        if args.workflow and result.get("workflow_id") != args.workflow:
            result.update(passed=False, status="workflow_mismatch")
        fixture = repository.get("research_evaluations", args.fixture)
        if args.capability and (not fixture or args.capability not in fixture["capability_ids"]):
            result.update(passed=False, status="capability_mismatch")
        if args.mode and result.get("mode", "workflow") != args.mode:
            result.update(passed=False, status="mode_mismatch")
        report = {"passed": result["passed"], "executed": int(result["status"] == "executed"), "results": [result], "unmapped_fixture_ids": []}
    else:
        if args.capability or args.mode in {"capability", "general_research"}:
            report = research.run_all(args.capability, args.mode)
        else:
            report = service.run_all(args.workflow)
            if not args.workflow and args.mode is None:
                second = research.run_all()
                report = {**report, "passed": report["passed"] and second["passed"],
                          "executed": report["executed"] + second["executed"], "results": report["results"] + second["results"],
                          "unmapped_fixture_ids": report["unmapped_fixture_ids"] + second["unmapped_fixture_ids"],
                          "required_unmapped_fixture_ids": report.get("required_unmapped_fixture_ids", []) + second["required_unmapped_fixture_ids"]}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for result in report["results"]:
            failed = [c["name"] for c in result["checks"] if not c["passed"]]
            print(f"{'PASS' if result['passed'] else 'FAIL'} {result['fixture_id']}" + (": " + ", ".join(failed) if failed else ""))
        for fixture_id in report.get("required_unmapped_fixture_ids", []):
            print(f"FAIL {fixture_id}: required execution mapping missing")
        print(f"Executed {report['executed']} mapped fixtures; unmapped: {len(report['unmapped_fixture_ids'])}. Manual review remains pending; no release approval.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
