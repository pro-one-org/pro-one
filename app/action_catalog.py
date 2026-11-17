"""Validate the development policy graph against the existing authority catalogs."""
from pathlib import Path

from app.action_models import ActionCatalogData
from app.claim_catalog import fingerprint
from app.matter_state import EVENT_FIELDS, OPTIONAL_EVENT_FIELDS, PARTY_FIELDS
from app.procedural_authority import PUBLICATIONS
from app.procedural_research import forum_matches, requirement_evidence


def index(records):
    by_id = {item.id: item for item in records}
    if len(by_id) != len(records):
        raise ValueError("duplicate action policy identity")
    return by_id


class ActionCatalog:
    def __init__(self, procedure, claims, data=None, calendars=()):
        self.procedure, self.claims = procedure, claims
        if data is None:
            path = Path(__file__).resolve().parents[1] / "data" / "legal-action-os.json"
            data = ActionCatalogData.model_validate_json(path.read_bytes())
        self.actions = index(data.actions)
        self.templates = index(data.templates)
        self.deadlines = index(data.deadlines)
        self.calendars = {item.forum: item for item in calendars}
        if len(self.calendars) != len(calendars):
            raise ValueError("duplicate reviewed court calendar")
        for calendar in calendars:
            forum = procedure.forums.get(calendar.forum)
            if not forum or forum.jurisdiction != calendar.jurisdiction:
                raise ValueError("court calendar scope mismatch")
        try:
            self.validate()
        except KeyError:
            raise ValueError("unresolved action catalog reference") from None
        self.fingerprints = {
            "policy": fingerprint(data.model_dump(mode="json")),
            "procedure": fingerprint(procedure.model_dump(mode="json")),
            "calendars": fingerprint([row.model_dump(mode="json") for row in sorted(calendars, key=lambda r: r.forum)]),
        }

    def validate(self):
        for rule in self.deadlines.values():
            path = self.procedure.paths[rule.path]
            if rule.jurisdiction != path.jurisdiction or rule.forum not in path.forums:
                raise ValueError("deadline scope mismatch")
            if rule.procedure_ref:
                item = self.procedure.requirements[rule.procedure_ref]
                if item.path != rule.path or not item.deadline or not forum_matches(self.procedure, item, rule.forum):
                    raise ValueError("deadline rule mismatch")
                trigger_kinds = {"service_of_summons_and_complaint": "service", "filing_of_complaint": "filing"}
                if trigger_kinds.get(item.deadline.trigger) != rule.event_kind:
                    raise ValueError("deadline trigger mismatch")
            elif self.claims.active[rule.theory_ref].jurisdiction != rule.jurisdiction:
                raise ValueError("deadline theory mismatch")
        for action in self.actions.values():
            path = self.procedure.paths[action.path]
            if (action.jurisdiction != path.jurisdiction or (action.forum and action.forum not in path.forums)
                    or (action.stage and action.stage not in path.stages)):
                raise ValueError("action path scope mismatch")
            if any(self.claims.active[key].jurisdiction != action.jurisdiction for key in action.theories):
                raise ValueError("action theory scope mismatch")
            template = self.templates[action.template]
            if template.action != action.id:
                raise ValueError("template action mismatch")
            reqs = index(action.requirements)
            mandatory = {req.check for req in reqs.values() if req.severity == "blocking_requirement"}
            if "choice" not in mandatory or (action.theories and "claim" not in mandatory):
                raise ValueError("action requires an explicit choice and applicable claim analysis")
            for key in action.procedure_refs + template.procedure_refs:
                item = self.procedure.requirements[key]
                if item.path != action.path or not forum_matches(self.procedure, item, action.forum):
                    raise ValueError("action procedure mismatch")
            for key in action.deadline_rules:
                rule = self.deadlines[key]
                if (rule.jurisdiction, rule.path, rule.forum) != (action.jurisdiction, action.path, action.forum):
                    raise ValueError("action deadline mismatch")
            seen_facts = set()
            for req in reqs.values():
                scopes = {"matter": set(), "event": EVENT_FIELDS | OPTIONAL_EVENT_FIELDS,
                          "party": PARTY_FIELDS, "user": PARTY_FIELDS}
                if req.fact:
                    scope = req.fact.scope
                    if ((scope == "matter" and req.fact.field in EVENT_FIELDS | PARTY_FIELDS)
                            or (scope != "matter" and req.fact.field not in scopes[scope])
                            or (scope == "event" and not action.event_kind)
                            or (scope == "party" and not action.allowed_party_roles)
                            or (req.fact.same_as and req.fact.same_as not in seen_facts)):
                        raise ValueError("action fact scope mismatch")
                    seen_facts.add(req.id)
                    if req.fact.claim_element and not any(
                        element.id == req.fact.claim_element
                        and any(link.field == req.fact.field and link.scope == scope for link in element.fields)
                        for key in action.theories for element in self.claims.active[key].elements
                    ):
                        raise ValueError("action fact has no claim evidence binding")
                refs = {"procedural_authority": action.procedure_refs, "legal_authority": action.theories,
                        "document_template": (action.template,), "system_safety": (), "user_authorization": ()}
                if req.check == "deadline":
                    valid = action.deadline_rules
                else:
                    valid = refs[req.origin]
                if not set(req.refs) <= set(valid):
                    raise ValueError("invalid action requirement provenance")
            fields = index(tuple(field for section in template.sections for field in section.fields))
            for field in fields.values():
                if field.source in {"forum", "theory"}:
                    if field.source == "forum" and not action.forum or field.source == "theory" and not action.theories:
                        raise ValueError("unbound document field")
                elif (field.source not in reqs or reqs[field.source].check != "fact"
                      or field.required and reqs[field.source].severity != "blocking_requirement"):
                    raise ValueError("unbound document fact")
        if set(self.templates) != {action.template for action in self.actions.values()}:
            raise ValueError("unbound action template")

    def procedure_evidence(self, ids):
        return {ref.authority: self.authority(ref.authority)
                for key in ids for ref in requirement_evidence(self.procedure.requirements[key])}

    def authority(self, key):
        source = self.procedure.authorities[key]
        publisher = PUBLICATIONS[source.artifact]
        return {"id": key, "citation": source.version.citation, "url": publisher.url,
                "locator": source.locator, "edition": source.version.edition,
                "artifact_hash": source.artifact_hash, "status_hash": source.status_hash,
                "currentness": source.version.currentness, "current_as_of": source.version.current_as_of,
                "currentness_basis": source.version.currentness_basis}
