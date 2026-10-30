"""Run offline mapped fixture checks; failure gives a nonzero exit status."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation import EvaluationService
from app.repository import RecordRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the full deterministic report")
    parser.add_argument("--fixture", help="Run one existing explicitly mapped fixture")
    args = parser.parse_args()
    service = EvaluationService(RecordRepository())
    if args.fixture:
        result = service.run_fixture(args.fixture)
        report = {"passed": result["passed"], "executed": int(result["status"] == "executed"), "results": [result], "unmapped_fixture_ids": []}
    else:
        report = service.run_all()
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
