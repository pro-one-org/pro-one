"""Offline contract tests using invented statutory and regulatory text."""

from base64 import b64decode
from dataclasses import replace
from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app.national_corpus import CorpusError, CorpusQuery
from app.national_corpus_courtlistener import CourtListenerProvider
from app.national_corpus_providers import PROVIDERS
from app.national_corpus_store import SQLiteNormalizedCorpus


def uslm(body="A test commission may publish example notices.", release="119-88", section="1"):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("usc01.xml", f"""<uscDoc xmlns="http://xml.house.gov/schemas/uslm/1.0" identifier="/us/usc/t1">
          <meta><docNumber>1</docNumber><docPublicationName>Online@{release}</docPublicationName></meta>
          <main><title identifier="/us/usc/t1"><chapter identifier="/us/usc/t1/ch1">
            <section identifier="/us/usc/t1/s{section}"><num value="{section}">§ {section}</num>
              <heading>Example notices</heading><content>{body}</content>
              <notes><p>Editorial note, excluded from the normalized text.</p></notes>
            </section>
          </chapter></title></main>
        </uscDoc>""")
    return buffer.getvalue()


def cfr_section(section):
    return f"""<SECTION><SECTNO>§ 1.{section}</SECTNO><SUBJECT>Example notices</SUBJECT>
       <P>Example notices appear in the test commission bulletin.</P></SECTION>"""


def cfr_volume(sections, year="2023"):
    return f"""<CFRDOC><FMTR><TITLEPG><TITLENUM>Title 1</TITLENUM>
       <REVISED>Revised as of January 1, {year}</REVISED></TITLEPG></FMTR>
       <TITLE><PART><EAR>Pt. 1</EAR>{sections}</PART></TITLE></CFRDOC>""".encode()


class NationalCorpusTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteNormalizedCorpus(":memory:")
        self.addCleanup(self.store.connection.close)
        self.olrc = PROVIDERS["olrc"]
        self.cfr = PROVIDERS["govinfo_cfr"]

    def test_official_provenance_and_exact_artifact_round_trip(self):
        raw = uslm()
        ingested = self.store.ingest(self.olrc, "119-88/1", raw)
        [match] = self.store.search(CorpusQuery("US", "statute", citation="1 U.S.C. § 1"))
        [observation] = self.store.provenance(match["version_id"])
        self.assertEqual(match["review_state"], "proposed")
        self.assertNotIn("Editorial note", match["text"])
        self.assertEqual(match["hierarchy"], ["/us/usc/t1", "/us/usc/t1/ch1"])
        self.assertEqual(observation["native_id"], "/us/usc/t1/s1")
        self.assertEqual(observation["locator"], "usc01.xml#/us/usc/t1/s1")
        self.assertTrue(observation["source_metadata"]["official_publisher"])
        self.assertEqual(observation["hash"], ingested["source_hash"])
        self.assertEqual(self.store.snapshot_bytes(observation["hash"]), raw)

    def test_refresh_and_same_edition_conflict_are_traceable(self):
        initial = uslm()
        first = self.store.ingest(self.olrc, "119-88/1", initial)
        again = self.store.ingest(self.olrc, "119-88/1", initial)
        corrected = self.store.ingest(self.olrc, "119-88/1", uslm("Changed source text."))
        newer = self.store.ingest(self.olrc, "119-89/1", uslm(release="119-89"))
        self.assertEqual(again["snapshot"], first["snapshot"])
        self.assertTrue(again["unchanged_snapshot"])
        self.assertEqual(again["new_versions"], 0)
        self.assertEqual(corrected["changed_records"], 1)
        self.assertEqual(newer["new_versions"], 1)
        matches = self.store.search(CorpusQuery("US", "statute", edition="PL 119-88"))
        self.assertEqual(len(matches), 2)
        self.assertEqual(len({match["authority_id"] for match in matches}), 1)
        self.assertEqual(len({match["normalized_hash"] for match in matches}), 2)
        self.assertTrue(all(match["edition_conflict"] for match in matches))
        self.assertEqual(self.store.stats(), {"authorities": 1, "versions": 3, "snapshots": 3, "observations": 3})

    def test_second_provider_keeps_separate_provenance_on_identical_version(self):
        original = self.olrc

        class Derivative:
            source = replace(original.source, name="test_derivative", official_publisher=False)
            source_url = staticmethod(original.source_url)
            normalize = staticmethod(original.normalize)

        raw = uslm()
        self.store.ingest(original, "119-88/1", raw)
        result = self.store.ingest(Derivative(), "119-88/1", raw)
        [match] = self.store.search(CorpusQuery("US", "statute", provider="test_derivative"))
        provenance = self.store.provenance(match["version_id"])
        self.assertEqual(result["new_versions"], 0)
        self.assertEqual({item["provider"] for item in provenance}, {"olrc", "test_derivative"})
        self.assertEqual({item["source_metadata"]["official_publisher"] for item in provenance}, {True, False})

    def test_scoped_search_and_historical_negative(self):
        self.store.ingest(self.olrc, "119-88/1", uslm())
        self.store.ingest(self.cfr, "2023/1/1", cfr_volume(cfr_section(1)))
        self.assertEqual(len(self.store.search(CorpusQuery("US", "statute", text="example notices"))), 1)
        self.assertEqual(self.store.search(CorpusQuery("US-VA", "statute", text="example notices")), [])
        self.assertEqual(self.store.search(CorpusQuery("US", "regulation", citation="1 USC 1")), [])
        self.assertEqual(self.store.search(CorpusQuery("US", "statute", citation="999 USC 999")), [])
        self.assertEqual(self.store.search(CorpusQuery("US", "regulation", currentness="current")), [])
        self.assertEqual(self.store.search(CorpusQuery("US", "regulation")), [])
        [historical] = self.store.search(CorpusQuery("US", "regulation", citation="1 CFR 1.1", currentness="historical"))
        self.assertEqual(historical["edition"], "2023-01-01")
        self.assertIsNone(historical["effective_from"])

    def test_duplicate_native_id_rolls_back_snapshot_and_index(self):
        raw = cfr_volume(cfr_section(1) * 2)
        with self.assertRaisesRegex(CorpusError, "duplicate_source_native_identity"):
            self.store.ingest(self.cfr, "2023/1/1", raw)
        self.assertFalse(any(self.store.stats().values()))
        self.assertEqual(self.store.search(CorpusQuery("US", "regulation", text="example", currentness="historical")), [])

    def test_mismatched_edition_and_untrusted_xml_fail_closed(self):
        for selector, raw, error in (
            ("2024/1/1", cfr_volume(cfr_section(1)), "source_edition_identity_mismatch"),
            ("2023/1/1", b'<!DOCTYPE CFRDOC SYSTEM "https://example.org/a"><CFRDOC/>', "source_xml_doctype_forbidden"),
            ("2023/1/1", cfr_volume(cfr_section(1)).replace(b"Title 1", b"Title 3"), "source_title_identity_mismatch"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(CorpusError, error):
                self.store.ingest(self.cfr, selector, raw)
        self.assertFalse(any(self.store.stats().values()))

    def test_source_selectors_cannot_change_endpoint_hosts_or_add_queries(self):
        for provider in PROVIDERS.values():
            for selector in ("https://example.org/a", "1/../2", "2023/1/1?next=example.org"):
                with self.subTest(provider=provider.source.name, selector=selector), self.assertRaises(CorpusError):
                    provider.source_url(selector)

    def test_corrupt_archive_is_rejected(self):
        with self.assertRaisesRegex(CorpusError, "source_zip_invalid"):
            self.store.ingest(self.olrc, "119-88/1", b"invalid archive")

    def test_virginia_publisher_scope_and_ambiguous_section_are_closed(self):
        provider = PROVIDERS["virginia_code"]
        section = "55.1/12/55.1-1220"
        body = b'<section data-table="CoV" data-field="body"><p>Example state text.</p></section>'
        def page(content):
            return b'<article id="vacode"><h2>&sect; 55.1-1220. Sample statute.</h2>' + content + b"</article>"

        with self.assertRaisesRegex(CorpusError, "duplicate_statutory_body"):
            self.store.ingest(provider, section, page(body * 2))
        with self.assertRaisesRegex(CorpusError, "source_section_identity_mismatch"):
            self.store.ingest(provider, "55.1/12/55.1-1244", page(body))
        raw = page(body + b"<p>Editorial history.</p>")
        self.store.ingest(provider, section, raw)
        [match] = self.store.search(CorpusQuery("US-VA", "statute", citation="Va. Code § 55.1-1220"))
        self.assertEqual(match["text"], "Example state text.")
        self.assertEqual(self.store.search(CorpusQuery("US", "statute", text="example state")), [])
        self.assertEqual(self.store.search(CorpusQuery("US-MD", "statute", text="example state")), [])

    def test_courtlistener_replay_keeps_roles_citations_and_relationship_provenance(self):
        citation = "603 U.S. 369"
        cluster = {"id": 12, "docket": 13, "case_name": "Example v. Commission",
                   "citations": [citation], "sub_opinions": [14, 15],
                   "date_filed": "2024-06-28", "precedential_status": "Published"}
        raw_opinions = {
            14: b'{ "id": 14, "cluster_id": 12, "plain_text": "Example lead text.", "type": "020lead", "opinions_cited": [16] }',
            15: b'{ "id": 15, "cluster_id": 12, "plain_text": "Example dissent.", "type": "040dissent" }',
        }
        resources = {
            "citation-lookup/": [{"status": 200, "clusters": [cluster], "normalized_citations": [citation]}],
            "clusters/12/": cluster, "dockets/13/": {"id": 13, "court_id": "scotus"},
            "courts/scotus/": {"id": "scotus", "full_name": "Supreme Court of the United States"},
        }

        class FixtureTransport:
            def request(self, method, path, headers, body, timeout, max_bytes):
                resource = path.removeprefix("/api/rest/v4/")
                if resource.startswith("opinions/"):
                    raw = raw_opinions[int(resource.split("/")[1])]
                else:
                    raw = json.dumps(resources[resource]).encode()
                return 200, {"content-type": "application/json"}, raw

        provider = CourtListenerProvider(FixtureTransport())
        with patch.dict(os.environ, {"COURTLISTENER_API_TOKEN": "test-token-never-stored"}):
            fetched = provider.fetch(f"scotus/{citation}")
            with self.assertRaisesRegex(CorpusError, "courtlistener_case_identity_mismatch"):
                provider.fetch(f"ca4/{citation}")
        self.assertEqual(fetched.requests, 6)
        responses = [b64decode(item["response"]) for item in json.loads(fetched.raw)]
        self.assertTrue(all(b"test-token-never-stored" not in response for response in responses))
        self.assertIn(raw_opinions[14], responses)
        result = self.store.ingest(provider, f"scotus/{citation}", fetched.raw)
        self.assertEqual(result["relationships_created"], 5)
        self.assertEqual(result["records"], 2)
        matches = self.store.search(CorpusQuery("US", "opinion", citation=citation))
        self.assertEqual({match["opinion_role"] for match in matches}, {"lead", "dissent"})
        self.assertEqual(len({match["authority_id"] for match in matches}), 2)
        [lead] = self.store.search(CorpusQuery("US", "opinion", citation=citation, opinion_roles=("lead", "majority")))
        self.assertNotIn("dissent", lead["text"])
        edges = self.store.relationships(lead["version_id"])
        self.assertIn(("cites", "opinions/16/"), {(edge["kind"], edge["target_native_id"]) for edge in edges})
        self.assertTrue(all(edge["snapshot_id"] == result["snapshot"] for edge in edges))
        [provenance] = self.store.provenance(lead["version_id"])
        self.assertFalse(provenance["source_metadata"]["official_publisher"])
        self.assertEqual(self.store.snapshot_bytes(result["source_hash"]), fetched.raw)


if __name__ == "__main__":
    unittest.main()
