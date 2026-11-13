from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.capabilities import ResearchComparison, ResearchMatter
from app.config import Settings
from app.legal_research import GeneralLegalResearchService
from app.national_corpus import AuthorityVersion, CorpusQuery, Observation
from app.national_corpus_identity import compare_identity
from app.national_corpus_providers import PROVIDERS
from app.national_corpus_store import SQLiteNormalizedCorpus
from app.repository import RecordRepository


class CorpusExpansionTests(unittest.TestCase):
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
