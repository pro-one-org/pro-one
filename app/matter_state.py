"""Matter status, provenance checks and bounded downstream projections."""
from collections import defaultdict
from datetime import datetime

from app.matter_ingest import FACT_FIELDS, MONTH_DATE, MONTHS, grounded_rows
from app.matter_models import DocumentSource, ExternalSource, Gap, InferenceSource, Target, Temporal, UserSource
from app.procedural_research import FACT_QUESTIONS, MatterFacts

PARTY_FIELDS = {"brand", "legal_name", "registry_id", "entity_type", "alias", "operator", "property_owner",
                "registered_agent", "self_name"}
EVENT_FIELDS = {"date", "location", "street"}
OPTIONAL_EVENT_FIELDS = {"hazard", "warning_sign", "injury", "employee_notice", "hazard_duration",
                         "visit_purpose", "condition_visibility", "hazard_origin", "fall_mechanism",
                         "incident_locality", "service_date", "service_mode", "document_type",
                         "extension_status", "local_rules_checked"}
IDENTITY_FIELDS = {"legal_name", "operator", "property_owner", "registered_agent"}
IDENTITY_RELATIONSHIPS = {field: field for field in IDENTITY_FIELDS - {"property_owner"}} | {"property_owner": "owner"}
INDEPENDENT = {"alias", "allegation"}
SUPPORT_ORDER = {"asserted": 0, "documented": 1, "externally_verified": 2}
BASE_GAPS = {
    "jurisdiction": "In which jurisdiction did this happen?",
    "goal": "What outcome do you want?",
    "brand": "What name did the business or person use?",
    "date": "What date did the incident occur? Include the year if you know it.",
    "location": "Where did the incident take place?",
    "legal_name": "What legal name and registration identifier appear on a record for this party?",
    "operator": "What record identifies the operator of this location?",
    "property_owner": "What record identifies the owner of this location?",
    "registered_agent": "Do you have a registry entry identifying the registered agent?",
    "hazard": "Did you see any substance or condition on the floor?",
    "employee_notice": "Did anyone say what employees knew about the condition before the incident?",
    "incident_report": "Was an incident report made?",
    "surveillance": "Do you know if surveillance footage exists?",
    "injury": "What injury did you experience or have documented?",
    "medical_expenses": "What medical expenses do you have records for?",
    "lost_wages": "Have you lost wages because of the incident?",
}


class MatterError(ValueError):
    pass


def norm(value):
    return " ".join(value.casefold().replace("’", "'").split())


def equivalent(left, right):
    if isinstance(left, str) and isinstance(right, str):
        return norm(left) == norm(right)
    if isinstance(left, Temporal) and isinstance(right, Temporal):
        return (left.precision, left.start, left.end) == (right.precision, right.start, right.end) and (
            left.start is not None or norm(left.original) == norm(right.original))
    return type(left) is type(right) and left == right


def overlap(left, right):
    if equivalent(left, right):
        return True
    if not (isinstance(left, Temporal) and isinstance(right, Temporal)):
        return False
    if left.start is None and right.start is None:
        a, b = MONTH_DATE.fullmatch(left.original), MONTH_DATE.fullmatch(right.original)
        return not (a and b) or (a[1].casefold(), int(a[2])) == (b[1].casefold(), int(b[2]))
    if left.start is None or right.start is None:
        partial, dated = (left, right) if left.start is None else (right, left)
        parsed = MONTH_DATE.fullmatch(partial.original)
        if parsed and dated.end is None:
            return MONTHS[dated.start.month - 1].casefold() == parsed[1].casefold() and dated.start.day == int(parsed[2])
        return True
    if isinstance(left.start, datetime) != isinstance(right.start, datetime):
        return False
    return max(left.start, right.start) <= min(left.end or left.start, right.end or right.start)


def page_at(evidence, offset):
    return sum(start <= offset for start in evidence.page_offsets) or None


def source_status(source, evidence):
    if isinstance(source, UserSource):
        return "asserted"
    if isinstance(source, InferenceSource):
        return "inferred"
    if isinstance(source, ExternalSource):
        return "externally_verified"
    # Uploaded texts cannot prove liability, and a pleading is an allegation.
    return "alleged" if evidence.kind == "court_filing" else "documented"


