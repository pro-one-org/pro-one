from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.execution import ExecutionContextService, ExecutionResult
from app.intake import IntakeRequest, IntakeResolutionError
from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository, RepositoryLoadError
from app.retrieval import (
    PassageRetrievalService,
    RetrievalFilterError,
    RetrievalRequest,
    RetrievalResult,
)
from app.response_assembly import (
    AssemblyIntegrityError,
    ResponseAssemblyRequest,
    ResponseAssemblyResult,
    ResponseAssemblyService,
)
from app.generation import GenerationRequest, GenerationResult, GenerationService
from app.config import Settings
from app.routing import MatterRequest, MatterRoutingService, WorkflowCatalogService
from app.product import ProductResponseRequest, ProductService
from app.security import SecurityMiddleware


app = FastAPI(
    title="Pro-One",
    description="Runtime foundation for source-grounded legal-information workflows.",
    version="0.1.0",
)

try:
    repository = RecordRepository()
except RepositoryLoadError as exc:
    raise RuntimeError(
        f"Pro-One failed to load repository data: {exc}"
    ) from exc

readiness_service = WorkflowReadinessService(repository)
execution_service = ExecutionContextService(repository)
retrieval_service = PassageRetrievalService(repository)
response_assembly_service = ResponseAssemblyService(repository)
settings = Settings.from_environment()
generation_service = GenerationService(settings.registry())
app.add_middleware(SecurityMiddleware)
web_root = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=web_root), name="static")


@app.middleware("http")
async def production_inspection_boundary(request: Request, call_next):
    path = request.url.path
    if settings.mode == "production" and (
        path in {"/docs", "/redoc"} or path.endswith(("/resolved", "/response/assemble", "/intake/evaluate", "/retrieval"))
        or (path.startswith("/workflows/") and path.count("/") == 2)
    ):
        return JSONResponse({"detail": {"code": "development_inspection_disabled"}}, status_code=403)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def safe_generation_request_error(request: Request, exc: RequestValidationError):
    # Default diagnostics include raw input; omit values on every API path.
    return JSONResponse(status_code=422, content={"detail": {
        "code": "malformed_generation_request" if request.url.path.endswith("/response/generate") else "malformed_request",
        "errors": [{"type": e["type"], "loc": list(e["loc"])} for e in exc.errors()],
    }})


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "pro-one",
        "version": "0.1.0",
        "records_loaded": repository.count_records(),
        "domains_loaded": len(repository.records),
    }


@app.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str) -> dict:
    workflow = repository.get_workflow(workflow_id)

    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' was not found.",
        )

    return workflow


@app.get("/workflows/{workflow_id}/resolved")
def get_resolved_workflow(workflow_id: str) -> dict:
    resolved = repository.resolve_workflow(workflow_id)

    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' was not found.",
        )

    return resolved


@app.get("/workflows/{workflow_id}/readiness")
def get_workflow_readiness(workflow_id: str) -> dict:
    result = readiness_service.evaluate(workflow_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' was not found.",
        )

    return result


@app.post("/workflows/{workflow_id}/retrieval")
def retrieve_passages(workflow_id: str, request: RetrievalRequest) -> RetrievalResult:
    try:
        result = retrieval_service.retrieve(workflow_id, request)
    except RetrievalFilterError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "filters_not_in_workflow_package",
                "invalid_filters": exc.invalid_filters,
            },
        ) from exc
    except RepositoryLoadError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "corpus_integrity_error"},
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Workflow '{workflow_id}' was not found.",
        )
    return result


@app.post("/workflows/{workflow_id}/response/assemble")
def assemble_response(workflow_id: str, request: ResponseAssemblyRequest) -> ResponseAssemblyResult:
    try:
        result = response_assembly_service.assemble(workflow_id, request)
    except IntakeResolutionError as exc:
        raise HTTPException(status_code=409, detail={
            "code": exc.code, "candidate_intake_ids": exc.candidate_ids,
        }) from exc
    except RetrievalFilterError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "filters_not_in_workflow_package", "invalid_filters": exc.invalid_filters,
        }) from exc
    except RepositoryLoadError as exc:
        raise HTTPException(status_code=409, detail={"code": "corpus_integrity_error"}) from exc
    except AssemblyIntegrityError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' was not found.")
    return result


@app.post("/workflows/{workflow_id}/intake/evaluate")
def evaluate_intake(workflow_id: str, request: IntakeRequest) -> ExecutionResult:
    try:
        result = execution_service.build(
            workflow_id, request.answers, request.risk_ids,
        )
    except IntakeResolutionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "candidate_intake_ids": exc.candidate_ids,
            },
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' was not found.",
        )
    return result


@app.post("/workflows/{workflow_id}/response/generate")
def generate_response(workflow_id: str, request: GenerationRequest) -> GenerationResult:
    # Reuse exactly the assembly endpoint's scope and integrity error behavior.
    package = assemble_response(workflow_id, request)
    if settings.mode == "production" and (not package["public_execution"]["allowed"] or request.generation.provider == "testing"):
        raise HTTPException(status_code=403, detail={"code": "public_workflow_unavailable"})
    return generation_service.generate(package, request.generation)


@app.get("/workflows")
def workflow_catalog(user_type: str | None = None):
    return {"workflows": WorkflowCatalogService(repository).catalog(user_type)}


@app.post("/routing/evaluate")
def route_matter(request: MatterRequest):
    return MatterRoutingService(repository).evaluate(request)


@app.post("/workflows/{workflow_id}/scope")
def resolve_scope(workflow_id: str, request: MatterRequest):
    if repository.get_workflow(workflow_id) is None:
        raise HTTPException(status_code=404, detail={"code": "workflow_not_found"})
    return MatterRoutingService(repository).scope(workflow_id, request)


@app.get("/model/status")
def model_status():
    return settings.status(generation_service.registry)


@app.post("/workflows/{workflow_id}/response")
def product_response(workflow_id: str, request: ProductResponseRequest):
    try:
        return ProductService(repository, settings, generation_service).respond(workflow_id, request)
    except (RepositoryLoadError, AssemblyIntegrityError):
        raise HTTPException(status_code=409, detail={"code": "source_integrity_unavailable", "message": "Source evidence is temporarily unavailable. No answer was generated."}) from None
    except IntakeResolutionError:
        raise HTTPException(status_code=409, detail={"code": "intake_unavailable", "message": "This workflow’s intake is unavailable. No answer was generated."}) from None
    except RetrievalFilterError:
        raise HTTPException(status_code=422, detail={"code": "source_filter_unavailable", "message": "The requested evidence is outside this workflow."}) from None


@app.get("/", response_class=HTMLResponse)
@app.get("/coverage", response_class=HTMLResponse)
def product_page():
    return (web_root / "index.html").read_text(encoding="utf-8")
