"""Offline nationwide isolation, publication replay and routing regressions."""
from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.capabilities import ResearchMatter
from app.coverage_audit import build, retained_observations
from app.coverage_health import check
from app.jurisdictions import jurisdiction_id, possible_tribal_scope, registry, tribal_registry
from app.main import app
from app.national_corpus import AuthorityVersion, CorpusError, CorpusQuery, FetchedSource
from app.national_corpus_store import SQLiteNormalizedCorpus
from app.national_coverage import coverage, manifest
from app.national_excerpt_research import RetainedLegislativeResearch
from app.procedural_research import infer_jurisdiction


class NationalCoverageTests(unittest.TestCase):
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
        for provider, selector, raw, _ in retained_observations():
            with self.subTest(source=provider.source.name, selector=selector):
                observation, = provider.normalize(selector, raw)
                self.assertIn(observation.version.jurisdiction, provider.source.jurisdictions)
                if observation.version.currentness == "current_as_of":
                    self.assertEqual(observation.version.jurisdiction, "US-WI")
                    self.assertEqual(observation.version.current_as_of, date(2026, 11, 4))
                    self.assertIn("Published and certified", observation.version.currentness_basis)
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
