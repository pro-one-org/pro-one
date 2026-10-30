"""Release checks for actual selected evidence; no source-text interpretation."""

from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Callable, TypedDict

from app.corpus import passage_relationship_errors
from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository, RepositoryLoadError
from app.retrieval import eligible_record
from app.review_policy import SUPPORTED_REVIEW_SCOPES


class GroundingResult(TypedDict):
    workflow_id: str
    evaluation_date: str
    workflow_readiness: dict[str, Any]
    development_grounding: dict[str, Any]
    public_grounding: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def blocker(code: str, record_id: str, domain: str, **details: Any) -> dict[str, Any]:
    return {
        "code": code,
        "message": code.replace("_", " ") + ".",
        "record_id": record_id,
        "domain": domain,
        **details,
    }


def public_record_blockers(
    kind: str, label: str, record: dict[str, Any], evaluation_date: date,
) -> list[dict[str, Any]]:
    results = []
    record_id = record["id"]
    review = record["review"]
    if record["status"] != "supported":
        results.append(blocker(f"{label}_status_not_supported", record_id, kind))
    if review["status"] != "approved":
        results.append(blocker(f"{label}_review_not_approved", record_id, kind))
    missing = sorted(SUPPORTED_REVIEW_SCOPES[kind] - set(review["review_scope"]))
    if missing:
        results.append(blocker(f"{label}_review_scopes_missing", record_id, kind, missing_scopes=missing))
    if (
        not review.get("reviewed_by") or not review.get("reviewer_role")
        or review.get("reviewed_record_version") != record["record_version"]
        or not review.get("reviewed_on")
        or review["reviewed_on"] > evaluation_date.isoformat()
    ):
        results.append(blocker(f"{label}_review_provenance_invalid", record_id, kind))
    return results


