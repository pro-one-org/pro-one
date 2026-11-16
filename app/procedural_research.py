"""Development-only procedural planning on the shared Research Core."""

from datetime import date, timedelta
import hmac
import re
import secrets
from typing import Literal

from pydantic import Field

from app.assistant import seal, unseal
from app.capabilities import ResearchMatter
from app.generation import GenerationService
from app.legal_research import GeneralLegalResearchService
from app.models.base import GenerationConfig
from app.models.testing import TEST_MODEL, testing_registry
from app.national_corpus import AuthorityType, identity
from app.procedural_authority import ProceduralAuthorityProvider, load_catalog
from app.procedural_models import Key, Record, Scope
from app.rendering import ResponseRenderingService
from app.research_synthesis import ResearchSynthesisService

CHOICE_DOMAIN = b"pro-one/procedural-choice/v1"
DEVELOPMENT_CHOICE_KEY = secrets.token_bytes(32)
BLOCKED_CLASSIFICATIONS = {"strategy_legal_judgment", "reserved_legal_act"}
US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_NAME_SCOPES = {name.casefold(): f"US-{code}" for code, name in US_STATE_NAMES.items()}
STATE_NAME_PATTERN = re.compile(
    r"\b(?:" + "|".join(map(re.escape, sorted(STATE_NAME_SCOPES, key=len, reverse=True))) + r")\b", re.I,
)
FACT_QUESTIONS = {
    "forum": "What court are you considering, or what court is named on the document?",
    "document_type": "What is the full title on the court papers? If this is a summons, was a complaint included?",
    "incident_locality": "In what city or county did the incident happen?",
    "amount_sought": "What amount are you considering seeking, excluding interest and attorney fees?",
    "defendant_identity": "What legal name appears for the business or entity involved?",
    "defendant_location": "What city or county is the defendant’s principal or registered office in?",
    "defendant_type": "Is the defendant an individual, Virginia corporation, Virginia LLC or another entity?",
    "complaint_filed": "Has the complaint been filed?",
    "summons_issued": "Has the clerk issued the summons?",
    "service_date": "On what date were the summons and complaint served?",
    "service_mode": "Was the summons and complaint ordinarily served, or was service waived or handled another way?",
    "extension_status": "Is there an extension, court order or other exception affecting the time?",
    "local_rules_checked": "Have you checked the applicable rules and orders for this court?",
    "order_entered": "Has the court entered the judgment or order you want to ask about?",
}


class MatterFacts(Record):
    incident_locality: str | None = Field(default=None, max_length=120)
    defendant_identity: str | None = Field(default=None, max_length=200)
    defendant_type: Literal["individual", "virginia_llc", "virginia_corporation", "other"] | None = None
    defendant_location: str | None = Field(default=None, max_length=120)
    amount_sought: int | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)
    complaint_filed: bool = Field(default=False, strict=True)
    summons_issued: bool = Field(default=False, strict=True)
    document_type: Literal["summons_and_complaint", "other"] | None = None
    service_date: date | None = None
    service_mode: Literal["ordinary_service", "waiver", "other"] | None = None
    extension_status: Literal["none_confirmed", "extension_or_order", "unknown"] | None = None
    local_rules_checked: bool = Field(default=False, strict=True)
    order_entered: bool = Field(default=False, strict=True)


class ProceduralRequest(Record):
    message: str = Field(min_length=1, max_length=2000)
    jurisdiction: Scope | None = None
    forum: Key | None = None
    as_of: date | None = None
    selected_path: Key | None = None
    choice_token: str = Field(default="", max_length=2000)
    stage: Key | None = None
    authority_type: AuthorityType | None = None
    facts: MatterFacts = Field(default_factory=MatterFacts)


def fact_present(facts, name):
    value = getattr(facts, name)
    if name == "document_type":
        return value == "summons_and_complaint"
    if name == "extension_status":
        return value == "none_confirmed"
    if name == "service_mode":
        return value == "ordinary_service"
    return value is not None and value is not False and value != ""


def missing_facts(facts, fields):
    return sorted({name for name in fields if not fact_present(facts, name)})


def is_dated(authority, on):
    return authority.version.evidence_status == "current_as_of" and authority.version.current_as_of == on


def forum_matches(catalog, requirement, forum):
    if requirement.forum is None or requirement.forum == forum:
        return True
    if requirement.local:
        return False
    while forum and catalog.forums[forum].parent:
        forum = catalog.forums[forum].parent
        if forum == requirement.forum:
            return True
    return False


