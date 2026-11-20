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
from app.coverage_audit import build, retained_observations
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
        tolling, = provider.search(tolling_query)
        self.assertEqual(provider.fetch(tolling).source["citation"]["preferred_citation"], "Mich. Comp. Laws § 600.5855")
        self.assertFalse({accrual, tolling} & set(provider.search(matter.model_copy(update={"topics": ["limitations"]}))))
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
        self.assertIn("Filing a motion permitted under this rule alters the time", docs["Ind. Trial R. 12(A)"])
        self.assertNotIn(small_claim["citation"], docs)
        for day in ("2025-01-01", "2026-08-02"):
            self.assertFalse(provider.search(matter.model_copy(update={"authority_as_of": day})))
        small_matter = matter.model_copy(update={"topics": ["small_claims"], "authority_as_of": "2025-01-01"})
        small_citations = {provider.fetch(key).source["citation"]["preferred_citation"]
                           for key in provider.search(small_matter)}
        self.assertIn(small_claim["citation"], small_citations)
        self.assertNotIn(response["citation"], small_citations)

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

    def test_exact_publication_replay_rejects_invented_or_changed_text(self):
        publisher_editions = {
            ("US-WI", date(2026, 11, 4)): "Published and certified",
            ("US-MI", date(2026, 11, 18)): "Michigan Supreme Court Rules Chapter 2.",
            ("US-MI", date(2024, 9, 1)): "Michigan Supreme Court Rules Chapter 4.",
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
