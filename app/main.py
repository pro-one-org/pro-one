from fastapi import FastAPI, HTTPException

from app.execution import ExecutionContextService, ExecutionResult
from app.intake import IntakeRequest, IntakeResolutionError
from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository, RepositoryLoadError


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
