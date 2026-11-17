"""Readiness coordinates existing state under explicit, versioned preparation requirements."""
from datetime import date
from types import SimpleNamespace
from typing import get_args
import re

from app.action_models import Dimension
from app.claim_mapping import CONFLICT, fact_view
from app.matter_ingest import INSTRUCTIONS
from app.matter_models import Target, Temporal
from app.matter_state import MatterError, equivalent, norm
from app.procedural_research import is_dated

SOURCE_ORDER = {"asserted": 0, "documented": 1, "externally_verified": 2}
UNSAFE_OBSERVATION = re.compile(
    r"[\r\n<>\[\]{};:]|(?:\b(?:file|send|sign|pay|submit|serve)\s+(?:it|now|immediately)\b)"
    r"|\$|§|\b(?:plaintiff|defendant) (?:alleges|demands|is liable)\b", re.I,
)


def active_choice(matter, catalog, path, forum, stage=None):
    if not matter.choices:
        return None
    choice = matter.choices[-1]
    stages = catalog.procedure.paths[path].stages
    prior_stage = choice.stage in stages and stage in stages[choice.stage].transitions
    if ((choice.path, choice.forum, choice.based_on_revision + 1, choice.catalog_version)
            != (path, forum, matter.revision, catalog.procedure.record_version)
            or stage and choice.stage != stage and not prior_stage):
        return None
    return choice


def assertion_ref(assertion, evidence):
    item = evidence.get(getattr(assertion.source, "evidence_id", None))
    return {
        "assertion_id": assertion.id, "target": assertion.target, "status": assertion.status,
        "source_kind": assertion.source.kind, "message_id": getattr(assertion.source, "message_id", None),
        "evidence_id": item.id if item else None, "evidence_kind": item.kind if item else None,
        "content_hash": item.content_hash if item else None,
        "locator": assertion.locator or getattr(assertion.source, "excerpt", None),
        "page": getattr(assertion.source, "page", None),
    }


def select_event(matter, kind, identity):
    matches = tuple(row for row in matter.events if row.kind == kind)
    if identity and not any(row.id == identity for row in matches):
        raise MatterError("action_event_outside_scope")
    if identity:
        return next(row for row in matches if row.id == identity)
    return matches[0] if len(matches) == 1 else None


def allowed_value(rule, value):
    if rule.allowed_text and (not isinstance(value, str) or norm(value) not in map(norm, rule.allowed_text)):
        return False
    if rule.exact_date:
        return isinstance(value, Temporal) and value.precision == "exact" and type(value.start) is date
    if rule.minimum is not None:
        return type(value) is int and value >= rule.minimum
    if rule.equals is not None:
        if isinstance(rule.equals, str) and isinstance(value, str):
            return norm(rule.equals) == norm(value)
        return type(rule.equals) is type(value) and rule.equals == value
    if rule.format:
        if not isinstance(value, str) or INSTRUCTIONS.search(value):
            return False
        if rule.format == "name":
            return (value[0].isalpha() and 2 <= len(value) <= 120
                    and all(char.isalnum() or char in " .,'’&-()" for char in value)
                    and not UNSAFE_OBSERVATION.search(value))
        return not UNSAFE_OBSERVATION.search(value)
    return True


def fact_result(matter, fields, evidence, rule, event, party, user, theories):
    subject = {"matter": None, "event": event.id if event else None, "party": party, "user": user}[rule.scope]
    if rule.scope != "matter" and subject is None:
        return "unknown", ()
    target = Target(field=rule.field, subject=subject)
    selected = fields.get(target, {})
    preferred = selected.get("preferred")
    if rule.scope == "event" and event.kind == "incident":
        _, rows, state = fact_view(matter, fields, SimpleNamespace(field=rule.field, scope="event"), event, None)
        preferred = preferred or max((row for row in rows if row.status in SOURCE_ORDER),
                                     key=lambda row: SOURCE_ORDER[row.status], default=None)
    else:
        active = set(selected.get("assertions", ()))
        rows = tuple(row for row in matter.assertions if row.id in active)
        state = selected.get("status", "unknown")
    refs = tuple(assertion_ref(row, evidence) for row in rows)
    if state in CONFLICT:
        return "conflicting", refs
    if not preferred:
        return ("unknown" if not refs else "unsupported"), refs
    item = evidence.get(getattr(preferred.source, "evidence_id", None))
    if (preferred.status not in rule.sources or not allowed_value(rule, preferred.value)
            or rule.evidence_kinds and (not item or item.kind not in rule.evidence_kinds)):
        return "unsupported", refs
    if rule.claim_element:
        mappings = [row["mapping"] for theory in theories for element in theory["elements"]
                    if element["id"] == rule.claim_element for row in element.get("evidence", ())]
        if not any(row["assertion_id"] == str(preferred.id) and row["relationship"] == rule.claim_relation
                   for row in mappings):
            return "requires_review", refs
    value = preferred.value.start if rule.exact_date else preferred.value
    source = assertion_ref(preferred, evidence)
    return "satisfied", {"value": value, "selected": source, "sources": refs}


