from fastapi import FastAPI, HTTPException

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
