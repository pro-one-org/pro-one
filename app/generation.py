"""One bounded provider call followed by mandatory independent validation."""

from copy import deepcopy
from typing import Any, TypedDict

from app.generated_draft import GeneratedDraft
from app.generation_contract import INSTRUCTION_VERSION, build_model_request, request_size
from app.models.base import GenerationConfig, ModelResponse
from app.models.registry import ProviderConfigurationError, ProviderRegistry
from app.output_validation import OutputValidationService, ValidationResult
from app.response_assembly import ResponseAssemblyRequest, ResponseAssemblyResult


class GenerationRequest(ResponseAssemblyRequest):
    generation: GenerationConfig


class GenerationResult(TypedDict):
    workflow_id: str
    mode: str
    generation: dict[str, Any]
    draft: GeneratedDraft | None
    validation: ValidationResult
    assembly: dict[str, Any]
    public_execution: dict[str, Any]


class GenerationService:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry
        self.validator = OutputValidationService()

    def generate(self, package: ResponseAssemblyResult, config: GenerationConfig) -> GenerationResult:
        # Own the authority snapshot. Neither adapters nor returned structures can
        # mutate the caller's deterministic evidence or validation constraints.
        package = deepcopy(package)
        result = {
            "workflow_id": package["workflow_id"], "mode": "development_only",
            "generation": {"status": "not_attempted", "provider": config.provider, "model": config.model,
                           "instruction_version": INSTRUCTION_VERSION, "attempts": 0, "usage": {}, "allowed_claim_ids": []},
            "draft": None,
            "validation": {"valid": False, "errors": []},
            "assembly": {"package_integrity": package["development_package"]["package_integrity"],
                         "input_eligible": package["public_execution"]["input_eligible"],
                         "plan_claim_ids": [c["claim_id"] for c in package["response_plan"]["claims"]],
                         "routing": package["routing"],
                         "missing_information": package["user_context"]["missing_information"],
                         "support_gap_codes": [g["code"] for g in package["response_plan"]["support_gaps"]]},
            "public_execution": {"allowed": False, "assembly_eligible": package["public_execution"]["allowed"],
                                 "reason": "development_generation_only"},
        }

        def failure(code: str, status: str = "not_attempted") -> GenerationResult:
            result["generation"]["status"] = status
            result["validation"]["errors"] = [{"code": code}]
            return deepcopy(result)

        if not (package["development_package"]["available"] and package["development_package"]["package_integrity"]
                and package["response_plan"]["available"]
                and package["grounding"]["eligibility"]["development_grounding"]["available"]):
            return failure("development_package_unavailable")
        if config.scope == "outside_workflow":
            return failure("scope_outside_workflow")
        try:
            adapter = self.registry.resolve(config.provider, config.model)
        except ProviderConfigurationError as exc:
            return failure(str(exc))
        request = build_model_request(package, config)
        result["generation"]["allowed_claim_ids"] = [c["claim_id"] for c in request.grounded_package["claims"]]
        if not request.grounded_package["allowed_sections"] or not request.grounded_package["control_texts"]:
            return failure("generation_contract_unavailable")
        if request_size(request) > 160000:
            return failure("model_input_limit_exceeded")
        result["generation"]["attempts"] = 1
        try:
            response = adapter.generate(deepcopy(request))
            if (not isinstance(response, ModelResponse) or response.success is not True
                    or response.provider != config.provider or response.model != config.model):
                return failure("provider_error", "provider_error")
        except Exception:
            # Never return/log adapter exceptions, raw metadata, prompts, or output.
            return failure("provider_error", "provider_error")
        draft, validation = self.validator.validate(response.output, request)
        result["validation"] = validation
        result["draft"] = draft
        result["generation"]["status"] = "accepted" if validation["valid"] else "rejected"
        result["generation"]["usage"] = {
            key: value for key, value in response.usage.items()
            if key in {"input_tokens", "output_tokens", "total_tokens"}
            and type(value) is int and 0 <= value <= 1000000000
        } if isinstance(response.usage, dict) else {}
        return deepcopy(result)
