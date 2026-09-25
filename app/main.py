from fastapi import FastAPI, HTTPException

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