def requirement_evidence(requirement):
    return requirement.evidence + ((requirement.deadline.counting_authority,) if requirement.deadline else ())


def select_requirements(catalog, *, path_id, stage, jurisdiction, forum, authority_type=None):
    path = catalog.paths.get(path_id)
    if not path or path.jurisdiction != jurisdiction or (forum and forum not in path.forums):
        return {}
    return {
        key: row for key, row in catalog.requirements.items()
        if row.path == path_id and row.stage == stage and row.classification not in BLOCKED_CLASSIFICATIONS
        and forum_matches(catalog, row, forum)
        and (authority_type is None or all(ref.authority_type == authority_type for ref in requirement_evidence(row)))
    }


def bounded_deadline(rule, *, trigger, trigger_date, on, calendar, conditions_confirmed):
    """Apply the single reviewed counting convention to a complete supplied calendar.

    Calendar entries explicitly declare whether the clerk is open for the whole day.
    This evaluator has no holiday inference or matter-level deadline side effects.
    """
    if (not conditions_confirmed or trigger != rule.trigger or not trigger_date
            or not date.min <= trigger_date <= on or on > date.max - timedelta(days=372)):
        return None
    nominal = trigger_date + timedelta(days=rule.period)
    for offset in range(8):
        candidate = nominal + timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        if type(calendar.get(candidate)) is not bool:
            return None
        if calendar[candidate]:
            return candidate
    return None


def preview_deadline(catalog, *, path, stage, jurisdiction, forum, facts, on, calendar):
    """Evaluate only a fully scoped, dated deadline with explicit event facts."""
    rows = select_requirements(catalog, path_id=path, stage=stage, jurisdiction=jurisdiction, forum=forum)
    for row in rows.values():
        if (row.deadline and all(is_dated(catalog.authorities[ref.authority], on) for ref in requirement_evidence(row))
                and facts.service_date == on and not missing_facts(facts, row.facts)):
            return bounded_deadline(row.deadline, trigger="service_of_summons_and_complaint",
                                    trigger_date=facts.service_date, on=on, calendar=calendar,
                                    conditions_confirmed=True)
    return None


def infer_subject(message):
    if re.search(r"\b(?:received|served|got|handed|delivered|sent)\b", message, re.I) and re.search(
            r"\b(?:court (?:documents?|papers?)|summons|complaint)\b", message, re.I):
        return "response"
    if re.search(r"\b(?:serve|served|serving|service|process server)\b", message, re.I) and re.search(
            r"\b(?:complaint|summons|process|civil)\b", message, re.I):
        return "service"
    if re.search(r"\b(?:slip\w*|fell|fall|trip\w*)\b", message, re.I) and re.search(
            r"\b(?:pay|payment|compensat\w*|reimburse\w*|damages|money)\b", message, re.I):
        return "compensation"
    return None


def infer_jurisdiction(message):
    explicit = {STATE_NAME_SCOPES[match.group().casefold()] for match in STATE_NAME_PATTERN.finditer(message)}
    if re.search(r"\b(?:federal (?:district )?court|(?:United States|U\.?S\.?) district court)\b", message, re.I):
        if not re.search(r"\b(?:state court|circuit court|general district court)\b", message, re.I):
            return {"US"}
        explicit.add("US")
    return explicit


