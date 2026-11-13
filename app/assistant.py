"""Bounded, signed conversation state and server-owned product orchestration."""

import hashlib
import hmac
import json
import re
import secrets
from copy import deepcopy
from time import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.matter_extraction import MatterExtractionService, ExtractionUnavailable
from app.product import ProductService, ProductResponseRequest
from app.routing import MatterRequest, MatterRoutingService, WorkflowCatalogService
from app.capabilities import ResearchMatter
from app.document_inspection import inspect_document_question, select_document_passages
from app.legal_research import GeneralLegalResearchService

_STATE_KEY = secrets.token_bytes(32)
STATE_TTL_SECONDS = 3600
FIELDS = set(MatterRequest.model_fields) - {"user_goal"}
QUESTIONS = {
    "country": "What country is the court or agency in?",
    "state": "What state is the court or agency in?",
    "user_type": "Is this about you as an individual, or a business you own?",
    "court": "What court or agency is named on the document?",
    "form_number": "What form number appears on the paper?",
    "document_title": "What is the title printed on the document?",
    "role": "Are you the person being sued, or the business owner?",
    "matter_type": "What kind of matter does the document describe?",
    "listed_date": "What date and time are printed on the paper? You can say ‘Not shown’ or ‘Not sure’.",
}


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=2000)
    document_text: str = Field(default="", max_length=16000)
    conversation_state: str = Field(default="", max_length=24000)