def validate(matter):
    """Validate persisted graphs and source support, including locator boundaries."""
    messages = {row.id: row for row in matter.messages}
    evidence = {row.id: row for row in matter.evidence}
    assertions = {row.id: row for row in matter.assertions}
    parties = {row.id: row for row in matter.parties}
    events = {row.id: row for row in matter.events}
    ids = [row.id for rows in (matter.messages, matter.evidence, matter.assertions, matter.parties, matter.events) for row in rows]
    if len(set(ids)) != len(ids) or matter.created_at > matter.updated_at:
        raise MatterError("invalid_graph")
    sources = {}
    for row in matter.assertions:
        source = row.source
        if row.received_at > matter.updated_at or row.received_at < matter.created_at:
            raise MatterError("invalid_assertion_time")
        if row.target.field in PARTY_FIELDS and row.target.subject not in parties:
            raise MatterError("invalid_party_scope")
        if row.target.field in EVENT_FIELDS and row.target.subject not in events:
            raise MatterError("invalid_event_scope")
        if row.target.field in OPTIONAL_EVENT_FIELDS and row.target.subject is not None and row.target.subject not in events:
            raise MatterError("invalid_event_scope")
        if row.target.field not in PARTY_FIELDS | EVENT_FIELDS | OPTIONAL_EVENT_FIELDS and row.target.subject is not None:
            raise MatterError("invalid_fact_scope")
        item = None
        if isinstance(source, (UserSource, InferenceSource)):
            message = messages.get(source.message_id)
            if not message or message.received_at != row.received_at:
                raise MatterError("invalid_message_reference")
            text, locator = message.text, row.locator
            ref = source.message_id
        else:
            item = evidence.get(source.evidence_id)
            expected = "external_record" if isinstance(source, ExternalSource) else "user_upload"
            if not item or item.origin != expected or item.received_at != row.received_at:
                raise MatterError("invalid_evidence_reference")
            text, locator = item.extracted_text or "", source.excerpt
            ref = source.evidence_id
            if text[source.offset:source.offset + len(locator)] != locator or (
                isinstance(source, DocumentSource) and source.page != page_at(item, source.offset)
            ):
                raise MatterError("invalid_source_locator")
        if isinstance(source, ExternalSource) and row.target.field not in IDENTITY_FIELDS:
            raise MatterError("unsupported_external_fact")
        if row.status != source_status(source, item):
            raise MatterError("invalid_source_status")
        if row.status == "inferred":
            if row.target.field != "possible_legal_issue" or row.value not in ("premises_liability", "contract", "civil_procedure"):
                raise MatterError("unsupported_inference")
            continue
        if ref not in sources:
            sources[ref] = tuple(grounded_rows(text, source.kind, item.kind if item else None))
        if not any(field == row.target.field and value == row.value and quote == locator
                   and (item is None or offset == source.offset)
                   for field, value, quote, offset in sources[ref]):
            raise MatterError("unsupported_assertion")
    for row in matter.parties:
        origin = assertions.get(row.origin)
        if (not origin or origin.target.subject != row.id
                or origin.target.field not in {"brand", "legal_name", "self_name"}
                or origin.target.field == "self_name" and row.role != "user"):
            raise MatterError("invalid_party_origin")
    for row in matter.events:
        if row.origin not in messages and row.origin not in evidence:
            raise MatterError("invalid_event_origin")
        if not set(row.participants) <= parties.keys() or not set(row.evidence) <= evidence.keys():
            raise MatterError("invalid_event_reference")
    for row in matter.identities:
        assertion = assertions.get(row.assertion)
        field = next(field for field, relation in IDENTITY_RELATIONSHIPS.items() if relation == row.relationship)
        if row.party not in parties or not assertion or assertion.target != Target(field=field, subject=row.party):
            raise MatterError("invalid_identity_candidate")
        if row.corroborates:
            anchor = assertions.get(row.corroborates)
            item = evidence.get(assertion.source.evidence_id) if isinstance(assertion.source, ExternalSource) else None
            anchor_evidence = evidence.get(anchor.source.evidence_id) if anchor and isinstance(anchor.source, DocumentSource) else None
            origin = assertions[parties[row.party].origin]
            if (not item or not anchor or not anchor_evidence or anchor.status != "documented"
                    or anchor_evidence.content_hash != item.external.link_evidence_hash
                    or not equivalent(origin.value, item.external.subject_label)
                    or anchor.target != Target(field="registry_id", subject=row.party)
                    or anchor.value != f"{item.external.provider}/{item.external.record_id}" or anchor.received_at > assertion.received_at):
                raise MatterError("invalid_identity_link")
    superseded = set()
    order = {row.id: index for index, row in enumerate(matter.assertions)}
    for row in matter.corrections:
        old, new = assertions.get(row.previous), assertions.get(row.replacement)
        message = messages.get(row.message.message_id)
        if (not old or not new or old.target != new.target or old.id in superseded
                or order[old.id] >= order[new.id] or new.source != row.message
                or not message or message.received_at != row.received_at or new.received_at != row.received_at):
            raise MatterError("invalid_correction")
        superseded.add(old.id)
    for row in matter.disputes:
        message = messages.get(row.message.message_id)
        if not message or row.assertion not in assertions or message.received_at != row.received_at:
            raise MatterError("invalid_dispute")
    for row in matter.choices:
        message = messages.get(row.message.message_id)
        if not message or message.received_at != row.received_at or row.based_on_revision >= matter.revision:
            raise MatterError("invalid_choice")
    for gap in matter.gaps:
        index = parties if gap.target.field in PARTY_FIELDS else events if gap.target.field in EVENT_FIELDS | OPTIONAL_EVENT_FIELDS else {}
        if gap.target.subject is not None and gap.target.subject not in index:
            raise MatterError("invalid_gap_scope")
    return matter


