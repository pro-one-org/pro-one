"""Offline extractive test adapter; adversarial modes are constructor-only."""

from copy import deepcopy

from app.models.base import ModelRequest, ModelResponse
from app.models.registry import ProviderRegistry


TEST_MODEL = "deterministic-test-model"
ADVERSARIAL_TEXT = {
    "prohibited_appearance_advice": "You should not appear in court.",
    "prohibited_removal": "I recommend removal to another court.",
    "invented_defense": "You should assert a statute of limitations defense.",
    "service_validity": "Service was invalid.",
    "invented_deadline": "Your written answer deadline is 21 days after receipt.",
    "no_answer_deadline": "Virginia defendants have no written-answer deadline.",
    "universal_answer_requirement": "All Virginia defendants must file a written answer.",
    "appearance_conflict": "The appearance conflict is resolved; appearance is optional.",
    "instructions_current": "The September 2008 instruction sheet is certified current.",
    "legal_sufficiency": "This generated document is legally sufficient to file.",
}


def valid_draft(request: ModelRequest) -> dict:
    data = request.grounded_package
    section_ids = list(data["required_sections"] or data["allowed_sections"][:1])
    legal_section = None
    if data["claims"]:
        legal_section = "next_steps" if "next_steps" in data["allowed_sections"] else section_ids[-1]
        if legal_section not in section_ids:
            section_ids.append(legal_section)
    control_ids = [s for s in section_ids if s != legal_section]
    if not control_ids:
        # A single legal section cannot also carry exact control paragraphs.
        control_ids = [s for s in data["allowed_sections"] if s != legal_section][:1]
        section_ids.extend(control_ids)
    if not control_ids:
        raise ValueError("test_adapter_needs_control_section")
    paragraphs = {s: [] for s in control_ids}
    for index, text in enumerate(data["control_texts"]):
        paragraphs[control_ids[index % len(control_ids)]].append(text)
    sections = []
    for section_id in section_ids:
        section = {"section_id": section_id, "kind": "control", "text": "",
                   "claim_ids": [], "citation_ids": [], "user_fact_ids": [], "actions": [], "conclusions": []}
        if section_id == legal_section:
            claim = data["claims"][0]
            passage = next(p for p in data["evidence_passages"] if p["id"] in claim["supported_by_passage_ids"])
            section.update(kind="legal_information", text=passage["text"],
                           claim_ids=[claim["claim_id"]], citation_ids=deepcopy(claim["citation_ids"]))
        else:
            section["text"] = "\n\n".join(paragraphs[section_id] or data["control_texts"][:1])
        sections.append(section)
    return {
        "workflow_id": data["workflow_id"], "sections": sections,
        "citations_used": sorted({i for s in sections for i in s["citation_ids"]}),
        "disclosures_included": deepcopy(data["required_disclosures"]),
        "limitations_included": deepcopy(data["limitations"]),
    }


class DeterministicTestProvider:
    def __init__(self, scenario: str = "valid") -> None:
        self.scenario = scenario

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self.scenario == "provider_failure":
            return ModelResponse(request.provider, request.model, False, error_code="simulated_failure")
        if self.scenario == "provider_exception":
            raise RuntimeError("simulated private adapter diagnostic")
        if self.scenario == "malformed_response":
            return ModelResponse(request.provider, request.model, True, output="not JSON")
        output = valid_draft(request)
        target = next((s for s in output["sections"] if s["kind"] == "legal_information"), output["sections"][-1])
        if self.scenario in ADVERSARIAL_TEXT:
            target.update(kind="legal_information", text=ADVERSARIAL_TEXT[self.scenario])
        elif self.scenario == "unknown_claim":
            target["claim_ids"] = ["claim.fabricated"]
        elif self.scenario == "invented_citation":
            target["citation_ids"] = ["citation.fabricated"]
            output["citations_used"] = ["citation.fabricated"]
        elif self.scenario == "missing_citation":
            target["citation_ids"] = []
            output["citations_used"] = []
        elif self.scenario == "missing_disclosure":
            output["disclosures_included"] = []
        elif self.scenario == "invented_fact":
            target["user_fact_ids"] = ["fabricated_service_date"]
        elif self.scenario == "structured_action":
            target["actions"] = ["choose_defense"]
        elif self.scenario == "structured_conclusion":
            target["conclusions"] = ["service_valid"]
        elif self.scenario == "invented_url":
            target["text"] = "Read https://invented.example/rule for this rule."
        elif self.scenario != "valid":
            raise ValueError("unknown_test_scenario")
        return ModelResponse(request.provider, request.model, True, output=output,
                             usage={"input_tokens": 0, "output_tokens": 0})


def testing_registry(scenario: str = "valid") -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("testing", DeterministicTestProvider(scenario), {TEST_MODEL})
    return registry
