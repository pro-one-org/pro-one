"""Workflow-scoped local relationship retrieval and optional lexical ranking."""

from copy import deepcopy
import re
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str | None = Field(default=None, max_length=2000)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    legal_rule_ids: list[str] = Field(default_factory=list, max_length=50)
    process_step_ids: list[str] = Field(default_factory=list, max_length=50)
    proposition_ids: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=5, ge=1, le=20)


class RetrievalResult(TypedDict):
    workflow_id: str
    mode: str
    query: str | None
    filters: dict[str, list[str]]
    passages: list[dict[str, Any]]
    retrieval: dict[str, Any]
    limitations: list[str]
    public_execution: dict[str, Any]


class RetrievalFilterError(ValueError):
    def __init__(self, invalid_filters: dict[str, list[str]]) -> None:
        super().__init__("filters_not_in_workflow_package")
        self.invalid_filters = invalid_filters


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def lexical_score(query_tokens: set[str], passage: dict[str, Any]) -> int:
    """Title overlap counts twice; excerpt/locator/topic overlap counts once.

    Unique tokens only; no stemming, inference, or confidence interpretation.
    Limitations are always returned, but are not affirmative ranking evidence.
    """
    body = " ".join([passage["text"], passage["locator"], *passage["propositions"]])
    return 2 * len(query_tokens & tokens(passage["title"])) + len(query_tokens & tokens(body))


def eligible_record(record: dict[str, Any]) -> bool:
    return (
        record["status"] not in {"deprecated", "rejected"}
        and record["review"]["status"] != "rejected"
    )


class PassageRetrievalService:
    def __init__(self, repository: RecordRepository) -> None:
        self.repository = repository
        self.readiness_service = WorkflowReadinessService(repository)

    def retrieve(self, workflow_id: str, request: RetrievalRequest) -> RetrievalResult | None:
        resolved = self.repository.resolve_workflow(workflow_id)
        if resolved is None:
            return None
        self.repository.validate_source_passages(workflow_id)
        related = resolved["related"]
        sources = {record["id"]: record for record in related["sources"]}
        workflow_scope = resolved["workflow"]["jurisdiction"]
        dimensions = ("country", "state", "locality", "court", "agency")
        # Select package, source and jurisdiction eligibility BEFORE lexical work.
        candidates = []
        for passage in related["source_passages"]:
            source = sources.get(passage["source_id"])
            if source is None:
                continue  # Startup/shared integrity validation rejects broken links.
            if not eligible_record(passage) or not eligible_record(source):
                continue
            if source["authority"]["level"] not in {"official_primary", "official_secondary"}:
                continue
            if source["provenance"]["superseded_by_source_id"] is not None:
                continue
            if any(passage["jurisdiction"].get(key) != workflow_scope.get(key) for key in dimensions):
                continue
            candidates.append(passage)

        corpus_limitations = sorted({
            limitation for passage in candidates for limitation in passage["limitations"]
        })

        filters = {
            field: sorted(set(getattr(request, field)))
            for field in ("source_ids", "legal_rule_ids", "process_step_ids", "proposition_ids")
        }
        allowed = {
            "source_ids": set(sources),
            "legal_rule_ids": {record["id"] for record in related["legal_rules"]},
            "process_step_ids": {record["id"] for record in related["process_steps"]},
            "proposition_ids": {tag for passage in candidates for tag in passage["propositions"]},
        }
        invalid = {
            field: sorted(set(values) - allowed[field])
            for field, values in filters.items() if set(values) - allowed[field]
        }
        if invalid:
            raise RetrievalFilterError(invalid)

        def matches(passage: dict[str, Any]) -> bool:
            values = {
                "source_ids": [passage["source_id"]],
                "legal_rule_ids": passage["legal_rule_ids"],
                "process_step_ids": passage["process_step_ids"],
                "proposition_ids": passage["propositions"],
            }
            # OR within one filter, AND across filter types; no scope expansion.
            return all(not ids or set(ids).intersection(values[field]) for field, ids in filters.items())

        candidates = [passage for passage in candidates if matches(passage)]
        query_tokens = tokens(request.query) if request.query is not None else None
        ranked = [
            (lexical_score(query_tokens, passage) if query_tokens is not None else 0, passage)
            for passage in candidates
        ]
        if query_tokens is not None:
            ranked = [(score, passage) for score, passage in ranked if score > 0]
        ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
        passages = []
        for score, passage in ranked[:request.limit]:
            source = sources[passage["source_id"]]
            passages.append({
                **passage,
                "source_title": source["title"],
                "source_url": source["url"],
                "source_status": source["status"],
                "source_review": source["review"],
                "source_authority": source["authority"],
                "citation": source["citation"],
                "rights": source["rights"],
                "retrieval_score": float(score),
                "freshness": {
                    "source_dates": source["dates"],
                    "source_provenance": source["provenance"],
                    "passage_verification": passage["verification"],
                    "currentness_certified": False,
                },
                "limitations": sorted(set(
                    passage["limitations"] + source["workflow_fit"].get("limitations", [])
                )),
            })
        readiness = self.readiness_service.evaluate(workflow_id)
        status = (
            "empty_query" if query_tokens == set() else
            "no_eligible_passages" if not candidates else
            "no_matching_passages" if not ranked else "passages_found"
        )
        # This endpoint assembles inspection material; it never grants execution.
        return deepcopy({
            "workflow_id": workflow_id,
            "mode": "development_inspection",
            "query": request.query,
            "filters": filters,
            "passages": passages,
            "retrieval": {
                "status": status,
                "candidate_count": len(candidates),
                "matched_count": len(ranked),
                "returned_count": len(passages),
                "algorithm": "weighted_unique_token_overlap_v1" if query_tokens is not None else "relationship_selection_v1",
            },
            "limitations": [
                "Development inspection only; retrieval is not legal approval or an answer.",
                "Lexical overlap is not legal applicability or legal confidence.",
                "Verification dates do not certify current law, local practice, reuse rights, service validity, or source approval.",
                *corpus_limitations,
            ] if related["source_passages"] else ["No curated passages are linked to this workflow; no fallback is performed."],
            "public_execution": {
                "allowed": False,
                "reason": "development_inspection_only",
                "readiness": readiness,
            },
        })
