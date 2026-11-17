"""Deadline derivations over exact matter events and scoped procedural rule versions."""
from datetime import date

from app.action_models import FactRequirement
from app.action_readiness import active_choice, assertion_ref, fact_result, select_event
from app.deadline_counting import CountingMethod, count_days
from app.matter_models import Target, Temporal
from app.procedural_research import is_dated, requirement_evidence

SERVICE_CONDITIONS = {
    "document_type": "summons_and_complaint",
    "service_mode": "ordinary_service",
    "extension_status": "none_confirmed",
    "local_rules_checked": True,
}
UNRESOLVED_MESSAGES = {
    "jurisdiction_unresolved_or_mismatched": "Confirm the matter jurisdiction for this deadline rule.",
    "multiple_candidate_triggers": "More than one recorded event may trigger the rule. The applicable event needs review.",
    "missing_trigger": "Record the event that would trigger this deadline.",
    "conflicting_trigger": "The deadline remains unresolved because the recorded trigger accounts conflict.",
    "exact_documented_trigger_required": "Confirm an exact date using supporting documentation for this event.",
    "accrual_and_exceptions_require_review": "Review the date the claim accrued, the applicable rule version and any exceptions.",
    "confirm_matching_path_and_forum": "Confirm the matching procedural path and court for this matter revision.",
    "historical_rule_applicability_unresolved": "The retained authority does not confirm which rule applied on the event date.",
    "verify_trigger_conditions_and_case_orders": "Review what was served, how it was served, and applicable orders and extensions.",
    "reviewed_court_calendar_unavailable": "A reviewed calendar for this court is required to verify the last day.",
    "court_calendar_coverage_incomplete": "The reviewed calendar does not establish the applicable last day.",
}


def unresolved(payload, reason, **updates):
    return payload | updates | {"reason": reason, "explanation": UNRESOLVED_MESSAGES[reason]}


def active_reports(matter, field, event_id):
    # The procedural projection suppresses unscoped reports when a scoped row
    # exists. They cannot prove an event, but a competing account needs review.
    inactive = {row.previous for row in matter.corrections}
    return tuple(row for row in matter.assertions if row.target.field == field
                 and row.target.subject in {event_id, None} and row.id not in inactive
                 and row.status in {"asserted", "documented", "externally_verified"})


