"""Deterministic structural enforcement and supplementary prose guards.

This is not semantic legal/factual verification. Accepted means this development
contract passed; public release remains disabled by the generation service.
"""

import json
import re
import unicodedata
from typing import Any, TypedDict

from pydantic import ValidationError

from app.generated_draft import GeneratedDraft
from app.models.base import ModelRequest


class ValidationResult(TypedDict):
    valid: bool
    errors: list[dict[str, Any]]


def normalized(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf")
    return " ".join(text.casefold().replace("’", "'").split())


# Supplementary deny patterns for documented red-team cases, not a legal reasoner.
# Run on generated legal text; controls/facts have stricter exact-content checks.
PROSE_GUARDS = (
    ("instruction_override_attempt", r"\b(?:ignore|override|disregard)\b.{0,35}\b(?:instructions|policy|system|constraints|schema)\b"),
    ("privacy_overcollection", r"\b(?:send|share|provide|paste|upload)\b.{0,55}\b(?:unredacted|full (?:bank|account|social)|ssn|social security number)\b"),
    ("prohibited_appearance_advice", r"\b(?:you|defendants?|the defendant)\b.{0,60}\b(?:should|must|need to|do not|don't|can skip|safe not to)\b.{0,35}\b(?:appear|attend|go to court)\b"),
    ("prohibited_appearance_advice", r"\b(?:do not|don't|must not|should not|not required to|recommend.{0,15}|please)\s+(?:appear|attend|go to court)\b|^(?:appear|attend)\b"),
    ("prohibited_removal_recommendation", r"\b(?:you should|you must|i recommend|best (?:option|choice)|recommend(?:ed)?)\b.{0,60}\b(?:remov\w*|transfer\w*)\b"),
    ("prohibited_strategy_decision", r"\b(?:you should|you must|i recommend|choose|use|assert|plead|select)\b.{0,60}\b(?:settle|settlement|contest|admit|deny|admission|denial|defen[cs]e|limitations|fraud)\b"),
    ("service_validity_conclusion", r"\bservice\b.{0,35}\b(?:is|was|isn't|wasn't)\b.{0,20}\b(?:valid|invalid|defective|proper|improper)\b"),
    ("unsupported_deadline", r"\b(?:deadline|written[ -]answer|written response|answer|respond|file)\b.{0,80}\b(?:no deadline|no .{0,20}deadline|never due|\d+ (?:calendar |business )?days?|\d{4}-\d{2}-\d{2}|(?:january|february|march|april|may|june|july|august|september|october|november|december) \d|tomorrow|next week)\b"),
    ("universal_answer_deadline_conclusion", r"\b(?:no|not have|don't have|do not have|without|is no)\b.{0,55}\b(?:written[ -]answer|answer filing|written response)\b.{0,40}\bdeadline\b|\bwritten[ -]answer deadline\b.{0,25}\b(?:does not exist|never applies)\b"),
    ("universal_answer_deadline_conclusion", r"\bno\b.{0,20}\bdeadline\b.{0,60}\b(?:written[ -]answer|written response)\b"),
    ("universal_answer_requirement", r"\b(?:all|every|universally|always|must|required)\b.{0,65}\b(?:written answer|written response)\b|\b(?:written answer|written response)\b.{0,40}\b(?:always|universally|required|mandatory)\b"),
    ("appearance_conflict_resolved", r"\b(?:appearance|appear|attendance|attend)\b.{0,45}\b(?:optional|required|mandatory|resolved|unnecessary)\b|\b(?:conflict|contradiction)\b.{0,30}\b(?:resolved|settled)\b"),
    ("instruction_currentness_asserted", r"\b(?:2008|instruction(?:s| sheet)?)\b.{0,65}\b(?:certified current|is current|are current|up.to.date|verified current)\b"),
    ("legal_sufficiency_claim", r"\b(?:is|are|will be|guaranteed|fully|legally)\b.{0,30}\b(?:legally sufficient|filing.ready|sufficient to file|sufficient for filing|guaranteed to win)\b|\b(?:guarantee|will win|certain to win)\b"),
)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


class OutputValidationService:
    def validate(self, output: Any, request: ModelRequest) -> tuple[dict[str, Any] | None, ValidationResult]:
        errors = []

        def fail(code: str, index: int | None = None) -> None:
            item = {"code": code}
            if index is not None:
                item["section_index"] = index
            if item not in errors:
                errors.append(item)

        try:
            if isinstance(output, str):
                if len(output) > request.limits["max_output_characters"]:
                    raise ValueError("size")
                output = json.loads(output, object_pairs_hook=unique_object,
                                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
            if len(json.dumps(output, allow_nan=False)) > request.limits["max_output_characters"]:
                raise ValueError("size")
        except (ValueError, TypeError, RecursionError):
            return None, {"valid": False, "errors": [{"code": "model_output_unparseable"}]}
        try:
            draft = GeneratedDraft.model_validate(output)
        except ValidationError:
            return None, {"valid": False, "errors": [{"code": "generated_schema_invalid"}]}

        data = request.grounded_package
        claims = {c["claim_id"]: c for c in data["claims"]}
        citations = {c["citation_id"]: c for c in data["citations"]}
        passages = {p["id"]: p for p in data["evidence_passages"]}
        facts = data["user_facts"]
        seen_sections = set()
        used_citations = set()
        rendered_controls = set()
        if draft.workflow_id != data["workflow_id"]:
            fail("workflow_mismatch")
        for index, section in enumerate(draft.sections):
            if section.section_id not in data["allowed_sections"]:
                fail("unknown_section", index)
            if section.section_id in seen_sections:
                fail("duplicate_section", index)
            seen_sections.add(section.section_id)
            if section.actions:
                fail("prohibited_action", index)
            if section.conclusions:
                fail("prohibited_conclusion", index)
            for ids in (section.claim_ids, section.citation_ids, section.user_fact_ids):
                if len(ids) != len(set(ids)):
                    fail("duplicate_reference", index)
            for fact_id in section.user_fact_ids:
                if fact_id not in facts:
                    fail("unknown_user_fact_id", index)
            for claim_id in section.claim_ids:
                claim = claims.get(claim_id)
                if claim is None:
                    fail("unknown_claim_id", index)
                    continue
                supported = set(claim["supported_by_passage_ids"])
                if claim["workflow_id"] != data["workflow_id"] or not supported or not supported.issubset(passages):
                    fail("unsupported_claim", index)
                if not section.citation_ids:
                    fail("claim_without_citation", index)
                linked = set(claim["citation_ids"])
                if not linked.intersection(section.citation_ids):
                    fail("citation_not_supporting_claim", index)
                for citation_id in linked.intersection(section.citation_ids):
                    citation = citations.get(citation_id)
                    passage = passages.get(citation["passage_id"]) if citation else None
                    if (not citation or citation["passage_id"] not in supported or not passage
                            or citation["source_id"] != passage["source_id"]
                            or citation["source_id"] not in claim["source_ids"]
                            or claim["topic"] not in passage["propositions"]):
                        fail("unsupported_claim", index)
            for citation_id in section.citation_ids:
                if citation_id not in citations:
                    fail("unknown_citation_id", index)
                if not any(citation_id in claims[c]["citation_ids"] for c in section.claim_ids if c in claims):
                    fail("citation_not_supporting_claim", index)
                used_citations.add(citation_id)
            if section.kind == "legal_information":
                if not section.claim_ids:
                    fail("unsupported_claim", index)
                # Facts may only be repeated in the exact dedicated fact channel.
                if section.user_fact_ids:
                    fail("fact_use_outside_fact_section", index)
                text = normalized(section.text)
                for code, pattern in PROSE_GUARDS:
                    if re.search(pattern, text):
                        fail(code, index)
                # No free-form URLs: citations are rendered by the caller from
                # canonical IDs, never from generated text or provider metadata.
                if re.search(r"https?://|www\.", text):
                    fail("unstructured_citation", index)
                for pattern in data["response_constraints"]:
                    for phrase in pattern["prohibited_content"]["prohibited_language"] + pattern["user_message"]["phrases_to_avoid"]:
                        if normalized(phrase) in text:
                            fail("prohibited_conclusion", index)
                # Every matching topic's curated qualifications must accompany it.
                for c in section.claim_ids:
                    if c in claims and not set(claims[c]["limitations"]).issubset(draft.limitations_included):
                        fail("claim_limitation_missing", index)
                    if c in claims and not claims[c]["quotation_allowed"]:
                        if '"' in section.text or any(normalized(passages[p]["text"]) in text for p in claims[c]["supported_by_passage_ids"] if p in passages):
                            fail("source_quotation_not_allowed", index)
            elif section.kind == "control":
                paragraphs = section.text.split("\n\n")
                if not set(paragraphs).issubset(data["control_texts"]):
                    fail("unapproved_control_text", index)
                else:
                    rendered_controls.update(paragraphs)
                if section.claim_ids or section.citation_ids or section.user_fact_ids:
                    fail("control_reference_invalid", index)
            elif section.kind == "user_fact":
                if (len(section.user_fact_ids) != 1 or section.claim_ids or section.citation_ids
                        or section.user_fact_ids[0] not in facts
                        or section.text != str(facts[section.user_fact_ids[0]]["value"])):
                    fail("user_fact_changed", index)
                elif facts[section.user_fact_ids[0]]["provenance"] != "user_provided":
                    fail("user_fact_provenance_invalid", index)

        if set(data["required_sections"]) - seen_sections:
            fail("required_section_missing")
        for values in (draft.citations_used, draft.disclosures_included, draft.limitations_included):
            if len(values) != len(set(values)):
                fail("duplicate_reference")
        if set(draft.citations_used) - set(citations):
            fail("unknown_citation_id")
        if set(draft.citations_used) != used_citations:
            fail("citation_manifest_mismatch")
        if set(draft.disclosures_included) != set(data["required_disclosures"]) or not set(data["required_disclosures"]).issubset(rendered_controls):
            fail("required_disclosure_missing")
        if set(draft.limitations_included) != set(data["limitations"]) or not set(data["limitations"]).issubset(rendered_controls):
            fail("required_limitation_missing")
        if not set(data["required_risk_notices"]).issubset(rendered_controls):
            fail("risk_notice_missing")
        if not set(data["required_control_texts"]).issubset(rendered_controls):
            fail("required_control_missing")
        # Claim-bearing plans must actually use at least one supported claim.
        if claims and not any(s.claim_ids for s in draft.sections):
            fail("substantive_content_missing")
        valid = not errors
        return draft.model_dump() if valid else None, {"valid": valid, "errors": errors}
