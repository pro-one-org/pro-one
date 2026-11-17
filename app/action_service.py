"""Orchestrate scoped preparation, dependency checks, and exact review."""
from pathlib import Path
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import TypeAdapter

from app.action_catalog import ActionCatalog
from app.action_deadlines import evaluate_deadline
from app.action_documents import assemble
from app.action_models import CourtCalendar
from app.action_readiness import evaluate_readiness, select_event
from app.action_store import ActionStore
from app.action_workspace import project
from app.claim_catalog import fingerprint
from app.claim_service import ClaimService
from app.claim_store import ClaimStore
from app.matter_models import Target
from app.matter_state import MatterError, projection
from app.matter_store import MatterNotFound, RevisionConflict, now
from app.procedural_authority import load_catalog


OPERATIONAL_KINDS = ("readiness", "deadline", "document", "review")
ENGINE_VERSION = "1.0.0"


class ActionService:
    def __init__(self, ledger, repository, settings=None, catalog=None):
        self.ledger = ledger
        self.settings = settings
        self.claims = ClaimService(repository, settings)
        self.catalog = catalog or ActionCatalog(load_catalog(), self.claims.catalog)
        self.store = ActionStore(ledger)
        self.claim_store = ClaimStore(ledger)
        self.dependencies = self.catalog.fingerprints | {
            "engine_version": ENGINE_VERSION,
            "claim_catalog": fingerprint([theory.model_dump(mode="json")
                                          for theory in self.catalog.claims.active.values()]),
        }

    @staticmethod
    def load_calendars(path):
        if not path:
            return ()
        with Path(path).open("rb") as file:
            raw = file.read(262145)
        if len(raw) > 262144:
            raise MatterError("court_calendar_size_limit")
        return TypeAdapter(tuple[CourtCalendar, ...]).validate_json(raw)

    def read(self, matter_id, revision):
        matter = self.ledger.get(matter_id)
        if matter.revision != revision:
            raise RevisionConflict("revision_conflict")
        return matter

    def definitions(self, fields):
        scope = fields.get(Target(field="jurisdiction"), {}).get("preferred")
        return [row for row in self.catalog.actions.values() if scope and row.jurisdiction == scope.value]

    def list_actions(self, matter_id):
        matter = self.ledger.get(matter_id)
        fields = projection(matter)
        scope = fields.get(Target(field="jurisdiction"), {}).get("preferred")
        return {"matter_revision": matter.revision, "actions": self.definitions(fields),
                "deadline_rules": [row for row in self.catalog.deadlines.values()
                                   if scope and row.jurisdiction == scope.value], "external_execution": "disabled"}

    def deadline(self, matter_id, request):
        matter = self.read(matter_id, request.revision)
        rule = self.catalog.deadlines.get(request.rule_id)
        if not rule:
            raise MatterError("unsupported_deadline_rule")
        return self.store.save(matter, self.derive_deadline(matter, rule, request.event_id, projection(matter)))[0]

    def derive_deadline(self, matter, rule, event_id, fields):
        result = evaluate_deadline(self.catalog, matter, rule, event_id, fields, self.settings)
        return self.store.prepare(matter, "deadline", self.dependencies, result)

    def readiness(self, matter_id, request):
        matter = self.read(matter_id, request.revision)
        action = self.catalog.actions.get(request.action_id)
        if not action:
            raise MatterError("unsupported_action")
        fields = projection(matter)
        event = select_event(matter, action.event_kind, request.event_id)
        claim = self.claim_store.get(matter_id, request.claim_analysis_id, self.claims) if request.claim_analysis_id else None
        deadlines = {}
        for key in action.deadline_rules:
            rule = self.catalog.deadlines[key]
            event_id = event.id if event and event.kind == rule.event_kind else None
            deadlines[key] = self.derive_deadline(matter, rule, event_id, fields)
        result = evaluate_readiness(self.catalog, matter, action, request, claim, deadlines, fields)
        artifact = self.store.prepare(matter, "readiness", self.dependencies, result)
        return self.store.save(matter, *deadlines.values(), artifact)[-1]

    def freshness(self, matter, item, claims, records):
        reasons = []
        if item["matter_revision"] != matter.revision:
            reasons.append("matter_revision_changed")
        reasons.extend(key + "_changed" for key in self.dependencies
                       if item["dependencies"].get(key) != self.dependencies[key])
        if not reasons:
            if item["kind"] == "readiness" and item["claim_analysis_id"] and item["claim_status"] == "satisfied":
                key = item["claim_analysis_id"]
                if key not in claims:
                    claims[key] = self.claim_store.get(matter.id, key, self.claims)
                if claims[key]["freshness"] != "latest_snapshot":
                    reasons.append("claim_analysis_changed")
            for kind, identity in self.references(item):
                dependency = records.get(identity)
                if dependency is None:
                    dependency = self.freshness(matter, self.store.record(matter.id, kind, identity), claims, records)
                    records[identity] = dependency
                if dependency["freshness"] != "current":
                    reasons.append(kind + "_dependency_changed")
            if item["kind"] == "deadline" and item["rule"]["theory_ref"]:
                rule = self.catalog.deadlines[item["rule"]["id"]]
                event_id = UUID(item["event_id"]) if item["event_id"] else None
                current = self.derive_deadline(matter, rule, event_id, projection(matter))
                if current["artifact_id"] != item["artifact_id"]:
                    reasons.append("deadline_authority_changed")
        return item | {"freshness": "stale" if reasons else "current", "stale_reasons": sorted(set(reasons)),
                       "latest_matter_revision": matter.revision}

    @staticmethod
    def references(item):
        match item["kind"]:
            case "readiness":
                return tuple(("deadline", key) for key in item["deadline_ids"])
            case "document":
                return (("readiness", item["readiness_id"]),)
            case "review":
                return (("document", item["package_id"]),)
            case "workspace":
                return tuple((row["kind"], row["artifact_id"]) for row in item["inputs"])
        return ()

    def artifact(self, matter_id, kind, identity):
        matter = self.ledger.get(matter_id)
        result = self.freshness(matter, self.store.record(matter_id, kind, identity), {}, {})
        if kind == "workspace" and result["freshness"] == "current":
            ids = {row["artifact_id"] for row in self.store.current(matter, OPERATIONAL_KINDS)}
            if ids != set(result["observed_artifact_ids"]):
                result |= {"freshness": "stale", "stale_reasons": ["workspace_inputs_changed"]}
        if kind == "document" and result["freshness"] == "current":
            review = next((row for row in self.store.current(matter, ("review",))
                           if row["package_id"] == identity and row["dependencies"] == self.dependencies), None)
            result["current_review_id"] = review["artifact_id"] if review else None
        return result

    @staticmethod
    def require_current(item):
        if item["freshness"] != "current":
            raise RevisionConflict("action_dependency_stale")
        return item

    def documents(self, matter_id, request):
        matter = self.read(matter_id, request.revision)
        records = {}
        readiness = self.require_current(self.freshness(
            matter, self.store.record(matter_id, "readiness", request.readiness_id), {}, records
        ))
        deadlines = [records[key] for key in readiness["deadline_ids"]]
        result = assemble(self.catalog, matter, readiness, deadlines)
        return self.store.save(matter, self.store.prepare(matter, "document", self.dependencies, result))[0]

    def review(self, matter_id, request):
        matter = self.read(matter_id, request.revision)
        document = self.require_current(self.freshness(
            matter, self.store.record(matter_id, "document", request.package_id), {}, {}
        ))
        if document["status"] != "ready_for_user_review":
            raise MatterError("document_not_reviewable")
        if document["displayed_digest"] != request.displayed_digest:
            raise RevisionConflict("review_digest_mismatch")
        scope = {key: document[key] for key in ("action_id", "readiness_id", "displayed_digest", "destination",
                                               "fees", "service", "service_contact", "deadline_context")}
        result = {"package_id": request.package_id, "status": "reviewed", "review_scope": scope,
                  "displayed_to_user_attested": request.reviewed, "execution_authorization": "absent",
                  "external_execution": "disabled"}
        artifact = self.store.prepare(matter, "review", self.dependencies, result, actor="matter_bearer_user")
        return self.store.save(matter, artifact)[0]

    def deadlines(self, matter_id):
        matter = self.ledger.get(matter_id)
        return {"matter_revision": matter.revision, "deadlines": [
            self.freshness(matter, row, {}, {}) for row in self.store.current(matter, ("deadline",))
        ]}

    def workspace(self, matter_id, as_of=None, revision=None):
        matter = self.ledger.get(matter_id) if revision is None else self.read(matter_id, revision)
        fields = projection(matter)
        as_of = as_of or now().date()
        claims, records = {}, {}
        rows = self.store.current(matter, OPERATIONAL_KINDS)
        projected = []
        for row in rows:
            identity = row["artifact_id"]
            if identity not in records:
                records[identity] = self.freshness(matter, row, claims, records)
            projected.append(records[identity])
        result = jsonable_encoder(project(matter, fields, projected, claims, self.definitions(fields), as_of))
        if revision is None:
            return {"matter_id": matter_id, "matter_revision": matter.revision, **result}
        result["inputs"] = [{"kind": row["kind"], "artifact_id": row["artifact_id"]}
                            for row in projected if row["freshness"] == "current"]
        result["observed_artifact_ids"] = [row["artifact_id"] for row in projected]
        artifact = self.store.prepare(matter, "workspace", self.dependencies, result)
        return self.store.save(matter, artifact)[0]

    def task(self, matter_id, task_id, as_of=None):
        workspace = self.workspace(matter_id, as_of)
        task = next((row for row in workspace["tasks"] if row["id"] == task_id), None)
        if task is None:
            raise MatterNotFound("action_task_not_found")
        return task