def seal(state, *, key=None):
    payload = json.dumps({"expires_at": int(time()) + STATE_TTL_SECONDS, **state},
                         separators=(",", ":"), ensure_ascii=True)
    signature = hmac.new(key or _STATE_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return signature + "." + payload


def unseal(token, *, key=None):
    if not token:
        return {"facts": {}, "pending": {}, "question": "", "turn": 0, "expires_at": int(time()) + STATE_TTL_SECONDS}
    signature, payload = token.split(".", 1)
    expected = hmac.new(key or _STATE_KEY, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        raise ValueError("invalid_state")
    state = json.loads(payload)
    expires_at = state.get("expires_at") if isinstance(state, dict) else None
    if type(expires_at) is not int or time() >= expires_at:
        raise ValueError("expired_state")
    return state


class AssistantService:
    def __init__(self, repository, settings, generation):
        self.repository, self.settings, self.generation = repository, settings, generation
        self.catalog = WorkflowCatalogService(repository).catalog()
        self.router = MatterRoutingService(repository)

    def configuration(self):
        available = self.generation.registry.configured_models()
        provider, model = self.settings.provider, self.settings.model
        if provider == "testing":
            for name in ("openai", "anthropic"):
                if available.get(name):
                    return name, available[name][0]
        return provider, model

    def status(self):
        provider, model = self.configuration()
        available = model in self.generation.registry.configured_models().get(provider, [])
        return {"demo": provider == "testing" and self.settings.mode != "production", "available": available,
                "offline_notice": "Live AI is not configured. The offline demo can exercise known example matters only.",
                "coverage": [{"title": c["title"], "state": c["jurisdiction"]["state"], "purpose": "Proposed source collection; legal and currentness review pending."} for c in self.repository.records["legal_capabilities"].values()]}

    def message(self, request):
        try:
            state = unseal(request.conversation_state, key=self.settings.conversation_signing_key)
        except (ValueError, TypeError):
            return {"status": "restart_needed", "message": "This conversation has expired. Start a new conversation to continue."}
        state["turn"] += 1
        def reply(status, message, response=None):
            return {"status": status, "message": message, "response": response,
                    "conversation_state": seal(state, key=self.settings.conversation_signing_key), "matter": state["facts"],
                    "needs_confirmation": state["pending"], "demo": self.status()["demo"],
                    "followups": ["Explain the document", "What information should I gather?", "Show me the official source"] if response else []}
        if state["turn"] > 30:
            return {"status": "restart_needed", "message": "Please start a new conversation to keep the context manageable."}
        message = request.message.strip()
        if re.search(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b|\b\d{12,19}\b", message + " " + request.document_text):
            return reply("redaction_needed", "Please remove Social Security numbers, account numbers, and other unnecessary sensitive information, then try again.")
        if re.search(r"\b(evict\w*|foreclos\w*|immigration|criminal|custody|domestic violence|bankruptcy)\b", message + " " + request.document_text, re.I):
            state["facts"], state["pending"] = {}, {}
            state.pop("research", None)
            return reply("unsupported", "This matter is outside the legal topics Pro-One currently covers. If a date is imminent, check the instructions from the court and seek qualified help promptly. I cannot provide an answer about this matter.")
        if self.settings.mode == "production":
            return reply("unavailable", "These legal topics are still under review and are not available for public use.")
        inspection = inspect_document_question(message, request.document_text)
        if inspection:
            provider, model = self.configuration()
            if provider != "testing" and model in self.generation.registry.configured_models().get(provider, []):
                from app.models.base import GenerationConfig
                inspection = select_document_passages(inspection, message, request.document_text, self.generation.registry,
                                                      GenerationConfig(provider=provider, model=model))
            response = reply("document_inspected", "Here is what I can identify from the uploaded text.", inspection)
            response.update(matter={}, needs_confirmation={}, followups=[])
            return response
        provider, model = self.configuration()
        if model not in self.generation.registry.configured_models().get(provider, []):
            return reply("provider_unavailable", "Live AI is temporarily unavailable. Please try again later.")
        if provider != "testing" and re.search(r"\b(?:find|look up|lookup)\b", message, re.I) and re.search(r"\b\d+\s+(?:Va\.|U\.S\.|S\.E\.2d|F\.3d)\s+\d+", message):
            # Lookup transmits only a base legal citation, never the conversation.
            from app.citation_research import CitationResearchRequest, lookup_configured_citation, render_citation_identity
            found = re.findall(r"\b\d+\s+(?:Va\.|U\.S\.|S\.E\.2d|F\.3d)\s+\d+", message)
            jurisdiction = state["facts"].get("state", {}).get("value")
            if "Virginia" in message:
                jurisdiction = "Virginia"
            if len(found) != 1 or not jurisdiction or re.search(r"[\"“”]|\d,\s*\d|\bv\.\s", message):
                return reply("citation_unverified", "Give one base citation and its state. A quotation, case name or pin cite needs separate verification against the retrieved opinion.")
            value = lookup_configured_citation(CitationResearchRequest(citation=found[0], state=jurisdiction), self.settings)
            if value.get("reason") == "courtlistener_unconfigured":
                return reply("unavailable", "Case lookup is not configured on this server.")
            if value.get("reason") == "corpus_storage_unavailable":
                return reply("unavailable", "Case lookup is temporarily unavailable. Please try again later.")
            return reply(value["status"], "Base citation lookup; substantive support and currentness require separate review.", render_citation_identity(value))
        if provider == "testing" and (message.casefold() == "try courtlistener research example"
                or state.get("corpus_demo") and message.casefold() in {"show the cases", "why does notice matter?", "explain the evidence", "show me the official source"}):
            from app.research_demo import run_research_demo, DEMO_NOTICE
            state["corpus_demo"] = True
            result = run_research_demo(self.repository)
            response = reply(result["status"], DEMO_NOTICE, result["response"])
            response["followups"] = ["Show the cases", "Why does notice matter?", "Explain the evidence"]
            return response
        if provider == "testing" and state.get("corpus_demo") and re.search(r"\d+\s+(?:Va\.|S\.E\.)", message):
            if message.casefold() in {"find the virginia case supporting 278 va. 84", "find the virginia case supporting 254 va. 134"}:
                from app.research_demo import demo_bundles, DEMO_NOTICE
                from app.corpus_store import SQLiteCorpusStore
                from app.citation_research import CitationResearchRequest, resolve_citation, render_citation_identity
                citation = "278 Va. 84" if "278" in message else "254 Va. 134"
                with SQLiteCorpusStore() as store:
                    for bundle in demo_bundles(self.repository):
                        store.ingest(bundle)
                        store.save_verification({"citation": bundle.cluster.citations[0], "cluster": bundle.cluster.id, "name": bundle.cluster.name, "origin": "fixture"})
                    result = resolve_citation(CitationResearchRequest(citation=citation, state="Virginia"), store)
                return reply(result["status"], DEMO_NOTICE, render_citation_identity(result))
            return reply("citation_unverified", "This offline example cannot validate a supplied case name, quotation or pin cite. Use the linked sources; live citation lookup is not configured.")
        if provider == "testing" and message.casefold() == "try premises liability example":
            from app.models.base import GenerationConfig
            result = GeneralLegalResearchService(self.repository, self.settings, self.generation).respond(
                ResearchMatter(country="US", state="Virginia", legal_area="torts", topics=["premises_liability"]),
                GenerationConfig(provider=provider, model=model))
            return reply(result["status"], "Known Virginia premises-liability example. Live AI is not configured; this is an offline demonstration.", result["response"])
        if state["pending"] and message.casefold() in {"yes", "confirm", "yes, that's correct", "correct"}:
            state["facts"].update({k: {"value": v["value"], "provenance": "user_confirmed", "origin": v["provenance"]} for k, v in state["pending"].items()})
            state["pending"] = {}
        elif state.get("asking") == "listed_date" and not re.search(r"Virginia|Maryland|\bDC[- ]?402\b|\bSCC\b|court|business", message, re.I):
            field = state.pop("asking")
            state["facts"][field] = {"value": message[:250], "provenance": "user_explicit"}
        else:
            state["question"] = message
            if provider == "testing":
                candidates = self.demo_candidates(message, request.document_text)
                if not state["facts"] and not any(k in candidates for k in ("form_number", "document_title")):
                    return reply("offline_demo_only", "Live AI is not configured. The offline demo can exercise known example matters only.")
            else:
                try:
                    extraction_model = self.settings.openai_extraction_model if provider == "openai" else ""
                    extracted = MatterExtractionService(self.generation.registry).extract(
                        message, request.document_text,
                        {"workflows": self.catalog, "capabilities": [{k: c[k] for k in ("title", "jurisdiction", "legal_area", "topics")} for c in self.repository.records["legal_capabilities"].values()]},
                        {"facts": state["facts"], "research": state.get("research", {})}, provider, extraction_model or model)
                except ExtractionUnavailable:
                    return reply("provider_unavailable", "I couldn't interpret that message safely. Please try again.")
                if extracted.unsupported:
                    state["facts"], state["pending"] = {}, {}
                    state.pop("research", None)
                    return reply("unsupported", "I don't yet have coverage for this matter, so I cannot give a source-supported answer.")
                candidates = {f.name: {"value": f.value, "provenance": f.provenance} for f in extracted.fields}
                specialized = any(k in candidates for k in ("form_number",)) or any(
                    word in (message + " " + request.document_text).casefold() for word in ("dc-402", "dc402", "scc", "summons"))
                if not specialized and ("legal_area" in candidates or state.get("research")):
                    return self.research_reply(candidates, state, reply, provider, model)
                # Research context cannot make an unrelated procedural matter
                # inherit a prior accident's scope or facts.
                if specialized:
                    state.pop("research", None)
                if not specialized and not state["facts"] and not any(k in candidates for k in ("user_type", "role")):
                    return reply("clarification_needed", "What legal issue would you like help understanding, and what state is involved?")
            candidates = {k: v for k, v in candidates.items() if k in FIELDS}
            # Every extracted candidate is confirmed explicitly, including model claims of explicit provenance.
            changed = {k: v for k, v in candidates.items() if state["facts"].get(k, {}).get("value") != v["value"]}
            if changed:
                if any(k in changed for k in ("state", "matter_type", "user_type")):
                    state["facts"] = {}
                    changed = candidates
                state["pending"] = changed
        if state["pending"]:
            combined = {**state["facts"], **state["pending"]}
            summary = "; ".join(combined[k]["value"].replace("_", " ") for k in ("state", "court", "document_title", "form_number", "role") if k in combined)
            return reply("confirmation_needed", "Does this describe your situation: " + summary + "? Please check the court and document carefully. Reply Yes, or tell me what to correct.")
        values = {k: v["value"] for k, v in state["facts"].items() if k in FIELDS}
        if values.get("user_type") not in {"self_represented_individual", "small_business_owner"}:
            state["asking"] = "user_type"
            return reply("clarification_needed", "Are you an individual being sued, or a business owner? Please describe your situation.")
        try:
            matter = MatterRequest(**values)
        except ValidationError:
            state["facts"], state["pending"] = {}, {}
            return reply("clarification_needed", "Those details could not be verified. Please give the state and the short title or form number printed on the document.")
        routed = self.router.evaluate(matter)
        if routed["state"] == "unsupported":
            return reply("unsupported", "These details do not fit the legal topics Pro-One currently covers. Check the court or agency's official help resources.")
        if routed["state"] != "exact_match":
            missing = routed["missing_fields"]
            if not missing:
                return reply("clarification_needed", "More than one topic fits. Please describe the court and document more specifically.")
            field = next((f for f in ("state", "country", "form_number", "court", "document_title", "role", "matter_type") if f in missing), missing[0])
            state["asking"] = field
            return reply("clarification_needed", QUESTIONS[field])
        workflow_id = routed["workflow_ids"][0]
        workflow = self.repository.get_workflow(workflow_id)
        if "return_date_and_time_if_shown" in workflow["intake"]["required_inputs"] and "listed_date" not in state["facts"]:
            state["asking"] = "listed_date"
            return reply("clarification_needed", QUESTIONS["listed_date"])
        answers = {"state": matter.state, "user_goal": state["question"] or message,
                   "court_name_or_locality": matter.court,
                   "document_title_or_form_number": matter.form_number or matter.document_title}
        if "listed_date" in state["facts"]:
            answers["return_date_and_time_if_shown"] = state["facts"]["listed_date"]["value"]
        from app.models.base import GenerationConfig
        risks = [r["id"] for r in self.repository.records["risks"].values()
                 if workflow_id in r["related_records"]["workflow_ids"] and r["risk_type"] == "deadline_risk"] if "listed_date" in state["facts"] else []
        result = ProductService(self.repository, self.settings, self.generation).respond(workflow_id, ProductResponseRequest(
            matter=matter, answers=answers, risk_ids=risks, generation=GenerationConfig(provider=provider, model=model),
            retrieval={"query": (state["question"] or message) + " " + (matter.form_number or matter.document_title), "limit": 5}))
        if result["response"]:
            return reply("answered", "Official-source excerpts for this demo." if provider == "testing" else "", result["response"])
        return reply(result["status"], "I couldn't produce an answer that passed Pro-One's source and safety checks. Please check the official court or agency information.")

    def research_reply(self, candidates, state, reply, provider, model):
        from app.models.base import GenerationConfig
        prior = state.get("research", {})
        values = deepcopy(prior)
        state.pop("asking", None)
        # Area changes start a fresh subject; no inherited source scope.
        if "legal_area" in candidates and candidates["legal_area"]["value"] != values.get("legal_area"):
            values = {}
        for name in ("legal_area", "user_posture", "court", "agency", "document_type"):
            if name in candidates:
                values[name] = candidates[name]["value"]
        sovereign = candidates.get("sovereign")
        if sovereign and sovereign["provenance"] == "user_explicit":
            values["sovereign"] = sovereign["value"]
            if sovereign["value"] == "federal":
                values.pop("state", None)
        if "legal_topics" in candidates:
            values["topics"] = [v.strip() for v in candidates["legal_topics"]["value"].split(",") if v.strip()][:12]
        for name in ("country", "state"):
            field = candidates.get(name)
            # Source documents and model inference cannot establish jurisdiction.
            if field and field["provenance"] == "user_explicit":
                values[name] = field["value"]
            elif field and field["value"] != values.get(name):
                values.pop(name, None)
        if values.get("state") in {"Virginia", "Maryland", "Florida", "New York", "California"}:
            values["country"] = "US"
        if values.get("sovereign") == "federal" and not values.get("country"):
            values["country"] = "US"
        state["research"], state["pending"] = values, {}
        state["facts"] = {k: {"value": v, "provenance": "user_explicit" if k in {"state", "country"} else "candidate_classification"}
                          for k, v in values.items() if isinstance(v, str)}
        if not values.get("state") and values.get("sovereign") != "federal":
            return reply("clarification_needed", "What state did this happen in?")
        if not values.get("country"):
            return reply("clarification_needed", "What country did this happen in?")
        try:
            matter = ResearchMatter(**values)
        except ValidationError:
            state.pop("research", None)
            return reply("clarification_needed", "Please describe the legal topic and where this happened.")
        result = GeneralLegalResearchService(self.repository, self.settings, self.generation).respond(
            matter, GenerationConfig(provider=provider, model=model))
        if result["response"]:
            return reply("answered", "", result["response"])
        return reply(result["status"], "I don't have enough authoritative support in the configured source collections to answer this question confidently.")

    def demo_candidates(self, message, document):
        """Explicitly labeled offline demonstration; never represented as AI extraction."""
        text = message + " " + document
        chosen = None
        if re.search(r"\bDC[- ]?402\b", text, re.I):
            chosen = next(c for c in self.catalog if "DC-402" in c["routing"]["selectors"].get("form_number", []))
        elif re.search(r"\b(SCC|Virginia.*business|Virginia.*LLC)\b", text, re.I):
            chosen = next(c for c in self.catalog if "scc" in c["workflow_id"])
        elif re.search(r"Maryland", text, re.I) and re.search(r"summons|sued|civil", text, re.I):
            chosen = next(c for c in self.catalog if c["jurisdiction"]["state"] == "Maryland")
        if not chosen:
            values = {}
            for name in ("Virginia", "Maryland"):
                if re.search(r"\b" + name + r"\b", message, re.I):
                    values["state"] = name
            if re.search(r"individual|being sued|got sued|defendant", message, re.I):
                values.update(user_type="self_represented_individual", role="defendant")
            if re.search(r"business owner|own.*business", message, re.I):
                values.update(user_type="small_business_owner", role="business_operator")
            return {k: {"value": v, "provenance": "inferred"} for k, v in values.items()}
        values = {"country": "US", "state": chosen["jurisdiction"]["state"], "user_type": chosen["user_types"][0],
                  **{k: v[0] for k, v in chosen["routing"]["selectors"].items()}}
        for name in ("Virginia", "Maryland"):
            if re.search(r"\b" + name + r"\b", message, re.I):
                values["state"] = name
        return {k: {"value": v, "provenance": "inferred"} for k, v in values.items()}
