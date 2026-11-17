"""A deterministic operational view over the scoped matter and its artifact history."""
from datetime import date, timedelta

from app.action_readiness import assertion_ref
from app.claim_catalog import fingerprint
from app.matter_models import Target, Temporal
from app.matter_state import questions


def tasks_for(matter, readiness, documents, deadlines, reviews, applicable_actions, as_of):
    tasks = []
    reviewed = {row["package_id"] for row in reviews}

    def add(key, title, description, priority, source, **links):
        identity = fingerprint([str(matter.id), matter.revision, key]).split(":", 1)[1]
        tasks.append({"id": identity, "matter_id": matter.id, "matter_revision": matter.revision,
                      "title": title, "description": description, "reason": source, "status": "open",
                      "priority": priority, **links})

    for row in deadlines:
        if row["status"] == "verified":
            due = date.fromisoformat(row["calculated_date"])
            if as_of <= due <= as_of + timedelta(days=min(14, (date.max - as_of).days)):
                add(["approaching_deadline", row["artifact_id"]], "Review the approaching verified deadline",
                    row["explanation"], "high", "verified_deadline", related_deadline=row["artifact_id"], due_date=due)
        else:
            add(["deadline", row["artifact_id"]], "Review the deadline inputs", row["explanation"],
                "normal", "unresolved_deadline", related_deadline=row["artifact_id"])

    for row in readiness:
        action = row["action"]["id"]
        for issue in row["blockers"]:
            add([row["artifact_id"], issue["id"]], issue["message"], issue["message"],
                "high", "readiness_requirement", related_action=action, related_party=row["party_id"],
                related_requirement=issue["id"], readiness_id=row["artifact_id"])
        for issue in row["warnings"]:
            if issue["dimension"] != "deadlines":
                add([row["artifact_id"], issue["id"]], issue["message"], issue["message"],
                    "normal", "readiness_review", related_action=action,
                    related_requirement=issue["id"], readiness_id=row["artifact_id"])
        package = next((doc for doc in reversed(documents) if doc["readiness_id"] == row["artifact_id"]), None)
        if row["status"] == "ready_for_document_preparation" and (not package or package["status"] != "ready_for_user_review"):
            add([row["artifact_id"], "prepare"], "Prepare the structured draft for review", row["action"]["label"],
                "normal", "readiness_evaluation", related_action=action, readiness_id=row["artifact_id"])
        if package and package["status"] == "ready_for_user_review" and package["artifact_id"] not in reviewed:
            add([package["artifact_id"], "review"], "Review the exact draft", package["document"]["title"],
                "normal", "document_review", related_action=action, related_document=package["artifact_id"])

    if not readiness and applicable_actions:
        add(["evaluate"], "Confirm a covered path and evaluate preparation requirements",
            "Use the selected path and the current matter revision.", "normal", "action_available")
    source_order = {"verified_deadline": 0, "readiness_requirement": 1, "document_review": 2,
                    "readiness_evaluation": 3, "unresolved_deadline": 4, "readiness_review": 5, "action_available": 6}
    return sorted(tasks, key=lambda row: (source_order[row["reason"]], str(row.get("due_date", "")), row["title"], row["id"]))


