"""Stateless orchestration; unsupported structured matters stop before a model call."""

from time import perf_counter

from app.config import Settings
from app.generation import GenerationService
from app.generation_contract import build_model_request
from app.models.base import GenerationConfig
from app.rendering import ResponseRenderingService
from app.response_assembly import ResponseAssemblyRequest, ResponseAssemblyService
from app.routing import MatterRequest, MatterRoutingService


class ProductResponseRequest(ResponseAssemblyRequest):
    matter: MatterRequest
    generation: GenerationConfig | None = None


MESSAGES = {
    "unsupported": "Pro-One does not yet cover this matter. Use the official resources listed, or check the coverage page.",
    "insufficient_information": "Please confirm the missing information before continuing.",
    "out_of_workflow": "These details do not fit this workflow. Check the court, agency, and document.",
    "provider_unavailable": "The selected model is unavailable. Check server configuration or use the labeled offline test provider in development.",
    "rejected": "The draft did not pass our checks. No generated answer is displayed. You can review the official sources or revise your question.",
    "public_workflow_unavailable": "This workflow has not been approved for public use. It is available only in a local development environment.",
    "grounding_unavailable": "No usable source evidence was found for this question. Pro-One cannot provide an unsupported answer.",
}


class ProductService:
    def __init__(self, repository, settings: Settings, generation: GenerationService) -> None:
        self.repository, self.settings, self.generation = repository, settings, generation
        self.assembly = ResponseAssemblyService(repository)
        self.router = MatterRoutingService(repository)

    def respond(self, workflow_id: str, request: ProductResponseRequest) -> dict:
        timing = {}

        def stopped(status, missing=None):
            return {"status": status, "message": MESSAGES[status], "response": None,
                    "missing_information": missing or [], "public_execution": {"allowed": False}, "timing_ms": timing}

        start = perf_counter()
        scope = self.router.scope(workflow_id, request.matter)
        timing["routing"] = round((perf_counter() - start) * 1000, 2)
        if self.repository.get_workflow(workflow_id) is None:
            return stopped("unsupported")
        if scope["state"] == "outside_workflow":
            return stopped("out_of_workflow")
        if scope["state"] != "confirmed_for_workflow":
            return stopped("insufficient_information", scope["missing_fields"])
        start = perf_counter()
        package = self.assembly.assemble(workflow_id, request, metrics=timing)
        timing["assembly_including_retrieval"] = round((perf_counter() - start) * 1000, 2)
        if package["scope_resolution"]["state"] == "outside_workflow":
            return stopped("out_of_workflow")
        if package["risks"]["unknown"] or package["risks"]["not_applicable"]:
            return stopped("insufficient_information", ["recognized workflow risk selection"])
        if package["user_context"]["missing_information"]:
            return stopped("insufficient_information", package["user_context"]["missing_information"])
        if self.settings.mode == "production" and not package["public_execution"]["allowed"]:
            return stopped("public_workflow_unavailable")
        config = request.generation or GenerationConfig(provider=self.settings.provider or "unavailable", model=self.settings.model or "unavailable")
        if config.model not in self.generation.registry.configured_models().get(config.provider, []):
            return stopped("provider_unavailable")
        if self.settings.mode == "production" and config.provider == "testing":
            return stopped("provider_unavailable")
        if not build_model_request(package, config).grounded_package["claims"]:
            return stopped("grounding_unavailable")
        start = perf_counter()
        result = self.generation.generate(package, config)
        timing["generation_and_validation"] = round((perf_counter() - start) * 1000, 2)
        status = result["generation"]["status"]
        if status == "provider_error":
            return stopped("provider_unavailable")
        if status == "not_attempted":
            return stopped("grounding_unavailable")
        rendered = ResponseRenderingService().render(result, package, config)
        if rendered is None:
            return stopped("rejected")
        return {"status": "accepted_development", "message": "Development response — sources and legal review remain proposed.",
                "response": rendered, "missing_information": [], "public_execution": {"allowed": False},
                "model": {"provider": config.provider, "model": config.model, "testing": config.provider == "testing"},
                "timing_ms": timing}
