"""Cross-provider development measurements with non-authoritative manual review."""

import hashlib
import json
from copy import deepcopy
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation import EvaluationService
from app.generation import GenerationService
from app.models.base import GenerationConfig


DIMENSIONS = ("groundedness", "citation_fidelity", "factual_integrity", "legal_support", "support_gap_preservation",
              "user_fact_preservation", "clarity", "usefulness", "user_control", "warning_presence")


class ManualReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fixture_id: str
    workflow_id: str
    provider: str
    model: str
    draft_hash: str
    scores: dict[str, int]  # 0 concern, 1 mixed, 2 satisfactory; never legal approval.
    notes: str = Field(default="", max_length=2000)


def apply_manual_review(report: dict, review: ManualReview) -> dict:
    """Score an existing exact result without regenerating nondeterministic text."""
    report = deepcopy(report)
    if (report.get("fixture_id") != review.fixture_id or report.get("workflow_id") != review.workflow_id
            or set(review.scores) != set(DIMENSIONS) or any(type(v) is not int or v not in {0, 1, 2} for v in review.scores.values())):
        raise ValueError("manual_review_identity_or_dimensions_invalid")
    row = next((r for r in report["results"] if r["provider"] == review.provider and r["model"] == review.model), None)
    if (not row or row.get("status") != "accepted" or not row.get("deterministic_validation", {}).get("valid")
            or row.get("draft_hash") != review.draft_hash):
        raise ValueError("manual_review_not_bound_to_valid_draft")
    if "development_draft" in row and hashlib.sha256(json.dumps(row["development_draft"], sort_keys=True).encode()).hexdigest() != review.draft_hash:
        raise ValueError("manual_review_draft_hash_invalid")
    row["semantic_review"].update(status="manual_measurement_recorded", dimensions=review.scores, notes=review.notes, release_approval=False)
    report["public_approval"] = False
    return report


def benchmark(repository, registry, fixture_id: str, workflow_id: str, review: ManualReview | None = None, include_drafts=False):
    fixture, mapping, request, package = EvaluationService(repository).prepare_fixture(fixture_id)
    if mapping.workflow_id != workflow_id:
        raise ValueError("fixture_workflow_mismatch")
    results = []
    configured = registry.configured_models()
    for provider in sorted(set(configured) | {"openai", "anthropic"}):
        models = configured.get(provider, [])
        if not models:
            results.append({"provider": provider, "model": None, "status": "unavailable", "semantic_review": "not_run"})
        for model in models:
            started = perf_counter()
            result = GenerationService(registry).generate(package, GenerationConfig(provider=provider, model=model))
            valid = result["validation"]["valid"]
            draft_hash = hashlib.sha256(json.dumps(result["draft"], sort_keys=True).encode()).hexdigest() if valid else None
            semantic = {"authority": "non_authoritative_manual_measurement", "status": "pending_manual_review" if valid else "blocked_by_deterministic_failure",
                        "dimensions": {d: None for d in DIMENSIONS}, "release_approval": False}
            row = {"provider": provider, "model": model, "status": result["generation"]["status"],
                   "deterministic_validation": result["validation"], "latency_ms": round((perf_counter() - started) * 1000, 2),
                   "usage": result["generation"]["usage"], "draft_hash": draft_hash, "semantic_review": semantic}
            if include_drafts:
                row["development_draft"] = result["draft"]
            results.append(row)
    report = {"workflow_id": workflow_id, "fixture_id": fixture_id, "results": results, "public_approval": False}
    return apply_manual_review(report, review) if review else report