def evaluate_deadline(catalog, matter, policy, event_id, fields, authority_settings=None):
    event = select_event(matter, policy.event_kind, event_id)
    evidence = {item.id: item for item in matter.evidence}
    choice = active_choice(matter, catalog, policy.path, policy.forum)
    calendar = catalog.calendars.get(policy.forum)
    scope = fields.get(Target(field="jurisdiction"), {}).get("preferred")
    payload = {
        "rule": policy, "choice_message_id": choice.message.message_id if choice else None,
        "event_id": event.id if event else None, "event_origin": event.origin if event else None,
        "trigger_date": None, "calculated_date": None, "status": "unresolved", "reason": None,
        "authority": (), "rule_parameters": None, "trigger_sources": (), "conditions": {},
        "calendar": None, "calculation_steps": (), "exceptions_applied": (), "assumptions": (),
        "rule_summary": policy.message,
    }
    params = None
    if policy.procedure_ref:
        requirement = catalog.procedure.requirements[policy.procedure_ref]
        params = requirement.deadline
        refs = requirement_evidence(requirement)
        payload["authority"] = tuple(catalog.authority(ref.authority) for ref in refs)
        payload["rule_parameters"] = params
    else:
        theory = catalog.claims.active[policy.theory_ref]
        bindings, _, limits = catalog.claims.research(theory, authority_settings, None)
        payload["authority"] = tuple({ref["passage_id"]: ref for rows in bindings.values() for ref in rows}.values())
        payload["assumptions"] = limits

    if scope is None or scope.value != policy.jurisdiction:
        return unresolved(payload, "jurisdiction_unresolved_or_mismatched")
    if sum(row.kind == policy.event_kind for row in matter.events) > 1 and (not event or policy.procedure_ref):
        return unresolved(payload, "multiple_candidate_triggers")
    if not event:
        return unresolved(payload, "missing_trigger")
    date_rule = FactRequirement(scope="event", field="date", exact_date=True,
                                sources=("documented",) if params else ("asserted", "documented", "externally_verified"),
                                evidence_kinds=policy.trigger_evidence)
    status, support = fact_result(matter, fields, evidence, date_rule, event, None, None, ())
    disputed = {item.assertion for item in matter.disputes}
    if params and params.trigger == "service_of_summons_and_complaint":
        reported = active_reports(matter, "service_date", event.id)
        reported_days = {row.value.start for row in reported if isinstance(row.value, Temporal)
                         and row.value.precision == "exact" and type(row.value.start) is date}
        if (len(reported_days) > 1 or any(row.id in disputed for row in reported)
                or status == "satisfied" and reported_days - {support["value"]}):
            return unresolved(payload, "conflicting_trigger",
                              trigger_sources=tuple(assertion_ref(row, evidence) for row in reported))
    if status != "satisfied":
        reason = "conflicting_trigger" if status == "conflicting" else "exact_documented_trigger_required"
        return unresolved(payload, reason, trigger_sources=support)
    trigger = support["value"]
    payload.update(trigger_date=trigger, trigger_sources=support["sources"])
    if not params:
        return unresolved(payload, "accrual_and_exceptions_require_review")
    if not choice or choice.jurisdiction != policy.jurisdiction:
        return unresolved(payload, "confirm_matching_path_and_forum")
    if not all(is_dated(catalog.procedure.authorities[ref.authority], trigger) and
               (not catalog.procedure.authorities[ref.authority].version.effective_from
                or catalog.procedure.authorities[ref.authority].version.effective_from <= trigger) for ref in refs):
        return unresolved(payload, "historical_rule_applicability_unresolved")
    conditions = {}
    proof_id = support["selected"]["evidence_id"]
    if params.trigger == "service_of_summons_and_complaint":
        for field, value in SERVICE_CONDITIONS.items():
            expected = fields.get(Target(field=field, subject=event.id), {})
            row = expected.get("preferred")
            other_accounts = active_reports(matter, field, event.id)
            if (not row or type(row.value) is not type(value) or row.value != value
                    or any(other.id in disputed or other.value != value for other in other_accounts)
                    or field in {"document_type", "service_mode"} and
                    getattr(row.source, "evidence_id", None) != proof_id
                    or field in {"extension_status", "local_rules_checked"} and row.status != "asserted"):
                return unresolved(payload, "verify_trigger_conditions_and_case_orders", conditions=conditions)
            conditions[field] = assertion_ref(row, evidence)
        payload["assumptions"] = ("The service record is user supplied.", "Case orders and extensions are based on the user's recorded confirmation.")
    payload["conditions"] = conditions
    if calendar is None:
        return unresolved(payload, "reviewed_court_calendar_unavailable")
    open_days = {day: record.state == "open" for day, record in calendar.days.items()}
    dates = count_days(CountingMethod(params.period, params.unit, False, "next_open"), trigger, open_days)
    if dates is None:
        return unresolved(payload, "court_calendar_coverage_incomplete")
    nominal, deadline = dates.nominal, dates.due
    adjustments = [
        {"date": day, "state": "weekend" if day.weekday() >= 5 else calendar.days[day].state,
         "source": "Gregorian weekday" if day.weekday() >= 5 else calendar.days[day].source}
        for day, _ in dates.calendar
    ]
    return payload | {
        "status": "verified", "calculated_date": deadline, "authority_review_date": trigger,
        "calendar": {"id": calendar.id, "version": calendar.version, "forum": calendar.forum,
                     "reviewed_by": calendar.reviewed_by, "days_consulted": adjustments},
        "calculation_steps": [
            {"operation": params.counting, "start": trigger, "duration": params.period, "unit": params.unit, "result": nominal},
            {"operation": params.last_day, "start": nominal, "result": deadline},
        ],
        "exceptions_applied": [row for row in adjustments if row["date"] != deadline],
        "explanation": (
            f"The recorded service date is {trigger.isoformat()}. The retained rule allows {params.period} days "
            f"excluding that date. The nominal last day is {nominal.isoformat()}. The reviewed court calendar "
            f"places the last day on {deadline.isoformat()} under the retained counting provision."
        ),
    }