def projection(matter):
    """Resolve active assertions per subject and field, with original assertions retained."""
    grouped = defaultdict(list)
    for row in matter.assertions:
        grouped[row.target].append(row)
    superseded = {row.previous for row in matter.corrections}
    confirmed = {row.replacement for row in matter.corrections}
    disputed = {row.assertion for row in matter.disputes}
    origins = {row.id: row.origin for row in matter.parties}
    linked = {row.assertion: row.corroborates for row in matter.identities
              if row.corroborates and origins[row.party] not in superseded | disputed}
    blocked_links = superseded | disputed
    for target, rows in grouped.items():
        if target.field == "registry_id":
            live = [row for row in rows if row.id not in superseded and row.status in SUPPORT_ORDER]
            if any(not equivalent(left.value, right.value) for left in live for right in live):
                blocked_links |= {row.id for row in live}
    result = {}
    gaps = {gap.target: gap for gap in matter.gaps}
    for party in matter.parties:
        for field in {"legal_name", "operator", "property_owner", "registered_agent"}:
            target = Target(field=field, subject=party.id)
            gaps[target] = Gap(target=target, status="unresolved", question=BASE_GAPS[field])
    for event in matter.events:
        if event.kind != "document_received":
            target = Target(field="date", subject=event.id)
            gaps[target] = Gap(target=target, status="unknown", question=
                                      "When did this event occur? Include the year if you know it.")
    scoped = {target.field for target in grouped.keys() | gaps.keys() if target.subject is not None}
    for target in sorted(grouped.keys() | gaps.keys(), key=lambda t: (str(t.subject or ""), t.field)):
        if target.subject is None and target.field in scoped:
            continue
        active = [row for row in grouped[target] if row.id not in superseded]
        support = [row for row in active if row.status in SUPPORT_ORDER]
        conflicts = [(a.id, b.id) for i, a in enumerate(support) for b in support[i + 1:] if not overlap(a.value, b.value)]
        preferred = None
        status = gaps[target].status if target in gaps else "unknown"
        if target.field not in INDEPENDENT and conflicts:
            status = "conflicting"
        elif any(row.id in disputed for row in active):
            status = "disputed"
        elif support:
            if target.field in IDENTITY_FIELDS:
                support = [row for row in support if row.id in linked and linked[row.id] not in blocked_links]
            if target.field == "defendant_identity":
                # Entity attribution never determines the legal defendant.
                support = []
            if support and target.field not in INDEPENDENT:
                best = max(support, key=lambda row: (
                    isinstance(row.value, Temporal) and row.value.precision == "exact",
                    row.id in confirmed, SUPPORT_ORDER[row.status], isinstance(row.value, Temporal) and row.value.start is not None))
                status = best.status
                if isinstance(best.value, Temporal) and best.value.start is None:
                    status = "unresolved"
                preferred = best
            else:
                status = "unresolved"
        elif active:
            status = active[0].status
        result[target] = {"status": status, "preferred": preferred,
                          "confirmed": bool(preferred and preferred.id in confirmed),
                          "assertions": tuple(row.id for row in active),
                          "superseded": tuple(row.id for row in grouped[target] if row.id in superseded),
                          "question_template": gaps[target].question if target in gaps else None,
                          "conflicts": tuple(conflicts) if target.field not in INDEPENDENT else ()}
    return result


