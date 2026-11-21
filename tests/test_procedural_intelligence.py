"""Offline end-to-end and adversarial Procedural Intelligence acceptance cases."""

from copy import deepcopy
from datetime import date, timedelta
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.assistant import seal
from app.config import Settings
from app.generation import GenerationService
from app.main import app
from app.models.base import ModelResponse
from app.models.registry import ProviderRegistry
from app.national_corpus import CorpusError
from app.procedural_authority import ProceduralPublicationProvider, load_catalog
from app.procedural_models import Catalog
from app.procedural_research import (
    MatterFacts, ProceduralRequest, ProceduralResearchService, bounded_deadline, preview_deadline, select_requirements,
)
from app.repository import RecordRepository


FALL = "I slipped and fell at a restaurant in Virginia, I was injured, and I want them to pay me."
SERVED = "I was served a Virginia summons and complaint. What do I do next?"
FEDERAL = "How do I serve an initial complaint in federal court?"
FLORIDA = "How do I serve initial civil process in Florida?"
FORUM_FACTS = {"incident_locality": "City of Richmond", "defendant_location": "City of Richmond",
               "amount_sought": 51_000, "defendant_identity": "Example Restaurant LLC"}
FILED_FACTS = {**FORUM_FACTS, "complaint_filed": True, "summons_issued": True, "defendant_type": "virginia_llc"}


class SemanticFixture:
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = []

    def generate(self, request):
        self.calls.append(deepcopy(request))
        data = request.grounded_package
        if request.metadata["purpose"] == "claim_proposal":
            candidates = [binding for evidence in data["evidence"] for binding in evidence["procedure"]["bindings"]]
            if self.scenario == "unresolved":
                target = next(evidence for evidence in data["evidence"] if not evidence["procedure"]["bindings"])
                ids = [target["passage_id"]]
                statement = "The e-filing guidance applies today and everyone must use it."
            else:
                ids = candidates[0]["passage_ids"]
                statement = {
                    "unsupported": "A server has to be 25 or older.",
                    "strategy": "You should sue in circuit court and name the owner as defendant.",
                    "skip": "You can skip the complaint and serve the summons alone.",
                    "url": "The controlling source is https://example.invalid/procedure.",
                }.get(self.scenario, candidates[0]["text"])
            output = {"claims": [{"statement": statement, "issue": "civil procedure",
                                  "support": [{"passage_id": pid, "relationship": "supports"} for pid in ids],
                                  "jurisdiction": data["jurisdiction"]}]}
        else:
            output = {"result": "unsupported" if self.scenario == "verifier_rejects" else "entailed",
                      "passage_ids": [e["passage_id"] for e in data["cited_evidence"]],
                      "unsupported_fragments": [], "missing_qualifications": []}
        return ModelResponse(request.provider, request.model, True, output=output)


class ProceduralIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = RecordRepository()
        cls.catalog = load_catalog()
        cls.client = TestClient(app)

    def service(self, fixture=None):
        if not fixture:
            settings = Settings()
            return ProceduralResearchService(self.repo, settings, GenerationService(settings.registry({})))
        settings = Settings(provider="fixture", model="fixture-v1")
        registry = ProviderRegistry()
        registry.register("fixture", fixture, {"fixture-v1"})
        return ProceduralResearchService(self.repo, settings, GenerationService(registry))

    def choose(self, message, path, *, options=None, service=None, **kwargs):
        service = service or self.service()
        first = service.respond(ProceduralRequest(message=message, **(options or {})))
        self.assertEqual("choose_path", first["status"])
        return service.respond(ProceduralRequest(message=message, choice_token=first["choice_token"],
                                                  selected_path=path, **((options or {}) | kwargs)))

    def test_compensation_options_via_http_use_substantive_research(self):
        result = self.client.post("/research/procedure", json={"message": FALL}).json()
        self.assertEqual("choose_path", result["status"])
        self.assertIsNone(result["selected_path"])
        self.assertEqual({"possible_legal_area": "premises_liability", "desired_outcome": "compensation"}, result["inferences"])
        self.assertEqual({"claim", "demand", "negotiation", "civil_litigation"}, {row["kind"] for row in result["options"]})
        self.assertTrue(all(row["user_choice_required"] and row["evidence"] for row in result["options"]))
        self.assertTrue(result["substantive"]["sources"])
        self.assertFalse(result["external_action_allowed"])

    def test_explicit_litigation_choice_preserves_ambiguous_venue(self):
        result = self.choose(FALL, "va_litigation")
        self.assertEqual(("procedure_explained", "user", "forum"),
                         (result["status"], result["selection_origin"], result["stage"]))
        self.assertIn("incident_locality", result["missing_information"])
        self.assertIn("defendant_location", result["missing_information"])
        self.assertEqual([], result["available_transitions"])
        self.assertTrue(all(not row["forum_selected_for_user"] for row in result["forums"]))
        self.assertEqual({"district", "venue"}, set(result["evidence"]))
        self.assertTrue(all(item["current_as_of"] == self.catalog.reference_date for item in result["evidence"].values()))

    def test_user_can_choose_demand_without_entering_litigation(self):
        result = self.choose(FALL, "va_demand")
        self.assertEqual("option_explained", result["status"])
        self.assertEqual(["defendant_identity"], result["missing_information"])
        self.assertNotIn("requirements", result)

    def test_received_document_requires_court_and_exact_type(self):
        missing = self.choose(SERVED, "va_response")
        self.assertEqual("prerequisite_missing", missing["status"])
        self.assertEqual({"forum", "document_type"}, set(missing["missing_information"]))
        result = self.choose(SERVED, "va_response", forum="va_richmond",
                             facts={"document_type": "summons_and_complaint"})
        self.assertEqual("procedure_explained", result["status"])
        deadline = result["requirements"][0]["deadline"]
        self.assertEqual(("service_of_summons_and_complaint", 21), (deadline["trigger"], deadline["period"]))
        self.assertEqual("conditional", result["requirements"][0]["status"])
        self.assertIn("service_date", result["missing_information"])
        self.assertEqual({"response", "count"}, set(result["evidence"]))
        self.assertNotIn("due_date", result)

    def test_missing_jurisdiction_and_conflicting_sovereigns(self):
        service = self.service()
        missing = service.respond(ProceduralRequest(message="I slipped at a restaurant and want them to pay."))
        self.assertEqual("missing_jurisdiction", missing["status"])
        conflict = service.respond(ProceduralRequest(message=FALL, jurisdiction="US-FL"))
        self.assertEqual("jurisdiction_confirmation_required", conflict["status"])
        self.assertNotIn("evidence", conflict)
        self.assertEqual("outside_bounded_coverage", service.respond(ProceduralRequest(
            message="I slipped in West Virginia and want them to pay."))["status"])
        other = service.respond(ProceduralRequest(message="I fell in Maryland and want them to pay.",
                                                   jurisdiction="US-VA"))
        self.assertEqual("jurisdiction_confirmation_required", other["status"])

    def test_wrong_court_and_wrong_stage_do_not_leak_evidence(self):
        wrong = self.service().respond(ProceduralRequest(message=SERVED, forum="va_district"))
        self.assertEqual("wrong_forum", wrong["status"])
        self.assertNotIn("evidence", wrong)
        conflicting = self.service().respond(ProceduralRequest(
            message="I was served a Virginia General District Court summons and complaint.", forum="va_circuit"))
        self.assertEqual("wrong_forum", conflicting["status"])
        self.assertNotIn("choice_token", conflicting)
        result = self.choose(FALL, "va_litigation", stage="response")
        self.assertEqual("invalid_stage", result["status"])
        self.assertNotIn("requirements", result)

    def test_national_response_authority_is_a_scoped_reference(self):
        service = self.service()
        message = "I received a summons and complaint in Alaska."
        result = service.respond(ProceduralRequest(message=message))
        self.assertEqual("outside_bounded_coverage", result["status"])
        self.assertFalse(result["external_action_allowed"])
        reference, = result["reference_authorities"]
        self.assertEqual("Alaska R. Civ. P. 12(a)", reference["citation"])
        self.assertEqual("Alaska Superior Court", reference["court"])
        self.assertEqual("unresolved", reference["currentness"])
        self.assertNotIn("due_date", result)
        other = service.respond(ProceduralRequest(message=message, jurisdiction="US-TX"))
        self.assertNotIn("reference_authorities", other)
        excluded = service.respond(ProceduralRequest(message=message, authority_type="statute"))
        self.assertEqual([], excluded["reference_authorities"])

    def test_new_york_small_claims_reference_identifies_the_city_court(self):
        result = self.service().respond(ProceduralRequest(message="What are the small claims rules in New York?"))
        self.assertEqual("outside_bounded_coverage", result["status"])
        reference, = result["reference_authorities"]
        self.assertEqual("Civil Court of the City of New York", reference["court"])
        self.assertEqual("unresolved", reference["currentness"])
        self.assertFalse(result["external_action_allowed"])

    def test_wisconsin_filing_topics_return_dated_references_only(self):
        service = self.service()
        for message, count, citation in (
                ("What are the filing fees in Wisconsin Circuit Court?", 1, "Wis. Stat. § 814.61(1)(a)"),
                ("What are the e-filing rules in Wisconsin Circuit Court?", 6, "Wis. Stat. § 801.18(3)(b)")):
            with self.subTest(message=message):
                result = service.respond(ProceduralRequest(message=message))
                self.assertEqual("outside_bounded_coverage", result["status"])
                self.assertFalse(result["external_action_allowed"])
                self.assertNotIn("choice_token", result)
                references = result["reference_authorities"]
                self.assertEqual(count, len(references))
                self.assertIn(citation, {row["citation"] for row in references})
                for row in references:
                    self.assertEqual("Wisconsin Circuit Court", row["court"])
                    self.assertEqual("current_as_of", row["currentness"])
                    self.assertEqual("2026-11-04", row["current_as_of"])

    def test_prerequisite_cannot_be_skipped_by_requested_stage(self):
        result = self.choose(FALL, "va_litigation", stage="service", forum="va_circuit", facts=FORUM_FACTS)
        self.assertEqual("prerequisite_missing", result["status"])
        self.assertEqual(["complaint_filed", "summons_issued"], result["missing_information"])
        self.assertNotIn("evidence", result)

    def test_filing_method_fee_format_and_signing(self):
        result = self.choose(FALL, "va_litigation", stage="filing", forum="va_circuit", facts=FORUM_FACTS)
        self.assertEqual("procedure_explained", result["status"])
        rows = {row["id"]: row for row in result["requirements"]}
        self.assertEqual("paper", rows["paper_format"]["filing"]["method"])
        self.assertIn("8.5 by 11", rows["paper_format"]["filing"]["formatting"])
        self.assertTrue(rows["signature"]["filing"]["signature"])
        self.assertNotIn("amount_cents", rows["filing_fee"]["fee"])
        self.assertEqual("reference_only", rows["efiling"]["status"])
        self.assertNotIn("filing", rows["efiling"])
        self.assertEqual("court_instruction", result["evidence"]["fees"]["authority_type"])
        self.assertNotIn("service_proof", rows)

    def test_service_uses_entity_and_service_proof_controls(self):
        result = self.choose(FALL, "va_litigation", stage="service", forum="va_richmond", facts=FILED_FACTS)
        self.assertEqual("procedure_explained", result["status"])
        rows = {row["id"]: row for row in result["requirements"]}
        self.assertEqual(["Issued summons", "Copy of complaint"], rows["summons"]["service"]["documents"])
        self.assertIn("LLC", rows["entity_service"]["service"]["recipient"])
        self.assertTrue(rows["service_proof"]["service"]["proof"])
        self.assertNotIn("filing_fee", rows)
        unrelated = self.choose(FALL, "va_litigation", stage="service", forum="va_circuit",
                                facts=FILED_FACTS | {"defendant_type": "individual"})
        self.assertNotIn("service", unrelated["evidence"])

    def test_unreviewed_local_overlay_stays_in_exact_forum_and_stage(self):
        facts = FILED_FACTS | {"service_date": "2026-11-16"}
        local = self.choose(FALL, "va_litigation", stage="later_stages", forum="va_richmond", facts=facts)
        statewide = self.choose(FALL, "va_litigation", stage="later_stages", forum="va_circuit", facts=facts)
        self.assertIn("local", local["evidence"])
        self.assertNotIn("local", statewide.get("evidence", {}))
        overlay = next(row for row in local["requirements"] if row["local_overlay"])
        self.assertEqual(("reference_only", None), (overlay["status"], overlay["trigger"]))

    def test_appeal_and_post_judgment_have_distinct_stage_and_trigger(self):
        facts = FILED_FACTS | {"service_date": "2026-11-16"}
        before = self.choose(FALL, "va_litigation", stage="appeal", forum="va_circuit", facts=facts)
        self.assertEqual(("prerequisite_missing", ["order_entered"]), (before["status"], before["missing_information"]))
        after = facts | {"order_entered": True}
        for stage, authority in (("appeal", "appeal"), ("post_judgment", "postjudgment")):
            result = self.choose(FALL, "va_litigation", stage=stage, forum="va_circuit", facts=after)
            self.assertEqual("procedure_explained", result["status"])
            self.assertEqual({authority}, set(result["evidence"]))

    def test_deadline_preview_requires_trigger_currentness_and_complete_calendar(self):
        on = self.catalog.reference_date
        facts = MatterFacts(document_type="summons_and_complaint", service_date=on, service_mode="ordinary_service",
                            extension_status="none_confirmed", local_rules_checked=True)
        args = dict(path="va_response", stage="response", jurisdiction="US-VA", forum="va_circuit", facts=facts, on=on)
        nominal = on + timedelta(days=21)
        self.assertEqual(nominal, preview_deadline(self.catalog, **args, calendar={nominal: True}))
        self.assertIsNone(preview_deadline(self.catalog, **args, calendar={}))
        self.assertEqual(nominal + timedelta(days=1), preview_deadline(
            self.catalog, **args, calendar={nominal: False, nominal + timedelta(days=1): True}))
        self.assertIsNone(preview_deadline(self.catalog, **(args | {"facts": facts.model_copy(update={"service_mode": "waiver"})}),
                                           calendar={nominal: True}))
        rule = self.catalog.requirements["response_deadline"].deadline
        self.assertIsNone(bounded_deadline(rule, trigger="received_email", trigger_date=on, on=on,
                                           calendar={nominal: True}, conditions_confirmed=True))
        friday = date(2026, 11, 20)
        self.assertEqual(date(2026, 12, 14), bounded_deadline(
            rule, trigger=rule.trigger, trigger_date=friday, on=friday,
            calendar={date(2026, 12, 11): False, date(2026, 12, 14): True}, conditions_confirmed=True))

    def test_currentness_cannot_be_extended_or_inferred_from_capture(self):
        result = self.choose(FALL, "va_litigation", options={"as_of": "2026-11-17"})
        self.assertEqual("reference_only", result["status"])
        self.assertTrue(all(row["trigger"] is None for row in result["requirements"]))
        florida = self.choose(FLORIDA, "florida_service")
        self.assertEqual("reference_only", florida["status"])
        self.assertNotIn("service", florida["requirements"][0])
        self.assertEqual("unresolved", florida["evidence"]["florida_service"]["currentness"])

    def test_federal_and_state_isolation(self):
        result = self.choose(FEDERAL, "federal_service", forum="us_district")
        self.assertEqual("procedure_explained", result["status"])
        self.assertEqual({"federal_service"}, set(result["evidence"]))
        self.assertEqual("US", result["evidence"]["federal_service"]["jurisdiction"])
        self.assertEqual({}, select_requirements(self.catalog, path_id="federal_service", stage="service",
                                                 jurisdiction="US-VA", forum="us_district"))

    def test_historical_same_identity_edition_cannot_supply_current_rule(self):
        current = self.catalog.authorities["federal_service"].version
        historical = self.catalog.authorities["federal_service_old"].version
        self.assertEqual(current.authority_id, historical.authority_id)
        self.assertNotEqual(current.version_id, historical.version_id)
        self.assertEqual("historical", historical.evidence_status)
        fixture = self.catalog.model_dump(mode="json")
        fixture["requirements"]["federal_service"]["evidence"][0]["authority"] = "federal_service_old"
        service = self.service()
        service.catalog = Catalog.model_validate(fixture)
        result = self.choose(FEDERAL, "federal_service", service=service, forum="us_district")
        self.assertEqual("reference_only", result["status"])
        self.assertNotIn("service", result["requirements"][0])

    def test_authority_type_filter_rejects_wrong_family(self):
        result = self.service().respond(ProceduralRequest(message=FEDERAL, authority_type="statute"))
        self.assertEqual("no_authoritative_support", result["status"])
        self.assertNotIn("evidence", result)

    def test_explicit_selection_requires_bound_receipt(self):
        service = self.service()
        initial = service.respond(ProceduralRequest(message=FALL))
        for message, token in ((FALL, ""), (FALL, "modified." + initial["choice_token"]),
                               (FALL + " Changed facts.", initial["choice_token"]),
                               (FALL, seal({"turn": 1}))):
            with self.subTest(token=bool(token), same_message=message == FALL):
                result = service.respond(ProceduralRequest(message=message, selected_path="va_litigation", choice_token=token))
                self.assertEqual("explicit_choice_required", result["status"])
                self.assertNotIn("requirements", result)

    def test_user_cannot_delegate_strategy_or_external_action(self):
        for message, expected in (("Choose the right court for me. " + FALL, "legal_judgment_required"),
                                  ("File a complaint on my behalf. " + FALL, "reserved_legal_act")):
            result = self.service().respond(ProceduralRequest(message=message))
            self.assertEqual(expected, result["status"])
            self.assertFalse(result["external_action_allowed"])
            self.assertNotIn("choice_token", result)

    def test_arbitrary_url_and_changed_bytes_are_refused(self):
        provider = ProceduralPublicationProvider("rules", self.catalog)
        with self.assertRaisesRegex(CorpusError, "selector_not_allowlisted"):
            provider.source_url("https://vacourts.gov/other")
        with self.assertRaisesRegex(CorpusError, "snapshot_unreviewed"):
            list(provider.normalize("rules", b"fake rules"))
        invalid = self.client.post("/research/procedure", json={"message": FALL, "source_url": "https://evil.invalid"})
        self.assertEqual(422, invalid.status_code)

    def test_schema_rejects_wrong_cross_record_scope_and_cycles(self):
        graph = self.catalog.model_dump(mode="json")
        graph["requirements"]["response_deadline"]["evidence"][0]["authority"] = "federal_service"
        with self.assertRaisesRegex(ValidationError, "invalid procedure evidence"):
            Catalog.model_validate(graph)
        graph = self.catalog.model_dump(mode="json")
        graph["requirements"]["richmond_scheduling"]["forum"] = "va_circuit"
        with self.assertRaisesRegex(ValidationError, "invalid procedure evidence"):
            Catalog.model_validate(graph)
        graph = self.catalog.model_dump(mode="json")
        graph["paths"]["va_litigation"]["stages"]["filing"]["transitions"] = ["forum"]
        with self.assertRaisesRegex(ValidationError, "invalid stage transition"):
            Catalog.model_validate(graph)

    def test_independent_verification_receives_procedural_context(self):
        adapter = SemanticFixture("verified")
        result = self.choose(FEDERAL, "federal_service", service=self.service(adapter), forum="us_district")
        self.assertEqual("verified", result["responses"][0]["verification"])
        self.assertEqual(["claim_proposal", "claim_verification"], [item.metadata["purpose"] for item in adapter.calls])
        evidence = adapter.calls[1].grounded_package["cited_evidence"][0]
        binding = evidence["procedure"]["bindings"][0]
        self.assertEqual(("US", "us_district", "service"), (binding["jurisdiction"], binding["forum"], binding["stage"]))
        self.assertEqual("current_as_of", evidence["source"]["currentness"]["status"])
        self.assertIn("artifact_hash", result["evidence"]["federal_service"])

    def test_failed_semantic_verification_keeps_exact_evidence(self):
        adapter = SemanticFixture("verifier_rejects")
        result = self.choose(FEDERAL, "federal_service", service=self.service(adapter), forum="us_district")
        response = result["responses"][0]
        self.assertEqual("no_verified_claims", response["verification"])
        self.assertEqual(result["evidence"]["federal_service"]["excerpt"], response["sections"][0]["text"])
        self.assertEqual(2, len(adapter.calls))

    def test_model_strategy_prerequisite_hallucination_and_urls_are_rejected(self):
        for scenario in ("strategy", "skip", "unsupported", "url"):
            with self.subTest(scenario=scenario):
                adapter = SemanticFixture(scenario)
                result = self.choose(FEDERAL, "federal_service", service=self.service(adapter), forum="us_district")
                response = result["responses"][0]
                self.assertEqual("no_verified_claims", response["verification"])
                self.assertEqual(result["evidence"]["federal_service"]["excerpt"], response["sections"][0]["text"])
                self.assertEqual(1, len(adapter.calls))

    def test_model_cannot_promote_unresolved_publisher_guidance(self):
        adapter = SemanticFixture("unresolved")
        result = self.choose(FALL, "va_litigation", service=self.service(adapter), stage="filing", forum="va_circuit",
                             facts=FORUM_FACTS)
        self.assertEqual("procedure_explained", result["status"])
        self.assertFalse(any(response["verification"] == "verified" for response in result["responses"]))
        self.assertNotIn("claim_verification", [request.metadata["purpose"] for request in adapter.calls])
        self.assertNotIn("everyone must use it", str(result))

    def test_production_route_is_closed(self):
        with patch("app.main.settings", Settings(mode="production")):
            response = self.client.post("/research/procedure", json={"message": FALL})
        self.assertEqual(403, response.status_code)
        self.assertEqual("procedural_release_review_required", response.json()["detail"]["code"])