class ProceduralResearchService:
    def __init__(self, repository, settings, generation, *, catalog=None):
        self.repository = repository
        self.settings = settings
        self.generation = generation
        self.catalog = (catalog or load_catalog()) if settings.mode == "development" else None
        self.choice_key = (hmac.digest(settings.conversation_signing_key, CHOICE_DOMAIN, "sha256")
                           if settings.conversation_signing_key else DEVELOPMENT_CHOICE_KEY)

    def respond(self, request, *, matter_scope=None):
        if self.settings.mode != "development":
            return self.result("unavailable")
        if re.search(r"\b(?:file|submit|sign|serve|send|pay|settle|negotiate)\b.{0,55}\b(?:for me|on my behalf)\b", request.message, re.I):
            return self.result("reserved_legal_act", classification="reserved_legal_act")
        if re.search(r"\b(?:choose|pick|decide)\b.{0,55}\b(?:for me|on my behalf)\b", request.message, re.I):
            return self.result("legal_judgment_required", classification="strategy_legal_judgment")
        named = infer_jurisdiction(request.message)
        if len(named) > 1 or (named and request.jurisdiction and request.jurisdiction not in named):
            return self.result("jurisdiction_confirmation_required")
        jurisdiction = request.jurisdiction or next(iter(named), None)
        subject = infer_subject(request.message)
        if jurisdiction is None:
            return self.result("missing_jurisdiction", questions=["Where did the incident happen, or what court is named on the document?"])
        on = request.as_of or self.catalog.reference_date
        options = tuple(key for key, path in self.catalog.paths.items()
                        if path.jurisdiction == jurisdiction and path.inquiry == subject)
        forum = self.catalog.forums.get(request.forum)
        reported_district = jurisdiction == "US-VA" and re.search(r"\bGeneral District Court\b", request.message, re.I)
        if reported_district and (subject == "response" or (forum and forum.level != "limited_trial")):
            return self.result("wrong_forum", jurisdiction=jurisdiction)
        if request.forum and (not forum or forum.jurisdiction != jurisdiction
                              or subject != "compensation" and not any(request.forum in self.catalog.paths[key].forums for key in options)):
            return self.result("wrong_forum", jurisdiction=jurisdiction)
        if not options:
            return self.result("outside_bounded_coverage", jurisdiction=jurisdiction)
        if not request.selected_path and (request.choice_token or request.stage):
            return self.result("explicit_choice_required", jurisdiction=jurisdiction)
        # Only a user-originated choice referencing this response can enter a path.
        scope = {"purpose": "procedural_choice_v1", "catalog": self.catalog.record_version,
                 "topic": subject, "jurisdiction": jurisdiction, "as_of": on.isoformat(),
                 "inquiry": identity(request.message)}
        if matter_scope is not None:
            scope["matter"] = matter_scope
        common = {"jurisdiction": jurisdiction, "reference_date": on.isoformat(), "subject": subject,
                  "catalog_version": self.catalog.record_version,
                  "inferences": {"possible_legal_area": "premises_liability", "desired_outcome": "compensation"}
                  if subject == "compensation" else {"possible_legal_area": "civil_procedure"}}
        if request.selected_path:
            try:
                choice = unseal(request.choice_token, key=self.choice_key)
            except (ValueError, TypeError):
                choice = {}
            if (choice.get("matter") != matter_scope or any(choice.get(key) != value for key, value in scope.items())
                    or request.selected_path not in choice.get("paths", []) or request.selected_path not in options
                    or choice.get("forum") not in (None, request.forum)
                    or choice.get("authority_type") not in (None, request.authority_type)):
                return self.result("explicit_choice_required", **common)
            return self.explain(request, request.selected_path, on, common)

        substantive = None
        if subject == "compensation":
            research = GeneralLegalResearchService(self.repository)
            state = self.catalog.jurisdictions[jurisdiction].state_name
            substantive = research.assemble(ResearchMatter(country="US", state=state, legal_area="torts",
                                                            topics=["premises_liability"]))
            if not substantive["package"]:
                return self.result("no_authoritative_support", **common)
            substantive = self.render(substantive["package"])
        cards, refs = [], {}
        for key in options:
            path = self.catalog.paths[key]
            if request.authority_type and any(ref.authority_type != request.authority_type for ref in path.evidence):
                continue
            support = {ref.authority: self.catalog.authorities[ref.authority] for ref in path.evidence}
            refs.update(support)
            dated = all(is_dated(authority, on) for authority in support.values())
            cards.append({"id": key, "kind": path.kind, "label": path.label, "user_choice_required": True,
                          "classification": "available_user_option", "evidence": list(support),
                          "status": "dated_option" if dated else "reference_only",
                          "description": path.description if dated else "The retained source is available for reference. Its current applicability needs review."})
        if not cards:
            return self.result("no_authoritative_support", **common)
        token = seal({**scope, "paths": [item["id"] for item in cards], "forum": request.forum,
                      "authority_type": request.authority_type}, key=self.choice_key)
        return self.result("choose_path", **common, options=cards, choice_token=token, substantive=substantive,
                           evidence=self.evidence(refs), selected_path=None)

    def explain(self, request, path_id, on, common):
        path = self.catalog.paths[path_id]
        base = {**common, "selected_path": path_id, "selection_origin": "user",
                "proceeding": path.proceeding, "user_facts": request.facts.model_dump(mode="json", exclude_defaults=True)}
        if request.forum and request.forum not in path.forums:
            return self.result("wrong_forum", **base)
        support = {ref.authority: self.catalog.authorities[ref.authority] for ref in path.evidence}
        if not path.entry_stage:
            if request.stage:
                return self.result("invalid_stage", **base)
            dated = all(is_dated(authority, on) for authority in support.values())
            return self.result("option_explained" if dated else "reference_only", **base,
                               description=path.description if dated else None, evidence=self.evidence(support),
                               missing_information=missing_facts(request.facts, path.entry_facts))
        stage = request.stage or path.entry_stage
        if stage not in path.stages:
            return self.result("invalid_stage", **base)
        missing = self.stage_prerequisites(path, stage, request.facts)
        if stage != "forum" and path.forums and not request.forum:
            missing.append("forum")
        if missing:
            return self.result("prerequisite_missing", **base, stage=stage, missing_information=missing,
                               questions=[FACT_QUESTIONS[field] for field in missing])
        rows = select_requirements(self.catalog, path_id=path_id, stage=stage, jurisdiction=path.jurisdiction,
                                   forum=request.forum, authority_type=request.authority_type)
        if not rows:
            return self.result("no_authoritative_support", **base, stage=stage)
        refs, items, synthesis = {}, [], []
        for key, row in rows.items():
            support = {ref.authority: self.catalog.authorities[ref.authority] for ref in requirement_evidence(row)}
            refs.update(support)
            dated = all(is_dated(authority, on) for authority in support.values())
            needed = missing_facts(request.facts, row.facts)
            if row.service and row.service.entity_type and request.facts.defendant_type not in {None, "virginia_llc", "virginia_corporation"}:
                continue
            item = {"id": key, "status": ("reference_only" if not dated else "conditional" if
                                           needed or row.conditions or row.local else "dated_information"),
                    "classification": row.classification,
                    "action": row.action if dated else "informational", "trigger": row.trigger if dated else None,
                    "forum": row.forum, "local_overlay": row.local, "evidence": list(support),
                    "missing_information": needed}
            if dated:
                details = row.model_dump(mode="json", include={"filing", "fee", "service", "deadline", "conditions"}, exclude_none=True)
                item.update(details)
                synthesis.append({**item, "stage": stage, "proceeding": path.proceeding, "jurisdiction": path.jurisdiction,
                                  "text": row.text, "source_keys": list(support)})
            items.append(item)
        if not items:
            return self.result("no_authoritative_support", **base, stage=stage)
        seen = {key for item in items for key in item["evidence"]}
        refs = {key: value for key, value in refs.items() if key in seen}
        rendered = self.research(path, refs, synthesis)
        if not rendered:
            return self.result("evidence_rejected", **base, stage=stage)
        missing = sorted({field for item in items for field in item["missing_information"]}
                         | set(missing_facts(request.facts, path.stages[stage].completion_facts)))
        if stage == "forum" and request.forum is None:
            missing.append("forum")
        registry = self.forums(path, request.forum, on) if stage == "forum" and not request.authority_type else []
        transitions = []
        if not missing and synthesis:
            for target in path.stages[stage].transitions:
                if self.stage_prerequisites(path, target, request.facts):
                    continue
                target_rows = select_requirements(self.catalog, path_id=path_id, stage=target,
                                                  jurisdiction=path.jurisdiction, forum=request.forum,
                                                  authority_type=request.authority_type)
                if any(all(is_dated(self.catalog.authorities[ref.authority], on) for ref in requirement_evidence(row))
                       for row in target_rows.values()):
                    transitions.append(target)
        return self.result("procedure_explained" if synthesis else "reference_only", **base, stage=stage,
                           stage_label=path.stages[stage].label,
                           requirements=items, responses=rendered, evidence=self.evidence(refs), forums=registry,
                           missing_information=missing, questions=[FACT_QUESTIONS[field] for field in missing],
                           available_transitions=transitions,
                           limitations=["Court selection, case-specific legal judgment and calendar applicability require separate review.",
                                        "Unreviewed local rules, court orders and factual exceptions may affect this information."])

    @staticmethod
    def stage_prerequisites(path, stage, facts):
        def walk(current, required):
            node = path.stages[current]
            required = required | set(node.prerequisite_facts)
            if current == stage:
                return [missing_facts(facts, required)]
            return [result for target in node.transitions for result in walk(target, required | set(node.completion_facts))]
        return min(walk(path.entry_stage, set(path.entry_facts)), key=len)

    def research(self, path, refs, context):
        scope = path.jurisdiction
        matter = ResearchMatter(country="US", state=self.catalog.jurisdictions[scope].state_name,
                                sovereign="federal" if scope == "US" else "state", legal_area=path.legal_area,
                                topics=[path.proceeding])
        # Keep each multi-source binding together when applying the Research Core
        # per-provider limit. A new graph may include overlapping groups.
        groups = [binding["source_keys"] for binding in context]
        covered = {key for group in groups for key in group}
        groups += [[key] for key in refs if key not in covered]
        batches = []
        for group in groups:
            current = batches[-1] if batches else []
            union = list(dict.fromkeys(current + group))
            if current and len(union) <= 5:
                batches[-1] = union
            else:
                batches.append(group)
        results = []
        for keys in batches:
            batch = {key: refs[key] for key in keys}
            provider = ProceduralAuthorityProvider(matter, batch, self.catalog)
            prepared = GeneralLegalResearchService(self.repository, providers=[provider]).assemble(matter, force_general=True)
            if not prepared["package"]:
                return []
            bindings = [{k: v for k, v in binding.items() if k != "source_keys"} |
                        {"passage_ids": [pid for key in binding["source_keys"] for pid in provider.passage_ids[key]]}
                        for binding in context if set(binding["source_keys"]).issubset(batch)]
            package = prepared["package"]
            package["procedural_publisher_excerpts"] = True
            rendered = self.render(package, bindings)
            # Verified paraphrases may combine several exact excerpts. Every
            # citation binding still has to survive the final validation.
            if not rendered or len(rendered["sources"]) != sum(map(len, provider.passage_ids.values())):
                return []
            results.append(rendered)
        return results

    def render(self, package, bindings=None):
        config = GenerationConfig(provider="testing", model=TEST_MODEL)
        renderer = ResponseRenderingService()
        candidate = package
        if bindings and self.settings.provider != "testing" and self.settings.model:
            configured = GenerationConfig(provider=self.settings.provider, model=self.settings.model)
            candidate = ResearchSynthesisService(self.generation.registry).prepare(package, configured, procedural_context=bindings)
        offline = GenerationService(testing_registry())
        # The model never controls output shape or which evidence gets omitted.
        rendered = renderer.render(offline.generate(candidate, config), candidate, config)
        if rendered:
            rendered["verification"] = candidate.get("synthesis", {}).get("status", "exact_evidence")
        elif candidate is not package:
            rendered = renderer.render(offline.generate(package, config), package, config)
            if rendered:
                rendered["verification"] = "exact_evidence_after_rejection"
        return rendered

    def forums(self, path, forum, on):
        result = []
        for key in path.forums:
            if forum is not None and key != forum:
                continue
            item = self.catalog.forums[key]
            refs = {ref.authority: self.catalog.authorities[ref.authority] for ref in item.evidence}
            result.append({"id": key, **item.model_dump(mode="json"), "forum_selected_for_user": False,
                           "status": "dated_reference" if all(is_dated(authority, on) for authority in refs.values())
                           else "publisher_reference", "sources": self.evidence(refs)})
        return result

    @staticmethod
    def evidence(refs):
        from app.procedural_authority import PUBLICATIONS

        return {key: {"publisher": item.version.institution, "citation": item.version.citation, "jurisdiction": item.version.jurisdiction,
                      "authority_type": item.version.authority_type, "forum": item.version.court,
                      "edition": item.version.edition, "version": item.version.version_id, "locator": item.locator,
                      "source_url": PUBLICATIONS[item.artifact].url, "artifact_hash": item.artifact_hash,
                      "excerpt": item.version.text, "excerpt_hash": item.version.normalized_hash,
                      "currentness": item.version.evidence_status, "current_as_of": item.version.current_as_of,
                      "currentness_basis": item.version.currentness_basis,
                      "effective_from": item.version.effective_from, "effective_until": item.version.effective_until,
                      "status_source_url": PUBLICATIONS[item.status_artifact].url if item.status_artifact else None,
                      "status_source_hash": item.status_hash, "limitations": item.version.limitations}
                for key, item in refs.items()}

    @staticmethod
    def result(status, **fields):
        return {"schema_version": "1.0.0", "status": status, "review": "development_only", "publicly_approved": False,
                "external_action_allowed": False, **fields}
