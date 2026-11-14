from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.capabilities import ResearchComparison, ResearchMatter
from app.config import Settings
from app.generation_contract import build_model_request
from app.legal_research import GeneralLegalResearchService
from app.models.base import GenerationConfig, ModelResponse
from app.models.registry import ProviderRegistry
from app.models.testing import valid_draft
from app.national_corpus import AuthorityVersion, CorpusError, CorpusQuery, Observation, fingerprint
from app.national_corpus_identity import compare_identity
from app.national_corpus_providers import PROVIDERS
from app.national_corpus_store import SQLiteNormalizedCorpus
from app.national_corpus_supersession import ARTIFACTS, EFFECTIVE, record_reviewed_supersession
from app.output_validation import OutputValidationService
from app.repository import RecordRepository
from app.research_synthesis import ResearchSynthesisService


class CorpusExpansionTests(unittest.TestCase):
    def test_reviewed_amendment_preserves_versions_and_requires_exact_evidence(self):
        raw = (
            """<CFRDOC><FMTR><TITLEPG><TITLENUM>Title 8</TITLENUM><REVISED>Revised as of January 1, 2025</REVISED>
                </TITLEPG></FMTR><PART><EAR>Pt. 100</EAR><SECTION><SECTNO>§ 100.4</SECTNO>
                <SUBJECT>Field offices.</SUBJECT><P>Historical field offices.</P></SECTION></PART></CFRDOC>""",
            """<DLPSTEXTCLASS><HEADER><FILEDESC><PUBLICATIONSTMT><IDNO>8</IDNO></PUBLICATIONSTMT></FILEDESC></HEADER>
                <TEXT><BODY><ECFRBRWS><AMDDATE>Oct. 14, 2026(fm)</AMDDATE>
                <DIV5 TYPE="PART" N="100"><DIV8 TYPE="SECTION" N="§ 100.4" NODE="8:100.4">
                <HEAD>§ 100.4 Field offices.</HEAD><P>Detroit, MI, Gordie Howe International Bridge.</P>
                </DIV8></DIV5></ECFRBRWS></BODY></TEXT></DLPSTEXTCLASS>""",
            """<FEDREG><VOL>91</VOL><DATE>Friday, January 30, 2026</DATE><RULE><PREAMB>
                <SUBJECT>Establishing a port of entry</SUBJECT><ACT>ACTION: Final rule.</ACT><CFR>8 CFR Part 100</CFR>
                <EFFDATE>DATES: This final rule is effective March 2, 2026. CBP will notify the public when the Gordie Howe
                International Bridge border crossing is fully operational and open to the public for use through
                a notice published on the CBP website.</EFFDATE></PREAMB>
                <REGTEXT><AMDPAR>In § 100.4(a), add the bridge.</AMDPAR></REGTEXT>
                <FRDOC>[FR Doc. 2026-01868 Filed 1-29-26]</FRDOC></RULE></FEDREG>""",
        )
        raw = tuple(item.encode() for item in raw)
        fixtures = tuple((name, selector, fingerprint(data), citation)
                         for (name, selector, _, citation), data in zip(ARTIFACTS, raw))
        with SQLiteNormalizedCorpus(":memory:") as store:
            with self.assertRaisesRegex(CorpusError, "supersession_artifact_unavailable"):
                record_reviewed_supersession(store)
            with patch("app.national_corpus_supersession.ARTIFACTS", fixtures):
                for (name, selector, _, _), data in zip(fixtures, raw):
                    store.ingest(PROVIDERS[name], selector, data)
                proof = record_reviewed_supersession(store)
                self.assertEqual(proof, record_reviewed_supersession(store))
                query = CorpusQuery("US", "regulation", citation="8 CFR 100.4", currentness="superseded", as_of=EFFECTIVE)
                [superseded] = store.search(query)
                [historical] = store.search(replace(query, currentness="historical"))
                [unresolved] = store.search(replace(query, currentness="unresolved"))
                self.assertEqual(superseded["supersession"], proof)
                self.assertEqual(historical["version_id"], superseded["version_id"])
                self.assertEqual(historical["authority_id"], unresolved["authority_id"])
                self.assertNotEqual(historical["version_id"], unresolved["version_id"])
                self.assertNotEqual(proof["earlier_snapshot"], proof["later_snapshot"])
                self.assertEqual(store.search(replace(query, as_of=date(2026, 3, 1))), [])
                self.assertEqual(store.search(replace(query, currentness="current_as_of")), [])

    def test_synthesis_and_verifier_receive_retained_source_status_and_fallback_is_exact(self):
        raw = """<div class="nys-openleg-result-title-short">Example</div>
          <div class="nys-openleg-result-title-headline">SECTION {number}</div>
          <div class="nys-openleg-result-title-location">Real Property (RPP)</div>
          <div class="nys-openleg-result-text">&sect; {number}. A landlord shall repair the premises under the example conditions.</div>
          <div class="nys-openleg-history-published">Viewing most recent revision (from 2026-03-02)</div>"""
        with TemporaryDirectory() as directory:
            database = str(Path(directory) / "test.sqlite3")
            with SQLiteNormalizedCorpus(database) as store:
                for number in ("235-B", "226-B"):
                    store.ingest(PROVIDERS["new_york_code"], f"RPP/{number}", raw.format(number=number).encode())
            matter = ResearchMatter(country="US", state="New York", legal_area="landlord_tenant",
                                    topics=["landlord_repairs"], authority_types=["statute"])
            service = GeneralLegalResearchService(RecordRepository(), Settings(normalized_corpus_path=database))
            try:
                package = service.assemble(matter)["package"]
            finally:
                service.close()
        config = GenerationConfig(provider="fixture", model="demo")
        for statement, expected_calls in (
            ("The retained text describes a repair duty under the stated conditions.", ["claim_proposal", "claim_verification"]),
            ("This statute is currently in force.", ["claim_proposal"]),
        ):
            with self.subTest(statement=statement):
                calls = []

                class Fixture:
                    def generate(inner, request):
                        purpose = request.metadata["purpose"]
                        calls.append(purpose)
                        data = request.grounded_package
                        evidence = data["evidence"] if purpose == "claim_proposal" else data["cited_evidence"]
                        for passage in evidence:
                            status = passage["source"]["currentness"]
                            self.assertEqual(status["status"], "unresolved")
                            self.assertFalse(status["refresh_supported"])
                            self.assertIn("403", status["refresh_limitation"])
                        if purpose == "claim_proposal":
                            output = {"claims": [{"statement": statement, "issue": "landlord_repairs",
                                "jurisdiction": data["jurisdiction"],
                                "support": [{"passage_id": p["passage_id"], "relationship": "supports"} for p in evidence]}]}
                        else:
                            output = {"result": "entailed", "passage_ids": [p["passage_id"] for p in evidence],
                                      "missing_qualifications": [], "unsupported_fragments": []}
                        return ModelResponse(request.provider, request.model, True, output=output)

                registry = ProviderRegistry()
                registry.register("fixture", Fixture(), {"demo"})
                updated = ResearchSynthesisService(registry).prepare(package, config)
                self.assertEqual(calls, expected_calls)
                if len(calls) == 1:
                    self.assertEqual(updated["synthesis"]["ledger"][0]["rejection_reason"], "unsupported_operative_status")
                    self.assertEqual(updated["response_plan"]["claims"], package["response_plan"]["claims"])
                else:
                    self.assertEqual(updated["synthesis"]["status"], "verified")
                request = build_model_request(updated, config)
                draft, validation = OutputValidationService().validate(valid_draft(request), request)
                self.assertIsNotNone(draft, validation)

    def test_new_york_retained_snapshot_has_no_automated_refresh_or_currentness(self):
        for name, selector, number, law, family in (
            ("new_york_code", "RPP/235-B", "235-B", "Real Property (RPP)", "statute"),
            ("new_york_constitution", "CNS/A1S6", "6", "Constitution (CNS), ARTICLE I", "constitution"),
        ):
            with self.subTest(name=name), SQLiteNormalizedCorpus(":memory:") as store:
                provider = PROVIDERS[name]
                self.assertFalse(provider.source.refresh_supported)
                self.assertEqual(provider.source.refresh_mode, "retained_snapshot_replay")
                with patch("app.national_corpus_transport.PublicProvider.fetch") as network:
                    with self.assertRaisesRegex(CorpusError, "new_york_refresh_unavailable"):
                        provider.fetch(selector)
                    network.assert_not_called()
                raw = f"""<div class="nys-openleg-result-title-short">Example</div>
                  <div class="nys-openleg-result-title-headline">SECTION {number}</div>
                  <div class="nys-openleg-result-title-location">{law}</div>
                  <div class="nys-openleg-result-text">&sect; {number}. Example text.</div>
                  <div class="nys-openleg-history-published">Viewing most recent revision (from 2026-03-02)</div>""".encode()
                result = store.ingest(provider, selector, raw, retrieved_at="2026-11-09T13:30:00Z", replay=True)
                query = CorpusQuery("US-NY", family)
                [hit] = store.search(query)
                self.assertEqual(hit["currentness"], "unresolved")
                self.assertEqual(store.provenance(hit["version_id"])[0]["id"], result["snapshot"])
                for on in (date(2026, 3, 2), date(2026, 11, 9)):
                    self.assertEqual(store.search(replace(query, currentness="current_as_of", as_of=on)), [])

    def test_offline_replay_preserves_original_retrieval_timestamp(self):
        raw = b'<article id="vacode"><h2>&sect; 1-200. Example.</h2><section data-table="CoV" data-field="body"><p>Fixture text.</p></section></article>'
        provider = PROVIDERS["virginia_code"]
        with SQLiteNormalizedCorpus(":memory:") as store:
            original = store.ingest(provider, "1/2/1-200", raw)
            name, selector, artifact, retrieved = store.replay_artifact(original["snapshot"])
            [version] = store.search(CorpusQuery("US-VA", "statute"))
            before = store.provenance(version["version_id"])
            repeat = store.ingest(PROVIDERS[name], selector, artifact, retrieved_at=retrieved, replay=True)
            self.assertTrue(repeat["unchanged_snapshot"])
            self.assertEqual(store.provenance(version["version_id"]), before)
            with SQLiteNormalizedCorpus(":memory:") as other:
                other.ingest(PROVIDERS[name], selector, artifact, retrieved_at=retrieved, replay=True)
                [provenance] = other.provenance(version["version_id"])
                self.assertEqual(provenance["first_retrieved"], retrieved)

    def test_comparison_requires_two_distinct_states_and_the_same_authority_scope(self):
        base = dict(country="US", state="Virginia", legal_area="landlord_tenant", topics=["landlord_repairs"])
        left = ResearchMatter(**base)
        right = ResearchMatter(**(base | {"state": "Florida"}))
        self.assertEqual(len(ResearchComparison(matters=[left, right]).matters), 2)
        for update in ({"state": "Virginia"}, {"authority_types": ["statute"]}, {"sovereign": "federal"}):
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, "comparison_requires_distinct_states"):
                ResearchComparison(matters=[left, right.model_copy(update=update)])

    def test_register_categories_and_part_provenance(self):
        documents = []
        for index, (tag, action) in enumerate((
            ("RULE", "Final rule."), ("PRORULE", "Proposed rule."),
            ("NOTICE", "Notice."), ("RULE", "Correction."),
        ), 1):
            documents.append(f"""<{tag}><PREAMB><AGENCY>Example Agency</AGENCY>
                <SUBJECT>Example publication {index}</SUBJECT><ACT>ACTION: {action}</ACT>
                <CFR>1 CFR Part 1</CFR><EFFDATE>DATES: Effective March 2, 2026.</EFFDATE>
                </PREAMB><REGTEXT><AMDPAR>In § 1.1, revise paragraph (a).</AMDPAR></REGTEXT>
                <FRDOC>[FR Doc. 2026-0000{index} Filed 1-29-26; 8:45 am]</FRDOC></{tag}>""")
        raw = ("<FEDREG><VOL>91</VOL><DATE>Friday, January 30, 2026</DATE>"
               + "".join(documents) + "</FEDREG>").encode()
        with SQLiteNormalizedCorpus(":memory:") as store:
            result = store.ingest(PROVIDERS["govinfo_register"], "2026-01-30", raw)
            self.assertEqual(result["relationships_created"], 5)
            [proposed] = store.search(CorpusQuery("US", "register_document", currentness="proposed"))
            self.assertEqual(proposed["document_kind"], "proposed_rule")
            self.assertIsNone(proposed["effective_from"])
            self.assertFalse(store.search(CorpusQuery("US", "regulation", citation=proposed["citation"])))
            remaining = store.search(CorpusQuery("US", "register_document"))
            self.assertEqual({item["document_kind"] for item in remaining}, {"final_rule", "notice", "other"})
            self.assertEqual(next(item for item in remaining if item["document_kind"] == "final_rule")["effective_from"],
                             "2026-03-02")
            [edge] = store.relationships(proposed["version_id"])
            self.assertEqual(edge["target_native_id"], "1 CFR part 1")
            self.assertEqual(edge["snapshot_id"], result["snapshot"])
            final = next(item for item in remaining if item["document_kind"] == "final_rule")
            self.assertIn(("amends_cfr", "1 CFR 1.1"), {
                (item["kind"], item["target_native_id"]) for item in store.relationships(final["version_id"])
            })

    def test_as_of_current_excludes_repealed_superseded_and_later_queries(self):
        provider = PROVIDERS["virginia_code"]
        verified = date(2026, 10, 1)
        base = AuthorityVersion(jurisdiction="US-VA", sovereign="state", authority_type="statute",
                                identity_namespace="fixture", identity_key="test", title="Fixture", citation="Fixture 1",
                                edition="2026", text="Sample statute.", currentness="current", current_as_of=verified,
                                currentness_basis="Fixture active flag.")

        class Fixture:
            source = replace(provider.source, name="fixture")
            source_url = staticmethod(provider.source_url)

            def normalize(self, selector, raw):
                version = base
                if raw != b"current":
                    status = raw.decode()
                    version = AuthorityVersion(**(base.model_dump() | {
                        "edition": "2025", "currentness": status, "current_as_of": None, "currentness_basis": None,
                    }))
                yield Observation(version, "1", "test row", "Fixture 1")

        with SQLiteNormalizedCorpus(":memory:") as store:
            for state in (b"repealed", b"superseded", b"historical", b"current"):
                store.ingest(Fixture(), "1/2/1-200", state)
            query = CorpusQuery("US-VA", "statute", citation="Fixture 1", currentness="current", as_of=verified)
            [hit] = store.search(query)
            self.assertEqual(hit["edition"], "2026")
            self.assertFalse(store.search(replace(query, as_of=date(2026, 10, 2))))
            self.assertFalse(store.search(replace(query, as_of=None)))

    def test_identity_conflicts_and_probable_matches(self):
        first = dict(jurisdiction="US", authority_type="opinion", authority_id="one", edition="1", title="Example",
                     court="Court A", published_on="1954-01-01", citation="1 U.S. 1", normalized_hash="a")
        check = lambda second: compare_identity(first, second, {"provider": "a"}, {"provider": "b"})[0]
        self.assertEqual(check(first | {"edition": "2"}), "same_authority_different_version")
        self.assertEqual(check(first), "same_authority_same_version")
        self.assertEqual(check(first | {"authority_id": "two"}), "probable_match")
        self.assertEqual(check(first | {"authority_id": "two", "court": "Court B"}), "conflicting_identity")
        self.assertEqual(check(first | {"authority_id": "two", "citation": "1 U.S. 2"}), "unresolved_identity")

    def test_ecfr_title_metadata_does_not_establish_section_currentness(self):
        provider = PROVIDERS["govinfo_ecfr"]
        raw = """<DLPSTEXTCLASS><HEADER><FILEDESC><PUBLICATIONSTMT><IDNO>1</IDNO>
            </PUBLICATIONSTMT></FILEDESC></HEADER><TEXT><BODY><ECFRBRWS>
            <AMDDATE>Dec. 29, 2022(fm)</AMDDATE>
            <DIV5 TYPE="PART" N="1"><DIV8 TYPE="SECTION" N="§ 1.1" NODE="1:1.1">
            <HEAD>§ 1.1 Definitions.</HEAD><P>Example content.</P></DIV8></DIV5>
            <DIV5 TYPE="PART" N="2"><DIV8 TYPE="SECTION" N="§ 2.2" NODE="1:2.2">
            <HEAD>§ 2.2 Example.</HEAD><P>Example content.</P></DIV8></DIV5>
            </ECFRBRWS></BODY></TEXT></DLPSTEXTCLASS>""".encode()
        with SQLiteNormalizedCorpus(":memory:") as store:
            result = store.ingest(provider, "1", raw)
            self.assertEqual(result["records"], 2)
            [row] = store.search(CorpusQuery("US", "regulation", citation="1 CFR 1.1"))
            self.assertEqual(row["edition"], "eCFR title metadata 2022-12-29")
            self.assertFalse(store.search(CorpusQuery("US", "regulation", currentness="current", as_of=date(2022, 12, 29))))

    def test_research_core_replays_artifact_and_fails_closed_after_tampering(self):
        raw = b'<article id="vacode"><h2>&sect; 55.1-1220. Example.</h2><section data-table="CoV" data-field="body"><p>A landlord shall repair a broken fixture under the example conditions.</p></section></article>'
        with TemporaryDirectory() as directory:
            database = str(Path(directory) / "test.sqlite3")
            with SQLiteNormalizedCorpus(database) as store:
                store.ingest(PROVIDERS["virginia_code"], "55.1/12/55.1-1220", raw)
            repo = RecordRepository()
            settings = Settings(normalized_corpus_path=database)
            matter = ResearchMatter(country="US", state="Virginia", legal_area="landlord_tenant",
                                    topics=["landlord_repairs"], authority_types=["statute"])
            package = GeneralLegalResearchService(repo, settings).assemble(matter, force_general=True)["package"]
            self.assertFalse(package["public_execution"]["allowed"])
            [citation] = package["response_plan"]["citations"]
            self.assertEqual(citation["corpus_provenance"]["provider"], "virginia_code")
            self.assertEqual(citation["source_currentness"]["status"], "unresolved")
            with SQLiteNormalizedCorpus(database) as store:
                with store.connection:
                    store.connection.execute("UPDATE corpus_artifacts SET raw=?", (b"tampered",))
            result = GeneralLegalResearchService(repo, settings).assemble(matter, force_general=True)
            self.assertEqual(result["status"], "no_authoritative_support")
