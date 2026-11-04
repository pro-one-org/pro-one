"""Render only a freshly revalidated draft, using canonical citation metadata."""

from app.generation_contract import build_model_request
from app.output_validation import OutputValidationService


HEADINGS = {"acknowledgment": "Your question", "scope_boundary": "What this covers", "source_limit": "Source limits",
            "deadline_awareness": "Dates to verify", "safe_continuation": "How to continue", "next_steps": "From the official source",
            "redaction_prompt": "Protect your privacy", "privacy_prompt": "Your information", "risk_notice": "Important",
            "court_or_agency_resources": "Official resources", "questions_to_answer": "Questions to check"}


class ResponseRenderingService:
    def render(self, result: dict, package: dict, config) -> dict | None:
        if result["generation"]["status"] != "accepted" or not result["validation"]["valid"] or result["draft"] is None:
            return None
        draft, validation = OutputValidationService().validate(result["draft"], build_model_request(package, config))
        if not validation["valid"]:
            return None
        canonical = {c["citation_id"]: c for c in package["response_plan"]["citations"]}
        sources = {s["id"]: s for s in package["grounding"]["sources"]}
        used = draft["citations_used"]
        if package.get("evidence_mode") in {"capability", "general_research"}:
            claim_index = {c["claim_id"]: c for c in package["response_plan"]["claims"]}
            used = list(dict.fromkeys(cid for section in draft["sections"] for claim_id in section["claim_ids"]
                                     for cid in claim_index[claim_id]["citation_ids"]))
        numbers = {cid: i + 1 for i, cid in enumerate(used)}
        sections = [{"heading": HEADINGS.get(s["section_id"], "Information"), "text": s["text"],
                     "citation_numbers": [numbers[c] for c in s["citation_ids"]],
                     "user_provided": s["kind"] == "user_fact"} for s in draft["sections"] if s["kind"] != "control"]
        if package.get("evidence_mode") in {"capability", "general_research"}:
            claims = {c["claim_id"]: c for c in package["response_plan"]["claims"]}
            sections = [{"heading": "From the sources", "text": text,
                         "citation_numbers": [numbers[c] for c in claims[cid]["citation_ids"]], "user_provided": False}
                        for s in draft["sections"] if s["kind"] == "legal_information"
                        for cid, text in zip(s["claim_ids"], s["text"].split("\n\n"))]
        return {
            "sections": sections,
            "warnings": sorted({p for s in draft["sections"] if s["kind"] == "control" for p in s["text"].split("\n\n")}),
            "notices": sorted({text for risk in package["risks"]["recognized"] for text in risk["allowed_support"]["allowed_language"]}),
            "sources": [{"number": numbers[cid], "title": canonical[cid]["source_title"],
                         "source_type": sources[canonical[cid]["source_id"]]["source_type"],
                         "case_metadata": sources[canonical[cid]["source_id"]].get("case_metadata"),
                         "external_identifiers": sources[canonical[cid]["source_id"]].get("external_identifiers"),
                         "enactment_metadata": sources[canonical[cid]["source_id"]].get("enactment_metadata"),
                         "issuing_authority": sources[canonical[cid]["source_id"]]["authority"]["issuing_body"],
                         "citation": canonical[cid]["preferred_citation"], "locator": canonical[cid]["locator"],
                         "url": canonical[cid]["official_url"] if canonical[cid]["official_url"].startswith("https://") else None,
                         "limitations": canonical[cid]["limitations"], "currentness": canonical[cid]["source_currentness"]["status"],
                         "maturity": canonical[cid]["source_status"]} for cid in used],
            "limitations": package["response_plan"]["limitations"],
            "status_label": "Accepted development response", "publicly_approved": False,
            "evidence_mode": package.get("evidence_mode", "workflow"),
        }