def questions(fields):
    for target, fact in fields.items():
        status = fact["status"]
        if status in {"unknown", "unresolved", "disputed", "conflicting", "alleged"}:
            prompt = (f"Which account of {target.field.replace('_', ' ')} do you confirm?"
                      if status in {"disputed", "conflicting"} else
                      fact["question_template"] or BASE_GAPS.get(target.field) or FACT_QUESTIONS.get(target.field)
                      or f"What evidence supports {target.field.replace('_', ' ')}?")
            yield {"target": target, "reason": status, "question": prompt}


def snapshot(matter):
    fields = projection(matter)
    payload = matter.model_dump(mode="python", exclude={"evidence"})
    evidence_facts = defaultdict(list)
    for row in matter.assertions:
        if isinstance(row.source, (DocumentSource, ExternalSource)):
            evidence_facts[row.source.evidence_id].append(row.id)
    payload["evidence"] = [
        item.model_dump(exclude={"extracted_text"}) | {"assertions": evidence_facts[item.id]} for item in matter.evidence
    ]
    for event in payload["events"]:
        related = {row.source.evidence_id for row in matter.assertions if row.target.subject == event["id"]
                   and isinstance(row.source, (DocumentSource, ExternalSource))}
        event["evidence"] = tuple(sorted(set(event["evidence"]) | related))
    payload["facts"] = [{"target": target, **fact} for target, fact in fields.items()]
    payload["questions"] = list(questions(fields))
    payload["provenance_summary"] = {kind: sum(row.source.kind == kind for row in matter.assertions)
                                     for kind in ("user_statement", "document", "external_record", "model_inference")}
    payload["selected_path"] = matter.choices[-1] if matter.choices else None
    payload["path_review_required"] = bool(matter.choices and matter.choices[-1].based_on_revision + 1 != matter.revision)
    return payload


def procedural_facts(fields, parties=()):
    reports = {}
    for field in sorted(FACT_FIELDS | {"jurisdiction"}):
        fact = fields.get(Target(field=field), {})
        preferred = fact.get("preferred")
        value = preferred.value if preferred else None
        status = fact.get("status")
        if isinstance(value, Temporal):
            value = value.start if value.precision == "exact" and not isinstance(value.start, datetime) else None
        reports[field] = {
            "state": "known" if value is not None else "conflicting" if status in {"conflicting", "disputed"}
                     else "unsupported" if status in {"alleged", "inferred", "unresolved"} and fact.get("assertions") else "unknown",
            "value": value, "provenance": preferred.source if value is not None else None,
            "assertions": fact.get("assertions", ()),
        }
    designated = [p.id for p in parties if p.role == "potential_defendant"]
    if len(designated) == 1 and reports["defendant_identity"]["state"] != "conflicting":
        identity_fact = fields.get(Target(field="legal_name", subject=designated[0]), {})
        preferred = identity_fact.get("preferred")
        if preferred:
            reported = fields.get(Target(field="defendant_identity"), {})
            if reported.get("assertions"):
                # A separate identity report must agree with the linked registry record.
                reports["defendant_identity"]["state"] = "unsupported"
            else:
                reports["defendant_identity"] = {
                    "state": "known", "value": preferred.value, "provenance": preferred.source,
                    "assertions": identity_fact["assertions"],
                }
    arguments = {name: reports[name]["value"] for name in MatterFacts.model_fields if reports[name]["state"] == "known"}
    return MatterFacts.model_validate(arguments), reports