def evaluate_readiness(catalog, matter, action, request, claim, deadlines, fields):
    event = select_event(matter, action.event_kind, request.event_id)
    parties = {row.id: row for row in matter.parties}
    party, user = request.party_id, request.user_party_id
    if party and (party not in parties or parties[party].role not in action.allowed_party_roles
                  or action.event_kind and (not event or party not in event.participants)):
        raise MatterError("action_party_outside_scope")
    if user and (user not in parties or parties[user].role != "user"):
        raise MatterError("action_user_party_outside_scope")
    evidence = {row.id: row for row in matter.evidence}
    choice = active_choice(matter, catalog, action.path, action.forum, action.stage)
    jurisdiction = fields.get(Target(field="jurisdiction"), {}).get("preferred")
    if choice and (choice.jurisdiction != action.jurisdiction
                   or not jurisdiction or jurisdiction.value != action.jurisdiction):
        choice = None
    claim_status = "unknown"
    theories = ()
    if claim:
        selected = tuple(row for row in claim["theories"] if row["id"] in action.theories)
        claim_status = (
            "stale" if claim["freshness"] == "stale" else
            "unsupported" if (claim["jurisdiction"] != action.jurisdiction
                              or claim["event_id"] != (str(event.id) if event else None)
                              or claim["party_id"] != (str(party) if party else None)
                              or claim["status"] != "analysis_available"
                              or {row["id"] for row in selected} != set(action.theories)
                              or any(row["kind"] != "claim" or row["status"] == "authority_unresolved" for row in selected))
            else "satisfied"
        )
        if claim_status == "satisfied":
            theories = selected
    law_refs = tuple(dict.fromkeys(
        ref["passage_id"] for theory in theories for element in theory["elements"] for ref in element["authority"]
    ))
    rows = []
    values = {}
    statuses = {}
    for req in action.requirements:
        result, support = "requires_review", ()
        match req.check:
            case "fact":
                result, support = fact_result(matter, fields, evidence, req.fact, event, party, user, theories)
                if result == "satisfied" and req.fact.same_as:
                    other = values.get(req.fact.same_as)
                    if other is None:
                        result, support = "requires_review", support["sources"]
                    elif not equivalent(support["value"], other["value"]):
                        result, support = "conflicting", support["sources"] + other["sources"]
                if result == "satisfied":
                    values[req.id] = support
                    support = support["sources"]
            case "choice":
                result, support = ("satisfied", (choice.message.message_id,)) if choice else ("unknown", ())
            case "claim":
                result, support = claim_status, law_refs
            case "claim_currentness":
                result, support = "requires_review", law_refs
                # Currentness for a requested historical date does not certify applicability to the draft.
                if (theories and choice and claim["law_as_of"] == choice.reference_date.isoformat()
                        and all(row["status"] == "dated_analysis" for row in theories)):
                    result = "satisfied"
            case "procedure_currentness":
                on = choice.reference_date if choice else None
                refs = catalog.procedure_evidence(req.refs)
                support = tuple(refs.values())
                if on and all(is_dated(catalog.procedure.authorities[key], on) for key in refs):
                    result = "satisfied"
            case "deadline":
                support = tuple(deadlines[key]["artifact_id"] for key in req.refs if key in deadlines)
                if req.refs and all(deadlines.get(key, {}).get("status") == "verified" for key in req.refs):
                    result = "satisfied"
            case "assess_remedies":
                result = "requires_review"
            case "future_authorization":
                result = "blocked"
        statuses.setdefault(req.dimension, []).append(result)
        rows.append({"id": req.id, "dimension": req.dimension, "classification": req.severity, "status": result,
                     "message": req.message, "requirement_provenance": {"origin": req.origin, "references": req.refs},
                     "observed_provenance": support})
    blockers = [row for row in rows if row["classification"] == "blocking_requirement" and row["status"] != "satisfied"]
    issues = [row for row in rows if row["classification"] not in {"blocking_requirement", "informational_gap"}
              and row["status"] != "satisfied"]
    status_order = ("blocked", "conflicting", "stale", "unsupported", "unknown", "requires_review", "partially_satisfied")
    dimensions = {name: (next((status for status in status_order if status in statuses[name]), "satisfied")
                         if name in statuses else "not_applicable") for name in get_args(Dimension)}
    overall = ("blocked" if blockers else "conditionally_ready" if any(
        row["classification"] == "warning" for row in issues
    ) else "ready_for_document_preparation")
    # Review requirements remain prominent on a reference draft. The explicit
    # blocking requirements are the preparation contract.
    forum = catalog.procedure.forums.get(action.forum)
    return {
        "action": action, "choice": choice, "forum": forum, "event_id": event.id if event else None,
        "party_id": party, "user_party_id": user, "claim_analysis_id": request.claim_analysis_id,
        "claim_status": claim_status, "theory_refs": [
            {"id": row["id"], "version": row["version"], "label": row["label"], "status": row["status"],
             "authority": tuple(ref for element in row["elements"] for ref in element["authority"]),
             "adverse_or_conflicting_assertions": sorted({
                 item["mapping"]["assertion_id"] for element in row["elements"] for item in element.get("evidence", ())
                 if item["mapping"]["relationship"] in {"adverse", "conflicting"}
             })}
            for row in theories
        ],
        "status": overall, "dimensions": dimensions, "requirements": rows, "blockers": blockers,
        "warnings": issues, "next_steps": [row["message"] for row in blockers or issues],
        "resolved_fields": values, "deadline_ids": tuple(row["artifact_id"] for row in deadlines.values()),
        "external_execution": "disabled",
    }