def currentness_blockers(
    kind: str, record: dict[str, Any], evaluation_date: date,
) -> list[dict[str, Any]]:
    label = "source" if kind == "source" else "passage"
    certification = record.get("public_currentness", {})
    if certification.get("status") != "certified":
        return [blocker(f"{label}_freshness_unresolved", record["id"], kind)]
    version, verified = (
        (record["provenance"]["source_content_version"], record["dates"]["last_verified"])
        if kind == "source" else
        (record["verification"]["source_version"], record["verification"]["verified_on"])
    )
    try:
        checked = date.fromisoformat(certification["verified_on"])
        expires = date.fromisoformat(certification["valid_through"])
        valid = (
            certification["record_version"] == record["record_version"]
            and certification["source_content_version"] == version
            and certification["verified_on"] == verified
            and certification["unresolved_issues"] == []
            and checked <= evaluation_date <= expires
            and record["review"].get("reviewed_on", "") >= checked.isoformat()
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    results = [] if valid else [blocker(f"{label}_currentness_certification_invalid", record["id"], kind)]
    if kind == "source":
        dates = record["dates"]
        start, end = dates.get("effective_from"), dates.get("effective_through")
        if record["source_type"] in {"statute", "regulation", "court_rule", "agency_rule"} and not start:
            results.append(blocker("source_effective_period_unresolved", record["id"], kind))
        if (start and start > evaluation_date.isoformat()) or (end and end < evaluation_date.isoformat()):
            results.append(blocker("source_outside_effective_period", record["id"], kind))
    return results


class GroundingEligibilityService:
    def __init__(self, repository: RecordRepository, today: Callable[[], date] = utc_today) -> None:
        self.repository = repository
        self.readiness_service = WorkflowReadinessService(repository)
        self.today = today

    def evaluate(
        self,
        workflow_id: str,
        passage_ids: list[str],
        legal_rule_ids: list[str] | None = None,
        process_step_ids: list[str] | None = None,
        response_ids: list[str] | None = None,
        risk_ids: list[str] | None = None,
    ) -> GroundingResult | None:
        resolved = self.repository.resolve_workflow(workflow_id)
        if resolved is None:
            return None
        evaluation_date = self.today()
        readiness = self.readiness_service.evaluate(workflow_id)
        related = resolved["related"]
        development: list[dict[str, Any]] = []
        public: list[dict[str, Any]] = []

        def select(domain: str, ids: list[str]) -> list[dict[str, Any]]:
            linked = {record["id"]: record for record in related[domain]}
            records = []
            for record_id in sorted(set(ids)):
                record = self.repository.get(domain, record_id)
                if record is None:
                    development.append(blocker("grounding_reference_not_found", record_id, domain))
                elif record_id not in linked:
                    development.append(blocker("grounding_reference_not_in_workflow", record_id, domain))
                else:
                    records.append(record)
            return records

        passages = select("source_passages", passage_ids)
        if not passage_ids:
            development.append(blocker("grounding_passages_missing", workflow_id, "workflows"))
        sources = select("sources", [p["source_id"] for p in passages])
        # Implicit evidence links cannot be bypassed by supplying empty ID lists.
        rules = select("legal_rules", [*(legal_rule_ids or []), *(i for p in passages for i in p["legal_rule_ids"])])
        steps = select("process_steps", [*(process_step_ids or []), *(i for p in passages for i in p["process_step_ids"])])
        patterns = select("responses", [*(response_ids or []), *(r["id"] for r in related["responses"])])
        risks = select("risks", risk_ids or [])

        for passage in passages:
            errors = passage_relationship_errors(
                passage, sources=self.repository.records["sources"],
                workflows=self.repository.records["workflows"],
                legal_rules=self.repository.records["legal_rules"],
                process_steps=self.repository.records["process_steps"],
            )
            if errors:
                development.append(blocker("grounding_relationship_invalid", passage["id"], "source_passages", issues=errors))
        for domain, records in (
            ("source_passages", passages), ("sources", sources),
            ("legal_rules", rules), ("process_steps", steps), ("responses", patterns),
            ("risks", risks),
        ):
            for record in records:
                if not eligible_record(record) or record["review"]["status"] == "deprecated":
                    development.append(blocker("grounding_record_ineligible", record["id"], domain))
        for source in sources:
            if source["provenance"]["superseded_by_source_id"] is not None:
                development.append(blocker("source_superseded", source["id"], "sources"))
            if source["authority"]["level"] not in {"official_primary", "official_secondary"}:
                development.append(blocker("grounding_source_authority_ineligible", source["id"], "sources"))
            if not source["url"] or not source["citation"].get("preferred_citation"):
                development.append(blocker("grounding_citation_missing", source["id"], "sources"))
        for field, records in (("legal_rule_ids", rules), ("process_step_ids", steps)):
            for record in records:
                if not any(record["id"] in p[field] for p in passages):
                    development.append(blocker("grounding_record_passage_support_missing", record["id"], field))

        for kind, domain, label, records in (
            ("source_passage", "source_passages", "passage", passages),
            ("source", "sources", "source", sources),
            ("legal_rule", "legal_rules", "legal_rule", rules),
            ("process_step", "process_steps", "process_step", steps),
            ("response", "responses", "response_pattern", patterns),
            ("risk", "risks", "risk", risks),
        ):
            for record in records:
                public.extend(public_record_blockers(kind, label, record, evaluation_date))
                try:
                    self.repository.validate_record(domain, record)
                except RepositoryLoadError:
                    public.append(blocker(f"{label}_schema_invalid", record["id"], kind))
                if kind in {"source", "source_passage"}:
                    public.extend(currentness_blockers(kind, record, evaluation_date))
        for rule in rules:
            if not rule["rule_statement"]["user_facing_allowed"]:
                public.append(blocker("legal_rule_user_facing_not_allowed", rule["id"], "legal_rules"))
            covered = {p["source_id"] for p in passages if rule["id"] in p["legal_rule_ids"]}
            if set(rule["source_support"]["required_source_ids"]) - covered:
                public.append(blocker("legal_rule_required_source_support_missing", rule["id"], "legal_rules"))
        for source in sources:
            rights = source["rights"]
            if rights["reuse_status"] not in {"public_domain", "open_license"} or (
                rights["reuse_status"] == "open_license" and not rights.get("license")
            ):
                public.append(blocker("source_reuse_unresolved", source["id"], "sources"))
        for pattern in patterns:
            for source in sources:
                use = pattern["source_use"]
                if source["review"]["status"] not in use["allowed_source_review_statuses"] or source["authority"]["level"] not in use["allowed_source_authority_levels"]:
                    public.append(blocker("response_pattern_source_constraints_unsatisfied", pattern["id"], "responses", source_id=source["id"]))

        selected_topics = {topic for passage in passages for topic in passage["propositions"]}
        for gap in resolved["workflow"].get("response_constraints", {}).get("support_gaps", []):
            if gap["blocks_public_grounding"] and (
                not gap["propositions"] or selected_topics.intersection(gap["propositions"])
            ):
                public.append(blocker("grounding_proposition_unresolved", workflow_id, "workflows", gap_code=gap["code"]))
        if not readiness["ready_for_public_use"]:
            public.append(blocker("workflow_not_ready", workflow_id, "workflows"))
        public = development + public

        def ordered(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(items, key=lambda b: (b["domain"], b["record_id"], b["code"], str(b.get("gap_code", ""))))

        return deepcopy({
            "workflow_id": workflow_id,
            "evaluation_date": evaluation_date.isoformat(),
            "workflow_readiness": readiness,
            "development_grounding": {"available": not development, "blockers": ordered(development)},
            "public_grounding": {"allowed": not public, "blockers": ordered(public)},
            "records": {
                domain: records if not development else []
                for domain, records in (
                    ("passages", passages), ("sources", sources), ("legal_rules", rules),
                    ("process_steps", steps), ("response_patterns", patterns),
                    ("risks", risks),
                )
            },
        })
