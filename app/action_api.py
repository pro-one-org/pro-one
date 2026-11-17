"""Release-gated Legal Action OS commands under the existing matter bearer."""
from datetime import date
import os
from uuid import UUID

from fastapi import Request

from app.action_catalog import ActionCatalog
from app.action_models import (
    AssembleDocument, EvaluateAction, EvaluateDeadline, ReviewDocument, RevisionRequest,
)
from app.action_service import ActionService
from app.claim_catalog import ClaimCatalog
from app.matter_models import Digest
from app.matter_store import MatterStore
from app.procedural_authority import load_catalog


def install(routes, access, execute, repository):
    def run(request, matter_id, operation):
        config, path, _ = access(request, matter_id)

        def apply():
            calendars = ActionService.load_calendars(os.environ.get("PRO_ONE_ACTION_CALENDARS"))
            catalog = ActionCatalog(load_catalog(), ClaimCatalog(repository), calendars=calendars)
            action = ActionService(MatterStore(path), repository, config, catalog)
            return operation(action)

        return execute(apply)

    @routes.get("/{matter_id}/actions")
    def actions(request: Request, matter_id: UUID):
        return run(request, matter_id, lambda action: action.list_actions(matter_id))

    @routes.post("/{matter_id}/readiness", status_code=201)
    def evaluate(request: Request, matter_id: UUID, body: EvaluateAction):
        return run(request, matter_id, lambda action: action.readiness(matter_id, body))

    @routes.get("/{matter_id}/readiness/{artifact_id}")
    def readiness(request: Request, matter_id: UUID, artifact_id: Digest):
        return run(request, matter_id, lambda action: action.artifact(matter_id, "readiness", artifact_id))

    @routes.get("/{matter_id}/deadlines")
    def deadlines(request: Request, matter_id: UUID):
        return run(request, matter_id, lambda action: action.deadlines(matter_id))

    @routes.post("/{matter_id}/deadlines/evaluate", status_code=201)
    def deadline(request: Request, matter_id: UUID, body: EvaluateDeadline):
        return run(request, matter_id, lambda action: action.deadline(matter_id, body))

    @routes.get("/{matter_id}/deadlines/{artifact_id}")
    def read_deadline(request: Request, matter_id: UUID, artifact_id: Digest):
        return run(request, matter_id, lambda action: action.artifact(matter_id, "deadline", artifact_id))

    # POST /documents is already the evidence upload route.
    @routes.post("/{matter_id}/action-documents", status_code=201)
    def documents(request: Request, matter_id: UUID, body: AssembleDocument):
        return run(request, matter_id, lambda action: action.documents(matter_id, body))

    @routes.get("/{matter_id}/action-documents/{artifact_id}")
    def document(request: Request, matter_id: UUID, artifact_id: Digest):
        return run(request, matter_id, lambda action: action.artifact(matter_id, "document", artifact_id))

    @routes.post("/{matter_id}/reviews", status_code=201)
    def review(request: Request, matter_id: UUID, body: ReviewDocument):
        return run(request, matter_id, lambda action: action.review(matter_id, body))

    @routes.get("/{matter_id}/reviews/{artifact_id}")
    def read_review(request: Request, matter_id: UUID, artifact_id: Digest):
        return run(request, matter_id, lambda action: action.artifact(matter_id, "review", artifact_id))

    @routes.get("/{matter_id}/workspace")
    def workspace(request: Request, matter_id: UUID, as_of: date | None = None):
        return run(request, matter_id, lambda action: action.workspace(matter_id, as_of))

    @routes.post("/{matter_id}/workspace", status_code=201)
    def save_workspace(request: Request, matter_id: UUID, body: RevisionRequest, as_of: date | None = None):
        return run(request, matter_id, lambda action: action.workspace(matter_id, as_of, body.revision))

    @routes.get("/{matter_id}/workspace/{artifact_id}")
    def read_workspace(request: Request, matter_id: UUID, artifact_id: Digest):
        return run(request, matter_id, lambda action: action.artifact(matter_id, "workspace", artifact_id))

    @routes.get("/{matter_id}/tasks")
    def tasks(request: Request, matter_id: UUID, as_of: date | None = None):
        return run(request, matter_id, lambda action: action.workspace(matter_id, as_of)["tasks"])

    @routes.get("/{matter_id}/tasks/{task_id}")
    def task(request: Request, matter_id: UUID, task_id: Digest, as_of: date | None = None):
        return run(request, matter_id, lambda action: action.task(matter_id, task_id, as_of))
