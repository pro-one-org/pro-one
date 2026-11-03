"""Version-bound offline capability/general-research evaluations; no legal approval."""

from app.capabilities import ResearchMatter
from app.generation import GenerationService
from app.generation_contract import build_model_request
from app.legal_research import GeneralLegalResearchService
from app.models.base import GenerationConfig
from app.models.testing import TEST_MODEL, testing_registry, valid_draft
from app.output_validation import OutputValidationService


REGISTERED_RESEARCH_FIXTURES = {
    "va-premises-" + check + "-evaluation": ("0.1.0", check)
    for check in ("grounded_answer", "missing_state", "wrong_state", "invented_case", "invented_statute", "unsupported_proposition",
                  "currentness", "conflict", "no_workflow", "injection", "outcome", "deadline", "damages")
}


class ResearchEvaluationService:
    def __init__(self, repository):
        self.repository = repository

    def run_fixture(self, fixture_id):
        fixture = self.repository.get("research_evaluations", fixture_id)
        mapping = REGISTERED_RESEARCH_FIXTURES.get(fixture_id)
        result = {"fixture_id": fixture_id, "passed": False, "checks": [], "release_passed": False,
                  "manual_review_required": True, "manual_checks_pending": ["Legal relevance, completeness, exceptions, currentness and plain-language quality"],
                  "status": "not_executable", "mode": fixture["mode"] if fixture else None}
        if not fixture or not mapping or (fixture["record_version"], fixture["check"]) != mapping:
            return result
        check_name = mapping[1]
        matter = ResearchMatter.model_validate(fixture["matter"])
        prepared = GeneralLegalResearchService(self.repository).assemble(matter, force_general=fixture["mode"] == "general_research")
        expected = "missing_context" if check_name == "missing_state" else "no_authoritative_support" if check_name == "wrong_state" else "evidence_ready"
        result["checks"].append({"name": "expected_research_status", "passed": prepared["status"] == expected})
        package = prepared["package"]
        if package:
            config = GenerationConfig(provider="testing", model=TEST_MODEL)
            request = build_model_request(package, config)
            generated = GenerationService(testing_registry()).generate(package, config)
            result["checks"].extend([
                {"name": "baseline_grounded_answer", "passed": generated["generation"]["status"] == "accepted"},
                {"name": "no_workflow_required", "passed": request.grounded_package["workflow_id"] is None},
                {"name": "release_blocked", "passed": not generated["public_execution"]["allowed"]},
                {"name": "jurisdiction_fidelity", "passed": all(p["jurisdiction"]["state"] == matter.state for p in request.grounded_package["evidence_passages"])},
            ])
            draft = valid_draft(request)
            target = next(s for s in draft["sections"] if s["kind"] == "legal_information")
            attacks = {"invented_case": "Smith v. Jones, 999 Va. 123 establishes automatic liability.",
                       "invented_statute": "Va. Code section 99-999 guarantees damages.",
                       "unsupported_proposition": "A restaurant is automatically liable for every fall.",
                       "currentness": "All authorities are certified current and legally approved.",
                       "outcome": "You will win this claim.", "deadline": "Your filing deadline is tomorrow.",
                       "damages": "You will recover one million dollars."}
            if check_name in attacks:
                target["text"] = attacks[check_name]
                _, validation = OutputValidationService().validate(draft, request)
                result["checks"].append({"name": "unsupported_legal_text_rejected", "passed": not validation["valid"] and any(e["code"] == "unsupported_proposition" for e in validation["errors"])})
            if check_name == "conflict":
                draft["limitations_included"] = []
                _, validation = OutputValidationService().validate(draft, request)
                result["checks"].append({"name": "conflict_cannot_be_omitted", "passed": not validation["valid"] and any("dissent" in s.lower() for s in request.grounded_package["limitations"])})
            if check_name == "injection":
                changed = matter.model_copy(update={"goal": fixture["scenario"]})
                again = GeneralLegalResearchService(self.repository).assemble(changed, force_general=True)
                result["checks"].append({"name": "untrusted_goal_cannot_change_evidence", "passed": package == again["package"]})
        result["status"] = "executed"
        result["passed"] = all(c["passed"] for c in result["checks"])
        return result

    def run_all(self, capability=None, mode=None):
        fixtures = [f for f in self.repository.records["research_evaluations"].values()
                    if (capability is None or capability in f["capability_ids"]) and (mode is None or f["mode"] == mode)]
        results = [self.run_fixture(f["id"]) for f in fixtures]
        required = {fid for c in self.repository.records["legal_capabilities"].values() if capability is None or c["id"] == capability
                    for fid in c["research_evaluation_ids"]}
        unmapped = sorted(required - set(REGISTERED_RESEARCH_FIXTURES))
        return {"passed": bool(results) and all(r["passed"] for r in results) and not unmapped,
                "executed": sum(r["status"] == "executed" for r in results), "results": results,
                "unmapped_fixture_ids": unmapped, "required_unmapped_fixture_ids": unmapped, "release_passed": False}
