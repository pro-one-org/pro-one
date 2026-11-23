"""Offline nationwide isolation, publication replay and routing regressions."""
from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.capabilities import ResearchMatter
from app.national_certifications import certified_basis
from app.coverage_audit import build, retained_observations, state_baseline
from app.coverage_health import check
from app.jurisdictions import jurisdiction_id, possible_tribal_scope, registry, tribal_registry
from app.main import app
from app.national_corpus import AuthorityVersion, CorpusError, CorpusQuery, FetchedSource
from app.national_corpus_store import SQLiteNormalizedCorpus
from app.national_coverage import coverage, manifest
from app.national_excerpt_research import RetainedLegislativeResearch
from app.national_publications import LegislativeExcerpts
from app.procedural_research import infer_jurisdiction


class NationalCoverageTests(unittest.TestCase):
    def test_new_york_fault_amendment_keeps_the_commencement_date_and_prior_text(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="New York", legal_area="torts",
                               topics=["fault_allocation"], authority_status="unresolved")
        documents = [provider.fetch(key) for key in provider.search(query)]
        amended, = (doc for doc in documents if doc.source["citation"]["preferred_citation"] == "N.Y. CPLR 1411")
        self.assertIn("article fifty-one of the insurance law", amended.text)
        self.assertEqual(amended.source["dates"]["effective_from"], "2026-05-26")
        self.assertTrue(any("actions and proceedings commenced on or after such date" in doc.text for doc in documents))
        prior = [provider.fetch(key) for key in provider.search(query.model_copy(update={"authority_status": "historical"}))]
        predecessor, = (doc for doc in prior if doc.source["citation"]["preferred_citation"] == "N.Y. CPLR 1411")
        self.assertNotIn("article fifty-one", predecessor.text)
        self.assertEqual(predecessor.source["dates"]["effective_through"], "2026-05-26")

    def test_dc_vulnerable_user_fault_exception_retains_the_scope_and_other_doctrines(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="District of Columbia", sovereign="district", legal_area="torts",
                               topics=["fault_allocation"], authority_status="current_as_of", authority_as_of="2026-04-29")
        passages = [provider.fetch(key).text for key in provider.search(query)]
        self.assertTrue(any("greater than the aggregated total negligence" in text and "public highway or sidewalk" in text
                            for text in passages))
        self.assertTrue(any("joint and several liability or the last clear chance doctrine" in text for text in passages))
        self.assertTrue(any('"Vulnerable user" means an individual' in text for text in passages))

    def test_dc_tolling_replay_retains_the_qualifying_text_after_the_list(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="District of Columbia", sovereign="district", legal_area="torts",
                                topics=["tolling"], authority_status="current_as_of", authority_as_of="2026-04-29")
        passages = [provider.fetch(key).text for key in provider.search(matter)]
        general, = (text for text in passages if "(3) imprisoned" in text)
        self.assertTrue(general.endswith("after the disability is removed."))
        self.assertIn("Except as provided by subsection (b)", general)
        self.assertTrue(any("instrument under seal" in text for text in passages))

    def test_historical_illinois_tolling_cases_preserve_different_survival_rule_readings(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="Illinois", legal_area="torts",
                                topics=["tolling"], authority_types=["opinion"], authority_status="historical")
        passages = [provider.fetch(key).text for key in provider.search(matter)]
        self.assertTrue(any("does not contemplate a representative" in text for text in passages))
        self.assertTrue(any("the deceased’s representative had two years" in text for text in passages))
        self.assertEqual(provider.search(matter.model_copy(update={"authority_status": "current_as_of",
                                                                 "authority_as_of": "2019-09-26"})), [])

    def test_signed_mississippi_equal_pay_act_keeps_its_effective_date_and_topic(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="Mississippi", legal_area="employment",
                                topics=["equal_pay"], authority_status="unresolved")
        matches = provider.search(matter)
        self.assertEqual(len(matches), 2)
        self.assertTrue(any("same establishment" in provider.fetch(match).text for match in matches))
        manifest_row = manifest("US-MS")
        equal_pay = {selector: row for selector, row in manifest_row["passages"].items()
                     if manifest_row["sources"][row["source_id"]]["category"] == "wage_equal_pay"
                     and "ch. 490" in row["citation"]}
        self.assertEqual({row["effective_from"] for row in equal_pay.values()}, {"2022-07-01"})
        self.assertTrue(equal_pay.keys().isdisjoint(coverage("US-MS")["cells"]["wages.payment"]["passage_selectors"]))
        louisiana = provider.search(matter.model_copy(update={"state": "Louisiana"}))
        self.assertTrue(set(matches).isdisjoint(louisiana))

    def test_official_mandatory_form_reference_is_scoped_to_its_action_and_court(self):
        shells = {row["action_type"]: row for row in coverage("US-CA")["action_shells"]}
        self.assertEqual(shells["complaint"]["official_form_references"], [])
        forms = {row["publisher_identifier"]: row for row in shells["small_claim"]["official_form_references"]}
        form = forms["SC-100"]
        self.assertIn("Plaintiff initiating", form["applicability"])
        self.assertIn("Defendant asserting a claim", forms["SC-120"]["applicability"])
        self.assertEqual(form["revision"], "2026-01-01")
        self.assertEqual(form["court_scope"], "small_claims")
        self.assertEqual(form["requirement_currentness"], "unresolved")
        self.assertIn("Mandatory Form",
                      manifest("US-CA")["passages"][form["requirement_passage_selector"]]["text"])
        self.assertEqual((form["automated_completion"], shells["small_claim"]["execution"]),
                         ("disabled", "disabled"))
        self.assertTrue(all(form["id"] != other["id"] for shell in coverage("US-OR")["action_shells"]
                            for other in shell["official_form_references"]))

    def test_small_claim_forms_keep_mandatory_and_substantially_similar_requirements_distinct(self):
        idaho, = (row for row in coverage("US-ID")["action_shells"] if row["action_type"] == "small_claim")
        idaho_forms = {row["publisher_identifier"]: row for row in idaho["official_form_references"]}
        self.assertEqual(idaho_forms["CAO SC 1-2"]["requirement_level"], "required_for_stated_scope")

        utah, = (row for row in coverage("US-UT")["action_shells"] if row["action_type"] == "small_claim")
        utah_forms = {row["publisher_identifier"]: row for row in utah["official_form_references"]}
        odr, ordinary = (utah_forms[key] for key in ("2001SC", "1025XX"))
        self.assertIn("participating in online dispute resolution", odr["applicability"])
        self.assertIn("outside the online dispute resolution program", ordinary["applicability"])
        for form in (odr, ordinary):
            self.assertEqual(form["requirement_level"], "substantially_similar_form_required")
            self.assertEqual(form["requirement_citation"], "Utah Rules of Small Claims Procedure 1(c)")
            self.assertEqual(form["automated_completion"], "disabled")

    def test_premises_open_and_obvious_authority_stays_in_its_jurisdiction(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="Ohio", legal_area="torts", topics=["premises_liability"],
                                authority_types=["opinion"], authority_status="historical")
        ohio, = provider.search(matter)
        self.assertIn("obviates the duty to warn", provider.fetch(ohio).text)
        michigan, = provider.search(matter.model_copy(update={"state": "Michigan"}))
        self.assertIn("relevant to breach and the parties’ comparative fault", provider.fetch(michigan).text)
        self.assertNotEqual(ohio, michigan)

    def test_maine_dated_response_is_scoped_and_review_only(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Maine", legal_area="civil_procedure",
                               topics=["initial_response"], authority_status="current", authority_as_of="2026-06-01")
        key, = provider.search(query)
        self.assertIn("within 50 days after such service", provider.fetch(key).text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_as_of": "2026-11-21"})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "New Hampshire"})))
        filing, = provider.search(query.model_copy(update={"topics": ["electronic_filing"]}))
        self.assertIn("unless the court provides otherwise through an administrative order", provider.fetch(filing).text)
        shell, = [row for row in coverage("US-ME")["action_shells"] if row["action_type"] == "answer"]
        self.assertEqual((shell["readiness"], shell["execution"]), ("blocked", "disabled"))

    def test_arizona_wage_agency_claim_has_distinct_topic_and_scope(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Arizona", legal_area="employment",
                               topics=["wage_agency_claim"], authority_status="unresolved")
        key, = provider.search(query)
        document = provider.fetch(key)
        self.assertIn("does not exceed $12,000", document.text)
        self.assertIn("within one year of the accrual of such claim", document.text)
        self.assertNotIn(key, provider.search(query.model_copy(update={"topics": ["wage_payment"]})))

    def test_washington_certified_pdf_binds_section_text_and_publisher_date(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Washington", legal_area="consumer",
                               topics=["consumer_public_interest"], authority_status="current",
                               authority_as_of="2024-07-12")
        key, = provider.search(query)
        self.assertIn("has the capacity to injure other persons", provider.fetch(key).text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_as_of": "2026-11-21"})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "Oregon"})))

        record = manifest("US-WA")
        row, = [entry for entry in record["passages"].values()
                if entry["citation"] == "Wash. Rev. Code § 19.86.093"]
        source = record["sources"][row["source_id"]]
        with self.assertRaisesRegex(ValueError, "certified_excerpt_or_date_mismatch"):
            certified_basis("US-WA", source["url"], row["publisher_sha256"], row["publisher_path"],
                            row["citation"], row["text"].replace("other persons", "the claimant"))

    def test_consumer_enforcement_and_notice_have_distinct_research_topics(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="South Carolina", legal_area="consumer",
                               topics=["consumer_agency_enforcement"], authority_status="unresolved")
        enforcement, = provider.search(query)
        self.assertIn("in the name of the State", provider.fetch(enforcement).text)
        self.assertNotIn(enforcement, provider.search(query.model_copy(update={"topics": ["private_action"]})))

        wyoming = query.model_copy(update={"state": "Wyoming", "topics": ["consumer_pre_suit_notice"]})
        notice, = provider.search(wyoming)
        self.assertIn("notice in writing to the alleged violator", provider.fetch(notice).text)
        limitations, = provider.search(wyoming.model_copy(update={"topics": ["consumer_limitations"]}))
        self.assertNotEqual(notice, limitations)
        self.assertIn("after the furnishing of notice", provider.fetch(limitations).text)

    def test_minnesota_private_relief_is_distinct_from_public_injunctions(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Minnesota", legal_area="consumer",
                               topics=["consumer_agency_enforcement"], authority_status="unresolved")
        public, = provider.search(query)
        self.assertIn("the attorney general or any county attorney", provider.fetch(public).text.lower())
        remedies, = provider.search(query.model_copy(update={"topics": ["consumer_remedies"]}))
        self.assertIn("personal, family, household, or agricultural purposes", provider.fetch(remedies).text)
        self.assertNotEqual(public, remedies)
        iowa, = provider.search(query.model_copy(update={"state": "Iowa"}))
        self.assertNotEqual(public, iowa)
        self.assertIn("Iowa Code § 714.16(7)", provider.fetch(iowa).source["citation"]["preferred_citation"])

    def test_new_york_consumer_research_distinguishes_private_and_attorney_general_scope(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="New York", legal_area="consumer",
                               topics=["private_action"], authority_status="unresolved")
        private, = provider.search(query)
        self.assertIn("injured by reason of any deceptive act or deceptive practice", provider.fetch(private).text)
        agency, = provider.search(query.model_copy(update={"topics": ["consumer_agency_enforcement"]}))
        self.assertIn("unfair, deceptive, or abusive", provider.fetch(agency).text)
        self.assertNotEqual(agency, private)
        self.assertFalse(provider.search(query.model_copy(update={
            "authority_status": "current", "authority_as_of": "2026-04-03",
        })))

    def test_oregon_debt_pleading_and_judgment_evidence_are_review_only(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Oregon", legal_area="consumer_debt",
                               topics=["debt_pleading"], authority_status="historical")
        key, = provider.search(query)
        self.assertIn("on the debt buyer’s behalf", provider.fetch(key).text)
        actions = {action["action_type"]: action for action in coverage("US-OR")["action_shells"]}
        for action, topic, subsection in (
            ("complaint", "debt_pleading", "646A.670(1)"),
            ("answer", "debt_judgment_proof", "646A.670(2)"),
        ):
            shell = actions[action]
            evidence, = shell["review_evidence"][topic]
            self.assertIn(subsection, evidence["citation"])
            self.assertEqual(evidence["currentness"], "historical")
            self.assertNotIn(topic, shell["procedure_evidence"])
            self.assertEqual((shell["readiness"], shell["execution"]), ("blocked", "disabled"))

    def test_texas_debt_response_preserves_court_and_service_branches(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Texas", legal_area="consumer_debt", topics=["debt_response"],
                               court="Texas Justice Court", authority_status="unresolved")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("14th day after the day the defendant was served", text)
        self.assertIn("42nd day after the day the citation was issued", text)
        self.assertFalse(provider.search(query.model_copy(update={"court": "Texas District Court"})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "New Mexico"})))
        shell, = [row for row in coverage("US-TX")["action_shells"] if row["action_type"] == "answer"]
        evidence, = shell["review_evidence"]["debt_response"]
        self.assertEqual(evidence["court"], "Texas Justice Court")
        self.assertNotIn("debt_response", shell["procedure_evidence"])
        self.assertEqual((shell["readiness"], shell["execution"]), ("blocked", "disabled"))

    def test_new_york_debt_response_keeps_the_two_court_branches_separate(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="New York", legal_area="consumer_debt", topics=["debt_response"],
                               court="Civil Court of the City of New York", authority_status="unresolved")
        city, = provider.search(query)
        self.assertIn("after proof of service is filed with the clerk", provider.fetch(city).text)
        outside, = provider.search(query.model_copy(update={"court": "City Courts Outside the City of New York"}))
        self.assertIn("after service is complete", provider.fetch(outside).text)
        self.assertNotEqual(city, outside)
        self.assertFalse(provider.search(query.model_copy(update={"court": "New York Town and Village Justice Courts"})))

    def test_dc_consumer_enforcement_snapshot_and_later_codification_remain_distinct(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="District of Columbia", sovereign="district",
                               legal_area="consumer", topics=["consumer_agency_enforcement"],
                               authority_status="current", authority_as_of="2026-04-29")
        prior, = provider.search(query)
        self.assertNotIn("Dissolving an entity", provider.fetch(prior).text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_as_of": "2026-11-21"})))
        later, = provider.search(query.model_copy(update={"authority_status": "unresolved", "authority_as_of": None}))
        self.assertIn("Dissolving an entity", provider.fetch(later).text)
        self.assertNotEqual(prior, later)

    def test_minnesota_contract_pleading_retains_nominal_damages_qualification(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Minnesota", legal_area="contracts",
                               topics=["contract_breach"], authority_types=["opinion"],
                               authority_status="historical")
        documents = [provider.fetch(key) for key in provider.search(query)]
        park, = [doc for doc in documents if "Park Nicollet Clinic" in doc.source["citation"]["preferred_citation"]]
        self.assertIn("conditions precedent", park.text)
        self.assertIn("but see Sloggy", park.text)
        self.assertFalse(provider.search(query.model_copy(update={"topics": ["accepted_goods_damages"]})))
        self.assertFalse(provider.search(query.model_copy(update={
            "authority_status": "current", "authority_as_of": "2026-11-21",
        })))

    def test_new_york_wage_amendment_keeps_frequency_and_tolling_separate(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="New York", legal_area="employment",
                               topics=["wage_enforcement"], authority_status="unresolved")
        key, = provider.search(query)
        remedy = provider.fetch(key)
        self.assertEqual(remedy.source["dates"]["effective_from"], "2025-05-09")
        self.assertIn("no less frequently than semi-monthly", remedy.text)
        self.assertIn("employees performing the same work", remedy.text)
        self.assertIn("causes pending or commenced on or after May 9, 2025",
                      remedy.source["corpus_provenance"]["locator"])
        limitation, = provider.search(query.model_copy(update={"topics": ["wage_limitations"]}))
        self.assertNotEqual(key, limitation)
        self.assertIn("the commissioner commences an investigation, whichever is earlier",
                      provider.fetch(limitation).text)
        self.assertFalse(provider.search(query.model_copy(update={
            "authority_status": "current", "authority_as_of": "2025-05-16",
        })))

    def test_enacted_contract_limitation_references_keep_tolling_conditions(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Arkansas", legal_area="contracts",
                               topics=["written_contract_limitations"], authority_status="historical")
        arkansas, = provider.search(query)
        self.assertIn("partial payment or written acknowledgment of default", provider.fetch(arkansas).text)
        new_mexico, = provider.search(query.model_copy(update={"state": "New Mexico"}))
        self.assertNotEqual(arkansas, new_mexico)
        text = provider.fetch(new_mexico).text
        self.assertIn("agreement in writing to defer the payment", text)
        self.assertIn("the happening of the contingency", text)

    def test_new_jersey_contract_limit_preserves_governing_exceptions(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="New Jersey", legal_area="contracts",
                               topics=["contract_limitations"], authority_status="historical")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("not under seal", text)
        self.assertIn("contract for sale governed by N.J.S.12A:2-725", text)
        self.assertIn("owners comprise a majority of the board", text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_maryland_wrongful_death_timing_retains_statutory_exceptions(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Maryland", legal_area="torts",
                               topics=["wrongful_death_limitations"], authority_status="unresolved")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("whichever is the shorter", text)
        self.assertIn("criminal homicide under State or federal law", text)
        self.assertIn("unsealed and available to the public", text)
        self.assertNotIn(key, provider.search(query.model_copy(update={"topics": ["limitations"]})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_colorado_wrongful_death_timing_keeps_the_exception_distinct(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Colorado", legal_area="torts",
                               topics=["wrongful_death_limitations"], authority_status="historical")
        selectors = provider.search(query)
        passages = [provider.fetch(selector).text for selector in selectors]
        ordinary, = [text for text in passages if "within two years" in text]
        exception, = [text for text in passages if "within four years" in text]
        self.assertIn("except as described in subsection (2)", ordinary)
        self.assertIn("same criminal episode", exception)
        self.assertIn("leaving the scene of a crash that resulted in the death", exception)
        self.assertTrue(any("accrue on the date of death" in text for text in passages))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))
        self.assertTrue(set(selectors).isdisjoint(provider.search(query.model_copy(update={"state": "Wyoming"}))))

    def test_service_deadline_coverage_requires_timing_evidence(self):
        georgia = coverage("US-GA")
        methods = set(georgia["cells"]["procedure.service"]["passage_selectors"])
        timing, = georgia["cells"]["deadlines.service"]["passage_selectors"]
        self.assertTrue(methods)
        self.assertNotIn(timing, methods)
        self.assertIn("will not invalidate a later service", georgia["passages"][timing]["text"])
        wyoming = coverage("US-WY")
        timing, = wyoming["cells"]["deadlines.service"]["passage_selectors"]
        self.assertIn("Time Limit for Service", wyoming["passages"][timing]["text"])
        self.assertNotIn(timing, wyoming["cells"]["procedure.service"]["passage_selectors"])

    def test_louisiana_request_and_fee_timing_stay_in_blocked_review(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Louisiana", legal_area="civil_procedure",
                               topics=["service_time_limit"], authority_status="unresolved")
        request, fees = sorted((provider.fetch(key).text for key in provider.search(query)))
        self.assertIn("shall be requested on all named defendants within ninety days", request)
        self.assertIn("except summary and executory proceedings", request)
        self.assertIn("whichever period is longer", fees)
        self.assertIn("litigants permitted to litigate without the payment of costs", fees)
        historical, = provider.search(query.model_copy(update={"authority_status": "historical"}))
        self.assertIn("prospective application only", provider.fetch(historical).text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))
        complaint = next(shell for shell in coverage("US-LA")["action_shells"] if shell["action_type"] == "complaint")
        self.assertEqual(len(complaint["review_evidence"]["service_time_limit"]), 3)
        fee_evidence, = [row for row in complaint["review_evidence"]["service_time_limit"]
                         if row["citation"] == "La. Code Civ. Proc. art. 1201(D)–(F)"]
        self.assertEqual(fee_evidence["effective_from"], "2026-08-01")
        self.assertEqual(fee_evidence["currentness"], "unresolved")
        self.assertNotIn("service_time_limit", complaint["procedure_evidence"])
        self.assertEqual((complaint["readiness"], complaint["execution"]), ("blocked", "disabled"))

    def test_baseline_separates_sale_of_goods_and_general_contract_damages(self):
        damages = state_baseline()["contract.damages"]
        by_category = damages["by_authority_category"]
        self.assertIn("US-MO", by_category["contract_damages"]["with_passages"])
        self.assertIn("US-MO", by_category["sale_price_recovery"]["with_passages"])
        self.assertIn("US-WA", by_category["general_contract_damages"]["with_passages"])
        category_passages = Counter()
        for category in by_category.values():
            category_passages.update(category["passages"])
        self.assertEqual(category_passages, damages["passages"])

    def test_maryland_district_summons_versions_preserve_renewal_change(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Maryland", court="District Court of Maryland",
                               legal_area="civil_procedure", topics=["service_time_limit"],
                               authority_status="historical")
        documents = [provider.fetch(key) for key in provider.search(query)]
        by_effective_date = {document.source["dates"]["effective_from"]: document for document in documents}
        older = by_effective_date["2023-01-01"]
        later = by_effective_date["2023-07-01"]
        self.assertEqual(older.source["dates"]["effective_through"], "2023-07-01")
        for document in (older, later):
            self.assertIn("within 60 days after the date it is issued", document.text)
        self.assertNotIn("supplemental military service affidavit", older.text)
        self.assertIn("supplemental military service affidavit", later.text)
        self.assertFalse(provider.search(query.model_copy(update={"court": "Maryland Circuit Courts"})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_pennsylvania_service_timing_distinguishes_location_and_reissuance(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Pennsylvania", legal_area="civil_procedure",
                               topics=["service_time_limit"], authority_status="unresolved")
        documents = [provider.fetch(key) for key in provider.search(query)]
        by_citation = {document.source["citation"]["preferred_citation"]: document.text for document in documents}
        self.assertIn("within the Commonwealth within 30 days", by_citation["Pa. R. Civ. P. 401(a)"])
        self.assertIn("outside the Commonwealth within ninety days",
                      by_citation["Pa. R. Civ. P. 404 (outside-Commonwealth timing)"])
        self.assertIn("only if the writ or complaint has not been served on any defendant",
                      by_citation["Pa. R. Civ. P. 401(b)(1)–(2)"])
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_michigan_certified_summons_timing_stays_in_blocked_review(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Michigan", court="Michigan courts governed by Chapter 2",
                               legal_area="civil_procedure", topics=["service_time_limit"], authority_status="current",
                               authority_as_of="2026-11-18")
        documents = [provider.fetch(key) for key in provider.search(query)]
        by_citation = {doc.source["citation"]["preferred_citation"]: doc.text for doc in documents}
        self.assertIn("while a motion challenging the sufficiency", by_citation["MCR 2.102(D)"])
        self.assertIn("as to a defendant added", by_citation["MCR 2.102(E)"].lower())
        self.assertIn("within 28 days after notice", by_citation["MCR 2.102(F)"])
        self.assertFalse(provider.search(query.model_copy(update={"authority_as_of": "2026-11-19"})))
        self.assertFalse(provider.search(query.model_copy(update={"court": "Small Claims Division of the Michigan District Court"})))
        complaint = next(shell for shell in coverage("US-MI")["action_shells"] if shell["action_type"] == "complaint")
        self.assertEqual({row["citation"] for row in complaint["review_evidence"]["service_time_limit"]},
                         set(by_citation))
        self.assertNotIn("service_time_limit", complaint["procedure_evidence"])
        self.assertEqual((complaint["readiness"], complaint["execution"]), ("blocked", "disabled"))

    def test_delaware_service_deadline_certification_stays_with_its_court_and_edition(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Delaware", court="Delaware Court of Common Pleas",
                               legal_area="civil_procedure", topics=["service_time_limit"],
                               authority_status="current", authority_as_of="2023-01-10")
        key, = provider.search(query)
        self.assertIn("cannot show good cause", provider.fetch(key).text)
        self.assertFalse(provider.search(query.model_copy(update={"court": "Delaware Superior Court"})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_as_of": "2023-01-11"})))

    def test_delaware_contract_limitations_keep_exceptions_and_account_accrual(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Delaware", legal_area="contracts",
                               topics=["contract_limitations"], authority_status="unresolved")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("involving at least $100,000", text)
        self.assertIn("prior to the expiration of 20 years", text)
        self.assertIn("date of the denial of the claim by the insurer", text)
        accrual, = provider.search(query.model_copy(update={"topics": ["contract_accrual"]}))
        self.assertNotEqual(accrual, key)
        self.assertIn("while such account continues open and current", provider.fetch(accrual).text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-10-01"})))

    def test_colorado_service_preserves_substituted_service_conditions(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Colorado", legal_area="civil_procedure",
                               topics=["service_of_process"], authority_status="historical")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("due diligence has been used to attempt personal service", text)
        self.assertIn("authorize delivery to be made to the person deemed appropriate", text)
        self.assertIn("order the process to be mailed", text)
        self.assertNotIn(key, provider.search(query.model_copy(update={"topics": ["service_time_limit"]})))
        self.assertNotIn(key, provider.search(query.model_copy(update={"state": "Wyoming"})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_wyoming_commencement_preserves_conditional_refiling(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Wyoming", legal_area="civil_procedure",
                               topics=["commencement"], authority_status="historical")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("except when an action has been dismissed pursuant to Rule 4(w)", text)
        self.assertIn("if service is obtained within 90 days of the applicable statute of limitations", text)
        self.assertNotIn(key, provider.search(query.model_copy(update={"topics": ["service_time_limit"]})))
        self.assertNotIn(key, provider.search(query.model_copy(update={"state": "Vermont"})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_mississippi_service_time_does_not_supply_a_response_deadline(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Mississippi", legal_area="civil_procedure",
                               topics=["service_time_limit"], authority_status="historical")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("within 120 days after the filing of the complaint", text)
        self.assertIn("cannot show good cause", text)
        self.assertIn("without prejudice", text)
        self.assertNotIn(key, provider.search(query.model_copy(update={"topics": ["initial_response"]})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_wage_agency_authority_stays_scoped_to_the_publisher_and_claim_route(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="North Dakota", legal_area="employment", authority_status="unresolved",
                               topics=["wage_agency_claim"])
        key, = provider.search(query)
        doc = provider.fetch(key)
        self.assertIn("within two years from the date the wages are due", doc.text)
        self.assertIn("assigning employee", doc.text)
        michigan, = provider.search(query.model_copy(update={"state": "Michigan"}))
        self.assertIn("within 12 months after the alleged violation", provider.fetch(michigan).text)
        self.assertFalse(provider.search(query.model_copy(update={"topics": ["wage_limitations"]})))

    def test_ohio_written_contract_limitation_keeps_both_authenticated_versions(self):
        provider = LegislativeExcerpts("US-OH")
        versions = {}
        for selector, row in manifest("US-OH")["passages"].items():
            if row["citation"] == "Ohio Rev. Code § 2305.06":
                observation, = provider.normalize(selector, row["text"].encode())
                versions[observation.version.currentness] = observation.version
        older, later = versions["historical"], versions["unresolved"]
        self.assertEqual(older.authority_id, later.authority_id)
        self.assertNotEqual(older.version_id, later.version_id)
        self.assertEqual(older.effective_until, later.effective_from)
        self.assertEqual(later.effective_from, date(2026, 9, 23))
        self.assertNotIn("2305.041", older.text)
        self.assertIn("division (B) of section 2305.041", later.text)

    def test_colorado_contract_accrual_and_debt_exceptions_use_separate_topics(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Colorado", legal_area="contracts", authority_status="unresolved",
                               topics=["contract_accrual"])
        accrual, = provider.search(query)
        self.assertIn("breach is discovered or should have been discovered", provider.fetch(accrual).text)
        limitations, = provider.search(query.model_copy(update={"topics": ["contract_limitations"]}))
        self.assertNotEqual(accrual, limitations)
        self.assertIn("except as otherwise provided in section 13-80-103.5", provider.fetch(limitations).text)
        debt, = provider.search(query.model_copy(update={"legal_area": "consumer_debt", "topics": ["debt_limitations"]}))
        self.assertIn("a liquidated debt or an unliquidated, determinable amount", provider.fetch(debt).text)
        self.assertFalse(provider.search(query.model_copy(update={"legal_area": "torts"})))

    def test_maryland_refiling_rules_keep_the_receiving_court_and_trigger_separate(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Maryland", legal_area="civil_procedure", authority_status="historical",
                               court="District Court of Maryland", topics=["refiling_after_dismissal"])
        key, = provider.search(query)
        doc = provider.fetch(key)
        self.assertIn("the circuit court dismisses the action for lack of subject matter jurisdiction", doc.text)
        self.assertIn("timely filed in the District Court", doc.text)
        self.assertFalse(provider.search(query.model_copy(update={"topics": ["commencement"]})))
        circuit = query.model_copy(update={"court": "Maryland Circuit Courts"})
        docs = {doc.source["citation"]["preferred_citation"]: doc.text
                for doc in map(provider.fetch, provider.search(circuit))}
        self.assertIn("the District Court dismisses the action", docs["Md. Rule 2-101(c) (November 2003 order)"])
        self.assertIn("a United States District Court or a court of another state",
                      docs["Md. Rule 2-101(b) (November 2003 order)"])

    def test_dc_code_verification_binds_publication_date_subsection_and_jurisdiction(self):
        record = manifest("US-DC")
        wage = next(row for row in record["passages"].values() if row["citation"] == "D.C. Code § 32-1308(c)")
        url = record["sources"][wage["source_id"]]["url"]
        with self.assertRaisesRegex(ValueError, "certified_excerpt_or_date_mismatch"):
            certified_basis("US-DC", url, wage["publisher_sha256"], wage["publisher_path"], wage["citation"],
                            wage["text"].replace("within 3 years", "within 2 years"))
        with self.assertRaisesRegex(ValueError, "invalid_certified_publication"):
            certified_basis("US-DC", url, wage["publisher_sha256"], wage["publisher_path"],
                            "D.C. Code § 16-2702", wage["text"])

        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="District of Columbia", sovereign="district", legal_area="employment",
                               topics=["wage_limitations"], authority_status="current", authority_as_of="2026-04-29")
        key, = provider.search(query)
        doc = provider.fetch(key)
        self.assertIn("if the violation is continuous", doc.text)
        self.assertIn("actual or constructive notice", doc.text)
        self.assertEqual(doc.source["corpus_provenance"]["current_as_of"], "2026-04-29")
        for change in ({"authority_as_of": "2026-04-30"}, {"state": "Maryland", "sovereign": "state"},
                       {"sovereign": "federal"}, {"topics": ["wage_payment"]}):
            self.assertFalse(provider.search(query.model_copy(update=change)))

    def test_dc_debt_complaint_and_judgment_requirements_remain_separate(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="District of Columbia", sovereign="district", legal_area="consumer_debt",
                               topics=["debt_pleading"], authority_status="current", authority_as_of="2026-04-29")
        complaint, = provider.search(query)
        text = provider.fetch(complaint).text
        self.assertIn("last four digits", text)
        self.assertIn("You might have income or resources", text)
        self.assertIn("current phone number or numbers", text)
        proof, = provider.search(query.model_copy(update={"topics": ["debt_judgment_proof"]}))
        self.assertNotEqual(complaint, proof)
        self.assertIn("prior to entry of a default or summary judgment", provider.fetch(proof).text)
        shell = next(row for row in coverage("US-DC")["action_shells"] if row["action_type"] == "complaint")
        self.assertEqual(shell["readiness"], "blocked")
        self.assertEqual(shell["execution"], "disabled")

    def test_florida_contract_limitation_passages_keep_duration_and_scope_separate(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Florida", legal_area="contracts",
                               topics=["written_contract_limitations"], authority_status="unresolved")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("WITHIN FIVE YEARS", text)
        self.assertIn("except for an action to enforce a claim against a payment bond", text)
        oral, = provider.search(query.model_copy(update={"topics": ["oral_contract_limitations"]}))
        self.assertNotEqual(oral, key)
        self.assertIn("WITHIN FOUR YEARS", provider.fetch(oral).text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_connecticut_periodic_wage_limit_exposes_tolling_without_generalizing_it(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Connecticut", legal_area="employment",
                               topics=["wage_limitations"], authority_status="historical")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("employment payable periodically", text)
        self.assertIn("tolled upon the filing with the Labor Commissioner", text)
        self.assertFalse(provider.search(query.model_copy(update={"topics": ["wage_payment"]})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "Illinois"})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_alaska_small_claim_election_does_not_supply_ordinary_commencement(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Alaska", legal_area="civil_procedure",
                               court="Alaska District Court, small claims", topics=["small_claims"],
                               authority_status="unresolved")
        docs = {doc.source["citation"]["preferred_citation"]: doc.text
                for doc in map(provider.fetch, provider.search(query))}
        self.assertIn("When all parties elect small claims procedure", docs["Alaska Dist. Ct. R. Civ. P. 8(a)–(c)"])
        self.assertIn("waives the right to jury trial", docs["Alaska Dist. Ct. R. Civ. P. 10(a)"])
        self.assertFalse(provider.search(query.model_copy(update={"topics": ["commencement"]})))

    def test_partial_negligence_summary_uses_retained_passages_in_each_state(self):
        for scope, jurisdiction in registry().items():
            if jurisdiction.kind not in {"state", "district"}:
                continue
            with self.subTest(scope=scope):
                cell = coverage(scope)["cells"]["substantive.negligence"]
                self.assertTrue(cell["passage_selectors"])
                self.assertEqual(cell["coverage_depth"], "partial")

    def test_illinois_service_proof_is_separate_from_service_and_execution(self):
        complaint = next(row for row in coverage("US-IL")["action_shells"] if row["action_type"] == "complaint")
        proof, = complaint["review_evidence"]["service_proof"]
        self.assertIn("102(d)", proof["citation"])
        self.assertNotIn(proof, complaint["procedure_evidence"]["service"])
        self.assertEqual(proof["currentness"], "historical")
        self.assertEqual((complaint["readiness"], complaint["execution"]), ("blocked", "disabled"))

    def test_kentucky_limitations_commencement_is_separate_from_commencement_rule(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Kentucky", legal_area="civil_procedure",
                               topics=["limitations_commencement"], authority_status="unresolved")
        key, = provider.search(query)
        self.assertIn("first summons or process issued in good faith", provider.fetch(key).text)
        self.assertNotIn(key, provider.search(query.model_copy(update={"topics": ["commencement"]})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "Illinois"})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-21"})))

    def test_oklahoma_retains_both_limitations_versions_without_currentness_promotion(self):
        provider = LegislativeExcerpts("US-OK")
        versions = {}
        for selector, row in manifest("US-OK")["passages"].items():
            if row["citation"] == "Okla. Stat. tit. 12, § 95(A)(3)":
                observation, = provider.normalize(selector, row["text"].encode("utf-8"))
                versions[observation.version.currentness] = observation.version

        older = versions["historical"]
        later = versions["unresolved"]
        self.assertEqual(older.authority_id, later.authority_id)
        self.assertNotEqual(older.version_id, later.version_id)
        self.assertEqual(older.effective_until, date(2017, 11, 1))
        self.assertEqual(later.effective_from, older.effective_until)

    def test_accrual_and_tolling_do_not_supply_ordinary_limitations(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="Michigan", legal_area="torts",
                                authority_types=["statute"], authority_status="unresolved", topics=["accrual"])
        accrual, = provider.search(matter)
        source = provider.fetch(accrual).source
        self.assertEqual(source["citation"]["preferred_citation"], "Mich. Comp. Laws § 600.5827")
        self.assertEqual(source["dates"]["effective_from"], "1963-01-01")
        tolling_query = matter.model_copy(update={"topics": ["tolling"]})
        tolling_ids = provider.search(tolling_query)
        citations = {provider.fetch(key).source["citation"]["preferred_citation"] for key in tolling_ids}
        self.assertTrue({"Mich. Comp. Laws § 600.5855", "Mich. Comp. Laws § 600.5851(1)–(5)"}.issubset(citations))
        limitations_ids = set(provider.search(matter.model_copy(update={"topics": ["limitations"]})))
        self.assertTrue({accrual, *tolling_ids}.isdisjoint(limitations_ids))
        self.assertFalse(provider.search(tolling_query.model_copy(update={"authority_status": "current",
                                                                          "authority_as_of": "2026-11-20"})))

    def test_wisconsin_death_limitation_stays_separate_from_injury_limitation(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="Wisconsin", legal_area="torts",
                                topics=["wrongful_death_limitations"], authority_status="current",
                                authority_as_of="2026-11-04")
        key, = provider.search(matter)
        self.assertEqual(provider.fetch(key).source["citation"]["preferred_citation"], "Wis. Stat. § 893.54(2m)")
        injury_ids = provider.search(matter.model_copy(update={"topics": ["limitations"]}))
        self.assertEqual(len(injury_ids), 2)
        self.assertNotIn(key, injury_ids)

    def test_published_effective_interval_survives_without_currentness_promotion(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Virginia", legal_area="consumer",
                               topics=["unfair_practices"], authority_types=["statute"])
        version, = [provider.fetch(key).source for key in provider.search(query)
                    if provider.fetch(key).source["citation"]["preferred_citation"] == "Va. Code § 59.1-200(A)(1)–(6)"]
        self.assertEqual(version["dates"]["effective_from"], "2026-11-01")
        self.assertEqual(version["dates"]["effective_through"], "2027-07-01")
        self.assertEqual(version["corpus_provenance"]["currentness"], "unresolved")
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-19"})))

    def test_wisconsin_certificate_does_not_promote_future_text(self):
        record = manifest("US-WI")
        row = next(item for item in record["passages"].values() if item["citation"] == "Wis. Stat. § 799.01(1)(a)")
        url = record["sources"][row["source_id"]]["url"]
        with self.assertRaisesRegex(ValueError, "certified_version_requires_effective_date_review"):
            certified_basis(
                "US-WI", url, row["publisher_sha256"], "/statutes/statutes/799/01/1/d",
                "Wis. Stat. § 799.01(1)(d)", "Other civil actions where the amount claimed is $15,000 or less",
            )

    def test_michigan_rule_currentness_requires_exact_subsection_and_date(self):
        record = manifest("US-MI")
        service = next(row for row in record["passages"].values() if row["citation"] == "MCR 2.105(A)")
        args = (record["sources"][service["source_id"]]["url"], service["publisher_sha256"], service["publisher_path"])
        with self.assertRaisesRegex(ValueError, "certified_excerpt_or_date_mismatch"):
            certified_basis("US-MI", *args, "MCR 2.108(A)", service["text"])

        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Michigan", legal_area="civil_procedure",
                               topics=["service_of_process"], authority_types=["court_rule"],
                               authority_status="current", authority_as_of="2026-11-18")
        key, = provider.search(query)
        source = provider.fetch(key).source
        self.assertEqual(source["citation"]["preferred_citation"], "MCR 2.105(A)")
        self.assertEqual(source["corpus_provenance"]["current_as_of"], "2026-11-18")
        self.assertFalse(provider.search(query.model_copy(update={"authority_as_of": "2026-11-20"})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "Wisconsin"})))

    def test_michigan_small_claims_removal_has_a_distinct_rule_date_and_topic(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Michigan", legal_area="civil_procedure",
                               topics=["small_claims"], authority_types=["court_rule"],
                               authority_status="current", authority_as_of="2024-09-01")
        docs = [provider.fetch(key) for key in provider.search(query)]
        removal = next(doc for doc in docs if doc.source["citation"]["preferred_citation"] == "MCR 4.306(B)")
        self.assertIn("within 14 days after the date of the order", removal.text)
        self.assertEqual(removal.source["jurisdiction"]["court"], "Small Claims Division of the Michigan District Court")
        for change in ({"authority_as_of": "2026-11-18"}, {"topics": ["initial_response"]}):
            self.assertFalse(provider.search(query.model_copy(update=change)))

    def test_michigan_distinguishes_civil_procedure_topics(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="Michigan", legal_area="civil_procedure",
                                authority_types=["court_rule"], authority_status="current",
                                authority_as_of="2026-11-18")
        for topic, expected in (
            ("summons_issuance", {"MCR 2.102(A)"}),
            ("service_of_process", {"MCR 2.105(A)"}),
            ("proof_of_service", {"MCR 2.104(A)"}),
            ("service_on_business_entities", {"MCR 2.105(D)", "MCR 2.105(H)"}),
            ("initial_response", {"MCR 2.108(A)"}),
            ("postmotion_response", {"MCR 2.108(C)"}),
            ("pleading_contents", {"MCR 2.111(B)"}),
            ("answer_contents", {"MCR 2.111(C)"}),
        ):
            with self.subTest(topic=topic):
                query = matter.model_copy(update={"topics": [topic]})
                citations = {provider.fetch(key).source["citation"]["preferred_citation"]
                             for key in provider.search(query)}
                self.assertEqual(citations, expected)
                self.assertFalse(provider.search(query.model_copy(update={"state": "Indiana"})))
                self.assertFalse(provider.search(query.model_copy(update={"authority_as_of": "2026-11-19"})))

    def test_indiana_rule_edition_binds_rule_text_and_keeps_proceedings_separate(self):
        record = manifest("US-IN")
        response = next(row for row in record["passages"].values() if row["citation"] == "Ind. Trial R. 6(D)")
        small_claim = next(row for row in record["passages"].values()
                           if row["citation"] == "Ind. Small Claims R. 4(A)")
        url = record["sources"][response["source_id"]]["url"]
        for index, quote in ((small_claim["publisher_path"], response["text"]),
                             (response["publisher_path"], small_claim["text"])):
            with self.assertRaisesRegex(ValueError, "certified_excerpt_or_date_mismatch"):
                certified_basis("US-IN", url, response["publisher_sha256"], index, response["citation"], quote)

        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="Indiana", legal_area="civil_procedure",
                                topics=["initial_response"], authority_types=["court_rule"],
                                authority_status="current", authority_as_of="2026-08-01")
        docs = {doc.source["citation"]["preferred_citation"]: doc.text
                for doc in map(provider.fetch, provider.search(matter))}
        self.assertIn("within twenty days after service of the pleading", docs["Ind. Trial R. 6(D)"])
        self.assertIn("Filing a motion permitted under this rule alters the time", docs["Ind. Trial Rule 12(A)"])
        self.assertFalse(any(row["citation"] == "Ind. Trial R. 12(A)" for row in record["passages"].values()))
        self.assertNotIn(small_claim["citation"], docs)
        for day in ("2025-01-01", "2026-08-02"):
            self.assertFalse(provider.search(matter.model_copy(update={"authority_as_of": day})))
        small_matter = matter.model_copy(update={"topics": ["small_claims"], "authority_as_of": "2025-01-01"})
        small_citations = {provider.fetch(key).source["citation"]["preferred_citation"]
                           for key in provider.search(small_matter)}
        self.assertIn(small_claim["citation"], small_citations)
        self.assertNotIn(response["citation"], small_citations)

    def test_michigan_statute_currentness_requires_matching_enactment_and_compilation(self):
        record = manifest("US-MI")
        deposit = next(row for row in record["passages"].values()
                       if row["citation"] == "Mich. Comp. Laws § 554.609(3)")
        fees = next(row for row in record["passages"].values()
                    if row["citation"] == "Mich. Comp. Laws § 554.633(1)(o)")
        url = record["sources"][deposit["source_id"]]["url"]
        for act, quote in ((fees["publisher_path"], deposit["text"]),
                           (deposit["publisher_path"], deposit["text"].replace("10 days", "30 days"))):
            with self.assertRaisesRegex(ValueError, "certified_excerpt_or_date_mismatch"):
                certified_basis("US-MI", url, deposit["publisher_sha256"], act, deposit["citation"], quote)

        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Michigan", legal_area="landlord_tenant",
                               topics=["security_deposit"], authority_types=["statute"],
                               authority_status="current", authority_as_of="2026-11-16")
        docs = {doc.source["citation"]["preferred_citation"]: doc.text
                for doc in map(provider.fetch, provider.search(query))}
        self.assertIn("within 10 days after mailing the notice of damages", docs[deposit["citation"]])
        self.assertNotIn(fees["citation"], docs)
        for change in ({"authority_as_of": "2026-11-17"}, {"state": "Wisconsin"}):
            self.assertFalse(provider.search(query.model_copy(update=change)))

    def test_delaware_common_pleas_certification_binds_court_date_and_text(self):
        record = manifest("US-DE")
        row = next(item for item in record["passages"].values()
                   if item["citation"] == "Del. Ct. Com. Pl. Civ. R. 12(a)")
        url = record["sources"][row["source_id"]]["url"]
        with self.assertRaisesRegex(ValueError, "certified_excerpt_or_date_mismatch"):
            certified_basis("US-DE", url, row["publisher_sha256"], row["publisher_path"],
                            row["citation"], row["text"].replace("20 days", "21 days", 1))

        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Delaware", court="Delaware Court of Common Pleas",
                               legal_area="civil_procedure", topics=["initial_response"],
                               authority_types=["court_rule"], authority_status="current",
                               authority_as_of="2023-01-10")
        key, = provider.search(query)
        source = provider.fetch(key).source
        self.assertEqual(source["citation"]["preferred_citation"], row["citation"])
        self.assertEqual(source["corpus_provenance"]["current_as_of"], "2023-01-10")
        for change in ({"court": "Delaware Superior Court"}, {"authority_as_of": "2023-01-11"},
                       {"state": "Maryland"}):
            self.assertFalse(provider.search(query.model_copy(update=change)))

    def test_indiana_debt_pleading_preserves_assignment_proof_and_foreclosure_exception(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Indiana", legal_area="consumer_debt",
                               topics=["debt_pleading"], authority_types=["court_rule"],
                               authority_status="current", authority_as_of="2026-08-01")
        docs = {doc.source["citation"]["preferred_citation"]: doc.text
                for doc in map(provider.fetch, provider.search(query))}
        self.assertIn("chronological listing of the names of all prior owners", docs["Ind. Trial R. 9.2(A)"])
        self.assertIn("Subsection (2) does not apply to mortgage foreclosures", docs["Ind. Trial R. 9.2(A)"])
        self.assertIn("first responsive pleading or prior motion", docs["Ind. Trial R. 9.2(F)"])
        for change in ({"authority_as_of": "2026-07-31"}, {"authority_as_of": "2026-08-02"},
                       {"topics": ["debt_response"]}, {"state": "Ohio"}):
            self.assertFalse(provider.search(query.model_copy(update=change)))

    def test_california_response_statutes_keep_triggers_and_form_revision_separate(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="California", legal_area="civil_procedure",
                                authority_types=["statute"], authority_status="unresolved")
        for topic, section, trigger in (
            ("initial_response", "412.20(a)", "after summons is served"),
            ("demurrer_timing", "430.40(a)–(b)", "after service of the complaint or cross-complaint"),
            ("amended_pleading_response", "471.5(a)–(b)", "after service thereof"),
        ):
            with self.subTest(topic=topic):
                query = matter.model_copy(update={"topics": [topic]})
                key, = provider.search(query)
                doc = provider.fetch(key)
                self.assertIn(section, doc.source["citation"]["preferred_citation"])
                self.assertIn(trigger, doc.text)
                self.assertNotIn("January 1, 2027", doc.text)
                self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                          "authority_as_of": "2026-11-20"})))

    def test_action_references_expose_dated_authority_without_unlocking_execution(self):
        actions = coverage("US-WI")["action_shells"]
        complaint = next(action for action in actions if action["action_type"] == "complaint")
        evidence, = complaint["procedure_evidence"]["commencement"]
        self.assertEqual(evidence["citation"], "Wis. Stat. § 801.02(1)")
        self.assertEqual(evidence["current_as_of"], "2026-11-04")
        self.assertIn(evidence["source_id"], complaint["procedure_dependencies"]["commencement"])
        fee, = complaint["procedure_evidence"]["fees"]
        self.assertEqual(fee["citation"], "Wis. Stat. § 814.61(1)(a)")
        self.assertEqual(fee["current_as_of"], "2026-11-04")
        self.assertEqual(len(complaint["procedure_evidence"]["e_filing"]), 6)
        self.assertEqual(complaint["readiness"], "blocked")
        self.assertEqual(complaint["execution"], "disabled")
        washington = coverage("US-WA")["action_shells"]
        for action in washington:
            self.assertNotIn(evidence, action["procedure_evidence"].get("commencement", ()))

    def test_action_review_links_preserve_scope_without_satisfying_dependencies(self):
        actions = {row["action_type"]: row for row in coverage("US-MI")["action_shells"]}
        complaint, answer = actions["complaint"], actions["answer"]
        proof, = complaint["review_evidence"]["service_proof"]
        self.assertEqual(proof["citation"], "MCR 2.104(A)")
        self.assertEqual(proof["current_as_of"], "2026-11-18")
        self.assertNotIn(proof, complaint["procedure_evidence"]["service"])
        self.assertNotIn("service_proof", answer["review_evidence"])
        postmotion, = answer["review_evidence"]["postmotion_response"]
        self.assertNotIn(postmotion, answer["procedure_evidence"]["response"])
        self.assertFalse(actions["small_claim"]["review_evidence"])
        self.assertFalse(actions["demand"]["review_evidence"])
        self.assertTrue(all(row["readiness"] == "blocked" and row["execution"] == "disabled"
                            for row in actions.values()))

    def test_partial_historical_fault_authority_is_separate_from_current_support(self):
        cell = coverage("US-CO")["cells"]["substantive.fault_allocation"]
        self.assertEqual(cell["coverage_depth"], "partial")
        self.assertEqual(cell["status"], "historical_only")
        self.assertEqual(cell["allocation"]["regime"], "modified_comparative_50")
        self.assertEqual(cell["allocation"]["currentness"], "historical")
        self.assertFalse(cell["certified_passages_as_of"])

    def test_tortfeasor_contribution_does_not_supply_plaintiff_fault(self):
        query = ResearchMatter(country="US", state="Maryland", legal_area="torts",
                               topics=["tortfeasor_contribution"], authority_types=["statute"])
        provider = RetainedLegislativeResearch()
        key, = provider.search(query)
        self.assertIn("discharged the common liability", provider.fetch(key).text)
        self.assertFalse(provider.search(query.model_copy(update={"topics": ["fault_allocation"]})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "Missouri"})))

    def test_debt_assignee_venue_is_scoped_to_its_topic_and_jurisdiction(self):
        query = ResearchMatter(country="US", state="Ohio", legal_area="consumer_debt",
                               topics=["debt_forum"], authority_types=["statute"])
        provider = RetainedLegislativeResearch()
        key, = provider.search(query)
        self.assertIn("a county in which at least one of the co-debtors resides", provider.fetch(key).text)
        self.assertNotIn(key, provider.search(query.model_copy(update={"topics": ["debt_collection"]})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "Indiana"})))

    def test_texas_response_passages_keep_justice_and_district_court_rules_apart(self):
        query = ResearchMatter(country="US", state="Texas", legal_area="civil_procedure",
                               topics=["justice_court_response"], authority_types=["court_rule"])
        provider = RetainedLegislativeResearch()
        justice, = provider.search(query)
        self.assertIn("14th day after the day", provider.fetch(justice).text)
        self.assertEqual(provider.fetch(justice).source["jurisdiction"]["court"], "Texas Justice Court")
        district, = provider.search(query.model_copy(update={"topics": ["initial_response"]}))
        self.assertIn("Monday next after the expiration of twenty days", provider.fetch(district).text)
        self.assertFalse(provider.search(query.model_copy(update={"court": "Texas district and county courts"})))

    def test_florida_minimum_wage_amendment_preserves_constitutional_authority_type(self):
        query = ResearchMatter(country="US", state="Florida", legal_area="employment",
                               topics=["wage_payment"], authority_types=["constitution"])
        provider = RetainedLegislativeResearch()
        key, = provider.search(query)
        doc = provider.fetch(key)
        self.assertEqual(doc.source["source_type"], "constitution")
        self.assertIn("September 30th, 2026", doc.text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_types": ["statute"]})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "Georgia"})))

    def test_historical_negligence_elements_do_not_supply_fault_or_present_law(self):
        query = ResearchMatter(country="US", state="Alabama", legal_area="torts",
                               topics=["negligence_elements"], authority_types=["opinion"],
                               authority_status="historical")
        provider = RetainedLegislativeResearch()
        key, = provider.search(query)
        self.assertIn("actual cause", provider.fetch(key).text)
        for topic, citation in (("fault_allocation", "Imperial Aluminum-Scottsboro"),
                                ("limitations", "Ex parte Integra LifeSciences")):
            scoped = query.model_copy(update={"topics": [topic]})
            scoped_key, = provider.search(scoped)
            self.assertNotEqual(scoped_key, key)
            self.assertIn(citation, provider.fetch(scoped_key).source["citation"]["preferred_citation"])
        for topic in ("negligence_elements", "fault_allocation", "limitations"):
            current = query.model_copy(update={"topics": [topic], "authority_status": "current",
                                               "authority_as_of": "2026-11-20"})
            self.assertFalse(provider.search(current))
        self.assertFalse(provider.search(query.model_copy(update={"court": "Alabama Circuit Court"})))

    def test_archived_court_originals_preserve_role_tribunal_and_currentness(self):
        provider = RetainedLegislativeResearch()
        cases = (
            ("Tennessee", "contracts", "contract_formation", "opinion",
             "Court of Appeals of Tennessee", ("rejection of the original offer", "sufficient consideration")),
            ("Maryland", "torts", "fault_allocation", "opinion",
             "Court of Appeals of Maryland", ("abrogate the contributory negligence defense",)),
            ("California", "torts", "negligence_elements", "opinion",
             "California Court of Appeal, Fourth Appellate District, Division Two", ("duty, breach, causation, and damages",)),
            ("New Jersey", "civil_procedure", "small_claims", "court_rule",
             "New Jersey Superior Court, Law Division, Special Civil Part, Small Claims Section", ("$5,000",)),
        )
        for state, area, topic, kind, court, excerpts in cases:
            with self.subTest(state=state):
                query = ResearchMatter(country="US", state=state, legal_area=area, topics=[topic],
                                       authority_types=[kind], court=court, authority_status="historical")
                docs = [provider.fetch(key) for key in provider.search(query)]
                self.assertEqual(len(docs), len(excerpts))
                for excerpt in excerpts:
                    self.assertTrue(any(excerpt in doc.text for doc in docs))
                for doc in docs:
                    if kind == "opinion":
                        self.assertEqual(doc.source["case_metadata"]["opinion_role"], "majority")
                    else:
                        self.assertNotIn("$3,000", doc.text)
                self.assertFalse(provider.search(query.model_copy(update={"state": "Hawaii"})))
                self.assertFalse(provider.search(query.model_copy(update={
                    "authority_status": "current", "authority_as_of": "2026-11-20",
                })))

    def test_oregon_ordinary_negligence_retains_its_own_formulation(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Oregon", legal_area="torts",
                               topics=["negligence_elements"], authority_types=["opinion"],
                               authority_status="historical", court="Oregon Supreme Court")
        key, = provider.search(query)
        doc = provider.fetch(key)
        self.assertIn("unreasonably created a foreseeable risk", doc.text)
        self.assertIn("harm actually resulting from", doc.text)
        self.assertEqual(doc.source["case_metadata"]["opinion_role"], "majority")
        self.assertFalse(provider.search(query.model_copy(update={"state": "Washington"})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current", "authority_as_of": "2026-11-20"})))

    def test_archived_response_rules_enforce_court_and_topic_boundaries(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="New Jersey", legal_area="civil_procedure",
                               topics=["initial_response"], authority_types=["court_rule"],
                               authority_status="historical")
        for suffix, text in (("Civil Part", "may be enlarged"), ("Special Civil Part", "shall not apply")):
            with self.subTest(court=suffix):
                scoped = query.model_copy(update={"court": f"New Jersey Superior Court, Law Division, {suffix}"})
                key, = provider.search(scoped)
                evidence = provider.fetch(key).text
                self.assertIn("35 days", evidence)
                self.assertIn(text, evidence)
        dc = query.model_copy(update={"state": "District of Columbia", "sovereign": "district",
                                      "court": "District of Columbia Superior Court, Civil Division"})
        key, = provider.search(dc)
        for phrase in ("21 days after being served with the summons and complaint", "within 60 days", "within 14 days"):
            self.assertIn(phrase, provider.fetch(key).text)
        self.assertFalse(provider.search(dc.model_copy(update={"authority_status": "current", "authority_as_of": "2026-11-20"})))
        self.assertFalse(provider.search(dc.model_copy(update={"sovereign": "state"})))
        self.assertFalse(provider.search(dc.model_copy(update={"court": "District of Columbia Superior Court, Small Claims and Conciliation Branch"})))

    def test_maryland_answer_exceptions_and_intention_to_defend_are_tribunal_specific(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Maryland", legal_area="civil_procedure",
                               topics=["initial_response"], authority_types=["court_rule"],
                               authority_status="historical", court="Maryland Circuit Courts")
        key, = provider.search(query)
        circuit = provider.fetch(key).text
        self.assertIn("within 90 days", circuit)
        self.assertIn("within the time specified in the notice", circuit)
        self.assertNotIn("notice of intention to defend", circuit)
        key, = provider.search(query.model_copy(update={"court": "District Court of Maryland"}))
        district = provider.fetch(key).text
        self.assertIn("notice of intention to defend", district)
        self.assertIn("the notice shall be filed within 15 days", district)
        self.assertIn("the notice within 60 days", district)
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current", "authority_as_of": "2026-11-20"})))

    def test_new_hampshire_rulebook_retains_initial_and_motion_response_triggers(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="New Hampshire", legal_area="civil_procedure",
                               topics=["initial_response"], authority_types=["court_rule"],
                               authority_status="historical", court="New Hampshire Superior Court")
        excerpts = [provider.fetch(key).text for key in provider.search(query)]
        self.assertEqual(len(excerpts), 3)
        for text in ("served with the Summons and Complaint", "shall also file an appearance",
                     "if the supreme court accepts the appeal and rejects the party's challenge"):
            self.assertTrue(any(text.casefold() in excerpt.casefold() for excerpt in excerpts), text)
        self.assertFalse(provider.search(query.model_copy(update={"court": "New Hampshire Circuit Court"})))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current", "authority_as_of": "2026-11-20"})))

    def test_new_mexico_compilation_preserves_service_and_response_scope(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="New Mexico", legal_area="civil_procedure",
                               topics=["initial_response"], authority_types=["court_rule"],
                               authority_status="unresolved", court="New Mexico District Courts")
        key, = provider.search(query)
        response = provider.fetch(key).text
        self.assertIn("thirty (30) days after the service of the summons and complaint", response)
        self.assertIn("ten (10) days after the service of the more definite statement", response)
        service = query.model_copy(update={"topics": ["service_of_process"]})
        excerpts = [provider.fetch(key).text for key in provider.search(service)]
        electronic, = [text for text in excerpts if "Service by social media, e-mail and text message" in text]
        self.assertIn("showing by affidavit or other sworn testimony", electronic)
        self.assertIn("the court may authorize", electronic)
        for court in ("New Mexico Magistrate Courts", "Bernalillo County Metropolitan Court"):
            self.assertFalse(provider.search(service.model_copy(update={"court": court})))
        self.assertFalse(provider.search(service.model_copy(update={"authority_status": "current", "authority_as_of": "2026-11-20"})))

    def test_indiana_enacted_collection_provision_preserves_department_remedy(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Indiana", legal_area="consumer_debt",
                               topics=["debt_collection"], authority_types=["statute"],
                               authority_status="historical")
        passages = [provider.fetch(key) for key in provider.search(query)]
        remedy, = [doc.text for doc in passages if "the department may bring a civil action" in doc.text.lower()]
        self.assertIn("consumer credit sales, consumer leases, or consumer loans", remedy)
        self.assertIn("the court may grant relief only if it finds", remedy)
        other_state = query.model_copy(update={"state": "Illinois"})
        self.assertTrue(all(provider.fetch(key).text != remedy for key in provider.search(other_state)))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current", "authority_as_of": "2026-11-20"})))

    def test_historical_arkansas_deposit_amendment_excludes_replaced_text(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Arkansas", legal_area="landlord_tenant",
                               topics=["security_deposit"], authority_types=["statute"],
                               authority_status="historical")
        results = [provider.fetch(key).text for key in provider.search(query)]
        refund, = [text for text in results if "first class mail" in text]
        self.assertIn("sixty (60) days after termination of the tenancy and delivery of possession", refund)
        self.assertIn("unable to locate the tenant after reasonable effort", refund)
        self.assertNotIn("thirty (30)", refund)
        self.assertTrue(any("Section 18-16-301 et seq. shall determine" in text for text in results))
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current", "authority_as_of": "2026-11-20"})))

    def test_kentucky_response_publisher_edition_keeps_distinct_triggers(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Kentucky", legal_area="civil_procedure",
                               topics=["initial_response"], authority_types=["court_rule"],
                               authority_status="historical",
                               court="Kentucky courts governed by the Kentucky Rules of Civil Procedure")
        key, = provider.search(query)
        text = provider.fetch(key).text
        for phrase in ("20 days after service of the summons", "ten (10) days after entry of the court's order",
                       "10 days after the service of the more definite statement"):
            self.assertIn(phrase, text)
        for updates in ({"court": "Kentucky Small Claims Division"},
                        {"authority_status": "current", "authority_as_of": "2026-11-20"}):
            self.assertFalse(provider.search(query.model_copy(update=updates)))

    def test_mississippi_historical_wage_frequency_preserves_employer_scope(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Mississippi", legal_area="employment",
                               topics=["wage_payment"], authority_types=["statute"],
                               authority_status="historical")
        key, = provider.search(query)
        text = provider.fetch(key).text
        self.assertIn("fifty or more employees, and employing public labor", text)
        self.assertIn("every public service corporation", text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current", "authority_as_of": "2026-11-20"})))

    def test_automated_transaction_enactment_is_scoped_and_historical(self):
        query = ResearchMatter(country="US", state="Arkansas", legal_area="contracts",
                               topics=["automated_contract_formation"], authority_types=["statute"],
                               authority_status="historical")
        provider = RetainedLegislativeResearch()
        key, = provider.search(query)
        self.assertIn("In an automated transaction", provider.fetch(key).text)
        for changes in ({"topics": ["contract_formation"]}, {"authority_status": "unresolved"},
                        {"authority_status": "current", "authority_as_of": "2026-11-18"}):
            self.assertFalse(provider.search(query.model_copy(update=changes)))

    def test_decided_cases_keep_court_role_and_subsequent_treatment(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Mississippi", legal_area="contracts",
                               topics=["contract_formation"], authority_types=["opinion"],
                               authority_status="historical", court="Supreme Court of Mississippi")
        key, = provider.search(query)
        doc = provider.fetch(key)
        self.assertEqual(doc.source["source_type"], "court_opinion")
        self.assertEqual(doc.source["jurisdiction"]["court"], query.court)
        self.assertEqual(doc.passages[0]["jurisdiction"]["court"], query.court)
        self.assertEqual(doc.source["case_metadata"]["opinion_role"], "majority")
        self.assertEqual(doc.source["case_metadata"]["subsequent_treatment"], "unknown")
        self.assertIn("agreement that is sufficiently definite", doc.text)
        for change in ({"state": "Indiana"}, {"court": "Court of Appeals of Mississippi"},
                       {"authority_types": ["statute"]}, {"authority_status": "current"}):
            self.assertFalse(provider.search(query.model_copy(update=change)))

    def test_implied_employment_formation_keeps_its_own_historical_topic(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(
            country="US", state="New Mexico", legal_area="contracts",
            topics=["employment_contract_formation"], authority_types=["opinion"],
            authority_status="historical",
        )
        key, = provider.search(query)
        self.assertIn("employee handbook", provider.fetch(key).text)
        for change in (
            {"topics": ["contract_formation"]},
            {"state": "Colorado"},
            {"authority_status": "current", "authority_as_of": "2026-11-20"},
        ):
            self.assertNotIn(key, provider.search(query.model_copy(update=change)))

    def test_archive_edition_and_effective_date_do_not_establish_currentness(self):
        scope = "US-CA"
        selector, row = next((key, item) for key, item in manifest(scope)["passages"].items()
                             if item["citation"] == "Cal. Civ. Code § 1788.13")
        self.assertEqual(row["effective_from"], "2025-01-01")
        self.assertEqual(row["currentness"], "unresolved")
        with TemporaryDirectory() as folder:
            observation = check(scope, selector, Path(folder) / "health.sqlite3",
                                fetch=lambda _: self.fail("Unexpected whole-archive fetch"))
            self.assertEqual(observation["status"], "archive_member_replay_required")
            self.assertIsNone(observation["observed_hash"])
        query = ResearchMatter(country="US", state="New Jersey", legal_area="contracts",
                               topics=["contract_formation"], authority_types=["statute"])
        provider = RetainedLegislativeResearch()
        key, = provider.search(query)
        self.assertIn("contract for sale of goods", provider.fetch(key).text)
        self.assertFalse(provider.search(query.model_copy(update={"authority_status": "current",
                                                                  "authority_as_of": "2026-11-18"})))

    def test_certified_statute_requires_matching_date_and_jurisdiction(self):
        query = ResearchMatter(country="US", state="Wisconsin", legal_area="contracts",
                               topics=["contract_formation"], authority_types=["statute"],
                               authority_status="current", authority_as_of="2026-11-04")
        provider = RetainedLegislativeResearch()
        key, = provider.search(query)
        self.assertEqual(provider.fetch(key).source["corpus_provenance"]["current_as_of"], "2026-11-04")
        for change in ({"authority_as_of": "2026-11-05"}, {"authority_as_of": None}, {"state": "Montana"}):
            self.assertEqual(provider.search(query.model_copy(update=change)), [])

    def test_service_timing_rules_preserve_their_distinct_triggers_and_courts(self):
        provider = RetainedLegislativeResearch()
        for state, status, day, citation, condition in (
            ("Illinois", "historical", None, "103(b)", "reasonable diligence"),
            ("Minnesota", "unresolved", None, "3.01(c)", "delivered for service to the sheriff"),
            ("Minnesota", "unresolved", None, "508(d)", "proof of service"),
            ("Wisconsin", "current", "2026-11-04", "801.02(2)", "only an in rem or quasi in rem judgment"),
        ):
            with self.subTest(state=state, citation=citation):
                query = ResearchMatter(country="US", state=state, legal_area="civil_procedure",
                                       topics=["service_time_limit"], authority_status=status, authority_as_of=day)
                selectors = provider.search(query)
                documents = [provider.fetch(key) for key in selectors]
                match, = [doc for doc in documents if citation in doc.source["citation"]["preferred_citation"]]
                self.assertIn(condition, match.text)
                other_selectors = provider.search(query.model_copy(update={"state": "Alabama"}))
                self.assertTrue(set(selectors).isdisjoint(other_selectors))

    def test_tenancy_notice_keeps_publisher_version_limits_and_local_requirements(self):
        provider = RetainedLegislativeResearch()
        for state, citation, effective_until, condition in (
            ("Virginia", "55.1-1245(F)", "2027-07-01", "public housing authority"),
            ("New York", "711(2)", "2034-06-15", "good cause eviction law"),
            ("Minnesota", "504B.321", None, "local government rule or law"),
        ):
            with self.subTest(state=state):
                query = ResearchMatter(country="US", state=state, legal_area="landlord_tenant",
                                       topics=["tenancy_notice"],
                                       authority_status="historical" if state == "Minnesota" else "unresolved")
                documents = [provider.fetch(key) for key in provider.search(query)]
                match, = [doc for doc in documents if citation in doc.source["citation"]["preferred_citation"]]
                self.assertIn(condition, match.text)
                self.assertEqual(match.source["dates"]["effective_through"], effective_until)
                self.assertIsNone(match.source["corpus_provenance"]["current_as_of"])
                self.assertFalse(provider.search(query.model_copy(update={
                    "authority_status": "current", "authority_as_of": "2026-11-21",
                })))

    def test_formation_sources_preserve_local_subject_and_edition(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Arizona", legal_area="contracts",
                               topics=["contract_formation"], authority_types=["statute"])
        key, = provider.search(query)
        self.assertIn("sale of goods", provider.fetch(key).text)
        louisiana, = provider.search(query.model_copy(update={"state": "Louisiana"}))
        self.assertIn("consent of the parties", provider.fetch(louisiana).text)
        self.assertNotIn("sale of goods", provider.fetch(louisiana).text)
        self.assertEqual(provider.search(query.model_copy(update={"topics": ["contract_breach"]})), [])
        self.assertEqual(coverage("CO")["cells"]["contract.formation"]["status"], "historical_only")

    def test_health_journal_preserves_drift_and_outage_without_mutating_corpus(self):
        import sqlite3
        provider, selector, raw, _ = next(retained_observations())
        def unavailable(_):
            raise CorpusError("source_http_403")
        with TemporaryDirectory() as folder:
            history = Path(folder) / "health.sqlite3"
            for fetch, expected in [(lambda _: FetchedSource(raw, 1), "healthy"),
                                    (lambda _: FetchedSource(b"changed", 1), "changed_content"),
                                    (unavailable, "access_denied")]:
                self.assertEqual(check("US", selector, history, fetch=fetch)["status"], expected)
            with self.assertRaises(CorpusError):
                check("US-VA", selector, history, fetch=unavailable)
            connection = sqlite3.connect(history)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM publisher_health").fetchone()[0], 3)
            finally:
                connection.close()
            original, = provider.normalize(selector, raw)
            self.assertEqual(original.version.currentness, "historical")

    def test_every_required_jurisdiction_has_isolated_sources_and_action_status(self):
        self.assertEqual(Counter(owner.kind for owner in registry().values()),
                         {"state": 50, "district": 1, "territory": 5, "federal": 1})
        for scope, owner in registry().items():
            with self.subTest(scope=scope):
                row = coverage(scope)
                self.assertEqual(jurisdiction_id(owner.name), scope)
                self.assertTrue(all(key.startswith(scope + ":") for key in row["sources"]))
                self.assertTrue(all(ref in row["sources"] for cell in row["cells"].values()
                                    for ref in cell.get("source_ids", [])))
                if owner.kind in {"state", "district"}:
                    self.assertEqual(len(row["action_shells"]), 4)
                    self.assertTrue(all(shell["readiness"] == "blocked" and shell["execution"] == "disabled"
                                        for shell in row["action_shells"]))
                    self.assertTrue(row["cells"]["procedure.small_claims"]["source_ids"])
                    self.assertTrue(row["court_directory"])

    def test_general_civil_shell_binds_local_selection_and_procedure_in_every_state_and_dc(self):
        identifiers = set()
        for scope, owner in registry().items():
            row = coverage(scope)
            if owner.kind not in {"state", "district"}:
                self.assertEqual(row["action_shells"], [])
                continue
            with self.subTest(scope=scope):
                shell, = (action for action in row["action_shells"] if action["action_type"] == "complaint")
                self.assertEqual(shell["jurisdiction"], scope)
                self.assertNotIn(shell["id"], identifiers)
                identifiers.add(shell["id"])
                self.assertEqual((shell["path"], shell["stage"]), ("civil_initiation", "reference"))
                self.assertEqual(shell["court_selection"], "user_must_identify_court")
                self.assertEqual(shell["claim_analysis"], "verified_applicable_basis_required")
                self.assertIn("party_role", shell["party_requirements"])
                self.assertIn("attributed_material_facts", shell["matter_requirements"])
                self.assertEqual(set(shell["procedure_dependencies"]),
                                 {"commencement", "venue", "service", "fees", "e_filing"})
                self.assertEqual(shell["document_strategy"], "resolve_mandatory_form_and_local_requirements")
                self.assertEqual((shell["local_rules"], shell["coverage_status"]),
                                 ("local_rule_required", "local_rule_required"))
                self.assertEqual((shell["readiness"], shell["execution"]), ("blocked", "disabled"))
                self.assertTrue(shell["court_references"])
                self.assertTrue(shell["rules_references"])
                for category in ("commencement", "service"):
                    self.assertTrue(shell["procedure_evidence"][category])
                    for item in shell["procedure_evidence"][category]:
                        self.assertIn(item["source_id"], shell["procedure_dependencies"][category])
                        self.assertEqual(row["sources"][item["source_id"]]["category"], category)
                        self.assertEqual(manifest(scope)["passages"][item["passage_selector"]]["citation"],
                                         item["citation"])
        self.assertEqual(len(identifiers), 51)

    def test_exact_publication_replay_rejects_invented_or_changed_text(self):
        publisher_editions = {
            ("US-DC", date(2026, 4, 29)): "D.C. Council codified XML publication, current through April 29, 2026.",
            ("US-DE", date(2023, 1, 10)): "Court of Common Pleas Civil Rules. Current as of January 10, 2023.",
            ("US-ME", date(2026, 6, 1)): "Maine Rules of Civil Procedure Only (without advisory notes), "
                                       "as effective June 1, 2026.",
            ("US-WA", date(2024, 7, 12)): "Revised Code of Washington, certified July 12, 2024.",
            ("US-WI", date(2026, 11, 4)): "Published and certified",
            ("US-MI", date(2026, 11, 18)): "Michigan Supreme Court Rules Chapter 2.",
            ("US-MI", date(2024, 9, 1)): "Michigan Supreme Court Rules Chapter 4.",
            ("US-MI", date(2026, 10, 25)): "Michigan Compiled Laws Complete Through PA 114 of 2026.",
            ("US-MI", date(2026, 11, 16)): "Michigan Compiled Laws Complete Through PA 114 of 2026.",
            ("US-IN", date(2026, 8, 1)): "Indiana Rules of Trial Procedure.",
            ("US-IN", date(2025, 1, 1)): "Indiana Small Claims Rules.",
        }
        for provider, selector, raw, _ in retained_observations():
            with self.subTest(source=provider.source.name, selector=selector):
                observation, = provider.normalize(selector, raw)
                self.assertIn(observation.version.jurisdiction, provider.source.jurisdictions)
                if observation.version.currentness == "current_as_of":
                    edition = (observation.version.jurisdiction, observation.version.current_as_of)
                    self.assertIn(edition, publisher_editions)
                    basis = publisher_editions[edition]
                    self.assertIn(basis, observation.version.currentness_basis)
                else:
                    self.assertIn(observation.version.currentness, {"unresolved", "historical"})
                self.assertEqual(observation.version.authority_type, provider.source.authority_type)
                with self.assertRaises(CorpusError):
                    list(provider.normalize(selector, raw + b" This is now current law."))
                with self.assertRaises(CorpusError):
                    list(provider.normalize("invented-case-or-statute", raw))

    def test_scope_subject_sovereign_and_currentness_are_independent_gates(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Oregon", legal_area="civil_procedure",
                               topics=["commencement"], authority_types=["court_rule"])
        ids = provider.search(query)
        self.assertTrue(ids)
        self.assertIn("Other than for purposes of statutes of limitations", provider.fetch(ids[0]).text)
        for changes in ({"topics": ["service"]}, {"sovereign": "federal"}, {"authority_types": ["statute"]},
                        {"authority_status": "current"}, {"authority_as_of": "2025-01-01"}):
            self.assertEqual(provider.search(query.model_copy(update=changes)), [])
        self.assertEqual(infer_jurisdiction("I live in Maryland and work in Washington, D.C."), {"US-MD", "US-DC"})

    def test_retained_specialized_authority_is_routed_by_scope_and_topic(self):
        provider = RetainedLegislativeResearch()
        for state, area, topic, kind, status, day, citation in (
            ("Georgia", "torts", "premises_liability", "opinion", "historical", None, "Carmichael"),
            ("Kansas", "torts", "negligence_causation", "opinion", "historical", None, "Montgomery v. Saleh"),
            ("Indiana", "civil_procedure", "time_computation", "court_rule", "current", "2026-08-01", "Ind. Trial R. 6(A)"),
        ):
            with self.subTest(state=state, topic=topic):
                matter = ResearchMatter(country="US", state=state, legal_area=area, topics=[topic],
                                        authority_types=[kind], authority_status=status, authority_as_of=day)
                key, = provider.search(matter)
                self.assertIn(citation, provider.fetch(key).source["citation"]["preferred_citation"])
                self.assertFalse(provider.search(matter.model_copy(update={"state": "Wisconsin"})))

    def test_wage_preemption_does_not_establish_a_wage_payment_rule(self):
        provider = RetainedLegislativeResearch()
        for state, citation in (("Alabama", "Act 2016-18"), ("Mississippi", "H.B. 141")):
            with self.subTest(state=state):
                matter = ResearchMatter(country="US", state=state, legal_area="employment",
                                        topics=["wage_preemption"], authority_types=["statute"],
                                        authority_status="historical")
                key, = provider.search(matter)
                self.assertIn(citation, provider.fetch(key).source["citation"]["preferred_citation"])
                self.assertNotIn(key, provider.search(matter.model_copy(update={"topics": ["wage_payment"]})))

    def test_tennessee_electronic_form_preserves_transaction_scope(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Tennessee", legal_area="contracts",
                               topics=["electronic_contract_form"], authority_types=["statute"],
                               authority_status="historical")
        key, = provider.search(query)
        self.assertIn("solely because an electronic record was used", provider.fetch(key).text)
        consent, = provider.search(query.model_copy(update={"topics": ["electronic_transaction_consent"]}))
        self.assertIn("each of which has agreed to conduct transactions by electronic means",
                      provider.fetch(consent).text)
        self.assertFalse(provider.search(query.model_copy(update={"topics": ["contract_formation"]})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "Kentucky"})))

    def test_alabama_sales_commissions_require_wholesale_scope(self):
        provider = RetainedLegislativeResearch()
        query = ResearchMatter(country="US", state="Alabama", legal_area="employment",
                               topics=["sales_commissions"], authority_types=["statute"],
                               authority_status="historical")
        texts = [provider.fetch(key).text for key in provider.search(query)]
        self.assertTrue(any("purchase at wholesale" in value and "home solicitation sales" in value
                            for value in texts))
        self.assertTrue(any("within thirty days after the date of termination" in value for value in texts))
        for change in ({"topics": ["wage_payment"]}, {"state": "Mississippi"},
                       {"authority_status": "current", "authority_as_of": "1994-05-03"}):
            self.assertFalse(provider.search(query.model_copy(update=change)))

    def test_wisconsin_debt_cure_preserves_qualification_and_response_scope(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="Wisconsin", legal_area="consumer_debt",
                                topics=["debt_cure_prior_defaults"], authority_status="current",
                                authority_as_of="2026-11-04")
        citations = {provider.fetch(key).source["citation"]["preferred_citation"]
                     for key in provider.search(matter)}
        self.assertEqual(citations, {"Wis. Stat. § 425.105(3)(intro.)", "Wis. Stat. § 425.105(3)(a)",
                                     "Wis. Stat. § 425.105(3)(b)", "Wis. Stat. § 425.105(3)(c)"})
        query = matter.model_copy(update={"topics": ["debt_cure_exceptions"]})
        self.assertEqual(len(provider.search(query)), 4)
        self.assertFalse(provider.search(query.model_copy(update={"authority_as_of": "2026-11-05"})))
        self.assertFalse(provider.search(query.model_copy(update={"state": "South Dakota"})))
        self.assertFalse(provider.search(query.model_copy(update={"topics": ["debt_response"]})))

    def test_new_mexico_medical_debt_pleading_is_scoped_to_tribunal_and_topic(self):
        provider = RetainedLegislativeResearch()
        matter = ResearchMatter(country="US", state="New Mexico", legal_area="consumer_debt",
                                topics=["debt_pleading"], authority_types=["court_rule"],
                                authority_status="historical")
        cases = (
            ("New Mexico District Courts", "Rule 1-009(J)(2) NMRA", "Rule 1-017(E)"),
            ("New Mexico Magistrate Courts", "Rule 2-201(E)(2) NMRA", "Rule 2-401(D)"),
            ("New Mexico Metropolitan Courts", "Rule 3-201(E)(2) NMRA", "Rule 3-401(D)"),
        )
        for court, citation, requirement in cases:
            with self.subTest(court=court):
                key, = provider.search(matter.model_copy(update={"court": court}))
                doc = provider.fetch(key)
                self.assertEqual(doc.source["citation"]["preferred_citation"], citation)
                self.assertIn(requirement, doc.text)
                self.assertIn("Attestation of Indigency", doc.text)
        for changes in ({"topics": ["debt_response"]}, {"topics": ["debt_collection"]},
                        {"state": "Arizona"}, {"authority_status": "current", "authority_as_of": "2025-12-31"}):
            self.assertFalse(provider.search(matter.model_copy(update=changes)))
        complaint = next(shell for shell in coverage("US-NM")["action_shells"] if shell["action_type"] == "complaint")
        review = complaint["review_evidence"]["debt_pleading"]
        self.assertEqual({(item["court"], item["citation"]) for item in review},
                         {(court, citation) for court, citation, _ in cases})
        self.assertNotIn("debt_pleading", complaint["procedure_evidence"])
        self.assertEqual((complaint["readiness"], complaint["execution"]), ("blocked", "disabled"))

    def test_replay_idempotence_separate_courts_and_historical_federal_granules(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "corpus.sqlite3"
            self.assertEqual(build(path), build(path))
            with SQLiteNormalizedCorpus(path, read_only=True) as store:
                for scope in ("US-DC", "US-PR", "US-RI", "US"):
                    self.assertFalse(store.search(CorpusQuery(scope, "statute", citation="Invented authority")))
                for label in ("Super.", "Dist. Ct."):
                    hits = store.search(CorpusQuery("US-RI", "court_rule", citation=f"R.I. {label} R. Civ. P. 3"))
                    self.assertEqual(len(hits), 1)
                cite = "28 U.S.C. § 1331"
                self.assertTrue(store.search(CorpusQuery("US", "statute", citation=cite, currentness="historical")))
                self.assertFalse(store.search(CorpusQuery("US-PR", "statute", citation=cite, currentness="historical")))
                self.assertEqual(store.applicable_version("US", "statute", cite, date(2026, 1, 1))["status"],
                                 "currentness_unresolved")
                ok_cite = "Okla. Stat. tit. 12, § 95(A)(3)"
                historical, = store.search(CorpusQuery("US-OK", "statute", citation=ok_cite, currentness="historical"))
                unresolved, = store.search(CorpusQuery("US-OK", "statute", citation=ok_cite, currentness="unresolved"))
                self.assertEqual(store.identity_checks(historical["version_id"], unresolved["version_id"]),
                                 ["same_authority_different_version"])

    def test_named_tribal_authority_requires_its_own_sovereign(self):
        self.assertTrue(possible_tribal_scope("The matter is in Navajo Nation court in Arizona."))
        fields = dict(identity_namespace="synthetic", identity_key="example", citation="Test",
                      title="Fixture", text="Synthetic", edition="fixture", authority_type="court_rule")
        for scope in tribal_registry():
            self.assertEqual(AuthorityVersion(jurisdiction=scope, sovereign="tribal", **fields).jurisdiction, scope)
            with self.assertRaises(ValidationError):
                AuthorityVersion(jurisdiction=scope, sovereign="state", **fields)
        with self.assertRaises(ValidationError):
            AuthorityVersion(jurisdiction="TRIBAL-UNSPECIFIED", sovereign="tribal", **fields)

    def test_product_page_and_read_only_api_are_distinct(self):
        with TestClient(app) as client:
            self.assertIn("text/html", client.get("/coverage").headers["content-type"])
            self.assertEqual(client.get("/api/coverage").json()["jurisdictions"], 57)
            self.assertEqual(client.get("/api/coverage/PR/procedure").json()["jurisdiction"], "US-PR")
            self.assertEqual(client.get("/api/coverage/XX").status_code, 404)
            self.assertEqual(client.get("/api/coverage/OR/invented").status_code, 404)
            self.assertEqual(client.post("/api/coverage/OR").status_code, 405)
