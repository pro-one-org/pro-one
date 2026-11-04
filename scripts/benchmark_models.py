"""Explicit fixture benchmarking. Configured real providers may incur API charges."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmark import ManualReview, benchmark, apply_manual_review
from app.config import Settings
from app.repository import RecordRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--review-file", type=Path, help="Optional manual scores bound to an exact draft hash")
    parser.add_argument("--include-drafts", action="store_true", help="Print fixture development drafts for manual review; no prompts or credentials")
    parser.add_argument("--report-file", type=Path, help="Apply manual scores to a saved report without making new model calls")
    args = parser.parse_args()
    settings = Settings.from_environment()
    # Offline fixture benchmarking is explicitly a development tool, including
    # when the HTTP service's environment is production.
    registry = Settings("development", settings.provider, settings.model, settings.openai_model, settings.anthropic_model).registry()
    try:
        review = ManualReview.model_validate(json.loads(args.review_file.read_text(encoding="utf-8"))) if args.review_file else None
        if args.report_file:
            if review is None:
                raise ValueError("manual_review_required")
            original = json.loads(args.report_file.read_text(encoding="utf-8"))
            if original.get("workflow_id") != args.workflow or original.get("fixture_id") != args.fixture:
                raise ValueError("report_identity_mismatch")
            report = apply_manual_review(original, review)
        else:
            report = benchmark(RecordRepository(), registry, args.fixture, args.workflow, review, args.include_drafts)
    except Exception:
        print(json.dumps({"error": "benchmark_input_or_review_unavailable"}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if any(r.get("deterministic_validation", {}).get("valid") for r in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