def project(matter, fields, artifacts, claims, applicable_actions, as_of):
    current = [row for row in artifacts if row["freshness"] == "current"]
    readiness, deadlines, documents, reviews = (
        [row for row in current if row["kind"] == kind] for kind in ("readiness", "deadline", "document", "review")
    )
    # Multiple evaluations of the same action/scope can use different claim reports.
    # Project the most recent evaluation while preserving the historical artifact.
    scopes = {}
    for row in readiness:
        scopes[(row["action"]["id"], row["event_id"], row["party_id"], row["user_party_id"])] = row
    readiness = list(scopes.values())
    used_reports = {row["artifact_id"] for row in readiness}
    documents = [row for row in documents if row["readiness_id"] in used_reports]
    used_documents = {row["artifact_id"] for row in documents}
    reviews = [row for row in reviews if row["package_id"] in used_documents]
    tasks = tasks_for(matter, readiness, documents, deadlines, reviews, applicable_actions, as_of)
    evidence = {row.id: row for row in matter.evidence}
    by_assertion = {row.id: row for row in matter.assertions}
    timeline = []
    for event in matter.events:
        fact = fields.get(Target(field="date", subject=event.id), {})
        row = fact.get("preferred")
        actual = row.value.start if row and isinstance(row.value, Temporal) and row.value.precision == "exact" else None
        refs = tuple(assertion_ref(by_assertion[key], evidence) for key in fact.get("assertions", ()))
        timeline.append({"kind": event.kind, "id": event.id, "occurrence": actual,
                         "status": fact.get("status", "unknown"), "sources": refs, "origin": event.origin,
                         "participants": event.participants, "evidence": event.evidence})
    for correction in matter.corrections:
        timeline.append({"kind": "user_correction", "id": correction.replacement, "occurrence": correction.received_at,
                         "previous": correction.previous, "message_id": correction.message.message_id})
    for row in matter.choices:
        timeline.append({"kind": "user_path_choice", "id": row.message.message_id, "occurrence": row.received_at,
                         "path": row.path, "forum": row.forum})
    for claim in claims.values():
        timeline.append({"kind": "claim_analysis", "id": claim["analysis_id"], "occurrence": claim["created_at"],
                         "freshness": claim["freshness"], "matter_revision": claim["matter_revision"]})
    for item in artifacts:
        timeline.append({"kind": item["kind"], "id": item["artifact_id"], "occurrence": item["created_at"],
                         "matter_revision": item["matter_revision"], "freshness": item["freshness"]})
        if item["kind"] == "deadline" and item["status"] == "verified" and item["freshness"] == "current":
            timeline.append({"kind": "calculated_deadline", "id": item["artifact_id"],
                             "occurrence": item["calculated_date"], "event_id": item["event_id"]})
    timeline.sort(key=lambda row: (str(row["occurrence"] or ""), row["kind"], str(row["id"])), reverse=True)

    choice = matter.choices[-1] if matter.choices else None
    choice_current = choice and choice.based_on_revision + 1 == matter.revision
    reviewed = {row["package_id"] for row in reviews}
    summary = [{key: row[key] for key in ("artifact_id", "action_id", "status", "displayed_digest")}
               | {"review_status": "reviewed" if row["artifact_id"] in reviewed else "unreviewed"} for row in documents]
    blockers = [{"readiness_id": row["artifact_id"], **blocker} for row in readiness for blocker in row["blockers"]]
    goal = fields.get(Target(field="goal"), {}).get("preferred")
    linked_claims = {row["claim_analysis_id"] for row in readiness if row["claim_status"] == "satisfied"}
    reviewable = {row["artifact_id"] for row in documents if row["status"] == "ready_for_user_review"}
    stage = ("draft_review_recorded" if reviewable and reviewable <= reviewed else "draft_review" if reviewable
             else "preparation" if readiness else "path_selected" if choice_current else "matter_intake")
    upcoming = sorted((row for row in deadlines if row["status"] == "verified"
                       and row["calculated_date"] >= as_of.isoformat()), key=lambda row: row["calculated_date"])
    return {
        "goal": {"value": goal.value, "source": assertion_ref(goal, evidence)} if goal else None,
        "selected_path": choice if choice_current else None, "path_confirmation_required": bool(choice and not choice_current),
        "stage": stage,
        "parties": matter.parties, "evidence": [
            row.model_dump(exclude={"extracted_text"}) for row in evidence.values()
        ],
        "claims_and_defenses": [
            {key: row.get(key) for key in ("id", "kind", "label", "version", "status")}
            | {"analysis_id": identity} for identity, report in claims.items() if identity in linked_claims
            for row in report["theories"]
        ],
        "readiness": [{key: row[key] for key in ("artifact_id", "action", "status", "dimensions")} for row in readiness],
        "deadlines": [{key: row[key] for key in ("artifact_id", "rule", "status", "calculated_date", "reason", "explanation")}
                      for row in deadlines],
        "upcoming_deadline_id": upcoming[0]["artifact_id"] if upcoming else None,
        "documents": summary, "tasks": tasks, "timeline": timeline, "blockers": blockers,
        "questions": list(questions(fields)),
        "claim_questions": [row | {"analysis_id": identity} for identity, report in claims.items()
                            if identity in linked_claims for row in report["questions"]],
        "next_actions": tasks[:8],
        "filings": [row | {"record_status": "historically_reported"} for row in timeline if row["kind"] == "filing"],
        "service_status": [row | {"record_status": "historically_reported"} for row in timeline if row["kind"] == "service"],
        "hearings": [row for row in timeline if row["kind"] in {"hearing", "court_event"}],
        "correspondence_evidence_ids": [row.id for row in evidence.values() if row.kind in {"message", "email"}],
        "as_of": as_of, "external_execution": "disabled",
    }
